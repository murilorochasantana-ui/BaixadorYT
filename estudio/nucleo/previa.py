"""Prévia antes de baixar: título, miniatura, duração, tamanho estimado por qualidade e formatos reais."""
import re

import yt_dlp

from .ffmpeg import pasta_ffmpeg
from .plataformas import plataforma
from .qualidades import BYTES_POR_SEG_CONVERTIDO, ORDEM, QUALIDADES, codec_convertido

GB = 1024 ** 3


def tamanho_formato(f, duracao):
    """Tamanho em bytes de um formato: exato, aproximado ou calculado pelo bitrate."""
    tam = f.get("filesize") or f.get("filesize_approx")
    if tam:
        return int(tam)
    if f.get("tbr") and duracao:
        return int(f["tbr"] * 1000 / 8 * duracao)
    return None


def _tem(f, campo):
    v = f.get(campo)
    return bool(v) and v != "none"


def estimar_tamanho(ydl, info, opcoes):
    """Tamanho estimado (bytes) que a qualidade vai baixar, usando o mesmo seletor do yt-dlp.
    Retorna None quando não dá para saber."""
    duracao = info.get("duration")
    formatos = info.get("formats") or [info]
    try:
        selecionados = ydl._select_formats(formatos, ydl.build_format_selector(opcoes["format"]))
    except Exception:
        selecionados = []
    if not selecionados:
        return None
    escolhido = selecionados[0]
    convertido = codec_convertido(opcoes)
    if convertido in BYTES_POR_SEG_CONVERTIDO and duracao:
        return int(BYTES_POR_SEG_CONVERTIDO[convertido] * duracao)
    partes = escolhido.get("requested_formats") or [escolhido]
    tamanhos = [tamanho_formato(p, duracao) for p in partes]
    if not any(tamanhos):
        return None
    return sum(t for t in tamanhos if t)


def _codec_curto(c):
    if not c or c == "none":
        return ""
    c = c.lower()
    for chave, nome in (("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"),
                        ("vp09", "VP9"), ("vp9", "VP9"), ("av01", "AV1"), ("mp4a", "AAC"),
                        ("aac", "AAC"), ("opus", "Opus"), ("mp3", "MP3")):
        if c.startswith(chave):
            return nome
    return c.split(".")[0]


def tabela_formatos(info):
    """Formatos reais do vídeo para o modo Avançado (sem storyboards)."""
    duracao = info.get("duration")
    linhas = []
    for f in info.get("formats") or []:
        tem_v, tem_a = _tem(f, "vcodec"), _tem(f, "acodec")
        sem_nada = f.get("vcodec") == "none" and f.get("acodec") == "none"
        if f.get("format_note") == "storyboard" or f.get("ext") == "mhtml" or sem_nada:
            continue
        altura = f.get("height")
        if tem_v:
            res = f"{f.get('width') or '?'}x{altura}" if altura else (f.get("resolution") or "vídeo")
        else:
            res = "só áudio"
        linhas.append({
            "id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolucao": res,
            "altura": altura or 0,
            "fps": round(f["fps"]) if f.get("fps") else None,
            "vcodec": _codec_curto(f.get("vcodec")),
            "acodec": _codec_curto(f.get("acodec")),
            "tem_video": tem_v or (f.get("vcodec") is None and bool(altura)),
            "tem_audio": tem_a or (f.get("acodec") is None and not tem_v),
            "tamanho": tamanho_formato(f, duracao),
            "tbr": round(f["tbr"]) if f.get("tbr") else None,
            "nota": f.get("format_note") or "",
        })
    linhas.sort(key=lambda x: (not x["tem_video"], -(x["altura"] or 0), -(x["fps"] or 0), -(x["tbr"] or 0)))
    return linhas


def ler_previa(url, login_opts=None, aviso_gb=3):
    """Lê as informações do vídeo sem baixar. Pode demorar alguns segundos (roda fora da janela)."""
    opcoes = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
              "playlist_items": "1-20", "noprogress": True}
    if pasta_ffmpeg():
        opcoes["ffmpeg_location"] = pasta_ffmpeg()
    opcoes.update(login_opts or {})
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=False)
        entradas = [e for e in (info.get("entries") or []) if e]
        principal = entradas[0] if entradas else info
        tamanhos = {}
        for nome in ORDEM:
            if nome in QUALIDADES:
                tamanhos[nome] = estimar_tamanho(ydl, principal, QUALIDADES[nome])
    titulo = re.sub(r"\s+", " ", principal.get("title") or info.get("title") or url).strip()
    maior = max([t for t in tamanhos.values() if t] or [0])
    return {
        "url": url,
        "plataforma": plataforma(url),
        "titulo": titulo,
        "canal": principal.get("uploader") or principal.get("channel") or "",
        "duracao": principal.get("duration"),
        "miniatura": principal.get("thumbnail"),
        "ao_vivo": bool(principal.get("is_live")),
        "itens": len(entradas) if entradas else 1,
        "tem_legenda": bool(principal.get("subtitles") or principal.get("automatic_captions")),
        "tamanhos": tamanhos,
        "formatos": tabela_formatos(principal),
        "aviso_gb": aviso_gb,
        "grande": bool(maior and maior > aviso_gb * GB),
    }
