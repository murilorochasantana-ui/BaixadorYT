"""Tempos digitados pelo usuário (17:44, 1:02:30, 1064, 17m44s) e o ?t= dos links."""
import re
import urllib.parse

_HMS = re.compile(r"^(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:[.,]\d+)?)s?)?$")


def ler_tempo(texto):
    """Converte um tempo em segundos (float). Vazio → None. Inválido → ValueError com explicação."""
    t = (texto or "").strip().lower().replace(" ", "")
    if not t:
        return None
    if ":" in t:
        partes = t.split(":")
        if len(partes) > 3 or not all(re.fullmatch(r"\d+(?:[.,]\d+)?", p) for p in partes):
            raise ValueError(texto)
        seg = 0.0
        for p in partes:
            seg = seg * 60 + float(p.replace(",", "."))
        return seg
    m = _HMS.match(t)
    if not m or not any(m.groups()):
        raise ValueError(texto)
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float((s or "0").replace(",", "."))


def formatar_tempo(seg):
    """Segundos → '17:44' ou '1:02:30' (para mostrar ao usuário)."""
    seg = int(round(seg or 0))
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def tempo_para_nome(seg):
    """Segundos → '17m44s' / '1h02m30s' (pode ir no nome do arquivo no Windows)."""
    seg = int(round(seg or 0))
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def tempo_do_link(url):
    """Lê o início do link: ?t=1064, ?t=17m44s, &start=90, #t=1:30. Retorna segundos ou None."""
    try:
        partes = urllib.parse.urlparse((url or "").strip())
    except ValueError:
        return None
    for fonte in (partes.query, partes.fragment):
        args = urllib.parse.parse_qs(fonte)
        for chave in ("t", "start", "time_continue"):
            if args.get(chave):
                try:
                    v = ler_tempo(args[chave][0])
                    return v if v and v > 0 else None
                except ValueError:
                    return None
    return None


def validar_trecho(inicio_txt, fim_txt):
    """Valida o trecho digitado. Retorna (inicio, fim) em segundos; fim pode ser None (até o final).
    Erros saem com mensagem em português dizendo o que fazer."""
    exemplo = "Use, por exemplo, 17:44, 1:02:30 ou 1064 (segundos)."
    try:
        inicio = ler_tempo(inicio_txt)
    except ValueError:
        raise ValueError(f"Não entendi o início do trecho: \"{inicio_txt}\". {exemplo}") from None
    try:
        fim = ler_tempo(fim_txt)
    except ValueError:
        raise ValueError(f"Não entendi o fim do trecho: \"{fim_txt}\". {exemplo}") from None
    if inicio is None and fim is None:
        raise ValueError("Preencha o início e/ou o fim do trecho (ou desmarque \"Baixar só um trecho\").")
    inicio = inicio or 0.0
    if fim is not None and fim <= inicio:
        raise ValueError("O fim do trecho tem que ser depois do início.")
    return inicio, fim


def sufixo_trecho(inicio, fim):
    """Pedaço do nome do arquivo para não misturar o trecho com o vídeo inteiro."""
    return f" (trecho {tempo_para_nome(inicio)}-{tempo_para_nome(fim) if fim is not None else 'fim'})"
