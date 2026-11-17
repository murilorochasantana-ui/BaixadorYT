"""Fase 1C: lives da Twitch em andamento.

- `tipo_live(info)`: diz se o que o yt-dlp leu é uma live e se ela tem VOD sendo gerado.
  Com `live_from_start` o yt-dlp troca o link do canal (twitch.tv/<canal>) pelo VOD da live atual
  (twitch.tv/videos/<id>). Esse VOD é uma playlist HLS do tipo EVENT, que cresce enquanto a live
  continua, e o ffmpeg consegue pular para qualquer ponto dela: o trecho do nucleo/trecho.py
  (caminho "hls") funciona sem mudar nada.
- `gravar_live`: quando o canal não guarda VOD, grava a partir de agora até o usuário clicar em Parar.
  Lê a playlist da live e baixa os segmentos novos, pulando os anúncios que a Twitch encaixa (com o
  ffmpeg lendo direto, os 30 s de anúncio do começo entravam na gravação). Grava em .ts (se o PC
  desligar no meio, o que já foi gravado continua abrindo) e no fim passa para .mp4 sem recodificar.
"""
import os
import time
from urllib.parse import urljoin

from .controle import Interrompido
from .ffmpeg import exe_ffmpeg, rodar_cancelavel

MSG_LIVE_TRECHO = ("Essa live está acontecendo agora e o Estúdio achou o VOD que está sendo gerado.\n\n"
                   "Marque \"✂️ Baixar só um trecho\" e escolha o Início e o Fim do que já passou "
                   "(ex.: Início 5:30:00, Fim 5:32:00).")
MSG_LIVE_SEM_VOD = ("Esse canal está ao vivo, mas não guarda VOD (ou a Twitch ainda não liberou).\n\n"
                    "Clique em \"🔴 Gravar a partir de agora\" na prévia: o Estúdio grava até você clicar em Parar.")
MSG_LIVE_OUTRA = ("Isso é uma live acontecendo agora. Espere ela terminar e baixe o VOD "
                  "(na Twitch: aba Vídeos do canal) ou um clipe.")
MSG_NAO_AO_VIVO = ("Esse canal não está ao vivo agora, então não dá para gravar.\n\n"
                   "Para baixar uma live que já terminou, use o link do VOD (na Twitch: aba Vídeos do canal).")


def tipo_live(info):
    """None = não é live; "vod" = live da Twitch com VOD sendo gerado (dá para baixar trecho);
    "gravar" = live da Twitch sem VOD (só gravando a partir de agora); "outra" = live de outro site."""
    if not info or not info.get("is_live"):
        return None
    chave = info.get("extractor_key") or ""
    if chave == "TwitchVod":
        return "vod"
    if chave == "TwitchStream":
        return "gravar"
    return "outra"


def entrada_ffmpeg(ydl, info, fmt):
    """Cabeçalhos e cookies que o ffmpeg precisa para ler `fmt` como o yt-dlp leria."""
    args = []
    cab = {**(info.get("http_headers") or {}), **(fmt.get("http_headers") or {})}
    cookies = ydl.cookiejar.get_cookies_for_url(fmt["url"])
    if cookies:
        args += ["-cookies", "".join(f"{c.name}={c.value}; path={c.path}; domain={c.domain};\r\n" for c in cookies)]
    if cab:
        args += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in cab.items())]
    return args


def _tempo(seg):
    seg = int(seg or 0)
    h, m, s = seg // 3600, seg // 60 % 60, seg % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _segmentos(texto, base_url):
    """Lê uma playlist HLS de mídia: [(url, duração, título)]. O título diz se é anúncio na Twitch."""
    segs, dur, titulo = [], 0.0, ""
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("#EXTINF:"):
            d, _, titulo = linha[8:].partition(",")
            try:
                dur = float(d)
            except ValueError:
                dur = 0.0
        elif linha and not linha.startswith("#"):
            segs.append((urljoin(base_url, linha), dur, titulo.strip()))
            dur, titulo = 0.0, ""
    return segs


def e_anuncio(titulo):
    """Na Twitch, os segmentos da live se chamam "live"; os de anúncio, "Amazon|..." e afins."""
    return bool(titulo) and not titulo.lower().startswith("live")


def _ler(ydl, fmt, url):
    from yt_dlp.networking import Request
    with ydl.urlopen(Request(url, None, {"Accept-Encoding": "identity", **(fmt.get("http_headers") or {})})) as r:
        return r.read()


def gravar_live(ydl, info, base, checar, parar, avisar, intervalo=2.0, max_falhas=10):
    """Grava a live em `base`.mp4 até `parar()` ficar verdadeiro (ou a live acabar).
    Lê a playlist da live a cada `intervalo` s e baixa os segmentos novos, PULANDO os de anúncio
    (a Twitch encaixa ~30 s de anúncio no começo para quem não é inscrito/Turbo).
    `checar()` lança Interrompido para cancelar (apaga o que gravou).
    `avisar(status, arquivo_parcial)` mostra o andamento. Retorna o caminho do .mp4."""
    formatos = info.get("requested_formats") or [info]
    # na Twitch cada qualidade já traz o áudio junto: grava uma playlist só (a de vídeo, se houver)
    fmt = next((f for f in formatos if (f.get("vcodec") or "") != "none"), formatos[0])
    tmp, saida = base + ".gravando.ts", base + ".mp4"
    vistos, falhas = set(), 0
    gravado = anuncio = 0.0
    tamanho = 0
    try:
        with open(tmp, "ab") as arq:
            while not parar():
                checar()
                try:
                    texto = _ler(ydl, fmt, fmt["url"]).decode("utf-8", errors="ignore")
                    falhas = 0
                except Interrompido:
                    raise
                except Exception:
                    falhas += 1
                    if falhas >= max_falhas:
                        break             # a live caiu ou acabou: salva o que já tem
                    texto = ""
                for url, dur, titulo in _segmentos(texto, fmt["url"]):
                    if url in vistos:
                        continue
                    vistos.add(url)
                    if e_anuncio(titulo):
                        anuncio += dur
                        continue
                    if parar():
                        break
                    checar()
                    try:
                        dados = _ler(ydl, fmt, url)
                    except Interrompido:
                        raise
                    except Exception:
                        continue          # um segmento perdido vira um pulo de 2 s, não derruba a gravação
                    arq.write(dados)
                    arq.flush()           # grava na hora: se o PC desligar, o .ts continua abrindo
                    tamanho += len(dados)
                    gravado += dur
                if "#EXT-X-ENDLIST" in texto:
                    break                 # a live terminou
                pulo = f" • pulei {_tempo(anuncio)} de anúncio" if anuncio else ""
                if gravado or not anuncio:
                    avisar(f"🔴 Gravando • {_tempo(gravado)} • {tamanho / 2**20:.0f} MB{pulo} • "
                           "clique em Parar para salvar", tmp)
                else:
                    avisar(f"📺 Esperando o anúncio da Twitch acabar ({_tempo(anuncio)})... "
                           "ele não entra na gravação", tmp)
                fim_espera = time.time() + intervalo
                while time.time() < fim_espera and not parar():
                    checar()
                    time.sleep(0.2)
    except Interrompido:       # cancelar: apaga o que gravou
        _apagar(tmp)
        raise
    if not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
        _apagar(tmp)
        raise RuntimeError("A gravação não recebeu nada da live. Ela pode ter acabado, a conexão caiu ou "
                           "você parou antes do anúncio da Twitch terminar.\n\n"
                           "Tente de novo. Se continuar, rode o atualizar.bat.")
    avisar("Passando a gravação para MP4...", tmp)
    r = rodar_cancelavel([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-i", tmp,
                          "-map", "0", "-c", "copy", "-movflags", "+faststart", saida], checar)
    if r.returncode != 0 or not os.path.isfile(saida):
        _apagar(saida)
        return tmp    # o .ts já serve (abre no VLC/CapCut): melhor entregar ele do que perder a gravação
    _apagar(tmp)
    return saida



def _apagar(caminho):
    try:
        os.remove(caminho)
    except OSError:
        pass
