"""Aviso do Windows (toast) quando um download termina, sem instalar nada: usa o PowerShell
que já vem no Windows. A notificação aparece com o nome "Windows PowerShell" como origem
(na Fase 7, com o instalador, o Estúdio ganha nome próprio na notificação)."""
import base64
import os
import subprocess
from xml.sax.saxutils import escape

from .ffmpeg import SEM_JANELA

# identificador de app do PowerShell (registrado em todo Windows 10/11)
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _texto_ps(s):
    """Texto seguro dentro de XML e de uma string '...' do PowerShell."""
    return escape(str(s or ""), {'"': "&quot;", "'": "&apos;"}).replace("\r", " ").replace("\n", " ")[:250]


def montar_script(titulo, texto):
    xml = ("<toast><visual><binding template=\"ToastGeneric\">"
           f"<text>{_texto_ps(titulo)}</text><text>{_texto_ps(texto)}</text>"
           "</binding></visual></toast>")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$x.LoadXml('{xml}')\n"
        "$t = New-Object Windows.UI.Notifications.ToastNotification $x\n"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($t)\n"
    )


def notificar(titulo, texto):
    """Mostra o aviso sem travar nada (o PowerShell roda escondido, em segundo plano)."""
    if os.name != "nt":
        return False
    codificado = base64.b64encode(montar_script(titulo, texto).encode("utf-16-le")).decode()
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                          "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **SEM_JANELA)
        return True
    except OSError:
        return False
