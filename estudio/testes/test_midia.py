"""Divisão em partes (ffmpeg de verdade) e estimativa de tamanho da prévia (seletor real do yt-dlp)."""
import os
import re
import subprocess

import pytest
import yt_dlp

from nucleo.divisao import dividir
from nucleo.ffmpeg import SEM_JANELA, exe_ffmpeg, ffmpeg_disponivel
from nucleo.previa import estimar_tamanho, tabela_formatos
from nucleo.qualidades import QUALIDADES

pytestmark = pytest.mark.skipif(not ffmpeg_disponivel(), reason="ffmpeg não encontrado")


def _video_teste(caminho, segundos=30):
    """Vídeo com ruído (comprime mal = arquivo grande) + áudio, com keyframe a cada 1 s."""
    subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"nullsrc=s=320x240:r=25:d={segundos},geq=random(1)*255:128:128",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-b:v", "1500k",
                    "-c:a", "aac", "-shortest", str(caminho)], check=True, **SEM_JANELA)


def _tem_audio(caminho):
    r = subprocess.run([exe_ffmpeg(), "-hide_banner", "-i", str(caminho)], capture_output=True, **SEM_JANELA)
    saida = r.stderr.decode(errors="ignore")
    return "Audio:" in saida and "Video:" in saida


def test_dividir_em_partes_abaixo_do_limite(tmp_path):
    video = tmp_path / "Live teste.mp4"
    _video_teste(video, 60)                          # partes têm no mínimo 5 s: precisa de vídeo longo
    tamanho_mb = os.path.getsize(video) / 1024 / 1024
    limite = max(1, int(tamanho_mb / 3))
    partes = dividir(str(video), 60, limite)
    assert len(partes) >= 3
    assert not video.exists()                       # original apagado
    for p in partes:
        assert os.path.getsize(p) <= limite * 1024 * 1024
        assert re.search(r"Live teste - Parte \d\d\.mp4$", p)
        assert _tem_audio(p)


def test_dividir_nao_mexe_em_arquivo_que_ja_cabe(tmp_path):
    video = tmp_path / "curto.mp4"
    _video_teste(video, 3)
    assert dividir(str(video), 3, 400) == [str(video)]
    assert video.exists()


def test_carregar_audio_para_o_whisper(tmp_path):
    from nucleo.transcricao import carregar_audio
    video = tmp_path / "a.mp4"
    _video_teste(video, 2)
    audio = carregar_audio(str(video))
    assert abs(len(audio) - 32000) < 1600 and audio.dtype.name == "float32" and abs(audio).max() <= 1


def test_whisper_cai_para_o_processador_sem_cuda(monkeypatch):
    from nucleo import transcricao
    chamadas = []

    def falso(audio, modelo, dispositivo, avisar):
        chamadas.append(dispositivo)
        if dispositivo == "auto":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return [], "ok", "pt"
    monkeypatch.setattr(transcricao, "carregar_audio", lambda arq: [])
    monkeypatch.setattr(transcricao, "_transcrever", falso)
    assert transcricao.transcrever_whisper("x.mp4", "small", lambda *a: None) == ([], "ok", "pt")
    assert chamadas == ["auto", "cpu"]


# ---------- prévia ----------
# do pior para o melhor, como o yt-dlp entrega depois do extract_info
INFO_FALSA = {
    "id": "x", "title": "t", "duration": 100, "extractor": "generic", "webpage_url": "https://youtu.be/x",
    "formats": [
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none", "format_note": "storyboard",
         "url": "u"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "filesize": 1_000_000,
         "tbr": 128, "url": "u"},
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360,
         "width": 640, "fps": 30, "tbr": 500, "url": "u"},
        {"format_id": "136", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720,
         "width": 1280, "fps": 30, "filesize": 20_000_000, "tbr": 1600, "url": "u"},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080,
         "width": 1920, "fps": 30, "filesize_approx": 50_000_000, "tbr": 4000, "url": "u"},
    ],
}


@pytest.fixture
def ydl():
    with yt_dlp.YoutubeDL({"quiet": True}) as y:
        yield y


def test_estimativa_soma_video_e_audio(ydl):
    assert estimar_tamanho(ydl, INFO_FALSA, QUALIDADES["📱 720p"]) == 21_000_000
    assert estimar_tamanho(ydl, INFO_FALSA, QUALIDADES["🎬 1080p"]) == 51_000_000


def test_estimativa_mp3_usa_bitrate_de_saida(ydl):
    assert estimar_tamanho(ydl, INFO_FALSA, QUALIDADES["🎵 Só áudio (MP3 320k)"]) == 100 * 40_000


def test_estimativa_sem_formato_compativel_retorna_none(ydl):
    assert estimar_tamanho(ydl, INFO_FALSA, {"format": "bv*[height<=100]"}) is None


def test_tabela_formatos_tira_storyboard_e_ordena():
    linhas = tabela_formatos(INFO_FALSA)
    assert [l["id"] for l in linhas] == ["137", "136", "18", "140"]
    assert linhas[0]["vcodec"] == "H.264" and linhas[0]["tem_video"] and not linhas[0]["tem_audio"]
    assert linhas[2]["tem_audio"] and linhas[2]["tamanho"] == 500 * 125 * 100   # pelo bitrate
    assert linhas[3]["resolucao"] == "só áudio" and linhas[3]["acodec"] == "AAC"
