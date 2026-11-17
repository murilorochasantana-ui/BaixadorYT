"""Explorador de arquivos do canal (Fase 2): listar pastas, informações de mídia, texto para a
prévia, Lixeira com proteções, prévia de vídeo para formatos que o WebView2 não toca e o vigia
que avisa a interface quando algo muda (watchdog).

Segurança: todo caminho que vem da interface passa por `dentro_de(caminho, raizes)`. Só se mexe
na pasta do canal (e na pasta de downloads, se for outra). Apagar SEMPRE vai para a Lixeira.
"""
import hashlib
import json
import os
import subprocess
import threading
import time

from .config import pasta_do_canal, pasta_dados, pasta_downloads
from .ffmpeg import SEM_JANELA, exe_ffmpeg, exe_ffprobe, rodar_cancelavel

EXTS = {
    "video": {"mp4", "mkv", "webm", "mov", "avi", "m4v", "ts", "flv", "wmv"},
    "audio": {"mp3", "m4a", "wav", "opus", "aac", "ogg", "flac", "mka"},
    "imagem": {"jpg", "jpeg", "png", "webp", "gif", "bmp", "ico"},
    "texto": {"md", "txt", "log", "srt", "vtt", "csv", "ass"},
    "json": {"json"},
}
TOCA_DIRETO = {"mp4", "m4v", "mov", "webm", "mp3", "m4a", "wav", "opus", "ogg", "flac", "aac"}  # no WebView2
OCULTOS = {"desktop.ini", "thumbs.db", ".ds_store"}
LIMITE_TEXTO = 400_000
LIMITE_PASTA = 3000
PREVIA_SEGUNDOS = 600          # a prévia de formatos que não tocam cobre os primeiros 10 minutos
MAX_PREVIAS = 15


# ===================== caminhos e segurança =====================
def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def dentro_de(caminho, raizes):
    """O caminho está dentro de alguma das pastas permitidas (ou é uma delas)?"""
    if not caminho:
        return False
    c = _norm(caminho)
    for r in raizes:
        rr = _norm(r)
        if c == rr or c.startswith(rr.rstrip(os.sep) + os.sep):
            return True
    return False


def raizes_do_canal(cfg):
    """Pasta do canal + pasta de downloads (se ficar fora dela). Só as que existem."""
    raiz = str(pasta_do_canal(cfg))
    lista = [raiz]
    baixados = pasta_downloads(cfg)
    if not dentro_de(baixados, [raiz]):
        lista.append(baixados)
    return [r for r in lista if os.path.isdir(r)]


def pastas_protegidas(cfg):
    """Estrutura do canal que não pode ir para a Lixeira de uma vez (VideosLives, Ediçao, sfx...)."""
    protegidas = {str(pasta_do_canal(cfg))}
    for chave in (cfg.get("subpastas") or {}):
        protegidas.add(str(pasta_do_canal(cfg, chave)))
    raiz = str(pasta_do_canal(cfg))
    try:
        for nome in os.listdir(raiz):          # as pastas de primeiro nível (Cortes, VideosLives...)
            protegidas.add(os.path.join(raiz, nome))
    except OSError:
        pass
    protegidas.add(pasta_downloads(cfg))
    return [_norm(p) for p in protegidas]


def eh_parcial(nome, eh_pasta=False):
    n = nome.lower()
    return n.endswith((".part", ".ytdl")) or ".part-frag" in n or (eh_pasta and n.endswith(".trecho-tmp"))


def classificar(nome, eh_pasta=False):
    if eh_pasta:
        return "parcial" if eh_parcial(nome, True) else "pasta"
    if eh_parcial(nome):
        return "parcial"
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    for tipo, exts in EXTS.items():
        if ext in exts:
            return tipo
    return "outro"


# ===================== listar =====================
def _tamanho_pasta_parcial(caminho):
    total = 0
    try:
        with os.scandir(caminho) as it:
            for e in it:
                if e.is_file(follow_symlinks=False):
                    total += e.stat().st_size
    except OSError:
        pass
    return total


def listar(caminho, limite=LIMITE_PASTA):
    """Conteúdo de UMA pasta (a árvore carrega pasta por pasta). Pastas primeiro, depois por nome."""
    itens, truncado = [], False
    with os.scandir(caminho) as it:
        for e in it:
            nome = e.name
            if nome.lower() in OCULTOS or nome.startswith("$"):
                continue
            if len(itens) >= limite:
                truncado = True
                break
            try:
                eh_pasta = e.is_dir()
                st = e.stat()
            except OSError:
                continue          # sumiu no meio da leitura (download terminando)
            tipo = classificar(nome, eh_pasta)
            tamanho = _tamanho_pasta_parcial(e.path) if tipo == "parcial" and eh_pasta else \
                (None if eh_pasta else st.st_size)
            itens.append({"nome": nome, "caminho": e.path, "pasta": eh_pasta and tipo != "parcial",
                          "tipo": tipo, "tamanho": tamanho, "mtime": st.st_mtime,
                          "parcial": tipo == "parcial"})
    itens.sort(key=lambda x: (not x["pasta"], x["nome"].casefold()))
    return {"itens": itens, "truncado": truncado}


# ===================== informações de mídia =====================
_cache_info = {}


def _fps(txt):
    try:
        a, b = txt.split("/")
        return round(int(a) / int(b), 2) if int(b) else None
    except (ValueError, AttributeError):
        return None


def info_midia(caminho):
    """Duração, codecs, resolução e bitrate via ffprobe (com cache por arquivo+data+tamanho)."""
    st = os.stat(caminho)
    chave = (caminho, st.st_mtime, st.st_size)
    if chave in _cache_info:
        return _cache_info[chave]
    r = subprocess.run([exe_ffprobe(), "-v", "error", "-show_entries",
                        "format=duration,bit_rate,format_name:stream=codec_type,codec_name,width,height,"
                        "avg_frame_rate,sample_rate,channels", "-of", "json", caminho],
                       capture_output=True, timeout=60, **SEM_JANELA)
    try:
        d = json.loads(r.stdout or b"{}")
    except ValueError:
        d = {}
    fmt, fluxos = d.get("format") or {}, d.get("streams") or []
    v = next((s for s in fluxos if s.get("codec_type") == "video" and s.get("codec_name") != "mjpeg"), None)
    a = next((s for s in fluxos if s.get("codec_type") == "audio"), None)
    try:
        duracao = float(fmt.get("duration")) if fmt.get("duration") else None
    except ValueError:
        duracao = None
    info = {
        "duracao": duracao,
        "bitrate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "video": {"codec": v.get("codec_name"), "largura": v.get("width"), "altura": v.get("height"),
                  "fps": _fps(v.get("avg_frame_rate"))} if v else None,
        "audio": {"codec": a.get("codec_name"), "hz": int(a["sample_rate"]) if str(a.get("sample_rate", "")).isdigit()
                  else None, "canais": a.get("channels")} if a else None,
        "valido": bool(fluxos),
    }
    if len(_cache_info) > 500:
        _cache_info.clear()
    _cache_info[chave] = info
    return info


def ler_texto(caminho, limite=LIMITE_TEXTO):
    with open(caminho, "rb") as f:
        dados = f.read(limite + 1)
    return dados[:limite].decode("utf-8", errors="replace"), len(dados) > limite


def descrever(caminho):
    """Tudo que a prévia precisa saber sobre um arquivo (sem a URL de mídia, que é da ponte)."""
    st = os.stat(caminho)
    nome = os.path.basename(caminho)
    eh_pasta = os.path.isdir(caminho)
    tipo = classificar(nome, eh_pasta)
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome and not eh_pasta else ""
    d = {"nome": nome, "caminho": caminho, "tipo": tipo, "pasta": eh_pasta and tipo != "parcial",
         "tamanho": _tamanho_pasta_parcial(caminho) if tipo == "parcial" and eh_pasta else
         (None if eh_pasta else st.st_size), "mtime": st.st_mtime, "ext": ext}
    if eh_pasta and tipo == "pasta":
        try:
            d["n_itens"] = len([x for x in os.listdir(caminho) if x.lower() not in OCULTOS])
        except OSError:
            d["n_itens"] = None
    if tipo in ("video", "audio"):
        try:
            d["midia"] = info_midia(caminho)
        except Exception as e:
            d["midia"] = {"valido": False, "erro": str(e)[:120]}
        d["toca_direto"] = ext in TOCA_DIRETO
    elif tipo in ("texto", "json"):
        texto, cortado = ler_texto(caminho)
        if tipo == "json":
            try:
                texto = json.dumps(json.loads(texto), ensure_ascii=False, indent=1) if not cortado else texto
            except ValueError:
                pass
        d["texto"], d["truncado"] = texto, cortado
    return d


# ===================== Lixeira =====================
def para_lixeira(caminho, cfg):
    """Manda para a Lixeira do Windows (nunca apaga direto). Levanta ValueError com a explicação."""
    raizes = raizes_do_canal(cfg)
    if not dentro_de(caminho, raizes):
        raise ValueError("Esse arquivo está fora da pasta do canal: o Estúdio não mexe nele.")
    if not os.path.exists(caminho):
        raise ValueError("Esse arquivo já não existe (talvez já tenha sido apagado).")
    if _norm(caminho) in pastas_protegidas(cfg):
        raise ValueError("Essa pasta faz parte da estrutura do canal (VideosLives, Ediçao, Cortes…) e não pode "
                         "ir para a Lixeira de uma vez. Apague os arquivos de dentro, um por um.")
    try:
        import send2trash
    except ImportError:
        raise ValueError("Falta o componente da Lixeira. Rode o atualizar.bat (pasta estudio) e abra de novo.") from None
    try:
        send2trash.send2trash(os.path.normpath(caminho))
    except OSError as e:
        raise ValueError("Não consegui mandar para a Lixeira. Se for um download em andamento, pause ou cancele "
                         f"antes; se o arquivo estiver aberto em outro programa, feche-o.\n\n({e})") from None


# ===================== prévia de vídeo (formatos que o WebView2 não toca) =====================
def caminho_previa(caminho):
    st = os.stat(caminho)
    h = hashlib.sha1(f"{_norm(caminho)}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:16]
    pasta = pasta_dados() / "previas"
    pasta.mkdir(exist_ok=True)
    return str(pasta / f"{h}.mp4")


def _limpar_previas():
    pasta = pasta_dados() / "previas"
    arqs = sorted((p for p in pasta.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
    for velho in arqs[MAX_PREVIAS:]:
        try:
            velho.unlink()
        except OSError:
            pass


def gerar_previa(caminho, avisar, checar=lambda: None):
    """Cópia leve (540p, H.264/AAC, só os primeiros 10 min) para tocar no Estúdio. Cacheada."""
    destino = caminho_previa(caminho)
    if os.path.exists(destino):
        return destino
    try:
        total = min(info_midia(caminho).get("duracao") or PREVIA_SEGUNDOS, PREVIA_SEGUNDOS)
    except Exception:
        total = PREVIA_SEGUNDOS
    cmd = [exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-progress", "pipe:1", "-nostats",
           "-t", str(PREVIA_SEGUNDOS), "-i", caminho, "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", "scale=-2:'min(540,ih)'", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
           "-f", "mp4", destino + ".part"]

    def linha(l):
        chave, _, valor = l.partition("=")
        if chave in ("out_time_us", "out_time_ms") and valor.strip().lstrip("-").isdigit():
            avisar(min(int(valor) / 1e6 * 100 / max(total, 1), 99))
    try:
        r = rodar_cancelavel(cmd, checar, linha)
        if r.returncode != 0:
            raise RuntimeError("O ffmpeg não conseguiu gerar a prévia: " + r.stderr.decode(errors="ignore")[-200:])
        os.replace(destino + ".part", destino)
    finally:
        if os.path.exists(destino + ".part"):
            os.remove(destino + ".part")
    _limpar_previas()
    return destino


# ===================== vigia (watchdog) =====================
class Vigia:
    """Avisa quais pastas mudaram (agrupado: no máximo uma notificação a cada ~0,8 s)."""
    def __init__(self, ao_mudar, intervalo=0.8):
        self.ao_mudar, self.intervalo = ao_mudar, intervalo
        self.pendentes, self.trava = set(), threading.Lock()
        self.observador = None
        self.disponivel = False
        self._rodando = False

    def iniciar(self, raizes):
        self.parar()
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return False
        vigia = self

        class Tratador(FileSystemEventHandler):
            def on_any_event(self, evento):
                if evento.event_type in ("opened", "closed", "closed_no_write"):
                    return
                for p in (getattr(evento, "src_path", None), getattr(evento, "dest_path", None)):
                    if p:
                        vigia._marcar(os.path.dirname(os.fsdecode(p)))
        self.observador = Observer()
        for r in raizes:
            try:
                self.observador.schedule(Tratador(), r, recursive=True)
            except OSError:
                pass
        self.observador.daemon = True
        self.observador.start()
        self._rodando = True
        threading.Thread(target=self._despachar, daemon=True, name="vigia").start()
        self.disponivel = True
        return True

    def _marcar(self, pasta):
        with self.trava:
            self.pendentes.add(pasta)

    def _despachar(self):
        while self._rodando:
            time.sleep(self.intervalo)
            with self.trava:
                pastas, self.pendentes = sorted(self.pendentes), set()
            if pastas:
                try:
                    self.ao_mudar(pastas)
                except Exception:
                    pass

    def parar(self):
        self._rodando = False
        if self.observador:
            try:
                self.observador.stop()
            except Exception:
                pass
            self.observador = None
