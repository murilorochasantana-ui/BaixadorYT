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
