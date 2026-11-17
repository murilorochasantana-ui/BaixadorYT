"""Leitores de legenda (json3, vtt, srt) copiados do app antigo, mais tempos palavra por palavra."""
import json
import re


def tempo(seg):
    seg = int(seg or 0)
    h, r = divmod(seg, 3600)
    m, s_ = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s_:02d}" if h else f"{m:02d}:{s_:02d}"


def ler_json3(texto):
    dados = json.loads(texto)
    saida = []
    for ev in dados.get("events", []):
        frase = "".join(sg.get("utf8", "") for sg in ev.get("segs", []) or []).replace("\n", " ").strip()
        if frase:
            saida.append((ev.get("tStartMs", 0) / 1000, frase))
    return saida


def ler_vtt(texto):
    saida, inicio, linhas = [], None, []
    padrao = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->")

    def fechar():
        if inicio is not None and linhas:
            frase = re.sub(r"<[^>]+>", "", " ".join(linhas)).strip()
            if frase:
                saida.append((inicio, frase))
    for linha in texto.splitlines():
        m = padrao.search(linha)
        if m:
            fechar()
            h, mi, se, ms = m.groups()
            inicio = int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms) / 1000
            linhas = []
        elif linha.strip() and not linha.strip().isdigit() and inicio is not None \
                and not linha.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            linhas.append(linha.strip())
        elif not linha.strip():
            fechar()
            inicio, linhas = (None, []) if linhas else (inicio, linhas)
    fechar()
    # legendas automáticas repetem a linha anterior: remove repetição
    limpo = []
    for t, f in saida:
        if limpo and (f == limpo[-1][1] or limpo[-1][1].endswith(f)):
            continue
        if limpo and f.startswith(limpo[-1][1]):
            f = f[len(limpo[-1][1]):].strip()
            if not f:
                continue
        limpo.append((t, f))
    return limpo


def escolher_legenda(info):
    """Retorna (url, formato, descrição) da melhor legenda disponível, ou None."""
    lingua = (info.get("language") or "").split("-")[0]

    def pegar(dic, chaves):
        for k in chaves:
            if k in dic:
                for fmt in ("json3", "vtt", "srt"):
                    for f in dic[k]:
                        if f.get("ext") == fmt and f.get("url"):
                            return f["url"], fmt, k
        return None
    manuais = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    ordem = [k for k in manuais if lingua and k.split("-")[0] == lingua] + \
            [k for k in manuais if k.startswith("pt")] + list(manuais)
    r = pegar(manuais, ordem)
    if r:
        return r[0], r[1], f"legenda do criador ({r[2]})"
    autos = info.get("automatic_captions") or {}
    ordem = [k for k in autos if k.endswith("-orig")] + ([lingua] if lingua else [])
    r = pegar(autos, ordem)
    if r:
        return r[0], r[1], f"legenda automática da plataforma ({r[2].replace('-orig', '')})"
    return None


# ===================== TEMPOS PALAVRA POR PALAVRA =====================
# Formato de um segmento (o mesmo do Whisper, usado pelo .json da transcrição):
# {"inicio": 12.3, "fim": 15.0, "texto": "frase", "palavras": [{"inicio", "fim", "palavra"}]}

def distribuir_palavras(inicio, fim, texto):
    """Quando a fonte não tem o tempo de cada palavra, reparte o tempo da frase
    proporcionalmente ao tamanho de cada palavra (mesmo método da skill de cortes)."""
    palavras = texto.split()
    if not palavras:
        return []
    fim = max(fim, inicio + 0.05 * len(palavras))
    total = sum(len(p) for p in palavras)
    saida, t = [], inicio
    for p in palavras:
        dur = (fim - inicio) * len(p) / total
        saida.append({"inicio": round(t, 3), "fim": round(t + dur, 3), "palavra": p})
        t += dur
    return saida


def segmentos_de_falas(falas, duracao=None, maximo=10.0):
    """Converte [(início, frase)] em segmentos com fim e palavras aproximadas."""
    segs = []
    for i, (ini, frase) in enumerate(falas):
        if i + 1 < len(falas):
            fim = falas[i + 1][0]
        else:
            fim = duracao if duracao and duracao > ini else ini + 3
        fim = min(fim, ini + maximo)
        if fim <= ini:
            fim = ini + 0.5
        segs.append({"inicio": round(ini, 3), "fim": round(fim, 3), "texto": frase,
                     "palavras": distribuir_palavras(ini, fim, frase)})
    return segs


def cortar_segmentos(segmentos, inicio, fim=None):
    """Mantém só o que fala dentro do trecho [inicio, fim] e recomeça a contagem do zero,
    para os tempos baterem com o arquivo do trecho baixado."""
    saida = []
    for s in segmentos:
        if s["fim"] <= inicio or (fim is not None and s["inicio"] >= fim):
            continue
        dentro = lambda w: w["fim"] > inicio and (fim is None or w["inicio"] < fim)
        palavras = [{**w, "inicio": round(max(w["inicio"], inicio) - inicio, 3),
                     "fim": round((min(w["fim"], fim) if fim is not None else w["fim"]) - inicio, 3)}
                    for w in s.get("palavras", []) if dentro(w)]
        texto = " ".join(w["palavra"] for w in palavras) if palavras else s["texto"]
        fim_seg = min(s["fim"], fim) if fim is not None else s["fim"]
        saida.append({"inicio": round(max(s["inicio"], inicio) - inicio, 3),
                      "fim": round(fim_seg - inicio, 3), "texto": texto, "palavras": palavras})
    return saida


def ler_json3_segmentos(texto):
    """Lê json3 do YouTube com tempo de cada palavra quando ele existe (legenda automática traz
    tOffsetMs por palavra). Retorna (segmentos, precisas)."""
    dados = json.loads(texto)
    eventos = []
    for ev in dados.get("events", []):
        segs = [s for s in (ev.get("segs") or []) if s.get("utf8", "").strip()]
        if not segs:
            continue
        eventos.append(ev)
    saida, precisas = [], False
    for i, ev in enumerate(eventos):
        ini = ev.get("tStartMs", 0) / 1000
        fim = ini + ev.get("dDurationMs", 0) / 1000
        if i + 1 < len(eventos):  # legenda automática fica na tela por cima da próxima linha
            prox = eventos[i + 1].get("tStartMs", 0) / 1000
            if prox > ini:
                fim = min(fim, prox) if fim > ini else prox
        if fim <= ini:
            fim = ini + 2
        segs = [s for s in ev["segs"] if s.get("utf8", "").strip()]
        texto_ev = " ".join(s["utf8"].replace("\n", " ").strip() for s in segs).strip()
        texto_ev = re.sub(r"\s+", " ", texto_ev)
        tem_offset = len(segs) > 1 or any("tOffsetMs" in s for s in segs)
        if not tem_offset:
            saida.append({"inicio": round(ini, 3), "fim": round(fim, 3), "texto": texto_ev,
                          "palavras": distribuir_palavras(ini, fim, texto_ev)})
            continue
        precisas = True
        palavras = []
        for j, s in enumerate(segs):
            p_ini = ini + s.get("tOffsetMs", 0) / 1000
            p_fim = ini + segs[j + 1].get("tOffsetMs", 0) / 1000 if j + 1 < len(segs) else fim
            p_fim = max(p_fim, p_ini + 0.05)
            palavras += distribuir_palavras(p_ini, p_fim, s["utf8"].replace("\n", " ").strip())
        saida.append({"inicio": round(ini, 3), "fim": round(fim, 3), "texto": texto_ev, "palavras": palavras})
    return saida, precisas
