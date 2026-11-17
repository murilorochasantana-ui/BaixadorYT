"""Quais sites o Estúdio aceita (copiado do Baixador YT antigo)."""
import re

PLATAFORMAS = [
    ("YouTube", ("youtube.com", "youtu.be")),
    ("TikTok", ("tiktok.com",)),
    ("Instagram", ("instagram.com", "instagr.am")),
    ("Twitch", ("twitch.tv",)),
    ("Pinterest", ("pinterest.", "pin.it")),
    ("Facebook", ("facebook.com", "fb.watch", "fb.com")),
]


def plataforma(url):
    m = re.match(r"^https?://([^/?#]+)", (url or "").strip(), re.I)
    if not m:
        return None
    host = m.group(1).lower().split(":")[0]
    for nome, dominios in PLATAFORMAS:
        for d in dominios:
            if d.endswith("."):  # pinterest.com, pinterest.com.br, br.pinterest.com...
                if host.startswith(d) or f".{d}" in host:
                    return nome
            elif host == d or host.endswith("." + d):
                return nome
    return None


def link_valido(url):
    return plataforma(url) is not None


def separar_links(texto):
    """Separa um texto colado (um link por linha, ou separados por espaço) em (válidos, inválidos),
    na ordem em que foram colados e sem repetir o mesmo vídeo (youtu.be/X e watch?v=X contam como um)."""
    validos, invalidos, vistos = [], [], set()
    for pedaco in re.split(r"\s+", texto or ""):
        p = pedaco.strip().strip(",;")
        if not p:
            continue
        valido = link_valido(p)
        chave = chave_do_link(p) if valido else p
        if chave in vistos:
            continue
        vistos.add(chave)
        (validos if valido else invalidos).append(p)
    return validos, invalidos


def chave_do_link(url):
    """Identidade do vídeo para achar repetidos: o mesmo vídeo com links diferentes
    (youtu.be, ?si=, shorts/, ?t=) gera a mesma chave."""
    u = (url or "").strip()
    m = re.match(r"^https?://([^/?#]+)([^?#]*)\??([^#]*)", u, re.I)
    if not m:
        return u.lower()
    host, caminho, query = m.group(1).lower().split(":")[0], m.group(2), m.group(3)
    host = re.sub(r"^(www|m|vm|mobile)\.", "", host)
    nome = plataforma(u) or host
    if nome == "YouTube":
        v = re.search(r"(?:^|&)v=([\w-]{11})", query)
        if v:
            return f"youtube:{v.group(1)}"
        p = re.search(r"/(?:shorts|live|embed)/([\w-]{11})", caminho)
        if p:
            return f"youtube:{p.group(1)}"
        if host == "youtu.be":
            return f"youtube:{caminho.strip('/')[:11]}"
    if nome == "TikTok":
        v = re.search(r"/video/(\d+)", caminho)
        if v:
            return f"tiktok:{v.group(1)}"
    if nome == "Twitch":
        v = re.search(r"/videos/(\d+)", caminho)
        if v:
            return f"twitch:{v.group(1)}"
    return f"{nome.lower()}:{host}{caminho.rstrip('/')}"
