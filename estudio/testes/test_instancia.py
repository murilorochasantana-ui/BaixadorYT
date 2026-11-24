"""Só um Estúdio aberto: trava (mutex do Windows + instancia.pid) e a decisão de abrir ou trazer."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nucleo import sistema
from nucleo.sistema import TravaInstancia, abrir_ou_trazer

ESTUDIO = str(Path(__file__).resolve().parent.parent)
so_windows = pytest.mark.skipif(os.name != "nt", reason="mutex e janelas só no Windows")

SEGURAR = r"""
import sys
sys.path.insert(0, sys.argv[1])
from nucleo.sistema import TravaInstancia
t = TravaInstancia(sys.argv[2])
print("pegou" if t.pegar() else "nao", flush=True)
if sys.stdin.readline().strip() == "soltar":
    t.soltar()
    print("soltou", flush=True)
    sys.stdin.readline()
"""


def outro_estudio(pasta):
    """Outro processo Python segurando a trava da mesma pasta (como um segundo Estúdio)."""
    p = subprocess.Popen([sys.executable, "-c", SEGURAR, ESTUDIO, str(pasta)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "pegou"
    return p


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "dados"
    p.mkdir()
    return p


# ------------------------------------------------------------------ trava de verdade (Windows)
@so_windows
def test_segundo_nao_pega_a_trava_e_sabe_quem_e_o_dono(pasta):
    outro = outro_estudio(pasta)
    try:
        t = TravaInstancia(pasta)
        assert t.pegar() is False
        assert t.dono() == outro.pid
        assert sistema.processo_estudio_vivo(outro.pid)
        assert 0 <= sistema.idade_processo(outro.pid) < 60
        t.soltar()
    finally:
        outro.kill()
        outro.wait()


@so_windows
def test_trava_fica_livre_quando_o_dono_cai(pasta):
    outro = outro_estudio(pasta)
    t = TravaInstancia(pasta)
    assert t.pegar() is False
    outro.kill()  # caiu sem soltar (como um Estúdio travado encerrado)
    outro.wait()
    assert not sistema.processo_estudio_vivo(outro.pid)
    assert t.esperar(5) is True
    assert (pasta / "instancia.pid").read_text() == str(os.getpid())
    t.soltar()
    assert not (pasta / "instancia.pid").exists()


@so_windows
def test_soltar_libera_para_o_proximo(pasta):
    outro = outro_estudio(pasta)
    try:
        t = TravaInstancia(pasta)
        assert t.pegar() is False
        outro.stdin.write("soltar\n")
        outro.stdin.flush()
        assert outro.stdout.readline().strip() == "soltou"
        assert t.esperar(5) is True
        t.soltar()
    finally:
        outro.kill()
        outro.wait()


@so_windows
def test_pastas_de_dados_diferentes_nao_se_atrapalham(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    outro = outro_estudio(a)
    try:
        assert TravaInstancia(a).nome != TravaInstancia(b).nome
        t = TravaInstancia(b)
        assert t.pegar() is True
        t.soltar()
    finally:
        outro.kill()
        outro.wait()


def test_dono_ignora_arquivo_estragado(pasta):
    t = TravaInstancia(pasta)
    (pasta / "instancia.pid").write_text("lixo")
    assert t.dono() is None


@so_windows
def test_pid_que_nao_e_python_nao_conta_como_estudio():
    cmd = subprocess.Popen(["cmd", "/c", "ping -n 5 127.0.0.1 >nul"], creationflags=0x08000000)
    try:
        assert sistema.processo_estudio_vivo(cmd.pid) is False
    finally:
        cmd.kill()
        cmd.wait()
    assert sistema.processo_estudio_vivo(999999999) is False


JANELA = r"""
import sys, tkinter as tk
r = tk.Tk()
r.title(sys.argv[1])
r.geometry("200x80+30+30")
r.after(300, lambda: print("pronta", flush=True))
r.after(15000, r.destroy)
r.mainloop()
"""


@so_windows
def test_acha_a_janela_pelo_pid_e_traz_para_frente():
    titulo = sistema.TITULO_JANELA + " (teste)"
    p = subprocess.Popen([sys.executable, "-c", JANELA, titulo], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "pronta"
        hwnd = None
        for _ in range(20):
            hwnd = sistema.achar_janela(p.pid, sistema.TITULO_JANELA)
            if hwnd:
                break
            time.sleep(0.2)
        assert hwnd
        assert sistema.achar_janela(p.pid, "Outro título") is None
        assert sistema.achar_janela(os.getpid(), sistema.TITULO_JANELA) is None
        assert sistema.janela_nao_responde(hwnd) is False
        sistema.trazer_para_frente(hwnd)  # não pode dar erro (ir para a frente depende do Windows)
    finally:
        p.kill()
        p.wait()


# ------------------------------------------------------------------ decisão (com peças falsas)
class TravaFalsa:
    def __init__(self, livre=False, dono=1234, libera_ao_encerrar=True):
        self.livre, self._dono, self.libera = livre, dono, libera_ao_encerrar
        self.encerrado = False

    def pegar(self):
        return self.livre

    def dono(self):
        return self._dono

    def esperar(self, segundos):
        return self.livre or (self.encerrado and self.libera)


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


def decidir(trava, *, janela=None, idade=0.0, vivo=True, nao_responde=False, resposta=True,
            janela_aparece_em=None):
    rel = Relogio()
    log = {"trouxe": None, "perguntas": [], "avisos": [], "encerrou": None}

    def achar(pid, titulo):
        if janela_aparece_em is not None and rel.t >= janela_aparece_em:
            return 777
        return janela

    def encerrar(pid):
        log["encerrou"] = pid
        trava.encerrado = True

    def perguntar(texto):
        log["perguntas"].append(texto)
        return resposta

    r = abrir_ou_trazer(
        trava, perguntar, log["avisos"].append,
        vivo=lambda pid: vivo, idade=lambda pid: idade + rel.t, achar=achar,
        nao_responde=lambda h: nao_responde, trazer=lambda h: log.__setitem__("trouxe", h),
        encerrar=encerrar, dormir=rel.dormir, relogio=rel, espera_janela=30, limite=45)
    return r, log


def test_primeiro_estudio_abre():
    r, log = decidir(TravaFalsa(livre=True))
    assert r is True and log["trouxe"] is None and not log["perguntas"]


def test_segundo_traz_a_janela_do_primeiro_e_sai():
    r, log = decidir(TravaFalsa(), janela=555)
    assert r is False and log["trouxe"] == 555
    assert not log["perguntas"] and log["encerrou"] is None


def test_espera_a_janela_de_quem_acabou_de_abrir():
    r, log = decidir(TravaFalsa(), idade=1, janela_aparece_em=3)
    assert r is False and log["trouxe"] == 777 and not log["perguntas"]


def test_travado_sem_janela_pergunta_e_fecha_se_o_usuario_quiser():
    r, log = decidir(TravaFalsa(), idade=3600, resposta=True)
    assert r is True
    assert log["perguntas"] == [sistema.MSG_TRAVADO] and log["encerrou"] == 1234


def test_travado_sem_janela_e_usuario_diz_nao():
    r, log = decidir(TravaFalsa(), idade=3600, resposta=False)
    assert r is False and log["encerrou"] is None and not log["avisos"]


def test_travado_so_depois_de_esperar_a_janela():
    r, log = decidir(TravaFalsa(), idade=20, resposta=False)
    assert r is False and log["perguntas"] == [sistema.MSG_TRAVADO]


def test_janela_que_nao_responde_conta_como_travado():
    r, log = decidir(TravaFalsa(), janela=555, nao_responde=True, resposta=True)
    assert r is True and log["trouxe"] is None
    assert log["perguntas"] == [sistema.MSG_NAO_RESPONDE] and log["encerrou"] == 1234


def test_nao_conseguiu_fechar_o_travado():
    r, log = decidir(TravaFalsa(libera_ao_encerrar=False), idade=3600, resposta=True)
    assert r is False and log["avisos"] == [sistema.MSG_NAO_FECHOU]


def test_dono_que_ja_morreu_libera_a_trava():
    trava = TravaFalsa(dono=1234)
    trava.encerrado = True  # o mutex foi abandonado: esperar() consegue
    r, log = decidir(trava, vivo=False)
    assert r is True and not log["perguntas"] and not log["avisos"]


def test_sem_saber_o_dono_desiste_com_mensagem():
    r, log = decidir(TravaFalsa(dono=None))
    assert r is False and log["avisos"] == [sistema.MSG_SEM_RESPOSTA]
