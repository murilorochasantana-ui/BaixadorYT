"""Baixar só um trecho, rápido e cancelável.

Por que existe: o "download_ranges" do yt-dlp manda o ffmpeg ler o vídeo direto do site e, com
corte exato, RECODIFICA o trecho inteiro (lento: 1 h levava ~40 min) sem dar notícia de progresso
nem deixar cancelar. Aqui há três caminhos, do mais rápido para o mais simples:

1. "indice" (YouTube e outros MP4 por https): lê o índice (caixa `sidx`) no começo do arquivo,
   descobre quais bytes têm o trecho e baixa só eles, em vários pedaços ao mesmo tempo, pela
   mesma conexão do yt-dlp. Os pedaços ficam guardados: pausar e retomar continua de onde parou.
2. "hls" (Twitch e outros .m3u8): o ffmpeg lê só os segmentos do trecho, sem recodificar,
   num processo que o Estúdio controla (dá para pausar/cancelar na hora).
3. "inteiro" (TikTok, Instagram…, que são curtos): baixa o vídeo inteiro pelo yt-dlp e corta no PC.

No fim, o corte é feito no PC com `-c copy` (sem recodificar) começando num quadro-chave:
o trecho pode começar até alguns segundos antes do pedido, e esse início real é devolvido
para a transcrição ficar sincronizada.
"""
import concurrent.futures
import json
import os
import shutil
import struct
import subprocess
import threading
import time

from .controle import Interrompido
from .gravacao import entrada_ffmpeg
from .ffmpeg import SEM_JANELA, exe_ffmpeg, exe_ffprobe, matar_ffmpegs_filhos, rodar_cancelavel

BLOCO = 4 << 20            # 4 MB por pedido
PARALELOS = 6              # pedidos ao mesmo tempo
LEITURA = 256 << 10        # lê de 256 KB em 256 KB (para parar rápido)
EXTS_MP4 = ("mp4", "m4a", "m4v", "mov")
AUDIO_CONVERTIDO = {"mp3": ["-c:a", "libmp3lame", "-b:a", "320k"], "wav": ["-c:a", "pcm_s16le"]}


class SemIndice(Exception):
    """O arquivo não tem o índice esperado: usar outro caminho."""


# ===================== índice MP4 (sidx) =====================
def caixas(dados):
    """Caixas MP4 do nível de cima: (tipo, posição, tamanho, tamanho_do_cabeçalho)."""
    p = 0
    while p + 8 <= len(dados):
        tam, tipo = struct.unpack(">I4s", dados[p:p + 8])
        cab = 8
        if tam == 1:
            if p + 16 > len(dados):
                return
            tam = struct.unpack(">Q", dados[p + 8:p + 16])[0]
            cab = 16
        elif tam == 0:
            tam = len(dados) - p
        if tam < cab:
            return
        yield tipo.decode("latin1"), p, tam, cab
        p += tam


def ler_indice(dados):
    """Do começo do arquivo, devolve (bytes_de_inicializacao, segmentos).
    Cada segmento: (t_inicio, t_fim, byte_inicio, byte_fim) em segundos e bytes absolutos."""
    fim_init, sidx = None, None
    for tipo, p, tam, cab in caixas(dados):
        if tipo == "moov":
            fim_init = p + tam
        elif tipo == "sidx":
            if p + tam > len(dados):
                raise SemIndice("índice maior que o pedaço lido")
            sidx = (p, tam, cab)
            break
    if not fim_init or not sidx or fim_init > len(dados):
        raise SemIndice("sem moov/sidx no começo do arquivo")
    p, tam, cab = sidx
    c = dados[p + cab:p + tam]
    versao, q = c[0], 4
    escala = struct.unpack(">I", c[q + 4:q + 8])[0]
    q += 8
    if versao == 0:
        t, deslocamento = struct.unpack(">II", c[q:q + 8])
        q += 8
    else:
        t, deslocamento = struct.unpack(">QQ", c[q:q + 16])
        q += 16
    q += 2
    n = struct.unpack(">H", c[q:q + 2])[0]
    q += 2
    if not escala or not n:
        raise SemIndice("índice vazio")
    segs, b = [], p + tam + deslocamento
    for _ in range(n):
        ref, dur, _sap = struct.unpack(">III", c[q:q + 12])
        q += 12
        if ref & 0x80000000:
            raise SemIndice("índice em vários níveis")
        tam_ref = ref & 0x7FFFFFFF
        segs.append((t / escala, (t + dur) / escala, b, b + tam_ref - 1))
        b += tam_ref
        t += dur
    return dados[:fim_init], segs


def escolher_segmentos(segs, inicio, fim):
    """Segmentos que cobrem [inicio, fim]. Retorna (t_inicio_real, byte_inicio, byte_fim)."""
    sel = [s for s in segs if s[1] > inicio and (fim is None or s[0] < fim)]
    if not sel:
        raise SemIndice("trecho fora do vídeo")
    return sel[0][0], sel[0][2], sel[-1][3]


def dividir_em_blocos(b_ini, b_fim, bloco=BLOCO):
    return [(a, min(a + bloco - 1, b_fim)) for a in range(b_ini, b_fim + 1, bloco)]


# ===================== rede (pela conexão do yt-dlp) =====================
def esperar_liberacao(formatos, checar, avisar):
    """O YouTube só libera os links alguns segundos depois de lidos (campo available_at);
    antes disso responde 403. O yt-dlp também espera."""
    alvo = max((f.get("available_at") or 0) for f in formatos)
    while time.time() < alvo + 0.3:
        checar()
        avisar(f"Preparando o trecho... ({max(0, alvo - time.time()):.0f} s)")
        time.sleep(0.25)


def _pedido(ydl, fmt, a, b):
    from yt_dlp.networking import Request
    ext = {}
    if fmt.get("impersonate"):     # mesmo pedido que o yt-dlp faria (alguns sites exigem parecer navegador)
        from yt_dlp.downloader.common import FileDownloader
        alvo = FileDownloader(ydl, {})._get_impersonate_target(fmt)
        if alvo is not None:
            ext["impersonate"] = alvo
    cab = {"Accept-Encoding": "identity", **(fmt.get("http_headers") or {}), "Range": f"bytes={a}-{b}"}
    return ydl.urlopen(Request(fmt["url"], None, cab, extensions=ext))


def ler_bytes(ydl, fmt, a, b):
    with _pedido(ydl, fmt, a, b) as r:
        return r.read()


class Progresso:
    """Soma os bytes baixados por todas as threads e calcula velocidade."""
    def __init__(self, total, ja_tinha, avisar):
        self.total, self.feito, self.avisar = total, ja_tinha, avisar
        self.inicio, self.ultimo, self.trava = time.time(), 0, threading.Lock()
        self.base = ja_tinha

    def somar(self, n):
        with self.trava:
            self.feito += n

    def mostrar(self, rotulo="Baixando trecho"):
        agora = time.time()
        if agora - self.ultimo < 0.4:
            return
        self.ultimo = agora
        vel = (self.feito - self.base) / max(agora - self.inicio, 0.1)
        pct = self.feito * 100 / self.total if self.total else 0
        falta = (self.total - self.feito) / vel if vel > 0 else None
        self.avisar(f"{rotulo} {pct:.0f}% • {self.feito / 2**20:.0f} de {self.total / 2**20:.0f} MB",
                    pct, f"{vel / 2**20:.1f} MB/s", _tempo_curto(falta))


def _tempo_curto(seg):
    if seg is None:
        return "?"
    seg = int(seg)
    return f"{seg // 60}:{seg % 60:02d}" if seg < 3600 else f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def baixar_faixas(ydl, faixas, pasta_tmp, checar, progresso):
    """Baixa vários (fmt, a, b, arquivo) ao mesmo tempo. Arquivos já completos são pulados (retomar)."""
    parar = threading.Event()

    def um(fmt, a, b, arq):
        esperado = b - a + 1
        if os.path.exists(arq) and os.path.getsize(arq) == esperado:
            return
        tmp = arq + ".part"
        for tentativa in range(3):
            if parar.is_set():
                return
            try:
                feito = 0
                with _pedido(ydl, fmt, a, b) as r, open(tmp, "wb") as saida:
                    while not parar.is_set():
                        pedaco = r.read(LEITURA)
                        if not pedaco:
                            break
                        saida.write(pedaco)
                        feito += len(pedaco)
                        progresso.somar(len(pedaco))
                if parar.is_set():
                    return
                if feito != esperado:
                    raise IOError(f"pedaço incompleto ({feito} de {esperado} bytes)")
                os.replace(tmp, arq)
                return
            except Exception:
                progresso.somar(-feito)
                if tentativa == 2 or parar.is_set():
                    raise
                time.sleep(1 + tentativa)

    with concurrent.futures.ThreadPoolExecutor(PARALELOS) as ex:
        futuros = [ex.submit(um, *f) for f in faixas]
        try:
            while True:
                checar()
                progresso.mostrar()
                feitos, pendentes = concurrent.futures.wait(futuros, timeout=0.3)
                for f in feitos:
                    if f.exception():
                        raise f.exception()
                if not pendentes:
                    break
        except BaseException:
            parar.set()
            for f in futuros:
                f.cancel()
            raise


# ===================== corte local =====================
def info_local(arquivo):
    """start_time e se tem vídeo, lendo o arquivo baixado (rápido, é local)."""
    r = subprocess.run([exe_ffprobe(), "-v", "error", "-show_entries", "format=start_time:stream=codec_type",
                        "-of", "json", arquivo], capture_output=True, **SEM_JANELA)
    try:
        d = json.loads(r.stdout or b"{}")
    except ValueError:
        d = {}
    inicio = float((d.get("format") or {}).get("start_time") or 0)
    tipos = {s.get("codec_type") for s in d.get("streams") or []}
    return inicio, "video" in tipos


def quadro_chave_antes(arquivo, alvo):
    """Maior quadro-chave (no tempo do arquivo) que vem antes de `alvo`. Só lê os pacotes perto do alvo."""
    r = subprocess.run([exe_ffprobe(), "-v", "error", "-select_streams", "v:0",
                        "-read_intervals", f"{max(alvo - 30, 0):.3f}%{alvo + 0.05:.3f}",
                        "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", arquivo],
                       capture_output=True, text=True, **SEM_JANELA)
    chaves = []
    for linha in r.stdout.splitlines():
        partes = linha.split(",")
        if len(partes) >= 2 and "K" in partes[1]:
            try:
                t = float(partes[0])
            except ValueError:
                continue
            if t <= alvo + 0.001:
                chaves.append(t)
    return max(chaves) if chaves else None


def cortar(entradas, inicio, fim, saida, checar, avisar, extra_saida=()):
    """Junta e corta as peças baixadas, sem recodificar o vídeo.
    entradas: lista de arquivos (cada um com o tempo ORIGINAL do vídeo nos pacotes).
    Começa no quadro-chave antes de `inicio`. Retorna o início real (segundos do vídeo original)."""
    infos = [info_local(a) for a in entradas]
    inicio_real = inicio
    for arq, (_ini, tem_video) in zip(entradas, infos):
        if tem_video:
            k = quadro_chave_antes(arq, inicio)
            if k is not None:
                inicio_real = k
            break
    cmd = [exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    for arq, (ini_arq, _tem_video) in zip(entradas, infos):
        cmd += ["-ss", f"{max(inicio_real - ini_arq, 0):.3f}", "-i", arq]
    if fim is not None:
        cmd += ["-t", f"{fim - inicio_real:.3f}"]
    for i in range(len(entradas)):
        cmd += ["-map", f"{i}:v?", "-map", f"{i}:a?"]   # só vídeo e áudio (a Twitch traz dados que o MP4 não aceita)
    cmd += ["-c", "copy", *extra_saida]
    if saida.lower().endswith((".mp4", ".m4a", ".mov")):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-f", formato_ffmpeg(saida), saida + ".part"]
    avisar("Cortando o trecho (sem recodificar)...", 100, "", "")
    r = rodar_cancelavel(cmd, checar)
    if r.returncode != 0:
        raise RuntimeError("O ffmpeg não conseguiu cortar o trecho: " + r.stderr.decode(errors="ignore")[-300:])
    os.replace(saida + ".part", saida)
    return inicio_real


def formato_ffmpeg(caminho):
    ext = os.path.splitext(caminho)[1].lower().lstrip(".")
    return {"mkv": "matroska", "mka": "matroska", "m4a": "ipod", "mp3": "mp3", "wav": "wav",
            "webm": "webm"}.get(ext, "mp4")


def converter_audio(origem, saida, codec, checar, avisar):
    avisar(f"Convertendo para {codec.upper()}...", 100, "", "")
    r = rodar_cancelavel([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-i", origem,
                          "-vn", *AUDIO_CONVERTIDO[codec], "-f", formato_ffmpeg(saida), saida + ".part"], checar)
    if r.returncode != 0:
        raise RuntimeError("O ffmpeg não conseguiu converter o áudio: " + r.stderr.decode(errors="ignore")[-300:])
    os.replace(saida + ".part", saida)


def salvar_miniatura(ydl, info, base):
    """Capa do vídeo em <base>.jpg (no trecho o yt-dlp não baixa, então baixamos aqui)."""
    url = info.get("thumbnail")
    if not url:
        return None
    tmp = base + ".capa"
    try:
        with ydl.urlopen(url) as r, open(tmp, "wb") as f:
            f.write(r.read())
        subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", tmp, "-frames:v", "1",
                        base + ".jpg"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SEM_JANELA)
        return base + ".jpg" if os.path.exists(base + ".jpg") else None
    except Exception:
        return None  # sem capa não é motivo para falhar o download
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ===================== escolha do caminho =====================
def extensao_saida(formatos, codec_convertido=None):
    """mp4 sempre que der (CapCut/Premiere/Windows abrem melhor); mkv só se os codecs não couberem."""
    if codec_convertido in AUDIO_CONVERTIDO:
        return codec_convertido
    tem_video = any((f.get("vcodec") or "none") != "none" for f in formatos)
    acodecs = [(f.get("acodec") or "none").lower() for f in formatos if (f.get("acodec") or "none") != "none"]
    if not tem_video:
        return "m4a" if all(a.startswith(("mp4a", "aac")) for a in acodecs) else "mka"
    vcodecs = [(f.get("vcodec") or "").lower() for f in formatos if (f.get("vcodec") or "none") != "none"]
    video_ok = all(v.startswith(("avc", "h264", "hev", "hvc", "av01", "vp09", "vp9")) for v in vcodecs)
    audio_ok = all(a.startswith(("mp4a", "aac", "mp3", "opus")) for a in acodecs)
    return "mp4" if video_ok and audio_ok else "mkv"


def caminho_para(formatos):
    protocolos = {f.get("protocol") or "https" for f in formatos}
    if protocolos <= {"https", "http"} and all((f.get("ext") or "") in EXTS_MP4 for f in formatos) \
            and all(f.get("filesize") or f.get("filesize_approx") for f in formatos):
        return "indice"
    if any(p.startswith("m3u8") for p in protocolos):
        return "hls"
    return "inteiro"


class Trecho:
    """Baixa o trecho [inicio, fim] de `info` (já lido pelo yt-dlp, com o formato escolhido).
    Retorna (arquivo_final, inicio_real, fim). Lança a exceção de `checar` para pausar/cancelar.
    `avisar(status, pct, vel, eta)` mostra o progresso."""

    def __init__(self, ydl, info, base_saida, inicio, fim, checar, avisar, codec_convertido=None, opcoes_inteiro=None,
                 ao_fallback=lambda motivo: None):
        self.ydl, self.info, self.base = ydl, info, base_saida
        self.inicio, self.fim = inicio or 0.0, fim
        self.checar, self.avisar = checar, avisar
        self.formatos = info.get("requested_formats") or [info]
        self.codec = codec_convertido
        self.opcoes_inteiro = opcoes_inteiro or {}
        self.ao_fallback = ao_fallback        # chamado com o motivo quando o método rápido falha
        self.saida_real = None                 # caminho final (o método do yt-dlp pode mudar a extensão)
        self.pasta_tmp = base_saida + ".trecho-tmp"
        duracao = info.get("duration")
        if duracao and self.inicio >= duracao:
            raise RuntimeError("O início do trecho passa da duração do vídeo. Confira o tempo digitado.")
        if duracao and self.fim is not None and self.fim > duracao:
            self.fim = None   # até o final

    @property
    def saida(self):
        return f"{self.base}.{extensao_saida(self.formatos, self.codec)}"

    def baixar(self):
        os.makedirs(self.pasta_tmp, exist_ok=True)
        caminho = caminho_para(self.formatos)
        try:
            if caminho == "indice":
                inicio_real = self._por_indice()
            elif caminho == "hls":
                inicio_real = self._hls()
            else:
                inicio_real = self._inteiro()
        except Interrompido:
            raise                      # pausar/cancelar nunca vira "fallback"
        except Exception as e:
            if caminho == "inteiro":   # já era o último recurso: não há para onde voltar
                raise
            # O método rápido falhou (YouTube mudou o índice, 403, rede, arquivo inesperado...):
            # volta sozinho para o método do yt-dlp, mais lento, mas que funciona.
            self.ao_fallback(f"{type(e).__name__}: {e}"[:200])
            shutil.rmtree(self.pasta_tmp, ignore_errors=True)
            os.makedirs(self.pasta_tmp, exist_ok=True)
            self.checar()
            inicio_real = self._ytdlp()
        shutil.rmtree(self.pasta_tmp, ignore_errors=True)
        return self.saida_real or self.saida, inicio_real, self.fim
    def apagar_temporarios(self):
        """Cancelar: apaga os pedaços e qualquer arquivo pela metade."""
        shutil.rmtree(self.pasta_tmp, ignore_errors=True)
        for ext in ("mp4", "mkv", "m4a", "mka", "mp3", "wav"):
            for arq in (f"{self.base}.{ext}.part",):
                if os.path.exists(arq):
                    try:
                        os.remove(arq)
                    except OSError:
                        pass

    def _finalizar(self, pecas):
        """Corta as peças e, se for MP3/WAV, converte."""
        self.saida_real = self.saida
        if self.codec in AUDIO_CONVERTIDO:
            intermediario = os.path.join(self.pasta_tmp, "audio_cortado.m4a")
            inicio_real = cortar(pecas, self.inicio, self.fim, intermediario, self.checar, self.avisar)
            converter_audio(intermediario, self.saida, self.codec, self.checar, self.avisar)
            return inicio_real
        return cortar(pecas, self.inicio, self.fim, self.saida, self.checar, self.avisar)

    # ---------- caminho 1: índice ----------
    def _por_indice(self):
        esperar_liberacao(self.formatos, self.checar, lambda t: self.avisar(t, 0, "", ""))
        planos = []
        for i, fmt in enumerate(self.formatos):
            self.checar()
            self.avisar("Lendo o índice do vídeo...", 0, "", "")
            cabeca = ler_bytes(self.ydl, fmt, 0, (512 << 10) - 1)
            try:
                init, segs = ler_indice(cabeca)
            except SemIndice:
                cabeca = ler_bytes(self.ydl, fmt, 0, (4 << 20) - 1)   # índice grande (vídeo muito longo)
                init, segs = ler_indice(cabeca)
            t_ini, b_ini, b_fim = escolher_segmentos(segs, self.inicio, self.fim)
            planos.append((i, fmt, init, b_ini, b_fim))
        # manifesto: só reaproveita pedaços de uma pausa anterior se forem dos mesmos bytes
        manifesto = os.path.join(self.pasta_tmp, "plano.json")
        assinatura = [[f.get("format_id"), a, b] for _i, f, _init, a, b in planos]
        try:
            if json.load(open(manifesto, encoding="utf-8")) != assinatura:
                raise ValueError
        except (OSError, ValueError):
            shutil.rmtree(self.pasta_tmp, ignore_errors=True)
            os.makedirs(self.pasta_tmp, exist_ok=True)
            json.dump(assinatura, open(manifesto, "w", encoding="utf-8"))
        faixas = []
        for i, fmt, _init, b_ini, b_fim in planos:
            for n, (a, b) in enumerate(dividir_em_blocos(b_ini, b_fim)):
                faixas.append((fmt, a, b, os.path.join(self.pasta_tmp, f"f{i}_{n:05d}.bin")))
        total = sum(b - a + 1 for _f, a, b, _arq in faixas)
        ja = sum(os.path.getsize(arq) for _f, a, b, arq in faixas
                 if os.path.exists(arq) and os.path.getsize(arq) == b - a + 1)
        progresso = Progresso(total, ja, self.avisar)
        baixar_faixas(self.ydl, faixas, self.pasta_tmp, self.checar, progresso)
        pecas = []
        for i, fmt, init, _a, _b in planos:   # monta cada peça: inicialização + segmentos do trecho
            self.checar()
            peca = os.path.join(self.pasta_tmp, f"peca{i}.{fmt.get('ext') or 'mp4'}")
            with open(peca, "wb") as saida:
                saida.write(init)
                for _f, _a, _b, arq in [x for x in faixas if os.path.basename(x[3]).startswith(f"f{i}_")]:
                    with open(arq, "rb") as entrada:
                        shutil.copyfileobj(entrada, saida, 1 << 20)
            pecas.append(peca)
        return self._finalizar(pecas)

    # ---------- caminho 2: HLS (Twitch) ----------
    def _hls(self):
        esperar_liberacao(self.formatos, self.checar, lambda t: self.avisar(t, 0, "", ""))
        duracao = (self.fim - self.inicio) if self.fim is not None else \
            max((self.info.get("duration") or 0) - self.inicio, 1)
        intermediario = os.path.join(self.pasta_tmp, "hls.mkv")
        cmd = [exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-progress", "pipe:1", "-nostats"]
        for fmt in self.formatos:
            cmd += entrada_ffmpeg(self.ydl, self.info, fmt)
            cmd += ["-ss", f"{self.inicio:.3f}"]
            if self.fim is not None:
                cmd += ["-t", f"{duracao:.3f}"]
            cmd += ["-i", fmt["url"]]
        for i in range(len(self.formatos)):
            cmd += ["-map", f"{i}:v?", "-map", f"{i}:a?"]
        cmd += ["-c", "copy", "-f", "matroska", intermediario]
        estado = {"t": 0.0, "bytes": 0, "inicio": time.time()}

        def linha(l):
            chave, _, valor = l.partition("=")
            if chave in ("out_time_us", "out_time_ms") and valor.strip().lstrip("-").isdigit():
                estado["t"] = int(valor) / 1e6
            elif chave == "total_size" and valor.strip().isdigit():
                estado["bytes"] = int(valor)
            elif chave == "progress":
                gasto = max(time.time() - estado["inicio"], 0.1)
                pct = min(estado["t"] * 100 / duracao, 99)
                falta = (duracao - estado["t"]) * gasto / estado["t"] if estado["t"] > 0 else None
                self.avisar(f"Baixando trecho {_tempo_curto(estado['t'])} de {_tempo_curto(duracao)} • "
                            f"{estado['bytes'] / 2**20:.0f} MB", pct,
                            f"{estado['bytes'] / gasto / 2**20:.1f} MB/s", _tempo_curto(falta))
        r = rodar_cancelavel(cmd, self.checar, linha)
        if r.returncode != 0:
            raise RuntimeError("O ffmpeg não conseguiu baixar o trecho: " + r.stderr.decode(errors="ignore")[-300:])
        # O HLS já sai cortado pelo ffmpeg: só falta passar para o formato final (sem cortar de novo).
        # O tempo 0 do arquivo é o início pedido (com precisão de um segmento, poucos segundos).
        pedido_inicio, pedido_fim = self.inicio, self.fim
        self.inicio, self.fim = 0.0, None
        try:
            self._finalizar([intermediario])
        finally:
            self.inicio, self.fim = pedido_inicio, pedido_fim
        return pedido_inicio

    # ---------- plano B: o próprio yt-dlp (mais lento) ----------
    def _ytdlp(self):
        """Trecho pelo `download_ranges` do yt-dlp (o ffmpeg lê o site e recodifica o trecho: lento, mas
        não depende do índice do YouTube). Roda numa thread para dar para pausar/cancelar: ao
        interromper, os ffmpeg que o yt-dlp abriu são encerrados."""
        import threading
        import yt_dlp
        from yt_dlp.utils import download_range_func
        self.avisar("Método rápido indisponível: usando o método do yt-dlp (mais lento)...", 0, "", "")
        fim = self.fim if self.fim is not None else float("inf")
        opcoes = {**self.opcoes_inteiro, "outtmpl": os.path.join(self.pasta_tmp, "ytdlp.%(ext)s"),
                  "postprocessors": [], "writethumbnail": False, "progress_hooks": [], "postprocessor_hooks": [],
                  "download_ranges": download_range_func(None, [(self.inicio, fim)]),
                  "force_keyframes_at_cuts": True}
        resultado, erro = {}, []

        def trabalho():
            try:
                with yt_dlp.YoutubeDL(opcoes) as y:
                    resultado["info"] = y.process_ie_result(dict(self.info), download=True)
            except BaseException as e:   # entregue à thread principal
                erro.append(e)
        fio = threading.Thread(target=trabalho, daemon=True)
        fio.start()
        try:
            while fio.is_alive():
                self.checar()
                self.avisar("Baixando o trecho pelo yt-dlp (mais lento)...", None, "", "")
                fio.join(0.25)
        except BaseException:
            matar_ffmpegs_filhos()
            fio.join(timeout=15)
            raise
        if erro:
            raise erro[0]
        baixado = ((resultado.get("info") or {}).get("requested_downloads") or [{}])[-1].get("filepath")
        if not baixado or not os.path.exists(baixado):
            achados = [os.path.join(self.pasta_tmp, x) for x in os.listdir(self.pasta_tmp) if x.startswith("ytdlp.")]
            baixado = max(achados, key=os.path.getsize) if achados else None
        if not baixado:
            raise RuntimeError("O yt-dlp não entregou o trecho. Tente de novo ou baixe o vídeo inteiro.")
        if self.codec in AUDIO_CONVERTIDO:
            self.saida_real = self.saida
            converter_audio(baixado, self.saida, self.codec, self.checar, self.avisar)
        else:
            self.saida_real = f"{self.base}{os.path.splitext(baixado)[1]}"
            os.replace(baixado, self.saida_real)
        return self.inicio                 # o corte do yt-dlp é exato: começa onde foi pedido

    # ---------- caminho 3: inteiro + corte ----------
    def _inteiro(self):
        import yt_dlp
        modelo = os.path.join(self.pasta_tmp, "inteiro.%(ext)s")
        opcoes = {**self.opcoes_inteiro, "outtmpl": modelo, "postprocessors": [], "writethumbnail": False,
                  "download_ranges": None, "force_keyframes_at_cuts": False,
                  "merge_output_format": "mp4/mkv"}
        opcoes.pop("download_ranges", None)
        with yt_dlp.YoutubeDL(opcoes) as y:
            r = y.process_ie_result(dict(self.info), download=True)
            baixado = ((r or {}).get("requested_downloads") or [{}])[-1].get("filepath")
        if not baixado or not os.path.exists(baixado):
            candidatos = [os.path.join(self.pasta_tmp, x) for x in os.listdir(self.pasta_tmp) if x.startswith("inteiro.")]
            baixado = max(candidatos, key=os.path.getsize) if candidatos else None
        if not baixado:
            raise RuntimeError("Não achei o vídeo baixado para cortar o trecho.")
        return self._finalizar([baixado])
