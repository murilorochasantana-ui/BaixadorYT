"""Aba Voz: detectar e ligar o VozLocal (projeto à parte em D:\\VozLocal)."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nucleo import vozlocal


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def servidor_falso(resposta: bytes, codigo=200):
    class Manipulador(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(codigo)
            self.end_headers()
            self.wfile.write(resposta)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def porta_teste(monkeypatch):
    p = porta_livre()
    monkeypatch.setattr(vozlocal, "PORTA", p)
    return p


def test_instalado(tmp_path):
    assert not vozlocal.instalado(tmp_path)
    (tmp_path / "app.py").write_text("")
    assert not vozlocal.instalado(tmp_path)
    py = vozlocal.python_do_vozlocal(tmp_path)
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    assert vozlocal.instalado(tmp_path)


def test_porta_livre_ninguem(porta_teste):
    assert vozlocal.quem_esta_na_porta() is None
    assert vozlocal.url() == f"http://127.0.0.1:{porta_teste}/"


def test_reconhece_o_vozlocal_e_outros(monkeypatch):
    srv = servidor_falso(json.dumps({"title": "VozLocal"}).encode())
    monkeypatch.setattr(vozlocal, "PORTA", srv.server_port)
    assert vozlocal.quem_esta_na_porta() == "vozlocal"
    assert vozlocal.ligar("pasta/que/nao/existe") == {"ok": True, "url": vozlocal.url()}
    srv.shutdown()

    outro = servidor_falso(b"<html>outro programa</html>")
    monkeypatch.setattr(vozlocal, "PORTA", outro.server_port)
    assert vozlocal.quem_esta_na_porta() == "outro"
    r = vozlocal.ligar("pasta/que/nao/existe")
    assert not r["ok"] and "porta" in r["erro"]
    outro.shutdown()

    erro404 = servidor_falso(b"", codigo=404)
    monkeypatch.setattr(vozlocal, "PORTA", erro404.server_port)
    assert vozlocal.quem_esta_na_porta() == "outro"
    erro404.shutdown()


def test_nao_instalado_explica_o_que_fazer(porta_teste, tmp_path):
    r = vozlocal.ligar(tmp_path)
    assert not r["ok"]
    assert "instalar.bat" in r["erro"] and str(tmp_path) in r["erro"]


def test_estado(porta_teste, tmp_path):
    e = vozlocal.estado(tmp_path)
    assert e == {"instalado": False, "rodando": False, "url": vozlocal.url(),
                 "pasta": str(tmp_path), "ligado_pelo_estudio": False}


def test_desligar_sem_processo_nao_quebra():
    vozlocal.desligar()
