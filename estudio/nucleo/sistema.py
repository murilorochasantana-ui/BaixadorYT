"""Coisas do Windows: área de transferência, abrir pasta e mostrar arquivo no Explorer."""
import os
import subprocess
import sys


def ler_area_transferencia():
    """Texto da área de transferência (Windows), ou "" se não houver."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(None):
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def abrir(caminho):
    """Abre a pasta ou o arquivo no programa padrão."""
    if os.name == "nt":
        os.startfile(caminho)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho])


def mostrar_no_explorer(caminho):
    """Abre o Explorer com o arquivo selecionado."""
    if os.name == "nt" and os.path.isfile(caminho):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(caminho)])
    else:
        abrir(os.path.dirname(caminho) if os.path.isfile(caminho) else caminho)
