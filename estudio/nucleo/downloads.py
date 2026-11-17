"""Fila de downloads (lógica do app antigo, sem Tkinter) com pausar, cancelar, retomar,
vários ao mesmo tempo, trecho, miniatura e histórico.

A fila conversa com a interface só por eventos (dicionários) entregues à função `emitir`.
Cada evento de download traz `estado`: fila, baixando, pausado, cancelado, ok, erro.

Pausar = interromper guardando o arquivo .part; retomar = pôr o mesmo pedido de volta na fila
(o yt-dlp continua do .part). Cancelar = interromper e apagar os pedaços baixados.
"""
import dataclasses
import glob
import itertools
import os
import queue
import re
import threading
from dataclasses import dataclass, field

import yt_dlp
from yt_dlp.utils import download_range_func

from .divisao import dividir
from .erros import explicar_erro, limpar_mensagem
from .ffmpeg import pasta_ffmpeg
from .plataformas import plataforma
from .qualidades import opcoes_qualidade
from .tempos import sufixo_trecho
from .transcricao import gerar_transcricao, gravar_falha

EXTS_MIDIA = (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".wav")
MAX_PARALELOS = 4
_contador = itertools.count(1)


class Interrompido(Exception):
    """Lançada dentro dos ganchos do yt-dlp quando o usuário pausa ou cancela."""
    def __init__(self, motivo):
        super().__init__(f"interrompido: {motivo}")
        self.motivo = motivo


@dataclass
class Pedido:
    url: str
    pasta: str
    qualidade: str
    formato_avancado: dict | None = None
    limite_mb: int | None = None          # None = sem Modo Claude
    login_opts: dict = field(default_factory=dict)
    login: str = "Nenhum"
    modelo_whisper: str | None = None     # None = sem transcrição
    inicio: float | None = None           # trecho (segundos); None = desde o começo
    fim: float | None = None              # None = até o final
    miniatura: bool = False
    id: str = field(default_factory=lambda: f"d{next(_contador)}")
    registro: int | None = None           # linha no histórico

    @property
    def tem_trecho(self):
        return self.inicio is not None or self.fim is not None

    def para_dict(self):
        """O que vai para o histórico (sem login nem ids, que são refeitos ao baixar de novo)."""
        d = dataclasses.asdict(self)
        for k in ("login_opts", "id", "registro"):
            d.pop(k, None)
        return d


def montar_opcoes(pedido, gancho, gancho_pp=None):
    """Opções do yt-dlp para um pedido (função separada para dar para testar)."""
    sufixo = sufixo_trecho(pedido.inicio or 0, pedido.fim) if pedido.tem_trecho else ""
    if pedido.limite_mb:
        modelo = os.path.join(pedido.pasta, "%(playlist_title,title).80B [%(playlist_id,id)s]",
                              "%(title).80B%(playlist_index& - |)s%(playlist_index|)s" + sufixo + ".%(ext)s")
    else:
        modelo = os.path.join(pedido.pasta, "%(title).150B [%(id)s]" + sufixo + ".%(ext)s")
    opcoes = {
        "outtmpl": modelo,
        "noplaylist": True,
        "playlist_items": "1-20",  # posts com vários vídeos (carrossel); nunca um perfil inteiro
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [gancho],
        "windowsfilenames": True,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,        # retomar do .part
    }
    if gancho_pp:
        opcoes["postprocessor_hooks"] = [gancho_pp]
    if pasta_ffmpeg():
        opcoes["ffmpeg_location"] = pasta_ffmpeg()
    qualidade = opcoes_qualidade(pedido.qualidade, pedido.formato_avancado)
    pos = list(qualidade.pop("postprocessors", []))
    opcoes.update(qualidade)
    if pedido.tem_trecho:
        fim = pedido.fim if pedido.fim is not None else float("inf")
        opcoes["download_ranges"] = download_range_func(None, [(pedido.inicio or 0, fim)])
        opcoes["force_keyframes_at_cuts"] = True   # corte exato (recodifica só as pontas)
    if pedido.miniatura:
        opcoes["writethumbnail"] = True
        pos.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
    if pos:
        opcoes["postprocessors"] = pos
    opcoes.update(pedido.login_opts or {})
    return opcoes


class Gerenciador:
    def __init__(self, emitir, paralelos=2, historico=None, ao_terminar=None):
        self.emitir = emitir
        self.historico = historico
        self.ao_terminar = ao_terminar        # chamado com (pedido, evento) quando termina ok/erro
        self.fila = queue.Queue()
        self.pedidos = {}                     # id -> Pedido
        self.estados = {}                     # id -> fila | baixando | pausado | cancelado | ok | erro
        self.pedir = {}                       # id -> "pausar" | "cancelar" (pedido feito durante o download)
        self.temporarios = {}                 # id -> arquivos .part/pedaços do download
        self.titulos = {}                     # id -> título do vídeo (para a notificação)
        self.trava = threading.Lock()
        self.paralelos = 0
        self._trabalhadores = 0
        self.definir_paralelos(paralelos)

    # ---------- configuração ----------
    def definir_paralelos(self, n):
        n = max(1, min(MAX_PARALELOS, int(n or 1)))
        with self.trava:
            self.paralelos = n
            while self._trabalhadores < n:
                i = self._trabalhadores
                threading.Thread(target=self._trabalhador, args=(i,), daemon=True, name=f"download-{i}").start()
                self._trabalhadores += 1
        return n

    # ---------- comandos (chamados pela interface) ----------
    def adicionar(self, pedido):
        with self.trava:
            self.pedidos[pedido.id] = pedido
            self.estados[pedido.id] = "fila"
        if self.historico and pedido.registro is None:
            pedido.registro = self.historico.registrar(pedido.para_dict())
        self.fila.put(pedido)
        self._evento(pedido, estado="fila", status="Na fila", pct=0,
                     titulo=f"[{plataforma(pedido.url)}] {pedido.url}")
        return pedido.id

    def pausar(self, id_):
        with self.trava:
            est = self.estados.get(id_)
            if est == "fila":
                self.estados[id_] = "pausado"
            elif est == "baixando":
                self.pedir[id_] = "pausar"
                return True
            else:
                return False
        self._evento(self.pedidos[id_], estado="pausado", status="⏸ Pausado")
        return True

    def retomar(self, id_):
        """Volta para a fila um download pausado, cancelado ou com erro."""
        with self.trava:
            if self.estados.get(id_) not in ("pausado", "cancelado", "erro"):
                return False
            self.estados[id_] = "fila"
            pedido = self.pedidos[id_]
        self.fila.put(pedido)
        self._evento(pedido, estado="fila", status="Na fila", erro=None)
        return True

    def cancelar(self, id_):
        with self.trava:
            est = self.estados.get(id_)
            if est in ("fila", "pausado"):
                self.estados[id_] = "cancelado"
            elif est == "baixando":
                self.pedir[id_] = "cancelar"
                return True
            else:
                return False
        self._apagar_temporarios(id_)
        self._evento(self.pedidos[id_], estado="cancelado", status="✖ Cancelado", pct=0)
        return True

    def na_fila(self):
        with self.trava:
            return sum(1 for e in self.estados.values() if e in ("fila", "baixando"))

    # ---------- internos ----------
    def _evento(self, pedido, **d):
        if "estado" in d and d["estado"] in ("ok", "erro", "cancelado", "pausado"):
            d["fim"] = True
        if d.get("titulo"):
            self.titulos[pedido.id] = d["titulo"]
        self.emitir({"tipo": "download", "id": pedido.id, **{k: v for k, v in d.items() if v is not None or k == "erro"}})
        if self.historico and pedido.registro:
            campos = {}
            if d.get("estado"):
                campos["status"] = d["estado"]
            if d.get("titulo") and not d["titulo"].endswith(pedido.url):
                campos["titulo"] = d["titulo"].split("] ", 1)[-1]
            if "erro" in d and d.get("estado") in ("erro", "fila"):
                campos["erro"] = d["erro"]
            if d.get("arquivos") is not None:
                campos["arquivos"] = d["arquivos"]
            if d.get("pasta"):
                campos["pasta"] = d["pasta"]
            try:
                self.historico.atualizar(pedido.registro, **campos)
            except Exception:
                pass  # o histórico nunca pode derrubar um download

    def _checar(self, pedido):
        motivo = self.pedir.get(pedido.id)
        if motivo:
            raise Interrompido(motivo)

    def _trabalhador(self, indice):
        while True:
            if indice >= self.paralelos:       # usuário diminuiu o número de downloads ao mesmo tempo
                threading.Event().wait(0.5)
                continue
            try:
                pedido = self.fila.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.trava:
                if self.estados.get(pedido.id) != "fila":
                    continue                    # foi pausado/cancelado enquanto esperava
                self.estados[pedido.id] = "baixando"
                self.pedir.pop(pedido.id, None)
            try:
                self.baixar(pedido)
            except Exception as e:  # nunca deixa a thread morrer
                self._terminar(pedido, "erro", status="✘ Erro", erro=f"Erro inesperado: {e}")

    def _terminar(self, pedido, estado, **d):
        with self.trava:
            self.estados[pedido.id] = estado
            self.pedir.pop(pedido.id, None)
        self._evento(pedido, estado=estado, **d)
        if estado in ("ok", "erro") and self.ao_terminar:
            try:
                self.ao_terminar(pedido, {"estado": estado, "titulo": self.titulos.get(pedido.id, pedido.url), **d})
            except Exception:
                pass

    def _apagar_temporarios(self, id_):
        """Apaga os pedaços de um download cancelado (.part, fragmentos, formatos ainda não juntados)."""
        for base in self.temporarios.pop(id_, set()):
            for arq in glob.glob(glob.escape(base) + "*"):
                if arq.endswith((".part", ".ytdl")) or ".part-Frag" in arq or re.search(r"\.f[\w-]+\.\w+(\.part)?$", arq):
                    try:
                        os.remove(arq)
                    except OSError:
                        pass

    def baixar(self, pedido):
        enviar = lambda **d: self._evento(pedido, **d)
        temporarios = self.temporarios.setdefault(pedido.id, set())

        def gancho(d):
            self._checar(pedido)
            for chave in ("tmpfilename", "filename"):
                if d.get(chave):
                    temporarios.add(d[chave])
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                feito = d.get("downloaded_bytes") or 0
                pct = feito * 100 / total if total else 0
                enviar(estado="baixando", status=f"{pct:.0f}%", pct=pct,
                       vel=(d.get("_speed_str") or "").strip(), eta=(d.get("_eta_str") or "").strip())
            elif d["status"] == "finished":
                enviar(status="Juntando...", pct=100)

        def gancho_pp(d):
            self._checar(pedido)
            if d.get("status") == "started" and d.get("postprocessor") in ("Merger", "FFmpegMerger"):
                enviar(status="Juntando áudio e vídeo...")

        def avisar(t, p=None):
            self._checar(pedido)
            enviar(status=t, **({"pct": p} if p is not None else {}))

        arquivos_finais = []
        trecho = (pedido.inicio or 0.0, pedido.fim) if pedido.tem_trecho else None
        try:
            os.makedirs(pedido.pasta, exist_ok=True)
            opcoes = montar_opcoes(pedido, gancho, gancho_pp)
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                enviar(estado="baixando", status="Lendo vídeo...", pct=0)
                info = ydl.extract_info(pedido.url, download=False)
                self._checar(pedido)
                if info.get("is_live"):
                    raise RuntimeError("Isso é uma live acontecendo agora. Espere ela terminar e baixe o VOD "
                                       "(na Twitch: aba Vídeos do canal) ou um clipe.")
                if pedido.inicio and info.get("duration") and pedido.inicio >= info["duration"]:
                    raise RuntimeError("O início do trecho passa da duração do vídeo. Confira o tempo digitado.")
                titulo = info.get("title") or info.get("description") or pedido.url
                titulo = re.sub(r"\s+", " ", titulo).strip()[:90]
                enviar(titulo=f"[{plataforma(pedido.url)}] {titulo}")
                destino = ydl.prepare_filename(info)
                info = ydl.process_ie_result(info, download=True) or info
                itens = [e for e in (info.get("entries") or []) if e] or [info]
                for item in itens:
                    downs = item.get("requested_downloads") or [{}]
                    arq = downs[-1].get("filepath") or item.get("filepath") or ydl.prepare_filename(item)
                    arquivos_finais.append(arq)
                    if pedido.modelo_whisper:
                        try:
                            gerar_transcricao(ydl, item, arq, pedido.url, pedido.modelo_whisper, avisar, trecho)
                        except Interrompido:
                            raise
                        except Exception as e:
                            gravar_falha(arq, item, pedido.url, e, trecho)
            if pedido.limite_mb:
                pasta_video = os.path.dirname(destino)
                arquivos = [os.path.join(pasta_video, x) for x in os.listdir(pasta_video)
                            if x.lower().endswith(EXTS_MIDIA) and " - Parte " not in x]
                if not arquivos:
                    raise RuntimeError("Arquivo baixado não encontrado na pasta do vídeo.")
                partes = []
                for arq in sorted(arquivos):
                    item = next((e for e in (info.get("entries") or []) if e and e.get("title")
                                 and os.path.basename(arq).startswith(e["title"][:20])), info)
                    duracao = (pedido.fim or item.get("duration") or 0) - (pedido.inicio or 0) if trecho \
                        else item.get("duration")
                    partes += dividir(arq, duracao, pedido.limite_mb, lambda t: avisar(t))
                self.temporarios.pop(pedido.id, None)
                self._terminar(pedido, "ok", status=f"✔ {len(partes)} partes" if len(partes) > 1 else "✔ Concluído",
                               pct=100, arquivos=partes, pasta=pasta_video)
                return
            self.temporarios.pop(pedido.id, None)
            self._terminar(pedido, "ok", status="✔ Concluído", pct=100, arquivos=arquivos_finais, pasta=pedido.pasta)
        except Exception as e:
            motivo = self.pedir.get(pedido.id) or (e.motivo if isinstance(e, Interrompido) else None)
            if motivo == "pausar":
                self._terminar(pedido, "pausado", status="⏸ Pausado")
            elif motivo == "cancelar":
                self._apagar_temporarios(pedido.id)
                self._terminar(pedido, "cancelado", status="✖ Cancelado", pct=0)
            else:
                self._terminar(pedido, "erro", status="✘ Erro",
                               erro=explicar_erro(limpar_mensagem(e), pedido.login))
