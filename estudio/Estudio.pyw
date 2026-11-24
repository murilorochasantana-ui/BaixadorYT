#! python3.12
# (linha acima: faz o duplo clique usar o Python 3.12, onde o instalar.bat põe as bibliotecas)
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

TITULO = "Estúdio ViceCityDay"


def perguntar(texto):
    """Caixa Sim/Não. True = Sim."""
    if os.name != "nt":
        return False
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, texto, TITULO, 0x4 | 0x30) == 6  # MB_YESNO|MB_ICONWARNING


def avisar(texto):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, TITULO, 0x30)
    else:
        print(texto)


def main():
    if os.name == "nt":
        try:  # janela nítida em telas com zoom
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    # Só um Estúdio aberto: se já houver outro, a janela dele vem para a frente e este sai.
    from nucleo.config import pasta_dados
    from nucleo.sistema import TravaInstancia, abrir_ou_trazer
    trava = TravaInstancia(pasta_dados())
    if not abrir_ou_trazer(trava, perguntar, avisar, titulo=TITULO):
        sys.exit(0)
    try:
        abrir_janela()
    finally:
        trava.soltar()


def abrir_janela():
    from ponte import Ponte
    ponte = Ponte()
    janela = webview.create_window(
        TITULO,
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
    _limpar_cache_navegador(p)
    return p


def _limpar_cache_navegador(pasta):
    """Apaga o cache HTTP do WebView2 antes de abrir.

    A página vem sempre do mesmo endereço (http://127.0.0.1:42001/index.html) e o WebView2 guardava
    index.html/app.js em cache: depois de uma atualização a janela continuava mostrando a tela antiga
    (24/11: a aba "Voz" não aparecia). As páginas são locais, então não perder nada com isso.
    Os dados do usuário (Local Storage, cookies) ficam em outras pastas e não são tocados.
    """
    import shutil
    padrao = pasta / "EBWebView" / "Default"
    for sub in ("Cache", "Code Cache"):
        shutil.rmtree(padrao / sub, ignore_errors=True)  # em uso por outra janela aberta: segue sem apagar


if __name__ == "__main__":
    main()
