"""Fase 1C: lives da Twitch em andamento (trecho do VOD que está sendo gerado e gravação a partir de agora)
e o limite de tempo da prévia."""
import os
import subprocess
import threading
import time

import pytest

from nucleo import gravacao
from nucleo.controle import Interrompido
from nucleo.downloads import Gerenciador, Pedido, montar_opcoes
from nucleo.erros import explicar_erro
from nucleo.ffmpeg import exe_ffmpeg, ffmpeg_disponivel

precisa_ffmpeg = pytest.mark.skipif(not ffmpeg_disponivel(), reason="sem ffmpeg")


def test_tipo_live():
    assert gravacao.tipo_live({"is_live": False}) is None
    assert gravacao.tipo_live({}) is None
    assert gravacao.tipo_live({"is_live": True, "extractor_key": "TwitchVod"}) == "vod"
    assert gravacao.tipo_live({"is_live": True, "extractor_key": "TwitchStream"}) == "gravar"
    assert gravacao.tipo_live({"is_live": True, "extractor_key": "Youtube"}) == "outra"


def test_opcoes_twitch_usam_vod_da_live_menos_na_gravacao(tmp_path):
    base = dict(pasta=str(tmp_path), qualidade="📱 720p")
    assert montar_opcoes(Pedido(url="https://www.twitch.tv/gaules", **base), lambda d: None)["live_from_start"]
    assert "live_from_start" not in montar_opcoes(
        Pedido(url="https://www.twitch.tv/gaules", gravar=True, **base), lambda d: None)
    assert "live_from_start" not in montar_opcoes(
        Pedido(url="https://www.youtube.com/watch?v=jNQXAC9IVRw", **base), lambda d: None)


def test_erro_canal_fora_do_ar_em_portugues():
    m = explicar_erro("ERROR: [twitch:stream] casimiro: The channel is not currently live", "Nenhum")
    assert "não está ao vivo" in m and "VOD" in m
    # as mensagens da live passam direto (não viram "erro desconhecido")
    assert explicar_erro(gravacao.MSG_LIVE_TRECHO, "Nenhum") == gravacao.MSG_LIVE_TRECHO
    assert explicar_erro(gravacao.MSG_LIVE_SEM_VOD, "Nenhum") == gravacao.MSG_LIVE_SEM_VOD


# ---------- recusas no download (yt-dlp falso) ----------
class YDLLive:
    info = {}

    def __init__(self, opcoes):
        self.opcoes = opcoes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return dict(self.info)

    def prepare_filename(self, info):
        return os.path.join(os.path.dirname(self.opcoes["outtmpl"]), "live [1].mp4")


def _rodar(monkeypatch, tmp_path, info, **pedido):
    import nucleo.downloads as D
    YDLLive.info = info
    monkeypatch.setattr(D.yt_dlp, "YoutubeDL", YDLLive)
    eventos = []
    g = Gerenciador(eventos.append, 1)
    p = Pedido(url="https://www.twitch.tv/gaules", pasta=str(tmp_path), qualidade="📱 720p", **pedido)
    g.adicionar(p)
    for _ in range(100):
        if g.estados.get(p.id) in ("ok", "erro"):
            break
        time.sleep(0.05)
    return g.estados[p.id], [e for e in eventos if e.get("erro")]


@pytest.mark.parametrize("info,pedido,trecho_msg", [
    ({"is_live": True, "extractor_key": "TwitchVod"}, {}, gravacao.MSG_LIVE_TRECHO),
    ({"is_live": True, "extractor_key": "TwitchStream"}, {}, gravacao.MSG_LIVE_SEM_VOD),
    ({"is_live": False, "extractor_key": "TwitchVod"}, {"gravar": True}, gravacao.MSG_NAO_AO_VIVO),
])
def test_live_recusada_com_explicacao(monkeypatch, tmp_path, info, pedido, trecho_msg):
    estado, erros = _rodar(monkeypatch, tmp_path, info, **pedido)
    assert estado == "erro" and erros[-1]["erro"] == trecho_msg


def test_parar_so_vale_para_gravacao(tmp_path):
    g = Gerenciador(lambda e: None, 1)
    normal = Pedido(url="https://www.twitch.tv/videos/1", pasta=str(tmp_path), qualidade="📱 720p")
    grav = Pedido(url="https://www.twitch.tv/gaules", pasta=str(tmp_path), qualidade="📱 720p", gravar=True)
    for p in (normal, grav):
        g.pedidos[p.id], g.estados[p.id] = p, "baixando"
    assert not g.parar(normal.id)
    assert g.pausar(grav.id) and g.pedir[grav.id] == "parar"   # Pausar numa gravação = Parar e salvar
    g._checar(grav)                                               # "parar" não interrompe o resto (transcrição...)
    g.pedir[grav.id] = "cancelar"
    with pytest.raises(Interrompido):
        g._checar(grav)


# ---------- gravação de verdade (uma "live" HLS local, com anúncio no começo, que não termina) ----------
class _YDL:
    """Lê file:// como o ydl.urlopen leria https://."""
    def urlopen(self, req):
        from urllib.request import url2pathname
        return open(url2pathname(req.url[len("file:"):]), "rb")


def _live_local(tmp_path):
    """Playlist HLS sem #EXT-X-ENDLIST (live que continua). Os 2 primeiros segmentos (de 5) são
    anúncio, com o título que a Twitch usa ("Amazon|..."); os outros se chamam "live"."""
    pasta = tmp_path / "hls"
    pasta.mkdir()
    m3u8 = pasta / "live.m3u8"
    subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=25:duration=15", "-f", "lavfi", "-i", "sine=duration=15",
                    "-c:v", "libx264", "-g", "25", "-c:a", "aac", "-shortest", "-f", "hls", "-hls_time", "3",
                    "-hls_playlist_type", "event", str(m3u8)], check=True)
    linhas, n = [], 0
    for l in m3u8.read_text().splitlines():
        if l.startswith("#EXTINF:"):
            l = l.split(",")[0] + ("," + ("Amazon|123" if n < 2 else "live"))
            n += 1
        if l != "#EXT-X-ENDLIST":
            linhas.append(l)
    m3u8.write_text("\n".join(linhas))
    return {"url": m3u8.as_uri(), "vcodec": "avc1"}


def test_segmentos_e_anuncio():
    texto = "#EXTM3U\n#EXTINF:2.000,Amazon|99\na.ts\n#EXTINF:2.000,live\nhttps://x/b.ts\n"
    segs = gravacao._segmentos(texto, "https://cdn/p/index.m3u8")
    assert segs == [("https://cdn/p/a.ts", 2.0, "Amazon|99"), ("https://x/b.ts", 2.0, "live")]
    assert gravacao.e_anuncio("Amazon|99") and not gravacao.e_anuncio("live") and not gravacao.e_anuncio("")


@precisa_ffmpeg
def test_gravar_pula_anuncio_ate_parar_e_salva_mp4(tmp_path):
    info = _live_local(tmp_path)
    parar = threading.Event()
    avisos = []
    threading.Timer(1.5, parar.set).start()
    t = time.time()
    arq = gravacao.gravar_live(_YDL(), info, str(tmp_path / "gaules (gravado)"), lambda: None,
                               parar.is_set, lambda s, p: avisos.append(s), intervalo=0.3)
    assert time.time() - t < 10
    assert arq.endswith(".mp4") and os.path.getsize(arq) > 10_000
    assert not os.path.exists(str(tmp_path / "gaules (gravado).gravando.ts"))
    assert any("Gravando" in a and "pulei 0:06 de anúncio" in a for a in avisos)
    sonda = subprocess.run([exe_ffmpeg(), "-hide_banner", "-i", arq], capture_output=True).stderr.decode(errors="ignore")
    assert "Video: h264" in sonda and "Audio: aac" in sonda
    assert "Duration: 00:00:08" in sonda or "Duration: 00:00:09" in sonda   # 15 s - 6 s de anúncio


@precisa_ffmpeg
def test_so_anuncio_nao_vira_arquivo(tmp_path):
    info = _live_local(tmp_path)
    m3u8 = tmp_path / "hls" / "live.m3u8"
    m3u8.write_text(m3u8.read_text().replace(",live", ",Amazon|1"))
    avisos = []
    parar = threading.Event()
    threading.Timer(1, parar.set).start()
    with pytest.raises(RuntimeError, match="anúncio"):
        gravacao.gravar_live(_YDL(), info, str(tmp_path / "x"), lambda: None, parar.is_set,
                             lambda s, p: avisos.append(s), intervalo=0.3)
    assert any("Esperando o anúncio" in a for a in avisos)


@precisa_ffmpeg
def test_cancelar_gravacao_apaga_tudo(tmp_path):
    info = _live_local(tmp_path)
    base = str(tmp_path / "cancelada")
    cancelar = threading.Event()
    threading.Timer(1, cancelar.set).start()

    def checar():
        if cancelar.is_set():
            raise Interrompido("cancelar")
    with pytest.raises(Interrompido):
        gravacao.gravar_live(_YDL(), info, base, checar, lambda: False, lambda s, p: None, intervalo=0.3)
    assert not os.path.exists(base + ".gravando.ts") and not os.path.exists(base + ".mp4")


# ---------- prévia com limite de tempo ----------
def test_previa_desiste_depois_do_limite(monkeypatch):
    import ponte as P
    monkeypatch.setattr(P, "LIMITE_PREVIA", 0.5)
    monkeypatch.setattr(P, "ler_previa", lambda *a, **k: time.sleep(5))
    p = P.Ponte()
    try:
        t = time.time()
        r = p.previa("https://www.youtube.com/watch?v=9CfgGwzfKWc")
        assert time.time() - t < 2
        assert not r["ok"] and "demorou mais de" in r["erro"] and "atualizar.bat" in r["erro"]
    finally:
        p._midia.parar()
