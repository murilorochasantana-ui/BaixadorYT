"""Qualidades de download. As 5 primeiras têm o MESMO nome do app antigo (o config.json antigo continua valendo)."""
import copy

AVANCADO = "⚙️ Avançado (escolher o formato)"

QUALIDADES = {
    "🏆 Melhor qualidade (até 4K/8K)": {"format": "bv*+ba/b", "merge_output_format": "mp4/mkv"},
    "🎬 1080p": {"format": "bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4/mkv"},
    "📱 720p": {"format": "bv*[height<=720]+ba/b[height<=720]/b", "merge_output_format": "mp4/mkv"},
    "✂️ Para edição (H.264 - CapCut/Premiere)": {
        "format": "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
    },
    "🎵 Só áudio (MP3 320k)": {
        "format": "ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
    },
    # ---- novas ----
    "🖥️ 4K (2160p)": {"format": "bv*[height<=2160]+ba/b[height<=2160]/b", "merge_output_format": "mp4/mkv"},
    "🖥️ 1440p": {"format": "bv*[height<=1440]+ba/b[height<=1440]/b", "merge_output_format": "mp4/mkv"},
    "🎵 Só áudio (M4A)": {
        "format": "ba[ext=m4a]/ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    },
    "🎵 Só áudio (WAV)": {
        "format": "ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
    },
    "🎞️ Só vídeo (sem áudio)": {"format": "bv", "merge_output_format": "mp4/mkv"},
}

# ordem em que aparecem na lista
ORDEM = [
    "🏆 Melhor qualidade (até 4K/8K)", "🖥️ 4K (2160p)", "🖥️ 1440p", "🎬 1080p", "📱 720p",
    "✂️ Para edição (H.264 - CapCut/Premiere)", "🎵 Só áudio (MP3 320k)", "🎵 Só áudio (M4A)",
    "🎵 Só áudio (WAV)", "🎞️ Só vídeo (sem áudio)", AVANCADO,
]

# Ordem de preferência entre formatos da MESMA qualidade (yt-dlp "format_sort"): resolução e fps
# primeiro (nunca troca qualidade por compatibilidade), depois H.264 + AAC em MP4.
ORDEM_FORMATOS = ("res", "fps", "vcodec:h264", "acodec:aac", "ext:mp4:m4a")

# bitrate de saída quando o áudio é convertido (para estimar o tamanho), em bytes por segundo
BYTES_POR_SEG_CONVERTIDO = {"mp3": 320_000 / 8, "wav": 44_100 * 2 * 2}


def nome_valido(nome):
    return nome in QUALIDADES or nome == AVANCADO


def opcoes_qualidade(nome, formato_avancado=None):
    """Opções do yt-dlp para a qualidade escolhida.
    formato_avancado: {"id": "137", "tem_video": True, "tem_audio": False} (só no modo Avançado)."""
    if nome == AVANCADO:
        if not formato_avancado or not formato_avancado.get("id"):
            raise ValueError("No modo Avançado, escolha um formato na tabela antes de baixar.")
        fid = str(formato_avancado["id"])
        if formato_avancado.get("tem_video") and not formato_avancado.get("tem_audio"):
            # formato só de vídeo: junta com o melhor áudio para não sair mudo
            return {"format": f"{fid}+ba/{fid}", "merge_output_format": "mp4/mkv"}
        return {"format": fid}
    return copy.deepcopy(QUALIDADES[nome])


def codec_convertido(opcoes):
    for pp in opcoes.get("postprocessors", []):
        if pp.get("key") == "FFmpegExtractAudio":
            return pp.get("preferredcodec")
    return None
