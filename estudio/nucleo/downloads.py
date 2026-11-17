"""Fila de downloads (lógica do app antigo, sem Tkinter).

A fila roda numa thread de trabalho e conversa com a interface só por eventos (dicionários)
entregues à função `emitir`. Na Fase 1B entram: pausar/cancelar/retomar, vários ao mesmo tempo,
histórico, trecho e notificação.
"""
import itertools
import os
import queue
import re
import threading
from dataclasses import dataclass, field

import yt_dlp

from .divisao import dividir
from .erros import explicar_erro, limpar_mensagem
from .ffmpeg import pasta_ffmpeg
from .plataformas import plataforma
from .qualidades import opcoes_qualidade
from .transcricao import gerar_transcricao, gravar_falha

EXTS_MIDIA = (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".wav")
_contador = itertools.count(1)


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
    id: str = field(default_factory=lambda: f"d{next(_contador)}")


def montar_opcoes(pedido, gancho):
    """Opções do yt-dlp para um pedido (função separada para dar para testar)."""
    if pedido.limite_mb:
        modelo = os.path.join(pedido.pasta, "%(playlist_title,title).80B [%(playlist_id,id)s]",
                              "%(title).80B%(playlist_index& - |)s%(playlist_index|)s.%(ext)s")
    else:
        modelo = os.path.join(pedido.pasta, "%(title).150B [%(id)s].%(ext)s")
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
    }
    if pasta_ffmpeg():
        opcoes["ffmpeg_location"] = pasta_ffmpeg()
    opcoes.update(opcoes_qualidade(pedido.qualidade, pedido.formato_avancado))
    opcoes.update(pedido.login_opts or {})
    return opcoes


class Gerenciador:
    def __init__(self, emitir):
        self.emitir = emitir
        self.fila = queue.Queue()
        threading.Thread(target=self._trabalhador, daemon=True, name="downloads").start()

    def adicionar(self, pedido):
        self.fila.put(pedido)
        self.emitir({"tipo": "download", "id": pedido.id, "status": "Na fila", "pct": 0,
                     "titulo": f"[{plataforma(pedido.url)}] {pedido.url}"})
        return pedido.id

    def na_fila(self):
        return self.fila.qsize()

    def _trabalhador(self):
        while True:
            pedido = self.fila.get()
            try:
                self.baixar(pedido)
            except Exception as e:  # nunca deixa a thread morrer
                self.emitir({"tipo": "download", "id": pedido.id, "status": "✘ Erro", "fim": True,
                             "erro": f"Erro inesperado: {e}"})

    def baixar(self, pedido):
        enviar = lambda **d: self.emitir({"tipo": "download", "id": pedido.id, **d})

        def gancho(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                feito = d.get("downloaded_bytes") or 0
                pct = feito * 100 / total if total else 0
                enviar(status=f"{pct:.0f}%", pct=pct, vel=(d.get("_speed_str") or "").strip(),
                       eta=(d.get("_eta_str") or "").strip())
            elif d["status"] == "finished":
                enviar(status="Juntando...", pct=100)

        arquivos_finais = []
        try:
            os.makedirs(pedido.pasta, exist_ok=True)
            opcoes = montar_opcoes(pedido, gancho)
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                enviar(status="Lendo vídeo...", pct=0)
                info = ydl.extract_info(pedido.url, download=False)
                if info.get("is_live"):
                    raise RuntimeError("Isso é uma live acontecendo agora. Espere ela terminar e baixe o VOD "
                                       "(na Twitch: aba Vídeos do canal) ou um clipe.")
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
                            gerar_transcricao(ydl, item, arq, pedido.url, pedido.modelo_whisper,
                                              lambda t, p=None: enviar(status=t, **({"pct": p} if p is not None else {})))
                        except Exception as e:
                            gravar_falha(arq, item, pedido.url, e)
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
                    partes += dividir(arq, item.get("duration"), pedido.limite_mb, lambda t: enviar(status=t))
                enviar(status=f"✔ {len(partes)} partes" if len(partes) > 1 else "✔ Concluído",
                       pct=100, fim=True, arquivos=partes, pasta=pasta_video)
                return
            enviar(status="✔ Concluído", pct=100, fim=True, arquivos=arquivos_finais, pasta=pedido.pasta)
        except Exception as e:
            enviar(status="✘ Erro", fim=True, erro=explicar_erro(limpar_mensagem(e), pedido.login))
