"""Ponte entre a interface (HTML/JS) e o Python.

O pywebview roda cada método chamado pelo JavaScript numa thread própria, então métodos
demorados (como a prévia) não travam a janela. Os eventos (progresso dos downloads) vão do
Python para a página por uma fila, entregue em lotes a cada 150 ms por `window.estudio.receber`.
Atributos começam com "_" para o pywebview não expô-los ao JavaScript.
"""
import importlib.util
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
from nucleo.historico import Historico
from nucleo.login import LOGINS, NAVEGADORES_BLOQUEIAM, opcoes_login
from nucleo.notificacao import notificar
from nucleo.plataformas import link_valido, separar_links
from nucleo.previa import ler_previa
from nucleo.qualidades import AVANCADO, ORDEM, nome_valido
from nucleo.sistema import abrir, ler_area_transferencia, mostrar_no_explorer
from nucleo.tempos import formatar_tempo, tempo_do_link, validar_trecho
from nucleo.transcricao import whisper_disponivel

AVISO_LINK = "Cole um link do YouTube, TikTok, Instagram, Twitch, Pinterest ou Facebook."


class Ponte:
    def __init__(self):
        self._cfg = config.carregar()
        self._eventos = queue.Queue()
        self._janela = None
        try:
            self._historico = Historico()
            self._historico.marcar_interrompidos()   # o que estava baixando quando o Estúdio fechou
        except Exception:
            self._historico = None                   # sem histórico o resto continua funcionando
        self._downloads = Gerenciador(self._eventos.put, self._cfg.get("downloads_paralelos", 2),
                                      historico=self._historico, ao_terminar=self._avisar_fim)

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

    def _avisar_fim(self, pedido, ev):
        """Notificação do Windows quando um download termina (se estiver ligada)."""
        if not self._cfg.get("notificacao", True):
            return
        titulo = (ev.get("titulo") or pedido.url).split("] ", 1)[-1]
        if ev["estado"] == "ok":
            n = len(ev.get("arquivos") or [])
            notificar("✔ Download concluído", titulo + (f" ({n} partes)" if n > 1 else ""))
        else:
            notificar("✘ Download com erro", f"{titulo}: {(ev.get('erro') or '').splitlines()[0]}")

    # ---------- chamados pelo JavaScript ----------
    def estado_inicial(self):
        colado = ler_area_transferencia().strip()
        validos, _ = separar_links(colado)
        return {
            "cfg": self._cfg,
            "pasta_downloads": config.pasta_downloads(self._cfg),
            "qualidades": ORDEM,
            "avancado": AVANCADO,
            "logins": LOGINS,
            "versao_ytdlp": yt_dlp.version.__version__,
            "whisper": whisper_disponivel(),
            "ffmpeg": ffmpeg_disponivel(),
            # componente que faz o yt-dlp parecer um navegador (o TikTok exige)
            "imita_navegador": importlib.util.find_spec("curl_cffi") is not None,
            "historico": self._historico is not None,
            "link_colado": "\n".join(validos),
        }

    def colar(self):
        return ler_area_transferencia().strip()

    def analisar_link(self, texto):
        """Quantos links válidos há no texto e o início que vem no ?t= (quando é um link só)."""
        validos, invalidos = separar_links(texto)
        inicio = tempo_do_link(validos[0]) if len(validos) == 1 else None
        return {"links": validos, "invalidos": invalidos, "inicio_link": inicio,
                "inicio_texto": formatar_tempo(inicio) if inicio else ""}

    def salvar_config(self, mudancas):
        self._cfg = config.atualizar(self._cfg, mudancas)
        if "downloads_paralelos" in (mudancas or {}):
            self._downloads.definir_paralelos(self._cfg["downloads_paralelos"])
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
        """Põe na fila um ou vários links.
        dados.forcar: None = avisar se já baixou; "todos" = baixar de novo; "pular" = pular os repetidos."""
        links, invalidos = separar_links(dados.get("texto") or dados.get("url") or "")
        if not links:
            extra = f"\n\nNão reconheci: {', '.join(invalidos[:5])}" if invalidos else ""
            return {"ok": False, "erro": AVISO_LINK + extra}
        qualidade = dados.get("qualidade")
        if not nome_valido(qualidade):
            return {"ok": False, "erro": "Escolha uma qualidade."}
        formato = dados.get("formato_avancado")
        if qualidade == AVANCADO:
            if len(links) > 1:
                return {"ok": False, "erro": "O modo Avançado funciona com um link por vez.\n\n"
                                             "Para vários links, escolha uma qualidade da lista (ex.: 1080p)."}
            if not (formato and formato.get("id")):
                return {"ok": False, "erro": "No modo Avançado, escolha um formato na tabela da prévia antes de baixar."}
        inicio = fim = None
        trecho = dados.get("trecho") or {}
        if trecho.get("ativo"):
            if len(links) > 1:
                return {"ok": False, "erro": "Para baixar só um trecho, cole um link por vez."}
            try:
                inicio, fim = validar_trecho(trecho.get("inicio"), trecho.get("fim"))
            except ValueError as e:
                return {"ok": False, "erro": str(e)}
        pasta = (dados.get("pasta") or "").strip()
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError:
            return {"ok": False, "erro": f"Não consegui usar a pasta:\n{pasta}\n\nEscolha outra em \"Salvar em\"."}

        # já está na fila agora? (evita a mesma entrada duas vezes, ex.: Enter + clique)
        na_fila = [l for l in links if self._downloads.ja_na_fila(l, inicio, fim)]
        if na_fila and len(na_fila) == len(links):
            return {"ok": False, "erro": "Esse vídeo já está na fila de downloads." if len(links) == 1 else
                    "Todos esses vídeos já estão na fila de downloads."}
        links = [l for l in links if l not in na_fila]

        # já baixou antes?
        pulados = len(na_fila)
        if self._historico and dados.get("forcar") != "todos":
            repetidos = []
            for link in links:
                anterior = self._historico.procurar_duplicado(link, inicio, fim)
                if anterior:
                    repetidos.append({"url": link, "titulo": anterior["titulo"], "quando": anterior["criado_em"],
                                      "pasta": anterior["pasta"]})
            if repetidos and dados.get("forcar") != "pular":
                return {"ok": False, "duplicados": repetidos, "total": len(links)}
            if repetidos:
                ja = {r["url"] for r in repetidos}
                pulados += len(ja)
                links = [l for l in links if l not in ja]

        try:
            limite = max(10, int(dados.get("limite_mb") or 400))
        except (TypeError, ValueError):
            limite = 400
        self.salvar_config({"pasta": pasta, "qualidade": qualidade, "modo_claude": bool(dados.get("modo_claude")),
                            "limite_mb": limite, "transcricao": bool(dados.get("transcricao")),
                            "miniatura": bool(dados.get("miniatura"))})
        ids = []
        for link in links:
            pedido = Pedido(
                url=link, pasta=pasta, qualidade=qualidade,
                formato_avancado=formato if qualidade == AVANCADO else None,
                limite_mb=limite if dados.get("modo_claude") else None,
                login_opts=opcoes_login(self._cfg), login=self._cfg.get("login", "Nenhum"),
                modelo_whisper=self._cfg.get("modelo_whisper", "small") if dados.get("transcricao") else None,
                inicio=inicio, fim=fim, miniatura=bool(dados.get("miniatura")),
            )
            ids.append(self._downloads.adicionar(pedido))
        return {"ok": True, "ids": ids, "invalidos": invalidos, "pulados": pulados}

    # ---------- controle da fila ----------
    def pausar(self, id_):
        return self._downloads.pausar(id_)

    def retomar(self, id_):
        return self._downloads.retomar(id_)

    def cancelar(self, id_):
        return self._downloads.cancelar(id_)

    def na_fila(self):
        return self._downloads.na_fila()

    # ---------- histórico ----------
    def historico(self, busca=""):
        if not self._historico:
            return []
        return self._historico.listar(busca)

    def baixar_de_novo(self, registro):
        """Baixa de novo (ou retoma, se ficou o .part) com as mesmas opções de antes."""
        if not self._historico:
            return {"ok": False, "erro": "O histórico não está disponível."}
        linha = self._historico.obter(registro)
        if not linha or not linha.get("pedido"):
            return {"ok": False, "erro": "Não achei esse download no histórico."}
        p = dict(linha["pedido"])
        campos = {k: p.get(k) for k in ("url", "pasta", "qualidade", "formato_avancado", "limite_mb",
                                        "modelo_whisper", "inicio", "fim", "miniatura")}
        if not nome_valido(campos["qualidade"]):
            campos["qualidade"] = ORDEM[0]
        pedido = Pedido(**campos, login_opts=opcoes_login(self._cfg), login=self._cfg.get("login", "Nenhum"))
        return {"ok": True, "id": self._downloads.adicionar(pedido)}

    def apagar_do_historico(self, registro):
        """Tira a linha do histórico (os arquivos baixados continuam na pasta)."""
        if self._historico:
            self._historico.apagar(registro)
        return True

    # ---------- arquivos ----------
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
