"""Leitores de legenda, tempos palavra por palavra e os arquivos .md/.json."""
import json

from nucleo.legendas import (distribuir_palavras, ler_json3, ler_json3_segmentos, ler_vtt,
                             segmentos_de_falas, tempo)
from nucleo.transcricao import gravar, montar_md

VTT_AUTO = """WEBVTT
Kind: captions
Language: pt

00:00:01.000 --> 00:00:03.000
olá pessoal

00:00:03.000 --> 00:00:05.000
olá pessoal
hoje tem GTA

00:00:05.000 --> 00:00:07.000
hoje tem GTA
"""

JSON3_AUTO = json.dumps({"events": [
    {"tStartMs": 0, "dDurationMs": 4000, "segs": [
        {"utf8": "o"}, {"utf8": " GTA", "tOffsetMs": 400}, {"utf8": " seis", "tOffsetMs": 900}]},
    {"tStartMs": 1500, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
    {"tStartMs": 2000, "dDurationMs": 3000, "segs": [
        {"utf8": "vai"}, {"utf8": " vender", "tOffsetMs": 300}]},
]})

JSON3_MANUAL = json.dumps({"events": [
    {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Frase inteira aqui"}]},
]})


def test_tempo():
    assert tempo(65) == "01:05" and tempo(3725) == "01:02:05" and tempo(None) == "00:00"


def test_vtt_remove_repeticao_da_legenda_automatica():
    assert ler_vtt(VTT_AUTO) == [(1.0, "olá pessoal"), (3.0, "hoje tem GTA")]


def test_json3_frases():
    assert ler_json3(JSON3_MANUAL) == [(1.0, "Frase inteira aqui")]


def test_json3_com_tempo_de_cada_palavra():
    segs, precisas = ler_json3_segmentos(JSON3_AUTO)
    assert precisas
    assert [s["texto"] for s in segs] == ["o GTA seis", "vai vender"]
    p = segs[0]["palavras"]
    assert [w["palavra"] for w in p] == ["o", "GTA", "seis"]
    assert p[1]["inicio"] == 0.4 and p[2]["inicio"] == 0.9
    assert segs[0]["fim"] == 2.0          # cortado no início da próxima linha
    assert p[2]["fim"] == 2.0


def test_json3_manual_reparte_tempo():
    segs, precisas = ler_json3_segmentos(JSON3_MANUAL)
    assert not precisas
    ps = segs[0]["palavras"]
    assert ps[0]["inicio"] == 1.0 and abs(ps[-1]["fim"] - 3.0) < 0.01
    assert all(a["fim"] <= b["inicio"] + 1e-6 for a, b in zip(ps, ps[1:]))


def test_distribuir_proporcional_ao_tamanho():
    ps = distribuir_palavras(0, 3, "a bbbb c")
    durs = [p["fim"] - p["inicio"] for p in ps]
    assert durs[1] > durs[0] * 3.5 and abs(sum(durs) - 3) < 0.01


def test_segmentos_de_falas_usa_inicio_da_proxima():
    segs = segmentos_de_falas([(0, "um dois"), (4, "três")], duracao=6)
    assert segs[0]["fim"] == 4 and segs[1]["fim"] == 6


def test_md_agrupa_paragrafos_com_tempo():
    falas = [(0, "começo."), (16, "meio."), (40, "fim")]
    md = montar_md({"title": "Live", "duration": 100}, falas, "teste", "https://youtu.be/x")
    assert md.startswith("# Live")
    assert "- **Duração:** 01:40" in md
    assert "**[00:00]** começo. meio." in md
    assert "**[00:40]** fim" in md


def test_gravar_cria_md_e_json(tmp_path):
    segs, precisas = ler_json3_segmentos(JSON3_AUTO)
    md, js = gravar(str(tmp_path / "video"), {"title": "T", "webpage_url": "https://youtu.be/x"},
                    segs, "legenda automática", "https://youtu.be/x", precisas)
    dados = json.loads(open(js, encoding="utf-8").read())
    assert dados["palavras_precisas"] is True and dados["link"] == "https://youtu.be/x"
    assert dados["segmentos"][0]["palavras"][1]["palavra"] == "GTA"
    assert "o GTA seis" in open(md, encoding="utf-8").read()
