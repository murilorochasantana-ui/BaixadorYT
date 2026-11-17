"""Servidor local só para a prévia: entrega vídeos, áudios e imagens da pasta do canal à janela do Estúdio.

- Escuta SÓ em 127.0.0.1 (outros computadores não alcançam).
- A URL leva uma senha aleatória (gerada a cada abertura): outros sites/programas não adivinham.
- Confere o cabeçalho Host (proteção contra "DNS rebinding") e só entrega arquivos permitidos.
- Aceita "Range" (pular no vídeo sem baixar tudo).
"""
import mimetypes
import re
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os

TIPOS = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/mp4",
         ".mkv": "video/x-matroska", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
         ".opus": "audio/ogg", ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".gif": "image/gif", ".bmp": "image/bmp", ".ico": "image/x-icon"}
BLOCO = 256 * 1024
ERROS_DE_CONEXAO = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class ServidorMidia:
    def __init__(self, permitido):
        """permitido(caminho) -> bool decide quais arquivos podem ser entregues."""
        self.token = secrets.token_urlsafe(18)
        self.permitido = permitido
        servidor = self

        class Tratador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "EstudioMidia"

            def log_message(self, *a):
                pass

            def _negar(self, codigo, msg=""):
                corpo = msg.encode()
                self.send_response(codigo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corpo)

            def _entregar(self):
                host = (self.headers.get("Host") or "").lower()
                if host not in (f"127.0.0.1:{servidor.porta}", f"localhost:{servidor.porta}"):
                    return self._negar(403, "host")
                m = re.match(r"^/m/([^/]+)/(.+)$", self.path.split("?")[0])
                if not m or not secrets.compare_digest(m.group(1), servidor.token):
                    return self._negar(403, "senha")
                caminho = urllib.parse.unquote(m.group(2))
                if not os.path.isfile(caminho) or not servidor.permitido(caminho):
                    return self._negar(404, "arquivo")
                tamanho = os.path.getsize(caminho)
                ext = os.path.splitext(caminho)[1].lower()
                tipo = TIPOS.get(ext) or mimetypes.guess_type(caminho)[0] or "application/octet-stream"
                ini, fim, codigo = 0, tamanho - 1, 200
                r = self.headers.get("Range")
                if r:
                    mm = re.match(r"bytes=(\d*)-(\d*)$", r.strip())
                    if mm and (mm.group(1) or mm.group(2)):
                        if mm.group(1):
                            ini = int(mm.group(1))
                            fim = int(mm.group(2)) if mm.group(2) else tamanho - 1
                        else:                       # "últimos N bytes"
                            ini = max(tamanho - int(mm.group(2)), 0)
                        fim = min(fim, tamanho - 1)
                        if ini > fim or ini >= tamanho:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{tamanho}")
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            return
                        codigo = 206
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(fim - ini + 1))
                if codigo == 206:
                    self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command == "HEAD":
                    return
                falta = fim - ini + 1
                with open(caminho, "rb") as f:
                    f.seek(ini)
                    while falta > 0:
                        dados = f.read(min(BLOCO, falta))
                        if not dados:
                            break
                        self.wfile.write(dados)
                        falta -= len(dados)

            def _seguro(self):
                try:
                    self._entregar()
                except ERROS_DE_CONEXAO:
                    pass      # o vídeo pulou para outro ponto e a conexão antiga caiu: normal
                except OSError:
                    pass

            do_GET = do_HEAD = _seguro

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.httpd.daemon_threads = True
        self.porta = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="servidor-midia").start()

    def url(self, caminho):
        return f"http://127.0.0.1:{self.porta}/m/{self.token}/" + urllib.parse.quote(os.path.normpath(caminho), safe="")

    def parar(self):
        self.httpd.shutdown()
