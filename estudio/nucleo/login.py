"""Login por cookies do navegador ou arquivo cookies.txt (nunca senha). Copiado do app antigo."""
import os

LOGINS = ["Nenhum", "Firefox", "Chrome", "Edge", "Brave", "Opera", "Arquivo cookies.txt"]
NAVEGADORES_BLOQUEIAM = ("Chrome", "Edge", "Brave", "Opera")


def opcoes_login(cfg):
    """Converte a escolha de login em opções do yt-dlp."""
    login = cfg.get("login", "Nenhum")
    if login == "Arquivo cookies.txt" and cfg.get("cookies_txt") and os.path.isfile(cfg["cookies_txt"]):
        return {"cookiefile": cfg["cookies_txt"]}
    if login in ("Firefox", "Chrome", "Edge", "Brave", "Opera"):
        return {"cookiesfrombrowser": (login.lower(),)}
    return {}
