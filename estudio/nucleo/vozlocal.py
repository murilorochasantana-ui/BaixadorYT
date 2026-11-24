"""Aba "Voz": liga o VozLocal (gerador de voz offline, projeto separado em D:\\VozLocal).

O VozLocal tem o próprio Python (venv com PyTorch) e a própria interface (Gradio em 127.0.0.1).
O Estúdio só liga o programa escondido, espera ficar pronto e mostra a página dentro da janela.
Se o usuário já abriu o VozLocal pelo atalho, o Estúdio usa esse mesmo.
Ao fechar o Estúdio, ele desliga só o VozLocal que ele mesmo ligou.
"""
import atexit
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PASTA_PADRAO = r"D:\VozLocal"
PORTA = 7860
TITULO = "VozLocal"
ESPERA_MAX = 120  # segundos para o VozLocal abrir (a 1ª vez carrega o PyTorch)

MSG_NAO_INSTALADO = (
    "O VozLocal não foi encontrado em {pasta}.\n\n"
    "Ele é instalado à parte: dê dois cliques no instalar.bat da pasta D:\\VozLocal e depois volte aqui."
)
MSG_PORTA_OCUPADA = (
    "Outro programa está usando a porta {porta} do PC, então o VozLocal não conseguiu abrir.\n\n"
    "Feche outros geradores de voz/IA que estejam abertos e tente de novo."
)
MSG_DEMOROU = (
    "O VozLocal demorou demais para abrir.\n\n"
    "Tente abrir pelo atalho VozLocal da Área de Trabalho para ver a mensagem de erro na janela preta."
)

_trava = threading.Lock()
_processo: subprocess.Popen | None = None


def url(porta: int | None = None) -> str:
    return f"http://127.0.0.1:{porta or PORTA}/"


def python_do_vozlocal(pasta: str | os.PathLike) -> Path:
    return Path(pasta) / ".venv" / "Scripts" / "python.exe"


def instalado(pasta: str | os.PathLike) -> bool:
    return python_do_vozlocal(pasta).exists() and (Path(pasta) / "app.py").exists()


def quem_esta_na_porta(porta: int | None = None, tempo: float = 1.5) -> str | None:
    """None = porta livre; "vozlocal" = o VozLocal está aberto; "outro" = outro programa."""
    porta = porta or PORTA
    try:
        with urllib.request.urlopen(url(porta) + "config", timeout=tempo) as r:
            dados = json.loads(r.read().decode("utf-8", "replace"))
        return "vozlocal" if dados.get("title") == TITULO else "outro"
    except urllib.error.HTTPError:
        return "outro"
    except (urllib.error.URLError, OSError, ValueError):
        # recusou a conexão = ninguém ouvindo; resposta que não é JSON = outro programa
        return None if _porta_livre(porta) else "outro"


def _porta_livre(porta: int) -> bool:
    import socket

    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) != 0


def estado(pasta: str | os.PathLike) -> dict:
    quem = quem_esta_na_porta()
    return {
        "instalado": instalado(pasta),
        "rodando": quem == "vozlocal",
        "url": url(),
        "pasta": str(pasta),
        "ligado_pelo_estudio": _processo is not None and _processo.poll() is None,
    }


def ligar(pasta: str | os.PathLike, espera_max: float = ESPERA_MAX) -> dict:
    """Liga o VozLocal (se ainda não estiver aberto) e espera ele responder.

    Devolve {"ok": True, "url": ...} ou {"ok": False, "erro": mensagem em português}.
    """
    global _processo
    with _trava:
        quem = quem_esta_na_porta()
        if quem == "vozlocal":
            return {"ok": True, "url": url()}
        if quem == "outro":
            return {"ok": False, "erro": MSG_PORTA_OCUPADA.format(porta=PORTA)}
        if not instalado(pasta):
            return {"ok": False, "erro": MSG_NAO_INSTALADO.format(pasta=pasta)}

        if _processo is None or _processo.poll() is not None:
            ambiente = dict(os.environ, GRADIO_SERVER_PORT=str(PORTA), PYTHONIOENCODING="utf-8")
            # o Python do Estúdio não pode vazar para o venv do VozLocal
            for chave in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                ambiente.pop(chave, None)
            _processo = subprocess.Popen(
                [str(python_do_vozlocal(pasta)), "app.py", "--sem-navegador"],
                cwd=str(pasta),
                env=ambiente,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        fim = time.monotonic() + espera_max
        while time.monotonic() < fim:
            if _processo.poll() is not None:
                _processo = None
                return {
                    "ok": False,
                    "erro": "O VozLocal fechou sozinho ao abrir. Abra pelo atalho VozLocal da "
                    "Área de Trabalho para ver a mensagem de erro na janela preta.",
                }
            if quem_esta_na_porta(tempo=1.0) == "vozlocal":
                return {"ok": True, "url": url()}
            time.sleep(0.5)
        return {"ok": False, "erro": MSG_DEMOROU}


def desligar() -> None:
    """Desliga o VozLocal só se foi o Estúdio que ligou (o aberto pelo atalho continua)."""
    global _processo
    p, _processo = _processo, None
    if p is None or p.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()


atexit.register(desligar)
