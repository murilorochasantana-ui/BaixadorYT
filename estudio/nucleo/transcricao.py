"""Transcrição: gera <vídeo>.md (para ler) e <vídeo>.json (tempos palavra por palavra, para as
legendas amarelas dos cortes). Ordem das fontes igual à do app antigo:
legenda do criador > legenda automática > Whisper local > .md explicando como instalar o Whisper."""
import json
import os
import subprocess
from pathlib import Path

from .config import pasta_dados
from .ffmpeg import SEM_JANELA, exe_ffmpeg
from .legendas import (escolher_legenda, ler_json3_segmentos, ler_vtt, segmentos_de_falas, tempo)

VERSAO_JSON = 1


def pasta_modelos():
    """Modelos do Whisper (~460 MB) ficam em %LOCALAPPDATA%, fora do OneDrive."""
    p = pasta_dados() / "modelos"
    p.mkdir(exist_ok=True)
    return p


def whisper_disponivel():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def carregar_audio(arquivo, taxa=16000):
    """Lê o áudio com o ffmpeg (mono, 16 kHz) e devolve um array numpy pronto para o Whisper.
    Não usa o PyAV: a versão 19 dele é incompatível com o faster-whisper 1.2.1."""
    import numpy as np
    r = subprocess.run([exe_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", arquivo,
                        "-vn", "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, **SEM_JANELA)
    if r.returncode != 0:
        raise RuntimeError("Não consegui ler o áudio do vídeo: " + r.stderr.decode(errors="ignore")[-300:])
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0


def _erro_de_placa(e):
    t = str(e).lower()
    return any(x in t for x in ("cublas", "cudnn", "cuda", "cudart"))


def transcrever_whisper(arquivo, modelo, avisar):
    """Retorna (segmentos, fonte, idioma). Cada segmento traz as palavras com tempo real.
    Tenta a placa de vídeo; se as bibliotecas CUDA não estiverem instaladas, usa o processador."""
    avisar("Lendo o áudio...", 0)
    audio = carregar_audio(arquivo)
    try:
        return _transcrever(audio, modelo, "auto", avisar)
    except RuntimeError as e:
        if not _erro_de_placa(e):
            raise
        return _transcrever(audio, modelo, "cpu", avisar)


def _transcrever(audio, modelo, dispositivo, avisar):
    from faster_whisper import WhisperModel
    avisar("Carregando Whisper (na 1ª vez baixa o modelo)...", 0)
    wm = WhisperModel(modelo, device=dispositivo, compute_type="int8", download_root=str(pasta_modelos()))
    segmentos, inf = wm.transcribe(audio, vad_filter=True, beam_size=1, word_timestamps=True)
    saida = []
    for sg in segmentos:
        palavras = [{"inicio": round(float(w.start), 3), "fim": round(float(w.end), 3), "palavra": w.word.strip(),
                     "prob": round(float(w.probability), 3)} for w in (sg.words or []) if w.word.strip()]
        saida.append({"inicio": round(float(sg.start), 3), "fim": round(float(sg.end), 3), "texto": sg.text.strip(),
                      "palavras": palavras})
        if inf.duration:
            pct = min(sg.end * 100 / inf.duration, 100)
            avisar(f"Transcrevendo {pct:.0f}%", pct)
    return saida, f"Whisper ({modelo}, idioma detectado: {inf.language})", inf.language


def falas_de_segmentos(segmentos):
    return [(s["inicio"], s["texto"]) for s in segmentos if s.get("texto")]


def montar_md(info, falas, fonte, url):
    linhas = [f"# {info.get('title') or 'Vídeo'}", ""]
    meta = [("Link", info.get("webpage_url") or url),
            ("Canal/Perfil", info.get("uploader") or info.get("channel")),
            ("Duração", tempo(info.get("duration")) if info.get("duration") else None),
            ("Publicado", info.get("upload_date") and
             f"{info['upload_date'][6:8]}/{info['upload_date'][4:6]}/{info['upload_date'][:4]}"),
            ("Transcrição", fonte)]
    linhas += [f"- **{k}:** {v}" for k, v in meta if v]
    linhas += ["", "## Transcrição", ""]
    if not falas:
        linhas.append("_(sem falas detectadas)_")
    bloco_ini, bloco = None, []
    for t, f in falas:  # agrupa em parágrafos de ~30 s
        if bloco_ini is None:
            bloco_ini = t
        bloco.append(f)
        if t - bloco_ini >= 30 or f.endswith((".", "?", "!")) and t - bloco_ini >= 15:
            linhas += [f"**[{tempo(bloco_ini)}]** {' '.join(bloco)}", ""]
            bloco_ini, bloco = None, []
    if bloco:
        linhas += [f"**[{tempo(bloco_ini)}]** {' '.join(bloco)}", ""]
    return "\n".join(linhas)


def montar_json(info, segmentos, fonte, url, precisas, idioma=None):
    return {
        "versao": VERSAO_JSON,
        "titulo": info.get("title"),
        "link": info.get("webpage_url") or url,
        "canal": info.get("uploader") or info.get("channel"),
        "duracao": info.get("duration"),
        "fonte": fonte,
        "idioma": idioma or info.get("language"),
        # True = cada palavra tem o tempo real; False = tempo repartido pelo tamanho da palavra
        "palavras_precisas": bool(precisas),
        "segmentos": segmentos,
    }


def gravar(destino_base, info, segmentos, fonte, url, precisas, idioma=None):
    """Grava <base>.md e <base>.json. Retorna os dois caminhos."""
    md = destino_base + ".md"
    js = destino_base + ".json"
    Path(md).write_text(montar_md(info, falas_de_segmentos(segmentos), fonte, url), encoding="utf-8")
    Path(js).write_text(json.dumps(montar_json(info, segmentos, fonte, url, precisas, idioma),
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    return md, js


def gerar_transcricao(ydl, item, arquivo, url, modelo, avisar):
    """Cria <arquivo>.md e <arquivo>.json ao lado do vídeo. Retorna (md, json)."""
    base = os.path.splitext(arquivo)[0]
    segmentos, fonte, precisas, idioma = None, None, False, None
    leg = escolher_legenda(item)
    if leg:
        avisar("Baixando legenda...", None)
        try:
            texto = ydl.urlopen(leg[0]).read().decode("utf-8", errors="ignore")
            if leg[1] == "json3":
                segmentos, precisas = ler_json3_segmentos(texto)
            else:
                segmentos = segmentos_de_falas(ler_vtt(texto), item.get("duration"))
            fonte = leg[2]
        except Exception:
            segmentos = None
    if not segmentos:
        if whisper_disponivel() and arquivo and os.path.isfile(arquivo):
            segmentos, fonte, idioma = transcrever_whisper(arquivo, modelo, avisar)
            precisas = True
        else:
            segmentos, fonte = [], ("indisponível: o vídeo não tem legenda e o Whisper não está instalado "
                                    "(rode instalar_transcricao.bat)")
    return gravar(base, item, segmentos, fonte, url, precisas, idioma)


def gravar_falha(arquivo, item, url, erro):
    """Se a transcrição falhar, o download NÃO falha: grava o .md com o erro."""
    base = os.path.splitext(arquivo)[0]
    Path(base + ".md").write_text(montar_md(item, [], f"falhou: {erro}", url), encoding="utf-8")
