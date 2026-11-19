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


def exe_ffprobe():
    ffmpeg = exe_ffmpeg()
    vizinho = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    return vizinho if os.path.isfile(vizinho) else (shutil.which("ffprobe") or "ffprobe")


def matar_arvore(proc):
    """Encerra o processo E os filhos (no Windows, o ffmpeg pode ter abertos outros processos)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SEM_JANELA)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def matar_ffmpegs_filhos(contendo=None):
    """Encerra os ffmpeg abertos POR este programa (ex.: os que o yt-dlp inicia por dentro e que ele
    não deixa cancelar). Só mexe nos filhos diretos deste processo, nunca em outros ffmpeg do PC.
    `contendo`: só os que têm esse texto na linha de comando (a pasta temporária de UM download),
    para não derrubar os outros downloads que rodam ao mesmo tempo."""
    if os.name != "nt":
        return
    filtro = ""
    if contendo:
        texto = str(contendo).replace("'", "''")
        filtro = f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{texto}') }} | "
    script = (f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={os.getpid()} AND Name='ffmpeg.exe'\" | "
              + filtro + "ForEach-Object { taskkill /F /T /PID $_.ProcessId | Out-Null }")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SEM_JANELA)


def rodar_cancelavel(cmd, checar=lambda: None, ao_ler_linha=None):
    """Roda um comando checando a cada 0,25 s se o usuário pausou/cancelou.
    `checar` lança exceção para parar: o processo (e os filhos) é encerrado na hora.
    `ao_ler_linha` recebe cada linha da saída (usado com `ffmpeg -progress pipe:1`).
    Retorna o CompletedProcess (stderr em bytes)."""
    import queue
    import threading
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if ao_ler_linha else subprocess.DEVNULL,
                            stderr=subprocess.PIPE, **SEM_JANELA)
    erros, linhas = [], queue.Queue()
    leitores = [threading.Thread(target=lambda: erros.append(proc.stderr.read()), daemon=True)]
    if ao_ler_linha:
        leitores.append(threading.Thread(
            target=lambda: [linhas.put(l.decode(errors="ignore").strip()) for l in iter(proc.stdout.readline, b"")],
            daemon=True))
    for t in leitores:
        t.start()
    try:
        while True:
            checar()
            while not linhas.empty():
                ao_ler_linha(linhas.get_nowait())
            if proc.poll() is not None:
                break
            try:
                proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
    except BaseException:
        matar_arvore(proc)
        raise
    for t in leitores:
        t.join(timeout=5)
    while ao_ler_linha and not linhas.empty():
        ao_ler_linha(linhas.get_nowait())
    return subprocess.CompletedProcess(cmd, proc.returncode, None, b"".join(e for e in erros if e))
