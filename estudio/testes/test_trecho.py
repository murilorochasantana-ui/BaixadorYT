"""Baixador de trecho (nucleo/trecho.py) sem internet: vídeos gerados no PC no mesmo formato do
YouTube (MP4 fragmentado com índice sidx no começo) e um yt-dlp falso que entrega os bytes pedidos."""
import io
import os
import re
import subprocess
import time

import pytest

from nucleo import trecho as T
from nucleo.downloads import Gerenciador, Interrompido, Pedido
from nucleo.ffmpeg import SEM_JANELA, exe_ffmpeg, exe_ffprobe, ffmpeg_disponivel, rodar_cancelavel

pytestmark = pytest.mark.skipif(not ffmpeg_disponivel(), reason="ffmpeg não encontrado")
DASH = ["-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof+global_sidx"]


def _ff(*args):
    subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, **SEM_JANELA)


@pytest.fixture(scope="module")
def arquivos(tmp_path_factory):
    """60 s de vídeo (quadro-chave a cada 2 s) e de áudio, separados, como o YouTube entrega."""
    d = tmp_path_factory.mktemp("dash")
    video, audio = str(d / "video.mp4"), str(d / "audio.m4a")
    _ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=60", "-c:v", "libx264", "-preset", "ultrafast",
        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", *DASH, video)
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=60", "-c:a", "aac", "-b:a", "96k", *DASH, audio)
    return video, audio


def duracao(arq):
    r = subprocess.run([exe_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arq],
                       capture_output=True, text=True, **SEM_JANELA)
    return float(r.stdout.strip())


def fluxos(arq):
    r = subprocess.run([exe_ffprobe(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", arq],
                       capture_output=True, text=True, **SEM_JANELA)
    return sorted(r.stdout.split())


class Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class YDLFalso:
    """Responde aos pedidos com "Range" lendo o arquivo local (como o YouTube responderia)."""
    def __init__(self, caminhos):
        self.caminhos = caminhos
        self.pedidos = 0

    def urlopen(self, req):
        self.pedidos += 1
        a, b = map(int, re.match(r"bytes=(\d+)-(\d+)", req.headers["Range"]).groups())
        with open(self.caminhos[req.url], "rb") as f:
            f.seek(a)
            return Resposta(f.read(b - a + 1))


def _formatos(video, audio):
    return [
        {"format_id": "v", "url": "http://falso/v", "ext": "mp4", "protocol": "https", "vcodec": "avc1.4d401e",
         "acodec": "none", "filesize": os.path.getsize(video), "available_at": time.time() - 1},
        {"format_id": "a", "url": "http://falso/a", "ext": "m4a", "protocol": "https", "vcodec": "none",
         "acodec": "mp4a.40.2", "filesize": os.path.getsize(audio)},
    ]


def _trecho(tmp_path, arquivos, inicio, fim, checar=lambda: None, formatos=None, codec=None):
    video, audio = arquivos
    fmts = formatos or _formatos(video, audio)
    ydl = YDLFalso({"http://falso/v": video, "http://falso/a": audio})
    info = {"id": "x", "title": "t", "duration": 60, "requested_formats": fmts}
    avisos = []
    tr = T.Trecho(ydl, info, str(tmp_path / "Live (trecho)"), inicio, fim, checar,
                  lambda s, p=None, v="", e="": avisos.append(s), codec)
    return tr, ydl, avisos


# ---------- índice ----------
def test_le_o_indice_e_escolhe_os_bytes_do_trecho(arquivos):
    with open(arquivos[0], "rb") as f:
        init, segs = T.ler_indice(f.read(512 << 10))
    assert init[4:8] == b"ftyp" and len(segs) == 30 and segs[0][:2] == (0.0, 2.0)
    t_ini, b_ini, b_fim = T.escolher_segmentos(segs, 21, 33)
    assert t_ini == 20.0 and b_ini == segs[10][2] and b_fim == segs[16][3]
    with pytest.raises(T.SemIndice):
        T.ler_indice(b"\x00\x00\x00\x08free" * 10)


def test_blocos_cobrem_tudo_sem_sobrar():
    blocos = T.dividir_em_blocos(100, 1099, 300)
    assert blocos == [(100, 399), (400, 699), (700, 999), (1000, 1099)]


@pytest.mark.parametrize("fmts,codec,ext", [
    ([{"vcodec": "avc1.64001f", "acodec": "none"}, {"vcodec": "none", "acodec": "mp4a.40.2"}], None, "mp4"),
    ([{"vcodec": "av01.0.08M.08", "acodec": "none"}, {"vcodec": "none", "acodec": "opus"}], None, "mp4"),
    ([{"vcodec": "vp8", "acodec": "vorbis"}], None, "mkv"),
    ([{"vcodec": "none", "acodec": "mp4a.40.2"}], None, "m4a"),
    ([{"vcodec": "none", "acodec": "mp4a.40.2"}], "mp3", "mp3"),
])
def test_extensao_prefere_mp4(fmts, codec, ext):
    assert T.extensao_saida(fmts, codec) == ext


def test_caminho_escolhido_por_site():
    assert T.caminho_para([{"protocol": "https", "ext": "mp4", "filesize": 9}]) == "indice"
    assert T.caminho_para([{"protocol": "m3u8_native", "ext": "mp4"}]) == "hls"
    assert T.caminho_para([{"protocol": "https", "ext": "mp4"}]) == "inteiro"      # TikTok: sem tamanho
    assert T.caminho_para([{"protocol": "https", "ext": "webm", "filesize": 9}]) == "inteiro"


# ---------- trecho completo ----------
def test_trecho_baixa_so_o_pedaco_e_corta_sem_recodificar(tmp_path, arquivos):
    tr, ydl, avisos = _trecho(tmp_path, arquivos, 21, 33)
    saida, inicio_real, fim = tr.baixar()
    assert saida.endswith("Live (trecho).mp4") and os.path.exists(saida)
    assert inicio_real == pytest.approx(20.0, abs=0.05)          # quadro-chave antes de 21 s
    assert duracao(saida) == pytest.approx(13.0, abs=0.15)       # 20 → 33
    assert fluxos(saida) == ["audio", "video"]
    assert not os.path.exists(tr.pasta_tmp)                       # pedaços apagados no fim
    total = sum(os.path.getsize(a) for a in arquivos)
    assert os.path.getsize(saida) < total * 0.4                    # não baixou o vídeo inteiro
    assert any("Baixando trecho" in a for a in avisos) and any("Cortando" in a for a in avisos)


def test_trecho_ate_o_final(tmp_path, arquivos):
    tr, _ydl, _ = _trecho(tmp_path, arquivos, 50, None)
    saida, inicio_real, fim = tr.baixar()
    assert inicio_real == pytest.approx(50.0, abs=0.05) and fim is None
    assert duracao(saida) == pytest.approx(10.0, abs=0.15)


def test_trecho_so_audio_em_mp3(tmp_path, arquivos):
    video, audio = arquivos
    fmts = [_formatos(video, audio)[1]]
    tr, _ydl, _ = _trecho(tmp_path, arquivos, 10, 20, formatos=fmts, codec="mp3")
    saida, inicio_real, _ = tr.baixar()
    assert saida.endswith(".mp3") and fluxos(saida) == ["audio"]
    assert duracao(saida) == pytest.approx(20 - inicio_real, abs=0.3)


def test_pausar_guarda_os_pedacos_e_retomar_reaproveita(tmp_path, arquivos, monkeypatch):
    monkeypatch.setattr(T, "BLOCO", 32 << 10)          # pedaços pequenos: muitos pedidos
    monkeypatch.setattr(T, "PARALELOS", 1)
    contador = {"n": 0}

    def checar_pausa():
        contador["n"] += 1
        if contador["n"] > 6:
            raise Interrompido("pausar")
    tr, ydl1, _ = _trecho(tmp_path, arquivos, 5, 55, checar_pausa)
    with pytest.raises(Interrompido):
        tr.baixar()
    guardados = [x for x in os.listdir(tr.pasta_tmp) if x.endswith(".bin")]
    assert guardados                                             # o que baixou ficou guardado
    tr2, ydl2, _ = _trecho(tmp_path, arquivos, 5, 55)
    saida, _ini, _fim = tr2.baixar()
    assert duracao(saida) == pytest.approx(51.0, abs=0.2)
    blocos_total = len([1 for _ in T.dividir_em_blocos(0, os.path.getsize(arquivos[0]), 32 << 10)])
    assert ydl2.pedidos < ydl1.pedidos + blocos_total            # não baixou tudo de novo


def test_cancelar_apaga_tudo(tmp_path, arquivos, monkeypatch):
    monkeypatch.setattr(T, "BLOCO", 32 << 10)

    def checar():
        if len(os.listdir(tmp_path / "Live (trecho).trecho-tmp")) > 3:
            raise Interrompido("cancelar")
    tr, _ydl, _ = _trecho(tmp_path, arquivos, 5, 55, checar)
    with pytest.raises(Interrompido):
        tr.baixar()
    tr.apagar_temporarios()
    assert not os.path.exists(tr.pasta_tmp)
    assert [x for x in os.listdir(tmp_path)] == []               # nada sobrando na pasta


# ---------- plano B: se o método rápido falhar, usa o yt-dlp ----------
class YoutubeDLFalso:
    """Faz o papel do yt-dlp no plano B: entrega o trecho já cortado e guarda as opções recebidas."""
    opcoes = None
    bloquear = None          # Event: se definido, o "download" fica preso até o teste soltar
    pronto = None            # arquivo local que será "baixado"

    def __init__(self, opcoes):
        type(self).opcoes = opcoes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def process_ie_result(self, info, download=True):
        if type(self).bloquear is not None:
            type(self).bloquear.wait(10)
            raise RuntimeError("encerrado")
        destino = type(self).opcoes["outtmpl"].replace("%(ext)s", "mp4")
        import shutil
        shutil.copy(type(self).pronto, destino)
        return {"requested_downloads": [{"filepath": destino}]}


@pytest.fixture
def plano_b(tmp_path, monkeypatch):
    import yt_dlp
    pronto = str(tmp_path / "pronto.mp4")
    _ff("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=12", "-f", "lavfi", "-i", "sine=d=12",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", pronto)
    YoutubeDLFalso.opcoes, YoutubeDLFalso.bloquear, YoutubeDLFalso.pronto = None, None, pronto
    monkeypatch.setattr(yt_dlp, "YoutubeDL", YoutubeDLFalso)
    return YoutubeDLFalso


def _trecho_b(tmp_path, arquivos, ydl, inicio=21, fim=33, checar=lambda: None, codec=None, fmts=None):
    info = {"id": "x", "title": "t", "duration": 60, "requested_formats": fmts or _formatos(*arquivos)}
    motivos, avisos = [], []
    tr = T.Trecho(ydl, info, str(tmp_path / "Live (trecho)"), inicio, fim, checar,
                  lambda s, p=None, v="", e="": avisos.append(s), codec, {"format": "x"}, motivos.append)
    return tr, motivos, avisos


class YDLQueFalha(YDLFalso):
    def __init__(self, erro):
        super().__init__({})
        self.erro = erro

    def urlopen(self, req):
        raise self.erro


def test_403_do_youtube_volta_sozinho_para_o_ytdlp(tmp_path, arquivos, plano_b):
    ydl = YDLQueFalha(OSError("HTTP Error 403: Forbidden"))
    tr, motivos, avisos = _trecho_b(tmp_path, arquivos, ydl)
    saida, inicio_real, fim = tr.baixar()
    assert os.path.exists(saida) and saida.endswith("Live (trecho).mp4") and duracao(saida) == pytest.approx(12, abs=0.2)
    assert len(motivos) == 1 and "403" in motivos[0]                # avisou o motivo (para o aviso discreto)
    assert inicio_real == 21 and fim == 33                           # o corte do yt-dlp é exato
    faixa = list(plano_b.opcoes["download_ranges"]({"id": "x", "duration": 60}, None))
    assert faixa == [{"start_time": 21, "end_time": 33}]             # pediu o trecho certo ao yt-dlp
    assert plano_b.opcoes["force_keyframes_at_cuts"] is True
    assert not os.path.exists(tr.pasta_tmp)                          # sem sobras


def test_indice_diferente_do_esperado_tambem_cai_no_ytdlp(tmp_path, arquivos, plano_b):
    class Lixo(YDLQueFalha):
        def urlopen(self, req):
            return Resposta(b"\x00" * 4096)                          # o YouTube mudou o formato
    tr, motivos, _ = _trecho_b(tmp_path, arquivos, Lixo(None))
    saida, _i, _f = tr.baixar()
    assert os.path.exists(saida) and motivos and "SemIndice" in motivos[0]


def test_rede_caindo_no_meio_tambem_cai_no_ytdlp(tmp_path, arquivos, plano_b, monkeypatch):
    ydl = YDLFalso({"http://falso/v": arquivos[0], "http://falso/a": arquivos[1]})
    monkeypatch.setattr(T, "BLOCO", 32 << 10)
    original = ydl.urlopen

    def instavel(req):
        if ydl.pedidos >= 2:            # depois de ler o índice dos dois arquivos, a rede cai nos blocos
            raise ConnectionResetError("conexão encerrada")
        return original(req)
    ydl.urlopen = instavel
    tr, motivos, _ = _trecho_b(tmp_path, arquivos, ydl, 5, 55)
    saida, _i, _f = tr.baixar()
    assert os.path.exists(saida) and motivos and "ConnectionResetError" in motivos[0]


def test_pausar_ou_cancelar_nao_dispara_o_fallback(tmp_path, arquivos, plano_b):
    def checar():
        raise Interrompido("cancelar")
    ydl = YDLFalso({"http://falso/v": arquivos[0], "http://falso/a": arquivos[1]})
    tr, motivos, _ = _trecho_b(tmp_path, arquivos, ydl, checar=checar)
    with pytest.raises(Interrompido):
        tr.baixar()
    assert motivos == [] and plano_b.opcoes is None                  # o yt-dlp nem foi chamado


def test_cancelar_durante_o_ytdlp_encerra_os_ffmpeg_dele(tmp_path, arquivos, plano_b, monkeypatch):
    import threading
    plano_b.bloquear = threading.Event()
    mortos = []
    monkeypatch.setattr(T, "matar_ffmpegs_filhos", lambda: (mortos.append(1), plano_b.bloquear.set()))
    inicio = time.time()

    def checar():
        if time.time() - inicio > 0.6:
            raise Interrompido("cancelar")
    tr, motivos, _ = _trecho_b(tmp_path, arquivos, YDLQueFalha(OSError("403")), checar=checar)
    with pytest.raises(Interrompido):
        tr.baixar()
    assert mortos == [1] and time.time() - inicio < 5


def test_ytdlp_com_audio_mp3(tmp_path, arquivos, plano_b):
    tr, motivos, _ = _trecho_b(tmp_path, arquivos, YDLQueFalha(OSError("403")), codec="mp3",
                               fmts=[_formatos(*arquivos)[1]])
    saida, _i, _f = tr.baixar()
    assert saida.endswith(".mp3") and fluxos(saida) == ["audio"]


# ---------- processos ----------
def test_ffmpeg_e_encerrado_na_hora_ao_cancelar():
    inicio = time.time()

    def checar():
        if time.time() - inicio > 0.6:
            raise Interrompido("cancelar")
    with pytest.raises(Interrompido):
        rodar_cancelavel([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
                          "-i", "testsrc=s=64x64:r=10", "-f", "null", "-"], checar)
    assert time.time() - inicio < 4


def test_rodar_cancelavel_le_progresso():
    linhas = []
    r = rodar_cancelavel([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                          "-i", "testsrc=s=64x64:r=10:d=1", "-progress", "pipe:1", "-f", "null", "-"],
                         ao_ler_linha=linhas.append)
    assert r.returncode == 0 and "progress=end" in linhas


# ---------- fila: sem entrada duplicada ----------
def test_nao_retoma_enquanto_ainda_encerra_e_detecta_repetido_na_fila():
    g = Gerenciador(lambda e: None, 1)
    p = Pedido(url="https://youtu.be/aaaaaaaaaaa", pasta="p", qualidade="📱 720p", inicio=10, fim=20)
    g.pedidos[p.id], g.estados[p.id] = p, "pausado"
    g.rodando.add(p.id)                                       # a thread ainda está parando
    assert g.retomar(p.id) is False and g.estados[p.id] == "pausado"
    assert g.ja_na_fila("https://www.youtube.com/watch?v=aaaaaaaaaaa", 10, 20)
    assert not g.ja_na_fila("https://www.youtube.com/watch?v=aaaaaaaaaaa", 10, 30)
