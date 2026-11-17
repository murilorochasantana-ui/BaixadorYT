"""Acha o ffmpeg e roda comandos sem abrir janela preta (copiado do app antigo)."""
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

PASTA_BIN = Path(__file__).resolve().parent.parent / "bin"
SEM_JANELA = {"creationflags": 0x08000000} if os.name == "nt" else {}


@lru_cache(maxsize=1)
def pasta_ffmpeg():
    """Pasta do ffmpeg para passar ao yt-dlp, ou None se o ffmpeg já está no PATH."""
    if shutil.which("ffmpeg"):
        return None
    try:
        import imageio_ffmpeg
        origem = Path(imageio_ffmpeg.get_ffmpeg_exe())
        PASTA_BIN.mkdir(exist_ok=True)
        destino = PASTA_BIN / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not destino.exists():
            shutil.copy2(origem, destino)
            destino.chmod(0o755)
        return str(PASTA_BIN)
    except Exception:
        return None


def exe_ffmpeg():
    pasta = pasta_ffmpeg()
    if pasta:
        return os.path.join(pasta, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return shutil.which("ffmpeg") or "ffmpeg"


def ffmpeg_disponivel():
    return bool(shutil.which("ffmpeg") or pasta_ffmpeg())


def rodar(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **SEM_JANELA)
