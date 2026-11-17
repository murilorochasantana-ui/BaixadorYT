"""Histórico de downloads (SQLite em %LOCALAPPDATA%\\EstudioViceCityDay\\estudio.db).

Guarda cada pedido (para "Baixar de novo" / "Retomar"), o status e os arquivos gerados.
Também serve para avisar quando um vídeo já foi baixado antes.
"""
import json
import sqlite3
import threading
from datetime import datetime

from .config import pasta_dados
from .plataformas import chave_do_link, plataforma

# status que significam "não terminou": ao abrir o Estúdio de novo viram "interrompido"
NAO_TERMINADOS = ("fila", "baixando", "pausado")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    chave         TEXT NOT NULL,
    plataforma    TEXT,
    titulo        TEXT,
    pasta         TEXT,
    qualidade     TEXT,
    trecho        TEXT,              -- "" = vídeo inteiro; senão "inicio-fim" em segundos
    status        TEXT NOT NULL,     -- fila, baixando, pausado, ok, erro, cancelado, interrompido
    erro          TEXT,
    arquivos      TEXT,              -- lista JSON
    pedido        TEXT,              -- pedido em JSON (para baixar de novo)
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_chave ON downloads (chave);
"""


def texto_trecho(inicio, fim):
    if inicio is None and fim is None:
        return ""
    return f"{inicio or 0:g}-{'' if fim is None else f'{fim:g}'}"


def _agora():
    return datetime.now().isoformat(timespec="seconds")


class Historico:
    def __init__(self, caminho=None):
        self.caminho = str(caminho or pasta_dados() / "estudio.db")
        self._trava = threading.Lock()
        with self._abrir() as c:
            c.executescript(ESQUEMA)

    def _abrir(self):
        c = sqlite3.connect(self.caminho, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _executar(self, sql, args=()):
        with self._trava:
            c = self._abrir()
            try:
                with c:
                    cur = c.execute(sql, args)
                    return cur.lastrowid
            finally:
                c.close()

    def _consultar(self, sql, args=()):
        with self._trava:
            c = self._abrir()
            try:
                return [dict(r) for r in c.execute(sql, args).fetchall()]
            finally:
                c.close()

    # ---------- escrita ----------
    def registrar(self, pedido_dict):
        """Cria a linha do pedido (status "fila"). Retorna o id do registro."""
        agora = _agora()
        url = pedido_dict["url"]
        return self._executar(
            "INSERT INTO downloads (url, chave, plataforma, titulo, pasta, qualidade, trecho, status, pedido,"
            " criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (url, chave_do_link(url), plataforma(url), url, pedido_dict.get("pasta"), pedido_dict.get("qualidade"),
             texto_trecho(pedido_dict.get("inicio"), pedido_dict.get("fim")), "fila",
             json.dumps(pedido_dict, ensure_ascii=False), agora, agora))

    def atualizar(self, registro, **campos):
        permitidos = {"titulo", "pasta", "status", "erro", "arquivos"}
        campos = {k: v for k, v in campos.items() if k in permitidos}
        if not campos or not registro:
            return
        if "arquivos" in campos and not isinstance(campos["arquivos"], str):
            campos["arquivos"] = json.dumps(campos["arquivos"], ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in campos)
        self._executar(f"UPDATE downloads SET {sets}, atualizado_em = ? WHERE id = ?",
                       (*campos.values(), _agora(), registro))

    def marcar_interrompidos(self):
        """Downloads que estavam em andamento quando o Estúdio fechou."""
        marcas = ",".join("?" * len(NAO_TERMINADOS))
        self._executar(f"UPDATE downloads SET status = 'interrompido', atualizado_em = ? WHERE status IN ({marcas})",
                       (_agora(), *NAO_TERMINADOS))

    def apagar(self, registro):
        self._executar("DELETE FROM downloads WHERE id = ?", (registro,))

    # ---------- leitura ----------
    def procurar_duplicado(self, url, inicio=None, fim=None):
        """Último download CONCLUÍDO do mesmo vídeo (e mesmo trecho), ou None."""
        r = self._consultar(
            "SELECT * FROM downloads WHERE chave = ? AND trecho = ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
            (chave_do_link(url), texto_trecho(inicio, fim)))
        return self._preparar(r[0]) if r else None

    def obter(self, registro):
        r = self._consultar("SELECT * FROM downloads WHERE id = ?", (registro,))
        return self._preparar(r[0]) if r else None

    def listar(self, busca="", limite=100):
        busca = (busca or "").strip()
        if busca:
            padrao = f"%{busca}%"
            linhas = self._consultar(
                "SELECT * FROM downloads WHERE titulo LIKE ? OR url LIKE ? OR pasta LIKE ? ORDER BY id DESC LIMIT ?",
                (padrao, padrao, padrao, limite))
        else:
            linhas = self._consultar("SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limite,))
        return [self._preparar(x) for x in linhas]

    @staticmethod
    def _preparar(linha):
        for campo in ("arquivos", "pedido"):
            try:
                linha[campo] = json.loads(linha[campo]) if linha.get(campo) else None
            except (TypeError, ValueError):
                linha[campo] = None
        return linha
