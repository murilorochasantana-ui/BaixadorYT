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
import time
from dataclasses import dataclass, field

import yt_dlp

from .controle import Interrompido  # noqa: F401  (reexportado: os testes importam daqui)
from .divisao import dividir
from .erros import explicar_erro, limpar_mensagem
from .ffmpeg import pasta_ffmpeg
from .gravacao import (MSG_LIVE_OUTRA, MSG_LIVE_SEM_VOD, MSG_LIVE_TRECHO, MSG_NAO_AO_VIVO,
                       gravar_live, tipo_live)
from .plataformas import plataforma
from .qualidades import ORDEM_FORMATOS, codec_convertido, opcoes_qualidade
from .plataformas import chave_do_link
from .tempos import sufixo_trecho
from .trecho import Trecho, salvar_miniatura
from .transcricao import gerar_transcricao, gravar_falha

EXTS_MIDIA = (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".wav")
MAX_PARALELOS = 4
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
    inicio: float | None = None           # trecho (segundos); None = desde o começo
    fim: float | None = None              # None = até o final
    miniatura: bool = False
    gravar: bool = False                  # live da Twitch sem VOD: grava a partir de agora até Parar
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
    # Na mesma resolução, prefere H.264 + AAC (sai .mp4, que CapCut/Premiere/Windows abrem bem).
    # Acima de 1080p o YouTube não tem H.264: aí vem AV1/VP9, ainda em .mp4 sempre que der.
    opcoes["format_sort"] = list(ORDEM_FORMATOS)
    # O trecho NÃO usa o download_ranges do yt-dlp (lento: recodifica tudo e não deixa cancelar);
    # quem baixa o trecho é o nucleo/trecho.py. A capa do trecho também é baixada por lá.
    if pedido.miniatura and not pedido.tem_trecho:
        opcoes["writethumbnail"] = True
        pos.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
    if pos:
        opcoes["postprocessors"] = pos
    # Twitch ao vivo: o yt-dlp troca o link do canal pelo VOD que está sendo gerado (dá para baixar trecho).
    # Na gravação, não: aí queremos o sinal da live em si.
    if plataforma(pedido.url) == "Twitch" and not pedido.gravar:
        opcoes["live_from_start"] = True
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
        self.trechos = {}                     # id -> Trecho em andamento (para apagar os pedaços ao cancelar)
        self.rodando = set()                  # ids cuja thread ainda está trabalhando (mesmo pausando/cancelando)
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
        self._evento(pedido, estado="fila", status="Na fila", pct=0, gravacao=pedido.gravar or None,
                     titulo=f"[{plataforma(pedido.url)}] {pedido.url}")
        return pedido.id

    def parar(self, id_):
        """Gravação de live: para de gravar e salva o que já foi gravado."""
        with self.trava:
            p = self.pedidos.get(id_)
            if not p or not p.gravar or self.estados.get(id_) != "baixando":
                return False
            self.pedir[id_] = "parar"
        return True

    def pausar(self, id_):
        p = self.pedidos.get(id_)
        if p and p.gravar and self.estados.get(id_) == "baixando":
            return self.parar(id_)          # live não dá para pausar: Pausar vira Parar e salvar
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
            if id_ in self.rodando:      # ainda encerrando o download anterior: não duplicar
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

    def ja_na_fila(self, url, inicio=None, fim=None):
        """O mesmo vídeo (e mesmo trecho) já está na fila, baixando ou pausado? Evita entrada duplicada."""
        chave = chave_do_link(url)
        with self.trava:
            for id_, est in self.estados.items():
                p = self.pedidos[id_]
                if est in ("fila", "baixando", "pausado") and chave_do_link(p.url) == chave \
                        and (p.inicio, p.fim) == (inicio, fim):
                    return True
        return False

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
        if motivo and motivo != "parar":    # "parar" (gravação) não interrompe: só encerra a gravação
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
            self.rodando.discard(pedido.id)   # o trabalho acabou (ffmpeg já encerrado): pode retomar
        self._evento(pedido, estado=estado, **d)
        if estado in ("ok", "erro") and self.ao_terminar:
            try:
                self.ao_terminar(pedido, {"estado": estado, "titulo": self.titulos.get(pedido.id, pedido.url), **d})
            except Exception:
                pass

    def _apagar_temporarios(self, id_):
        """Apaga os pedaços de um download cancelado (.part, fragmentos, formatos ainda não juntados,
        arquivo temporário da junção) e a pasta de pedaços do trecho."""
        trecho = self.trechos.pop(id_, None)
        if trecho:
            trecho.apagar_temporarios()
        for base in self.temporarios.pop(id_, set()):
            raiz = re.sub(r"\.f[\w-]+\.\w+(\.part)?$|\.part$", "", base)
            for arq in set(glob.glob(glob.escape(base) + "*")) | set(glob.glob(glob.escape(os.path.splitext(raiz)[0]) + ".*")):
                if (arq.endswith((".part", ".ytdl")) or ".part-Frag" in arq or ".temp." in os.path.basename(arq)
                        or re.search(r"\.f[\w-]+\.\w+(\.part)?$", arq)):
                    try:
                        os.remove(arq)
                    except OSError:
                        pass

    def baixar(self, pedido):
        with self.trava:
            self.rodando.add(pedido.id)
        try:
            self._baixar(pedido)
        finally:
            with self.trava:
                self.rodando.discard(pedido.id)

    def _baixar(self, pedido):
        enviar = lambda **d: self._evento(pedido, **d)
        temporarios = self.temporarios.setdefault(pedido.id, set())
        checar = lambda: self._checar(pedido)

        def gancho(d):
            checar()
            for chave in ("tmpfilename", "filename"):
                if d.get(chave):
                    temporarios.add(d[chave])
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                feito = d.get("downloaded_bytes") or 0
                pct = feito * 100 / total if total else 0
                rotulo = "Baixando o vídeo para cortar" if pedido.tem_trecho else ""
                enviar(estado="baixando", status=f"{rotulo} {pct:.0f}%".strip(), pct=pct,
                       vel=(d.get("_speed_str") or "").strip(), eta=(d.get("_eta_str") or "").strip(),
                       arquivo_parcial=d.get("tmpfilename"))   # o explorador mostra o progresso no .part
            elif d["status"] == "finished":
                enviar(status="Juntando...", pct=100)

        def gancho_pp(d):
            checar()
            if d.get("status") == "started" and d.get("postprocessor") in ("Merger", "FFmpegMerger"):
                enviar(status="Juntando áudio e vídeo...")

        def avisar(t, p=None):
            checar()
            enviar(status=t, **({"pct": p} if p is not None else {}))

        def avisar_trecho(status, pct=None, vel="", eta=""):
            checar()
            tr = self.trechos.get(pedido.id)
            enviar(estado="baixando", status=status, pct=pct, vel=vel or None, eta=eta or None,
                   arquivo_parcial=getattr(tr, "pasta_tmp", None))

        arquivos_finais = []
        trecho = None
        try:
            os.makedirs(pedido.pasta, exist_ok=True)
            opcoes = montar_opcoes(pedido, gancho, gancho_pp)
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                enviar(estado="baixando", status="Lendo vídeo...", pct=0)
                info = ydl.extract_info(pedido.url, download=False)
                checar()
                live = tipo_live(info)
                if pedido.gravar and live != "gravar":
                    raise RuntimeError(MSG_NAO_AO_VIVO)
                if live == "vod" and not pedido.tem_trecho:
                    raise RuntimeError(MSG_LIVE_TRECHO)
                if live == "gravar" and not pedido.gravar:
                    raise RuntimeError(MSG_LIVE_SEM_VOD)
                if live == "outra":
                    raise RuntimeError(MSG_LIVE_OUTRA)
                titulo = info.get("title") or info.get("description") or pedido.url
                titulo = re.sub(r"\s+", " ", titulo).strip()[:90]
                enviar(titulo=f"[{plataforma(pedido.url)}] {titulo}")
                destino = ydl.prepare_filename(info)

                if pedido.gravar:
                    base = os.path.splitext(destino)[0] + time.strftime(" (gravado %d-%m %Hh%M)")
                    arq = gravar_live(ydl, info, base, checar, lambda: self.pedir.get(pedido.id) == "parar",
                                      lambda t, parcial: enviar(estado="baixando", status=t, arquivo_parcial=parcial))
                    arquivos_finais.append(arq)
                    itens_transcrever = [(info, arq)]
                elif pedido.tem_trecho:
                    # trecho: baixa só a parte pedida (nucleo/trecho.py) e corta sem recodificar
                    item = next((e for e in (info.get("entries") or []) if e), info)
                    base = os.path.splitext(ydl.prepare_filename(item))[0]
                    tr = Trecho(ydl, item, base, pedido.inicio, pedido.fim, checar, avisar_trecho,
                                codec_convertido(opcoes_qualidade(pedido.qualidade, pedido.formato_avancado)),
                                opcoes_inteiro=opcoes,
                                ao_fallback=lambda motivo: enviar(
                                    aviso="O método rápido de trecho falhou e o Estúdio usou o do yt-dlp "
                                          "(mais lento, mas funciona).", aviso_tecnico=motivo))
                    self.trechos[pedido.id] = tr
                    arq, inicio_real, fim_real = tr.baixar()
                    trecho = (inicio_real, fim_real)
                    arquivos_finais.append(arq)
                    if pedido.miniatura:
                        enviar(status="Salvando a miniatura...")
                        salvar_miniatura(ydl, item, base)
                    itens_transcrever = [(item, arq)]
                else:
                    info = ydl.process_ie_result(info, download=True) or info
                    itens_transcrever = []
                    for item in [e for e in (info.get("entries") or []) if e] or [info]:
                        downs = item.get("requested_downloads") or [{}]
                        arq = downs[-1].get("filepath") or item.get("filepath") or ydl.prepare_filename(item)
                        arquivos_finais.append(arq)
                        itens_transcrever.append((item, arq))

                if pedido.modelo_whisper:
                    for item, arq in itens_transcrever:
                        try:
                            gerar_transcricao(ydl, item, arq, pedido.url, pedido.modelo_whisper, avisar, trecho)
                        except Interrompido:
                            raise
                        except Exception as e:
                            gravar_falha(arq, item, pedido.url, e, trecho)

            self.trechos.pop(pedido.id, None)
            if pedido.limite_mb:
                pasta_video = os.path.dirname(destino)
                midias = [a for a in arquivos_finais if a and os.path.isfile(a) and a.lower().endswith(EXTS_MIDIA)]
                if not midias:   # segurança: procura na pasta do vídeo
                    midias = [os.path.join(pasta_video, x) for x in os.listdir(pasta_video)
                              if x.lower().endswith(EXTS_MIDIA) and " - Parte " not in x]
                if not midias:
                    raise RuntimeError("Arquivo baixado não encontrado na pasta do vídeo.")
                partes = []
                for arq in sorted(midias):
                    item = next((e for e in (info.get("entries") or []) if e and e.get("title")
                                 and os.path.basename(arq).startswith(e["title"][:20])), info)
                    duracao = ((trecho[1] or item.get("duration") or 0) - trecho[0]) if trecho else item.get("duration")
                    partes += dividir(arq, duracao, pedido.limite_mb, lambda t: avisar(t), checar)
                self.temporarios.pop(pedido.id, None)
                self._terminar(pedido, "ok", status=f"✔ {len(partes)} partes" if len(partes) > 1 else "✔ Concluído",
                               pct=100, arquivos=partes, pasta=pasta_video)
                return
            self.temporarios.pop(pedido.id, None)
            self._terminar(pedido, "ok", status="✔ Concluído", pct=100, arquivos=arquivos_finais,
                           pasta=os.path.dirname(arquivos_finais[0]) if arquivos_finais else pedido.pasta)
        except Exception as e:
            motivo = self.pedir.get(pedido.id) or (e.motivo if isinstance(e, Interrompido) else None)
            if motivo == "pausar":
                self._terminar(pedido, "pausado", status="⏸ Pausado")
            elif motivo == "cancelar":
                self._apagar_temporarios(pedido.id)
                self._terminar(pedido, "cancelado", status="✖ Cancelado", pct=0)
            else:
                self.trechos.pop(pedido.id, None)
                self._terminar(pedido, "erro", status="✘ Erro",
                               erro=explicar_erro(limpar_mensagem(e), pedido.login))