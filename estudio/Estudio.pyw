"""
Estúdio ViceCityDay
Abre com duplo clique (sem terminal). Interface web numa janela do Windows (pywebview + WebView2).
"""
import os
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))


def avisar_e_sair(texto):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, "Estúdio ViceCityDay", 0x10)
    else:
        print(texto)
    sys.exit(1)


try:
    import webview
    import yt_dlp  # noqa: F401
except ImportError as e:
    avisar_e_sair(f"Falta instalar uma parte do Estúdio ({e.name}).\n\n"
                  "Dê dois cliques no instalar.bat (pasta estudio) e abra de novo.")

from ponte import Ponte  # noqa: E402


def main():
    if os.name == "nt":
        try:  # janela nítida em telas com zoom
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    ponte = Ponte()
    janela = webview.create_window(
        "Estúdio ViceCityDay",
        url=str(PASTA / "interface" / "index.html"),
        js_api=ponte,
        width=1220, height=800, min_size=(900, 620),
        background_color="#0f0d14",
        text_select=True,
    )
    ponte._ligar(janela)
    icone = PASTA / "recursos" / "icone.ico"  # no Windows o ícone precisa ser .ico
    webview.start(http_server=True, debug=bool(os.environ.get("ESTUDIO_DEBUG")),
                  private_mode=False, storage_path=str(_pasta_navegador()),
                  icon=str(icone) if icone.exists() else None)


def _pasta_navegador():
    from nucleo.config import pasta_dados
    p = pasta_dados() / "navegador"
    p.mkdir(exist_ok=True)
    return p


if __name__ == "__main__":
    main()
