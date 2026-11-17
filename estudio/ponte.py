"""Ponte entre a interface (HTML/JS) e o Python.

O pywebview roda cada método chamado pelo JavaScript numa thread própria, então métodos
demorados (como a prévia) não travam a janela. Os eventos (progresso dos downloads) vão do
Python para a página por uma fila, entregue em lotes a cada 150 ms por `window.estudio.receber`.
Atributos começam com "_" para o pywebview não expô-los ao JavaScript.
"""
import json
import os
import queue
import threading
import time

import yt_dlp

from nucleo import config
from nucleo.downloads import Gerenciador, Pedido
from nucleo.erros import explicar_erro, limpar_mensagem
from nucleo.ffmpeg import ffmpeg_disponivel
from nucleo.login import LOGINS, NAVEGADORES_BLOQUEIAM, opcoes_login
from nucleo.plataformas import link_valido
from nucleo.previa import ler_previa
from nucleo.qualidades import AVANCADO, ORDEM, nome_valido
from nucleo.sistema import abrir, ler_area_transferencia, mostrar_no_explorer
from nucleo.transcricao import whisper_disponivel

AVISO_LINK = "Cole um link do YouTube, TikTok, Instagram, Twitch, Pinterest ou Facebook."


class Ponte:
    def __init__(self):
        self._cfg = config.carregar()
        self._eventos = queue.Queue()
        self._janela = None
        self._downloads = Gerenciador(self._eventos.put)

    # ---------- ligação com a janela ----------
    def _ligar(self, janela):
        self._janela = janela
        threading.Thread(target=self._entregar_eventos, daemon=True, name="eventos").start()

    def _entregar_eventos(self):
        while True:
            lote = [self._eventos.get()]
            time.sleep(0.15)
            while True:
                try:
                    lote.append(self._eventos.get_nowait())
                except queue.Empty:
                    break
            try:
                self._janela.evaluate_js(
                    f"window.estudio && window.estudio.receber({json.dumps(lote, ensure_ascii=False)})")
            except Exception:
                pass  # janela fechando

    # ---------- chamados pelo JavaScript ----------
    def estado_inicial(self):
        colado = ler_area_transferencia().strip()
        return {
            "cfg": self._cfg,
            "pasta_downloads": config.pasta_downloads(self._cfg),
            "qualidades": ORDEM,
            "avancado": AVANCADO,
            "logins": LOGINS,
            "versao_ytdlp": yt_dlp.version.__version__,
            "whisper": whisper_disponivel(),
            "ffmpeg": ffmpeg_disponivel(),
            "link_colado": colado if link_valido(colado) else "",
        }

    def colar(self):
        return ler_area_transferencia().strip()

    def salvar_config(self, mudancas):
        self._cfg = config.atualizar(self._cfg, mudancas)
        return self._cfg

    def escolher_pasta(self, atual=""):
        import webview
        inicio = atual if atual and os.path.isdir(atual) else ""
        r = self._janela.create_file_dialog(webview.FileDialog.FOLDER, directory=inicio)
        if not r:
            return None
        pasta = os.path.normpath(r[0] if isinstance(r, (list, tuple)) else r)
        self.salvar_config({"pasta": pasta})
        return pasta

    def mudar_login(self, login):
        """Troca o login. Para 'Arquivo cookies.txt' abre a janela para escolher o arquivo."""
        import webview
        aviso = None
        if login == "Arquivo cookies.txt":
            r = self._janela.create_file_dialog(webview.FileDialog.OPEN,
                                                file_types=("Arquivo de cookies (*.txt)", "Todos (*.*)"))
            if not r:
                return {"login": self._cfg.get("login", "Nenhum"), "aviso": None}
            self.salvar_config({"login": login, "cookies_txt": r[0] if isinstance(r, (list, tuple)) else r})
        else:
            if login in NAVEGADORES_BLOQUEIAM:
                aviso = (f"Feche o {login} por completo antes de baixar.\n\n"
                         "Se mesmo assim der erro, use o Firefox: é o que funciona melhor.")
            self.salvar_config({"login": login})
        return {"login": self._cfg["login"], "aviso": aviso}

    def previa(self, url):
        url = (url or "").strip()
        if not link_valido(url):
            return {"ok": False, "erro": AVISO_LINK}
        try:
            dados = ler_previa(url, opcoes_login(self._cfg), self._cfg.get("aviso_gb", 3))
            return {"ok": True, "dados": dados}
        except Exception as e:
            return {"ok": False, "erro": explicar_erro(limpar_mensagem(e), self._cfg.get("login", "Nenhum"))}

    def baixar(self, dados):
        url = (dados.get("url") or "").strip()
        if not link_valido(url):
            return {"ok": False, "erro": AVISO_LINK}
        qualidade = dados.get("qualidade")
        if not nome_valido(qualidade):
            return {"ok": False, "erro": "Escolha uma qualidade."}
        formato = dados.get("formato_avancado")
        if qualidade == AVANCADO and not (formato and formato.get("id")):
            return {"ok": False, "erro": "No modo Avançado, escolha um formato na tabela da prévia antes de baixar."}
        pasta = (dados.get("pasta") or "").strip()
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError:
            return {"ok": False, "erro": f"Não consegui usar a pasta:\n{pasta}\n\nEscolha outra em \"Salvar em\"."}
        try:
            limite = max(10, int(dados.get("limite_mb") or 400))
        except (TypeError, ValueError):
            limite = 400
        self.salvar_config({"pasta": pasta, "qualidade": qualidade, "modo_claude": bool(dados.get("modo_claude")),
                            "limite_mb": limite, "transcricao": bool(dados.get("transcricao"))})
        pedido = Pedido(
            url=url, pasta=pasta, qualidade=qualidade,
            formato_avancado=formato if qualidade == AVANCADO else None,
            limite_mb=limite if dados.get("modo_claude") else None,
            login_opts=opcoes_login(self._cfg), login=self._cfg.get("login", "Nenhum"),
            modelo_whisper=self._cfg.get("modelo_whisper", "small") if dados.get("transcricao") else None,
        )
        return {"ok": True, "id": self._downloads.adicionar(pedido)}

    def na_fila(self):
        return self._downloads.na_fila()

    def abrir_pasta(self, caminho):
        try:
            os.makedirs(caminho, exist_ok=True)
            abrir(caminho)
            return True
        except OSError:
            return False

    def mostrar_arquivo(self, caminho):
        if caminho and os.path.exists(caminho):
            mostrar_no_explorer(caminho)
            return True
        return False
