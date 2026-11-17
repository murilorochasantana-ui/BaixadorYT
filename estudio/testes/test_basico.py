"""Plataformas, erros, config, qualidades e montagem das opções do yt-dlp."""
import json
import os

import pytest

from nucleo import config
from nucleo.downloads import Pedido, montar_opcoes
from nucleo.erros import explicar_erro, limpar_mensagem
from nucleo.plataformas import link_valido, plataforma
from nucleo.qualidades import AVANCADO, ORDEM, QUALIDADES, opcoes_qualidade


# ---------- plataformas ----------
@pytest.mark.parametrize("url,esperado", [
    ("https://www.youtube.com/watch?v=abc", "YouTube"),
    ("https://youtu.be/abc?t=1064", "YouTube"),
    ("https://vm.tiktok.com/xyz/", "TikTok"),
    ("https://www.instagram.com/reel/abc/", "Instagram"),
    ("https://clips.twitch.tv/abc", "Twitch"),
    ("https://pin.it/abc", "Pinterest"),
    ("https://br.pinterest.com/pin/1/", "Pinterest"),
    ("https://www.pinterest.com.br/pin/1/", "Pinterest"),
    ("https://fb.watch/abc", "Facebook"),
    ("https://m.facebook.com/watch?v=1", "Facebook"),
])
def test_plataformas_aceitas(url, esperado):
    assert plataforma(url) == esperado


@pytest.mark.parametrize("url", ["", "youtube.com/watch", "https://evil.com/youtube.com",
                                 "https://notyoutube.com/x", "ftp://youtube.com"])
def test_links_recusados(url):
    assert not link_valido(url)


# ---------- erros ----------
def test_erro_idade_sem_login_explica_o_que_fazer():
    msg = explicar_erro("Sign in to confirm your age", "Nenhum")
    assert "Login (+18 / Instagram)" in msg and "Firefox" in msg


def test_erro_formato_indisponivel_sugere_avancado():
    assert "Avançado" in explicar_erro("Requested format is not available", "Nenhum")


def test_erro_desconhecido_sugere_atualizar():
    assert "atualizar.bat" in explicar_erro("algo estranho", "Nenhum")


def test_limpar_mensagem_tira_cores_e_prefixo():
    assert limpar_mensagem("\x1b[0;31mERROR: \x1b[0mfalhou; please report this") == "falhou"


# ---------- config ----------
def test_config_importa_app_antigo(tmp_path, monkeypatch):
    antigo = tmp_path / "config_antigo.json"
    antigo.write_text(json.dumps({"pasta": r"D:\ViceCityDay\VideosLives", "qualidade": "📱 720p",
                                  "modo_claude": True, "limite_mb": 300, "lixo": 1}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_APP_ANTIGO", antigo)
    cfg = config.carregar()
    assert cfg["qualidade"] == "📱 720p" and cfg["limite_mb"] == 300 and cfg["modo_claude"] is True
    assert "lixo" not in cfg
    assert cfg["modelo_whisper"] == "small"          # padrão preenchido
    assert config.arquivo_config().exists()          # já salvou no lugar novo


def test_importar_app_antigo_le_so_chaves_conhecidas(tmp_path):
    antigo = tmp_path / "c.json"
    antigo.write_text(json.dumps({"login": "Firefox", "x": 1}), encoding="utf-8")
    assert config.importar_app_antigo(antigo) == {"login": "Firefox"}
    assert config.importar_app_antigo(tmp_path / "nao_existe.json") == {}


def test_config_atualizar_valida_limite_e_ignora_chaves_desconhecidas():
    cfg = config.carregar()
    cfg = config.atualizar(cfg, {"limite_mb": "5", "senha": "123"})
    assert cfg["limite_mb"] == 10 and "senha" not in cfg
    assert json.loads(config.arquivo_config().read_text(encoding="utf-8"))["limite_mb"] == 10


def test_pastas_do_canal_vem_da_config():
    cfg = config.carregar()
    cfg["pasta"] = None
    cfg["pasta_raiz"] = r"E:\Canal"
    assert config.pasta_downloads(cfg) == os.path.join(r"E:\Canal", "VideosLives")
    assert str(config.pasta_do_canal(cfg, "prontos")).endswith(os.path.join("Cortes", "3-prontos"))


def test_config_estragada_volta_ao_padrao():
    config.arquivo_config().write_text("{quebrado", encoding="utf-8")
    assert config.carregar()["limite_mb"] == 400


# ---------- qualidades ----------
def test_nomes_antigos_continuam_existindo():
    for nome in ["🏆 Melhor qualidade (até 4K/8K)", "🎬 1080p", "📱 720p",
                 "✂️ Para edição (H.264 - CapCut/Premiere)", "🎵 Só áudio (MP3 320k)"]:
        assert nome in QUALIDADES
    assert set(ORDEM) == set(QUALIDADES) | {AVANCADO}


def test_avancado_so_video_junta_com_audio():
    o = opcoes_qualidade(AVANCADO, {"id": "137", "tem_video": True, "tem_audio": False})
    assert o["format"] == "137+ba/137"


def test_avancado_formato_completo_vai_direto():
    assert opcoes_qualidade(AVANCADO, {"id": "18", "tem_video": True, "tem_audio": True}) == {"format": "18"}


def test_avancado_sem_formato_da_erro_amigavel():
    with pytest.raises(ValueError, match="escolha um formato"):
        opcoes_qualidade(AVANCADO, None)


def test_opcoes_qualidade_nao_altera_o_original():
    o = opcoes_qualidade("🎵 Só áudio (MP3 320k)")
    o["postprocessors"].clear()
    assert QUALIDADES["🎵 Só áudio (MP3 320k)"]["postprocessors"]


# ---------- opções do download ----------
def test_modo_claude_cria_pasta_por_video():
    p = Pedido(url="https://youtu.be/x", pasta=r"D:\VCD", qualidade="📱 720p", limite_mb=400)
    o = montar_opcoes(p, lambda d: None)
    assert "[%(playlist_id,id)s]" in o["outtmpl"] and o["outtmpl"].count(os.sep) >= 2
    assert o["noplaylist"] and o["playlist_items"] == "1-20"


def test_sem_modo_claude_salva_direto_e_usa_login():
    p = Pedido(url="https://youtu.be/x", pasta=r"D:\VCD", qualidade="🎬 1080p",
               login_opts={"cookiesfrombrowser": ("firefox",)})
    o = montar_opcoes(p, lambda d: None)
    assert o["outtmpl"] == os.path.join(r"D:\VCD", "%(title).150B [%(id)s].%(ext)s")
    assert o["cookiesfrombrowser"] == ("firefox",)
    assert o["format"].startswith("bv*[height<=1080]")
