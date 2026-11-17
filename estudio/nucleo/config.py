"""Configurações do Estúdio.

Os dados do usuário (config.json, banco de dados, cache) ficam em %LOCALAPPDATA%\\EstudioViceCityDay,
fora do OneDrive, para o sincronizador não corromper arquivos abertos.
Este é o ÚNICO lugar com o caminho padrão D:\\ViceCityDay: o resto do código usa pasta_do_canal().
"""
import copy
import json
import os
from pathlib import Path

PASTA_ESTUDIO = Path(__file__).resolve().parent.parent          # .../BaixadorYT/estudio
CONFIG_APP_ANTIGO = PASTA_ESTUDIO.parent / "app" / "config.json"

RAIZ_PADRAO = r"D:\ViceCityDay" if os.name == "nt" else str(Path.home() / "ViceCityDay")

PADRAO = {
    "pasta_raiz": RAIZ_PADRAO,
    # subpastas relativas à pasta_raiz (podem ser trocadas na tela de configurações)
    "subpastas": {
        "lives": "VideosLives",
        "edicao": "Ediçao",
        "sfx": os.path.join("Ediçao", "sfx"),
        "musicas": os.path.join("Ediçao", "Musicas"),
        "logo": os.path.join("Ediçao", "logo_vcd_news.png"),
        "prontos": os.path.join("Cortes", "3-prontos"),
    },
    "pasta": None,                 # última pasta usada para salvar downloads (None = pasta das lives)
    "qualidade": "🏆 Melhor qualidade (até 4K/8K)",
    "login": "Nenhum",
    "cookies_txt": "",
    "modo_claude": False,
    "limite_mb": 400,
    "transcricao": False,
    "modelo_whisper": "small",
    "aviso_gb": 3,                 # avisa na prévia quando o download passar disso
}

# chaves que podem ser trocadas pela interface
CHAVES_EDITAVEIS = {"pasta", "qualidade", "login", "cookies_txt", "modo_claude", "limite_mb",
                    "transcricao", "modelo_whisper", "aviso_gb", "pasta_raiz", "subpastas"}


def pasta_dados():
    """Pasta onde o Estúdio guarda os dados do usuário (pode ser trocada por ESTUDIO_DADOS, nos testes)."""
    if os.environ.get("ESTUDIO_DADOS"):
        p = Path(os.environ["ESTUDIO_DADOS"])
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / "EstudioViceCityDay"
    else:
        p = Path.home() / ".estudio_vicecityday"
    p.mkdir(parents=True, exist_ok=True)
    return p


def arquivo_config():
    return pasta_dados() / "config.json"


def _mesclar(base, extra):
    saida = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict):
            saida[k] = {**saida[k], **v}
        else:
            saida[k] = v
    return saida


def importar_app_antigo(caminho=None):
    """Lê o config.json do Baixador YT antigo (se existir) para o usuário não perder as preferências."""
    caminho = caminho or CONFIG_APP_ANTIGO
    try:
        antigo = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in antigo.items() if k in CHAVES_EDITAVEIS}


def carregar():
    arq = arquivo_config()
    dados = None
    if arq.exists():
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            dados = None  # arquivo estragado: volta ao padrão
    if dados is None:
        dados = importar_app_antigo()
        cfg = _mesclar(PADRAO, dados)
        salvar(cfg)
        return cfg
    return _mesclar(PADRAO, dados)


def salvar(cfg):
    arq = arquivo_config()
    tmp = arq.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, arq)  # troca de uma vez: nunca fica um arquivo pela metade
        return True
    except OSError:
        return False


def atualizar(cfg, mudancas):
    """Aplica só as chaves conhecidas e salva. Retorna a config nova."""
    limpas = {k: v for k, v in (mudancas or {}).items() if k in CHAVES_EDITAVEIS}
    if "limite_mb" in limpas:
        try:
            limpas["limite_mb"] = max(10, int(limpas["limite_mb"]))
        except (TypeError, ValueError):
            limpas["limite_mb"] = 400
    novo = _mesclar(cfg, limpas)
    salvar(novo)
    return novo


def pasta_do_canal(cfg, chave=None):
    """Caminho da pasta do canal (raiz) ou de uma subpasta: pasta_do_canal(cfg, "lives")."""
    raiz = Path(cfg.get("pasta_raiz") or RAIZ_PADRAO)
    if not chave:
        return raiz
    sub = (cfg.get("subpastas") or {}).get(chave) or PADRAO["subpastas"][chave]
    return raiz / sub


def pasta_downloads(cfg):
    """Pasta onde salvar downloads: a última usada ou, na primeira vez, a pasta das lives."""
    return cfg.get("pasta") or str(pasta_do_canal(cfg, "lives"))
