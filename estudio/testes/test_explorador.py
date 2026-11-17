"""Fase 2: explorador (caminhos seguros, listagem, informações, Lixeira, vigia ao vivo, servidor de mídia e prévia)."""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from nucleo import config, explorador
from nucleo.controle import Interrompido
from nucleo.ffmpeg import SEM_JANELA, exe_ffmpeg, ffmpeg_disponivel
from servidor_midia import ServidorMidia

precisa_ffmpeg = pytest.mark.skipif(not ffmpeg_disponivel(), reason="ffmpeg não encontrado")


def _ff(*args):
    subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **SEM_JANELA)


@pytest.fixture
def canal(tmp_path):
    """Pasta do canal de mentira: VideosLives com uma live, Ediçao e Cortes\\3-prontos."""
    raiz = tmp_path / "Canal"
    for sub in ("VideosLives", "Ediçao", os.path.join("Cortes", "3-prontos"), os.path.join("Ediçao", "sfx")):
        (raiz / sub).mkdir(parents=True)
    cfg = config.carregar()
    cfg["pasta_raiz"], cfg["pasta"] = str(raiz), None
    return raiz, cfg


# ---------- classificar ----------
@pytest.mark.parametrize("nome,pasta,tipo", [
    ("Live [abc].mp4", False, "video"), ("Live.MKV", False, "video"), ("a.m4a", False, "audio"),
    ("capa.jpg", False, "imagem"), ("t.md", False, "texto"), ("t.json", False, "json"),
    ("Live.mp4.part", False, "parcial"), ("Live.f398.mp4.part-Frag12", False, "parcial"), ("x.ytdl", False, "parcial"),
    ("Live (trecho 1m-2m).trecho-tmp", True, "parcial"), ("VideosLives", True, "pasta"),
    ("coisa.xyz", False, "outro"), ("semextensao", False, "outro"),
])
def test_classificar(nome, pasta, tipo):
    assert explorador.classificar(nome, pasta) == tipo


# ---------- caminhos seguros ----------
def test_dentro_de_recusa_fora_e_parecidos(tmp_path):
    raiz = tmp_path / "ViceCityDay"
    raiz.mkdir()
    (tmp_path / "ViceCityDay2").mkdir()
    assert explorador.dentro_de(str(raiz), [str(raiz)])
    assert explorador.dentro_de(str(raiz / "a" / "b.mp4"), [str(raiz)])
    assert not explorador.dentro_de(str(tmp_path / "ViceCityDay2" / "x"), [str(raiz)])     # só começa igual
    assert not explorador.dentro_de(str(raiz / ".." / "ViceCityDay2"), [str(raiz)])        # sobe com ..
    assert not explorador.dentro_de(str(tmp_path), [str(raiz)])
    assert not explorador.dentro_de("", [str(raiz)]) and not explorador.dentro_de(None, [str(raiz)])
    assert explorador.dentro_de(str(raiz).upper(), [str(raiz)])                           # Windows ignora maiúsculas


def test_raizes_incluem_downloads_fora_do_canal(canal, tmp_path):
    raiz, cfg = canal
    assert explorador.raizes_do_canal(cfg) == [str(raiz)]
    fora = tmp_path / "Outros"
    fora.mkdir()
    cfg["pasta"] = str(fora)
    assert explorador.raizes_do_canal(cfg) == [str(raiz), str(fora)]
    cfg["pasta_raiz"] = str(tmp_path / "nao_existe")
    assert explorador.raizes_do_canal(cfg) == [str(fora)]


# ---------- listar ----------
def test_listar_pastas_primeiro_parciais_e_ocultos(canal):
    raiz, _ = canal
    live = raiz / "VideosLives" / "Live [x]"
    live.mkdir()
    (live / "Live [x] - Parte 02.mp4").write_bytes(b"0" * 20)
    (live / "Live [x] - Parte 01.mp4").write_bytes(b"0" * 10)
    (live / "Live [x].mp4.part").write_bytes(b"0" * 5)
    (live / "Live [x].md").write_text("# t")
    (live / "desktop.ini").write_text("x")
    tmp = live / "Outra (trecho 1m-2m).trecho-tmp"
    tmp.mkdir()
    (tmp / "f0_00000.bin").write_bytes(b"0" * 100)
    (tmp / "f0_00001.bin").write_bytes(b"0" * 50)
    r = explorador.listar(str(live))
    nomes = [i["nome"] for i in r["itens"]]
    assert "desktop.ini" not in nomes and not r["truncado"]
    assert nomes.index("Live [x] - Parte 01.mp4") < nomes.index("Live [x] - Parte 02.mp4")
    porNome = {i["nome"]: i for i in r["itens"]}
    assert porNome["Live [x].mp4.part"]["parcial"] and porNome["Live [x].mp4.part"]["tamanho"] == 5
    pasta_tmp = porNome["Outra (trecho 1m-2m).trecho-tmp"]
    assert pasta_tmp["parcial"] and not pasta_tmp["pasta"] and pasta_tmp["tamanho"] == 150
    topo = explorador.listar(str(raiz / "VideosLives"))["itens"]
    assert topo[0]["pasta"] and topo[0]["nome"] == "Live [x]"


def test_listar_pastas_vem_antes_dos_arquivos(canal):
    raiz, _ = canal
    (raiz / "a.txt").write_text("x")
    itens = explorador.listar(str(raiz))["itens"]
    assert [i["nome"] for i in itens if i["pasta"]] == ["Cortes", "Ediçao", "VideosLives"]
    assert itens[-1]["nome"] == "a.txt"


def test_listar_corta_pastas_gigantes(tmp_path):
    for n in range(12):
        (tmp_path / f"{n}.txt").write_text("x")
    r = explorador.listar(str(tmp_path), limite=5)
    assert r["truncado"] and len(r["itens"]) == 5


# ---------- descrever ----------
@precisa_ffmpeg
def test_descrever_video_mostra_duracao_codec_e_se_toca(tmp_path):
    mp4, mkv = str(tmp_path / "a.mp4"), str(tmp_path / "b.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=3", "-f", "lavfi", "-i", "sine=d=3",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", mp4)
    _ff("-i", mp4, "-c", "copy", mkv)
    d = explorador.descrever(mp4)
    assert d["tipo"] == "video" and d["toca_direto"] and d["tamanho"] == os.path.getsize(mp4)
    m = d["midia"]
    assert m["valido"] and m["duracao"] == pytest.approx(3, abs=0.2)
    assert m["video"]["codec"] == "h264" and (m["video"]["largura"], m["video"]["altura"]) == (320, 240)
    assert m["video"]["fps"] == 25 and m["audio"]["codec"] == "aac"
    assert explorador.descrever(mkv)["toca_direto"] is False                      # mkv não toca no WebView2


@precisa_ffmpeg
def test_descrever_arquivo_quebrado_nao_derruba(tmp_path):
    ruim = tmp_path / "ruim.mp4"
    ruim.write_bytes(b"isso nao e um video")
    d = explorador.descrever(str(ruim))
    assert d["tipo"] == "video" and d["midia"]["valido"] is False


def test_descrever_texto_json_e_pasta(tmp_path):
    (tmp_path / "t.md").write_text("# Título\n\n**[00:00]** oi", encoding="utf-8")
    (tmp_path / "t.json").write_text(json.dumps({"a": [1, 2]}), encoding="utf-8")
    (tmp_path / "grande.txt").write_text("x" * (explorador.LIMITE_TEXTO + 10))
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "um.txt").write_text("1")
    assert "**[00:00]**" in explorador.descrever(str(tmp_path / "t.md"))["texto"]
    assert '"a": [\n' in explorador.descrever(str(tmp_path / "t.json"))["texto"]        # JSON bonito
    g = explorador.descrever(str(tmp_path / "grande.txt"))
    assert g["truncado"] and len(g["texto"]) == explorador.LIMITE_TEXTO
    p = explorador.descrever(str(tmp_path / "p"))
    assert p["pasta"] and p["n_itens"] == 1 and p["tamanho"] is None


# ---------- Lixeira ----------
@pytest.fixture
def lixeira(monkeypatch):
    mandados = []
    import send2trash
    monkeypatch.setattr(send2trash, "send2trash", lambda p: mandados.append(p))
    return mandados


def test_lixeira_manda_arquivo_do_canal(canal, lixeira):
    raiz, cfg = canal
    arq = raiz / "VideosLives" / "Live" / "a.mp4"
    arq.parent.mkdir()
    arq.write_bytes(b"x")
    explorador.para_lixeira(str(arq), cfg)
    assert lixeira == [os.path.normpath(str(arq))]
    assert arq.exists()                                  # quem apaga é a Lixeira, não o Estúdio


def test_lixeira_aceita_pasta_de_uma_live(canal, lixeira):
    raiz, cfg = canal
    live = raiz / "VideosLives" / "Live [x]"
    live.mkdir()
    explorador.para_lixeira(str(live), cfg)
    assert lixeira == [os.path.normpath(str(live))]


@pytest.mark.parametrize("rel", ["", "VideosLives", "Ediçao", "Cortes", os.path.join("Cortes", "3-prontos"),
                                 os.path.join("Ediçao", "sfx")])
def test_lixeira_recusa_a_estrutura_do_canal(canal, lixeira, rel):
    raiz, cfg = canal
    with pytest.raises(ValueError, match="estrutura do canal"):
        explorador.para_lixeira(str(raiz / rel) if rel else str(raiz), cfg)
    assert lixeira == []


def test_lixeira_recusa_fora_do_canal_e_inexistente(canal, lixeira, tmp_path):
    raiz, cfg = canal
    fora = tmp_path / "documento.docx"
    fora.write_text("x")
    with pytest.raises(ValueError, match="fora da pasta do canal"):
        explorador.para_lixeira(str(fora), cfg)
    with pytest.raises(ValueError, match="fora da pasta do canal"):
        explorador.para_lixeira(str(raiz / ".." / "documento.docx"), cfg)
    with pytest.raises(ValueError, match="não existe"):
        explorador.para_lixeira(str(raiz / "VideosLives" / "sumiu.mp4"), cfg)
    assert lixeira == [] and fora.exists()


def test_lixeira_explica_arquivo_em_uso(canal, monkeypatch):
    raiz, cfg = canal
    arq = raiz / "VideosLives" / "a.mp4.part"
    arq.write_bytes(b"x")
    import send2trash

    def ocupado(p):
        raise PermissionError("em uso")
    monkeypatch.setattr(send2trash, "send2trash", ocupado)
    with pytest.raises(ValueError, match="pause ou cancele"):
        explorador.para_lixeira(str(arq), cfg)


# ---------- vigia ao vivo (watchdog de verdade) ----------
def test_vigia_avisa_quando_chega_arquivo_e_agrupa_a_enxurrada(tmp_path):
    avisos = []
    v = explorador.Vigia(avisos.append, intervalo=0.2)
    assert v.iniciar([str(tmp_path)]) and v.disponivel
    try:
        time.sleep(0.4)
        (tmp_path / "live").mkdir()
        (tmp_path / "live" / "a.mp4.part").write_bytes(b"0")
        for n in range(60):                               # download escrevendo sem parar
            with open(tmp_path / "live" / "a.mp4.part", "ab") as f:
                f.write(b"0" * 1000)
        fim = time.time() + 6
        while time.time() < fim and not any(str(tmp_path / "live") in lote for lote in avisos):
            time.sleep(0.1)
        assert any(str(tmp_path / "live") in lote for lote in avisos)
        assert any(str(tmp_path) in lote for lote in avisos)          # a pasta nova aparece na pasta de cima
        assert len(avisos) <= 6                                        # 60 escritas viraram poucos avisos
    finally:
        v.parar()


# ---------- servidor de mídia ----------
@pytest.fixture
def servidor(tmp_path):
    liberada = tmp_path / "liberada"
    liberada.mkdir()
    (tmp_path / "proibida").mkdir()
    s = ServidorMidia(lambda p: os.path.normcase(os.path.realpath(p)).startswith(os.path.normcase(str(liberada))))
    s.liberada, s.proibida = liberada, tmp_path / "proibida"
    yield s
    s.parar()


def pedir(url, cabecalhos=None, metodo="GET", host=None):
    req = urllib.request.Request(url, headers=cabecalhos or {}, method=metodo)
    if host:
        req.add_unredirected_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_servidor_entrega_arquivo_e_trechos(servidor):
    arq = servidor.liberada / "Vídeo [x] ｜ teste ？.mp4"                   # nome com caracteres difíceis
    dados = bytes(range(256)) * 400
    arq.write_bytes(dados)
    url = servidor.url(str(arq))
    st, cab, corpo = pedir(url)
    assert st == 200 and corpo == dados and cab["Content-Type"] == "video/mp4" and cab["Accept-Ranges"] == "bytes"
    st, cab, corpo = pedir(url, {"Range": "bytes=100-199"})
    assert st == 206 and corpo == dados[100:200] and cab["Content-Range"] == f"bytes 100-199/{len(dados)}"
    st, _c, corpo = pedir(url, {"Range": "bytes=102000-"})
    assert st == 206 and corpo == dados[102000:]
    st, _c, corpo = pedir(url, {"Range": "bytes=-50"})
    assert st == 206 and corpo == dados[-50:]
    assert pedir(url, {"Range": "bytes=999999-"})[0] == 416
    st, cab, corpo = pedir(url, metodo="HEAD")
    assert st == 200 and corpo == b"" and cab["Content-Length"] == str(len(dados))


def test_servidor_recusa_senha_errada_host_estranho_e_arquivo_proibido(servidor):
    ok = servidor.liberada / "a.mp4"
    ok.write_bytes(b"x" * 10)
    proibido = servidor.proibida / "segredo.txt"
    proibido.write_text("senha do banco")
    assert pedir(servidor.url(str(ok)))[0] == 200
    errada = servidor.url(str(ok)).replace(servidor.token, "senha-errada")
    assert pedir(errada)[0] == 403
    assert pedir(servidor.url(str(proibido)))[0] == 404                         # fora da pasta permitida
    traversal = servidor.url(str(servidor.liberada / ".." / "proibida" / "segredo.txt"))
    assert pedir(traversal)[0] == 404
    assert pedir(servidor.url(str(ok)), host="site-malvado.com")[0] == 403     # DNS rebinding
    assert pedir(f"http://127.0.0.1:{servidor.porta}/m/{servidor.token}/nada")[0] == 404
    assert pedir(f"http://127.0.0.1:{servidor.porta}/")[0] == 403


def test_servidor_so_escuta_no_computador_local(servidor):
    assert servidor.httpd.server_address[0] == "127.0.0.1"


# ---------- prévia leve para formatos que não tocam ----------
@precisa_ffmpeg
def test_previa_gera_mp4_leve_e_reaproveita_o_cache(tmp_path):
    mkv = str(tmp_path / "grande.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=1280x720:r=25:d=4", "-f", "lavfi", "-i", "sine=d=4", "-c:v", "libx264",
        "-preset", "ultrafast", "-c:a", "aac", "-shortest", mkv)
    progresso = []
    destino = explorador.gerar_previa(mkv, progresso.append)
    d = explorador.descrever(destino)
    assert os.path.exists(destino) and d["midia"]["video"]["altura"] == 540 and d["midia"]["video"]["codec"] == "h264"
    assert d["midia"]["audio"]["codec"] == "aac" and d["midia"]["duracao"] == pytest.approx(4, abs=0.3)
    assert progresso and max(progresso) <= 99
    t = time.time()
    assert explorador.gerar_previa(mkv, lambda p: None) == destino               # cache: instantâneo
    assert time.time() - t < 1
    assert not os.path.exists(destino + ".part")


@precisa_ffmpeg
def test_previa_nao_amplia_video_pequeno_e_cancela_limpando(tmp_path):
    pequeno = str(tmp_path / "p.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=2", "-c:v", "libx264", "-preset", "ultrafast", pequeno)
    assert explorador.descrever(explorador.gerar_previa(pequeno, lambda p: None))["midia"]["video"]["altura"] == 240
    longo = str(tmp_path / "longo.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=1920x1080:r=30:d=120", "-c:v", "libx264", "-preset", "ultrafast", longo)

    def cancelar():
        raise Interrompido("cancelar")
    with pytest.raises(Interrompido):
        explorador.gerar_previa(longo, lambda p: None, cancelar)
    assert not os.path.exists(explorador.caminho_previa(longo)) and \
        not os.path.exists(explorador.caminho_previa(longo) + ".part")


# ---------- a ponte (o que a interface chama) ----------
@pytest.fixture
def ponte(canal, tmp_path):
    import ponte as P
    raiz, cfg = canal
    p = P.Ponte()
    p.salvar_config({"pasta_raiz": str(raiz), "pasta": None})
    yield p
    p._midia.parar()


@precisa_ffmpeg
def test_ponte_lista_descreve_e_recusa_fora(ponte, canal, tmp_path):
    raiz, _ = canal
    live = raiz / "VideosLives" / "Live"
    live.mkdir()
    mp4, mkv = str(live / "a.mp4"), str(live / "b.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=2", "-c:v", "libx264", mp4)
    _ff("-i", mp4, "-c", "copy", mkv)
    (live / "capa.jpg").write_bytes(b"\xff\xd8\xff")
    rz = ponte.explorador_raizes()
    assert rz["raizes"][0]["caminho"] == str(raiz) and rz["erro"] is None
    assert {i["nome"] for i in ponte.listar_pasta(str(live))["itens"]} == {"a.mp4", "b.mkv", "capa.jpg"}
    mp = ponte.info_arquivo(mp4)["info"]
    assert mp["url"].startswith("http://127.0.0.1:") and "url_previa" not in mp
    assert urllib.request.urlopen(mp["url"], timeout=10).status == 200                 # toca de verdade
    mk = ponte.info_arquivo(mkv)["info"]
    assert "url" not in mk and mk["toca_direto"] is False                                # precisa de prévia
    assert ponte.info_arquivo(str(live / "capa.jpg"))["info"]["url"]
    fora = tmp_path / "segredo.txt"
    fora.write_text("x")
    assert ponte.listar_pasta(str(tmp_path))["ok"] is False
    assert ponte.info_arquivo(str(fora))["ok"] is False
    assert ponte.abrir_arquivo(str(fora))["ok"] is False and ponte.mostrar_no_explorer(str(fora))["ok"] is False
    assert ponte.mover_para_lixeira(str(fora))["ok"] is False and fora.exists()


@precisa_ffmpeg
def test_ponte_gera_previa_por_evento(ponte, canal):
    raiz, _ = canal
    mkv = str(raiz / "VideosLives" / "x.mkv")
    _ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=2", "-c:v", "libx264", "-preset", "ultrafast", mkv)
    assert ponte.gerar_previa(mkv)["ok"]
    fim = time.time() + 30
    pronto = None
    while time.time() < fim and not pronto:
        try:
            ev = ponte._eventos.get(timeout=0.5)
        except Exception:
            continue
        if ev.get("tipo") == "previa" and ev["estado"] in ("pronta", "erro"):
            pronto = ev
    assert pronto and pronto["estado"] == "pronta" and urllib.request.urlopen(pronto["url"], timeout=10).status == 200
    assert ponte.info_arquivo(mkv)["info"]["url_previa"]                                # da próxima vez já vem pronta


def test_ponte_sem_pasta_do_canal_explica_como_resolver(ponte, tmp_path):
    ponte.salvar_config({"pasta_raiz": str(tmp_path / "nao_existe"), "pasta": None})
    r = ponte.explorador_raizes()
    assert r["raizes"] == [] and "Escolha onde ela está" in r["erro"]


def test_ponte_lixeira_recusa_pasta_da_estrutura(ponte, canal):
    raiz, _ = canal
    r = ponte.mover_para_lixeira(str(raiz / "VideosLives"))
    assert r["ok"] is False and "estrutura do canal" in r["erro"] and (raiz / "VideosLives").exists()
