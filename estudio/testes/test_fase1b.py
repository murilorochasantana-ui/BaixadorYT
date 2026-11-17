"""Fase 1B: tempos/trecho, vários links, repetidos, histórico, notificação, opções e a fila
(pausar, retomar, cancelar, paralelo) com um yt-dlp falso."""
import math
import os
import threading
import time

import pytest

from nucleo import config, downloads
from nucleo.downloads import Gerenciador, Pedido, montar_opcoes
from nucleo.historico import Historico
from nucleo.legendas import cortar_segmentos
from nucleo.notificacao import montar_script
from nucleo.plataformas import chave_do_link, separar_links
from nucleo.tempos import formatar_tempo, ler_tempo, sufixo_trecho, tempo_do_link, validar_trecho


# ---------- tempos ----------
@pytest.mark.parametrize("texto,seg", [
    ("17:44", 1064), ("1:02:30", 3750), ("1064", 1064), ("17m44s", 1064), ("1h2m3s", 3723),
    ("90s", 90), (" 0:05 ", 5), ("1,5", 1.5), ("", None), (None, None),
])
def test_ler_tempo(texto, seg):
    assert ler_tempo(texto) == seg


@pytest.mark.parametrize("texto", ["abc", "1:2:3:4", "17;44", "-5", "1h:2"])
def test_ler_tempo_invalido(texto):
    with pytest.raises(ValueError):
        ler_tempo(texto)


@pytest.mark.parametrize("url,seg", [
    ("https://youtu.be/abcdefghijk?t=1064", 1064),
    ("https://www.youtube.com/watch?v=abcdefghijk&t=17m44s", 1064),
    ("https://www.youtube.com/watch?v=abcdefghijk&start=90", 90),
    ("https://www.twitch.tv/videos/123?t=1h2m3s", 3723),
    ("https://www.youtube.com/watch?v=abcdefghijk#t=1:30", 90),
    ("https://www.youtube.com/live/abcdefghijk?si=x&t=16466s", 16466),     # 4:34:26 (caso real)
    ("https://www.youtube.com/watch?v=abcdefghijk", None),
    ("https://youtu.be/abcdefghijk?t=0", None),
])
def test_tempo_do_link(url, seg):
    assert tempo_do_link(url) == seg


def test_validar_trecho():
    assert validar_trecho("17:44", "20:00") == (1064, 1200)
    assert validar_trecho("", "1:00") == (0.0, 60)
    assert validar_trecho("10", "") == (10, None)
    with pytest.raises(ValueError, match="depois do início"):
        validar_trecho("2:00", "1:00")
    with pytest.raises(ValueError, match="Não entendi o início"):
        validar_trecho("xx", "")
    with pytest.raises(ValueError, match="Preencha"):
        validar_trecho("", "")


def test_formatos_de_tempo_para_mostrar_e_para_nome():
    assert formatar_tempo(3750) == "1:02:30" and formatar_tempo(65) == "1:05"
    assert sufixo_trecho(1064, 1200) == " (trecho 17m44s-20m00s)"
    assert sufixo_trecho(3750, None) == " (trecho 1h02m30s-fim)"
    assert ":" not in sufixo_trecho(3750, 3800)          # Windows não aceita ":" no nome


# ---------- vários links e repetidos ----------
def test_separar_links_sem_repetir():
    texto = """https://youtu.be/aaaaaaaaaaa
    https://www.tiktok.com/@x/video/1  https://www.youtube.com/watch?v=aaaaaaaaaaa&si=z
    qualquer coisa, https://google.com"""
    validos, invalidos = separar_links(texto)
    assert validos == ["https://youtu.be/aaaaaaaaaaa", "https://www.tiktok.com/@x/video/1"]
    assert invalidos == ["qualquer", "coisa", "https://google.com"]


def test_chave_do_link_reconhece_o_mesmo_video():
    iguais = ["https://www.youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk?si=xyz&t=10",
              "https://m.youtube.com/watch?feature=share&v=abcdefghijk", "https://www.youtube.com/shorts/abcdefghijk",
              "https://www.youtube.com/live/abcdefghijk?si=1"]
    assert {chave_do_link(u) for u in iguais} == {"youtube:abcdefghijk"}
    assert chave_do_link("https://www.tiktok.com/@a/video/123?lang=pt") == chave_do_link(
        "https://tiktok.com/@a/video/123") == "tiktok:123"
    assert chave_do_link("https://www.twitch.tv/videos/999") == "twitch:999"
    assert chave_do_link("https://youtu.be/aaaaaaaaaaa") != chave_do_link("https://youtu.be/bbbbbbbbbbb")


# ---------- transcrição cortada no trecho ----------
def test_cortar_segmentos_recomeça_do_zero():
    segs = [
        {"inicio": 0, "fim": 5, "texto": "antes", "palavras": [{"inicio": 0, "fim": 5, "palavra": "antes"}]},
        {"inicio": 8, "fim": 12, "texto": "a b", "palavras": [{"inicio": 8, "fim": 9, "palavra": "a"},
                                                             {"inicio": 11, "fim": 12, "palavra": "b"}]},
        {"inicio": 15, "fim": 18, "texto": "dentro", "palavras": [{"inicio": 15, "fim": 18, "palavra": "dentro"}]},
        {"inicio": 30, "fim": 31, "texto": "depois", "palavras": []},
    ]
    r = cortar_segmentos(segs, 10, 20)
    assert [s["texto"] for s in r] == ["b", "dentro"]
    assert r[0]["inicio"] == 0 and r[0]["palavras"][0] == {"inicio": 1, "fim": 2, "palavra": "b"}
    assert r[1]["inicio"] == 5 and r[1]["fim"] == 8
    assert [s["texto"] for s in cortar_segmentos(segs, 10, None)] == ["b", "dentro", "depois"]


# ---------- opções do yt-dlp ----------
def test_opcoes_com_trecho_nao_usam_o_download_ranges_lento():
    p = Pedido(url="https://youtu.be/x", pasta=r"D:\VCD", qualidade="🎵 Só áudio (MP3 320k)",
               inicio=1064, fim=1200, miniatura=True)
    o = montar_opcoes(p, lambda d: None)
    # o download_ranges do yt-dlp recodificava o trecho inteiro (lento) e não deixava cancelar
    assert "download_ranges" not in o and "force_keyframes_at_cuts" not in o
    assert o["outtmpl"].endswith("[%(id)s] (trecho 17m44s-20m00s).%(ext)s")
    assert [pp["key"] for pp in o["postprocessors"]] == ["FFmpegExtractAudio"]   # capa do trecho é à parte


def test_miniatura_sem_trecho_soma_aos_pos_processadores():
    p = Pedido(url="https://youtu.be/x", pasta="p", qualidade="🎵 Só áudio (MP3 320k)", miniatura=True)
    o = montar_opcoes(p, lambda d: None)
    assert [pp["key"] for pp in o["postprocessors"]] == ["FFmpegExtractAudio", "FFmpegThumbnailsConvertor"]
    assert o["writethumbnail"] is True


def test_prefere_mp4_h264_sem_perder_resolucao():
    o = montar_opcoes(Pedido(url="https://youtu.be/x", pasta="p", qualidade="📱 720p"), lambda d: None)
    assert o["format_sort"][:2] == ["res", "fps"]               # qualidade primeiro
    assert "vcodec:h264" in o["format_sort"] and "acodec:aac" in o["format_sort"]
    assert o["merge_output_format"] == "mp4/mkv"
    assert "writethumbnail" not in o


def test_config_paralelos_limitado():
    cfg = config.carregar()
    assert cfg["downloads_paralelos"] == 2
    assert config.atualizar(cfg, {"downloads_paralelos": 9})["downloads_paralelos"] == 4
    assert config.atualizar(cfg, {"downloads_paralelos": "0"})["downloads_paralelos"] == 1


# ---------- notificação ----------
def test_notificacao_escapa_aspas_e_tags():
    s = montar_script("✔ Download concluído", "O 'CAP' <não> acerta & \"nada\"")
    assert "&apos;CAP&apos;" in s and "&lt;não&gt;" in s and "&amp;" in s and "&quot;nada&quot;" in s
    assert "'CAP'" not in s                                   # não quebra a string do PowerShell


# ---------- histórico ----------
def test_historico_registra_e_acha_repetido(tmp_path):
    h = Historico(tmp_path / "h.db")
    p = Pedido(url="https://www.youtube.com/watch?v=abcdefghijk", pasta="D:\\x", qualidade="📱 720p")
    r = h.registrar(p.para_dict())
    assert h.procurar_duplicado("https://youtu.be/abcdefghijk") is None      # ainda não terminou
    h.atualizar(r, status="ok", titulo="Live do Cross", arquivos=["a.mp4"])
    dup = h.procurar_duplicado("https://youtu.be/abcdefghijk?si=1")
    assert dup["titulo"] == "Live do Cross" and dup["arquivos"] == ["a.mp4"]
    assert dup["pedido"]["qualidade"] == "📱 720p" and "login_opts" not in dup["pedido"]
    assert h.procurar_duplicado("https://youtu.be/abcdefghijk", 10, 20) is None   # trecho é outro download
    assert h.listar("cross")[0]["id"] == r and h.listar("nada disso") == []


def test_historico_marca_interrompidos_e_apaga(tmp_path):
    h = Historico(tmp_path / "h.db")
    a = h.registrar(Pedido(url="https://youtu.be/aaaaaaaaaaa", pasta="p", qualidade="q").para_dict())
    b = h.registrar(Pedido(url="https://youtu.be/bbbbbbbbbbb", pasta="p", qualidade="q").para_dict())
    h.atualizar(a, status="baixando")
    h.atualizar(b, status="ok")
    h.marcar_interrompidos()
    assert h.obter(a)["status"] == "interrompido" and h.obter(b)["status"] == "ok"
    h.apagar(a)
    assert h.obter(a) is None


# ---------- fila com yt-dlp falso ----------
class Controle:
    """Segura o download falso até o teste liberar."""
    def __init__(self):
        self.liberar = {}
        self.rodando = set()


CTRL = Controle()


class YDLFalso:
    def __init__(self, opcoes):
        self.o = opcoes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return {"id": url[-3:], "title": f"Vídeo {url[-3:]}", "duration": 100}

    def prepare_filename(self, info):
        return self.o["outtmpl"].replace("%(title).150B [%(id)s]", info["title"]).replace(".%(ext)s", ".mp4")

    def process_ie_result(self, info, download=True):
        final = self.prepare_filename(info)
        tmp = final + ".part"
        open(tmp, "ab").close()
        CTRL.rodando.add(info["id"])
        ev = CTRL.liberar.setdefault(info["id"], threading.Event())
        try:
            n = 0
            while not ev.is_set():
                for h in self.o["progress_hooks"]:
                    h({"status": "downloading", "downloaded_bytes": n, "total_bytes": 100,
                       "tmpfilename": tmp, "filename": final})
                n = min(n + 1, 99)
                time.sleep(0.01)
        finally:
            CTRL.rodando.discard(info["id"])
        os.replace(tmp, final)
        return {**info, "requested_downloads": [{"filepath": final}]}


def esperar(cond, segundos=5):
    fim = time.time() + segundos
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def fila(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads.yt_dlp, "YoutubeDL", YDLFalso)
    CTRL.liberar.clear()
    eventos, terminados = [], []
    h = Historico(tmp_path / "h.db")

    def criar(paralelos=1):
        return Gerenciador(eventos.append, paralelos, historico=h,
                           ao_terminar=lambda p, ev: terminados.append((p.id, ev["estado"], ev["titulo"])))
    criar.eventos, criar.terminados, criar.historico, criar.pasta = eventos, terminados, h, str(tmp_path)
    return criar


def _pedido(pasta, n):
    return Pedido(url=f"https://youtu.be/aaaaaaaa{n:03d}", pasta=pasta, qualidade="📱 720p")


def test_pausar_e_retomar_mantem_o_part(fila):
    g = fila()
    p = _pedido(fila.pasta, 1)
    g.adicionar(p)
    assert esperar(lambda: "001" in CTRL.rodando)
    g.pausar(p.id)
    assert esperar(lambda: g.estados[p.id] == "pausado")
    assert os.path.exists(os.path.join(fila.pasta, "Vídeo 001.mp4.part"))     # guardado para continuar
    assert fila.historico.obter(p.registro)["status"] == "pausado"
    g.retomar(p.id)
    assert esperar(lambda: "001" in CTRL.rodando)
    CTRL.liberar["001"].set()
    assert esperar(lambda: g.estados[p.id] == "ok")
    assert os.path.exists(os.path.join(fila.pasta, "Vídeo 001.mp4"))
    assert fila.historico.obter(p.registro)["status"] == "ok"
    assert fila.historico.obter(p.registro)["titulo"] == "Vídeo 001"
    assert fila.terminados == [(p.id, "ok", "[YouTube] Vídeo 001")]


def test_cancelar_apaga_os_pedacos(fila):
    g = fila()
    p = _pedido(fila.pasta, 2)
    g.adicionar(p)
    assert esperar(lambda: "002" in CTRL.rodando)
    g.cancelar(p.id)
    assert esperar(lambda: g.estados[p.id] == "cancelado")
    assert not os.path.exists(os.path.join(fila.pasta, "Vídeo 002.mp4.part"))
    assert fila.terminados == []                                     # cancelado não notifica


def test_pausar_quem_ainda_esta_na_fila(fila):
    g = fila(paralelos=1)
    a, b = _pedido(fila.pasta, 3), _pedido(fila.pasta, 4)
    g.adicionar(a)
    g.adicionar(b)
    assert esperar(lambda: "003" in CTRL.rodando)
    assert g.estados[b.id] == "fila"
    g.pausar(b.id)
    assert g.estados[b.id] == "pausado"
    CTRL.liberar["003"].set()
    assert esperar(lambda: g.estados[a.id] == "ok")
    time.sleep(0.3)
    assert g.estados[b.id] == "pausado" and "004" not in CTRL.rodando   # não começou sozinho
    g.cancelar(b.id)
    assert g.estados[b.id] == "cancelado"


def test_dois_ao_mesmo_tempo_e_mudar_para_um(fila):
    g = fila(paralelos=2)
    ps = [_pedido(fila.pasta, n) for n in (5, 6, 7)]
    for p in ps:
        g.adicionar(p)
    assert esperar(lambda: {"005", "006"} <= CTRL.rodando)
    assert "007" not in CTRL.rodando and g.na_fila() == 3
    g.definir_paralelos(1)
    CTRL.liberar["005"].set()
    CTRL.liberar["006"].set()
    assert esperar(lambda: "007" in CTRL.rodando)
    CTRL.liberar["007"].set()
    assert esperar(lambda: all(g.estados[p.id] == "ok" for p in ps))


def test_tentar_de_novo_depois_de_erro(fila, monkeypatch):
    g = fila()
    p = Pedido(url="https://youtu.be/aaaaaaaa008", pasta=fila.pasta, qualidade="⚙️ Avançado (escolher o formato)")
    g.adicionar(p)                                     # Avançado sem formato → erro amigável
    assert esperar(lambda: g.estados[p.id] == "erro")
    erro = [e for e in fila.eventos if e.get("estado") == "erro"][-1]["erro"]
    assert "escolha um formato" in erro
    p.qualidade = "📱 720p"
    assert g.retomar(p.id)
    CTRL.liberar.setdefault("008", threading.Event()).set()
    assert esperar(lambda: g.estados[p.id] == "ok")
