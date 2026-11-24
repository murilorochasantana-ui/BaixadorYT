"""Coisas do Windows: área de transferência, abrir pasta, mostrar arquivo no Explorer e
garantir que só um Estúdio fique aberto (TravaInstancia, abrir_ou_trazer)."""
import hashlib
import os
import subprocess
import sys
import time


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


# ---------------------------------------------------------------------------------------------
# Uma instância só (24/11/2026: havia 3 Estúdios abertos ao mesmo tempo, um deles travado sem
# janela segurando a porta 42001; as janelas novas carregavam a página do travado e todas
# dividiam o mesmo perfil do WebView2, o mesmo estudio.db e o mesmo vigia de pastas).
#
# Como funciona: um mutex nomeado do Windows marca "tem um Estúdio aberto" e some sozinho quando
# o processo termina (mesmo se ele cair). Quem fica com o mutex grava o PID em instancia.pid.
# Quem chega depois procura a janela "Estúdio ViceCityDay" daquele PID e a traz para a frente.
# Se o dono existe mas não tem janela (ou ela não responde), pergunta se pode fechá-lo.
# ---------------------------------------------------------------------------------------------
TITULO_JANELA = "Estúdio ViceCityDay"
ESPERA_JANELA = 30      # s de vida do outro processo sem janela até considerar travado
LIMITE_ESPERA = 45      # s no máximo esperando decidir
ESPERA_FECHAR = 10      # s esperando o travado largar a trava depois de encerrado

MSG_TRAVADO = ("O Estúdio já está aberto, mas a janela dele não apareceu (parece que travou).\n\n"
               "Quer fechar o Estúdio travado e abrir de novo?\n\n"
               "Downloads que estavam em andamento nele param e podem ser retomados depois.")
MSG_NAO_RESPONDE = ("O Estúdio já está aberto, mas a janela dele não está respondendo.\n\n"
                    "Quer fechar o Estúdio travado e abrir de novo?\n\n"
                    "Downloads que estavam em andamento nele param e podem ser retomados depois.")
MSG_NAO_FECHOU = ("Não consegui fechar o Estúdio travado.\n\n"
                  "Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc), encerre os itens \"pythonw\" "
                  "e abra o Estúdio de novo. Se não der, reinicie o computador.")
MSG_SEM_RESPOSTA = ("O Estúdio já está aberto, mas não consegui encontrar a janela dele.\n\n"
                    "Procure o Estúdio na barra de tarefas. Se não estiver lá, abra o Gerenciador de "
                    "Tarefas (Ctrl+Shift+Esc), encerre os itens \"pythonw\" e abra de novo.")

_ERRO_JA_EXISTE = 183
_ESPERA_OK = (0x0, 0x80)  # WAIT_OBJECT_0, WAIT_ABANDONED (o dono anterior morreu: a trava é nossa)


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    return k


class TravaInstancia:
    """Trava "só um Estúdio aberto" para uma pasta de dados (ESTUDIO_DADOS diferente = trava diferente)."""

    def __init__(self, pasta_dados):
        pasta = os.path.normcase(os.path.realpath(str(pasta_dados)))
        resumo = hashlib.sha1(pasta.encode("utf-8")).hexdigest()[:12]
        self.nome = f"Local\\EstudioViceCityDay-{resumo}"
        self.arquivo_pid = os.path.join(str(pasta_dados), "instancia.pid")
        self._h = None
        self.dona = False

    def pegar(self):
        """Tenta ficar com a trava. True = este é o único Estúdio aberto."""
        if os.name != "nt":
            self.dona = True
            return True
        import ctypes
        k = _kernel32()
        if self._h is None:
            self._h = k.CreateMutexW(None, True, self.nome)
            if not self._h:
                self.dona = True  # sem mutex (muito raro): melhor abrir do que não abrir
                return True
            if ctypes.get_last_error() != _ERRO_JA_EXISTE:
                self._marcar_dona()
                return True
        return self.esperar(0)

    def esperar(self, segundos):
        """Espera o outro Estúdio largar a trava (fechou, caiu ou foi encerrado)."""
        if self.dona:
            return True
        if os.name != "nt" or self._h is None:
            return self.pegar()
        if _kernel32().WaitForSingleObject(self._h, int(segundos * 1000)) in _ESPERA_OK:
            self._marcar_dona()
            return True
        return False

    def _marcar_dona(self):
        self.dona = True
        try:
            with open(self.arquivo_pid, "w", encoding="ascii") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass

    def dono(self):
        """PID de quem está com a trava (lido de instancia.pid), ou None."""
        try:
            with open(self.arquivo_pid, encoding="ascii") as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return None
        return None if pid == os.getpid() else pid

    def soltar(self):
        if self.dona:
            try:
                with open(self.arquivo_pid, encoding="ascii") as f:
                    nosso = f.read().strip() == str(os.getpid())
                if nosso:  # só apaga se o arquivo ainda for deste processo
                    os.remove(self.arquivo_pid)
            except OSError:
                pass
            if os.name == "nt" and self._h:
                _kernel32().ReleaseMutex(self._h)
        if os.name == "nt" and self._h:
            _kernel32().CloseHandle(self._h)
        self._h = None
        self.dona = False


def processo_estudio_vivo(pid):
    """True se o PID existe e é um Python (protege contra PID reaproveitado por outro programa)."""
    if os.name != "nt" or not pid:
        return False
    import ctypes
    from ctypes import wintypes
    k = _kernel32()
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        codigo = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(codigo)) or codigo.value != 259:  # STILL_ACTIVE
            return False
        buf = ctypes.create_unicode_buffer(1024)
        tam = wintypes.DWORD(1024)
        if not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
            return False
        return "python" in os.path.basename(buf.value).lower()
    finally:
        k.CloseHandle(h)


def idade_processo(pid):
    """Há quantos segundos o processo foi aberto (0 se não der para saber)."""
    if os.name != "nt":
        return 0.0
    import ctypes
    from ctypes import wintypes
    k = _kernel32()
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return 0.0
    try:
        t = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
            return 0.0
        criado = ((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime) / 1e7 - 11644473600
        return max(0.0, time.time() - criado)
    finally:
        k.CloseHandle(h)


def _user32():
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.IsHungAppWindow.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    return u


def achar_janela(pid, titulo=TITULO_JANELA):
    """Janela visível do processo `pid` cujo título começa com `titulo` (ou None)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    u = _user32()
    achadas = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        dono = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid and u.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, buf, 256)
            if buf.value.startswith(titulo):
                achadas.append(hwnd)
                return False
        return True

    u.EnumWindows(cada, 0)
    return achadas[0] if achadas else None


def janela_nao_responde(hwnd):
    return os.name == "nt" and bool(_user32().IsHungAppWindow(hwnd))


def trazer_para_frente(hwnd):
    """Restaura a janela (se minimizada) e a põe na frente das outras."""
    if os.name != "nt":
        return False
    u = _user32()
    u.ShowWindow(hwnd, 9 if u.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
    return bool(u.SetForegroundWindow(hwnd))


def encerrar_processo(pid):
    """Encerra o processo e os filhos dele (taskkill /T /F), sem mostrar janela."""
    if os.name != "nt":
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=0x08000000, timeout=15)  # CREATE_NO_WINDOW


def abrir_ou_trazer(trava, perguntar, avisar, *, titulo=TITULO_JANELA,
                    vivo=processo_estudio_vivo, idade=idade_processo, achar=achar_janela,
                    nao_responde=janela_nao_responde, trazer=trazer_para_frente,
                    encerrar=encerrar_processo, dormir=time.sleep, relogio=time.monotonic,
                    espera_janela=ESPERA_JANELA, limite=LIMITE_ESPERA, espera_fechar=ESPERA_FECHAR):
    """Decide se este Estúdio pode abrir.

    True  = ficou com a trava: pode abrir a janela.
    False = já havia outro aberto (a janela dele veio para a frente) ou o usuário preferiu não
            fechar o travado: este processo deve sair sem abrir nada.
    `perguntar(texto) -> bool` e `avisar(texto)` mostram as caixas de mensagem.
    """
    if trava.pegar():
        return True
    fim = relogio() + limite
    while True:
        pid = trava.dono()
        if pid and vivo(pid):
            janela = achar(pid, titulo)
            travado = None
            if janela and nao_responde(janela):
                travado = MSG_NAO_RESPONDE
            elif janela:
                trazer(janela)
                return False
            elif idade(pid) >= espera_janela:
                travado = MSG_TRAVADO
            if travado:
                if not perguntar(travado):
                    return False
                encerrar(pid)
                if trava.esperar(espera_fechar):
                    return True
                avisar(MSG_NAO_FECHOU)
                return False
        elif trava.esperar(0.5):  # o outro fechou ou caiu agora há pouco
            return True
        if relogio() >= fim:
            avisar(MSG_SEM_RESPOSTA)
            return False
        dormir(0.5)
