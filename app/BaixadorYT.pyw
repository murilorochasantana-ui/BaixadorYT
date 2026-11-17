"""
Baixador YT - App
Cole o link, escolha a pasta e a qualidade, clique em Baixar.
"""
import glob
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import yt_dlp
except ImportError:
    tk.Tk().withdraw()
    messagebox.showerror("Baixador YT", "yt-dlp não está instalado.\nRode o instalar.bat primeiro.")
    sys.exit(1)

CONFIG = Path(__file__).with_name("config.json")
PASTA_PADRAO = r"D:\ViceCityDay" if os.name == "nt" else str(Path.home() / "Downloads" / "YouTube")

QUALIDADES = {
    "🏆 Melhor qualidade (até 4K/8K)": {"format": "bv*+ba/b", "merge_output_format": "mp4/mkv"},
    "🎬 1080p": {"format": "bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4/mkv"},
    "📱 720p": {"format": "bv*[height<=720]+ba/b[height<=720]/b", "merge_output_format": "mp4/mkv"},
    "✂️ Para edição (H.264 - CapCut/Premiere)": {
        "format": "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
    },
    "🎵 Só áudio (MP3 320k)": {
        "format": "ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
    },
}


def achar_ffmpeg():
    if shutil.which("ffmpeg"):
        return None
    try:
        import imageio_ffmpeg
        origem = Path(imageio_ffmpeg.get_ffmpeg_exe())
        pasta_bin = Path(__file__).parent / "bin"
        pasta_bin.mkdir(exist_ok=True)
        destino = pasta_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not destino.exists():
            shutil.copy2(origem, destino)
            destino.chmod(0o755)
        return str(pasta_bin)
    except Exception:
        return None


FFMPEG = achar_ffmpeg()
EXTS_MIDIA = (".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus")


def exe_ffmpeg():
    if FFMPEG:
        return os.path.join(FFMPEG, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return shutil.which("ffmpeg") or "ffmpeg"


def rodar(cmd):
    extra = {"creationflags": 0x08000000} if os.name == "nt" else {}  # sem janela preta
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **extra)


def dividir(arquivo, duracao, limite_mb, avisar=lambda t: None):
    """Divide o arquivo em partes de no máximo limite_mb, sem perder qualidade (sem recodificar).
    Retorna a lista de partes, ou [arquivo] se ele já couber."""
    limite = limite_mb * 1024 * 1024
    tamanho = os.path.getsize(arquivo)
    if tamanho <= limite:
        return [arquivo]
    pasta = os.path.dirname(arquivo)
    nome, ext = os.path.splitext(os.path.basename(arquivo))
    if not duracao:
        duracao = 0
    partes_n = math.ceil(tamanho / (limite * 0.92))  # margem: cortes caem em keyframes
    for tentativa in range(8):
        for velho in glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")):
            os.remove(velho)
        avisar(f"Dividindo em {partes_n} partes...")
        seg = max(duracao / partes_n, 5) if duracao else 600
        modelo = os.path.join(pasta, f"{nome} - Parte %02d{ext}")
        r = rodar([exe_ffmpeg(), "-hide_banner", "-y", "-i", arquivo, "-map", "0", "-c", "copy",
                   "-f", "segment", "-segment_time", f"{seg:.2f}", "-segment_start_number", "1",
                   "-reset_timestamps", "1", modelo])
        if r.returncode != 0:
            raise RuntimeError("ffmpeg falhou ao dividir: " + r.stderr.decode(errors="ignore")[-300:])
        partes = sorted(glob.glob(os.path.join(glob.escape(pasta), f"{glob.escape(nome)} - Parte *{ext}")))
        if partes and all(os.path.getsize(x) <= limite for x in partes):
            os.remove(arquivo)  # fica só com as partes
            return partes
        partes_n = math.ceil(partes_n * 1.25) + 1
    raise RuntimeError("Não consegui deixar todas as partes abaixo do limite.")


LOGINS = ["Nenhum", "Firefox", "Chrome", "Edge", "Brave", "Opera", "Arquivo cookies.txt"]


def opcoes_login(cfg):
    """Converte a escolha de login em opções do yt-dlp."""
    login = cfg.get("login", "Nenhum")
    if login == "Arquivo cookies.txt" and cfg.get("cookies_txt") and os.path.isfile(cfg["cookies_txt"]):
        return {"cookiefile": cfg["cookies_txt"]}
    if login in ("Firefox", "Chrome", "Edge", "Brave", "Opera"):
        return {"cookiesfrombrowser": (login.lower(),)}
    return {}


def explicar_erro(msg, login):
    m = msg.lower()
    if "sign in to confirm your age" in m or "age-restricted" in m:
        if login == "Nenhum":
            return ("Esse vídeo tem restrição de idade e o YouTube só libera para quem está logado.\n\n"
                    "Em \"Login (+18 / Instagram)\", escolha o navegador onde você está logado no YouTube "
                    "(o Firefox é o que funciona melhor) e tente de novo.")
        return ("Mesmo com o login, o YouTube não liberou. Confira se a conta logada nesse navegador "
                "é maior de 18 anos e está entrando no YouTube normalmente.")
    if "is_live" in m or "live event" in m or "está ao vivo" in m:
        return msg
    if any(x in m for x in ("login required", "requested content is not available",
                            "rate-limit", "rate limit", "empty media response", "only available for registered",
                            "you need to log in", "cookies")) and "cookies database" not in m:
        if login == "Nenhum":
            return ("Esse site pediu login para liberar o vídeo (o Instagram e o Facebook fazem isso muito).\n\n"
                    "Em \"Login (+18 / Instagram)\", escolha o navegador onde você está logado nesse site "
                    "e tente de novo.")
        return ("Mesmo com o login o site não liberou. Confira se você está logado nesse site pelo navegador "
                "escolhido e se o post é público ou você segue o perfil.")
    if "private" in m or "privado" in m:
        return "Esse vídeo é privado. Só dá para baixar se a sua conta (no navegador escolhido) tiver acesso."
    if "no video" in m and "pinterest" in m:
        return "Esse Pin não tem vídeo (é só imagem)."
    if "not a bot" in m:
        return ("O YouTube pediu para confirmar que você não é um robô.\n\n"
                "Escolha um navegador em \"Login (+18 / Instagram)\" e tente de novo. Se continuar, espere alguns minutos.")
    if "could not copy" in m and "cookie" in m:
        return ("Não consegui ler o login do navegador porque ele está aberto.\n\n"
                "Feche o navegador por completo e tente de novo, ou use o Firefox.")
    if "dpapi" in m or "app-bound" in m or "failed to decrypt" in m:
        return ("O Chrome/Edge bloqueia a leitura do login por outros programas.\n\n"
                "Use o Firefox (entre no site por ele uma vez) ou a opção \"Arquivo cookies.txt\".")
    if "could not find" in m and "cookies database" in m:
        return "Não achei esse navegador instalado ou ele nunca foi aberto. Escolha outro em \"Login (+18 / Instagram)\"."
    return msg + "\n\nDica: rode o atualizar.bat e tente de novo."


PLATAFORMAS = [
    ("YouTube", ("youtube.com", "youtu.be")),
    ("TikTok", ("tiktok.com",)),
    ("Instagram", ("instagram.com", "instagr.am")),
    ("Twitch", ("twitch.tv",)),
    ("Pinterest", ("pinterest.", "pin.it")),
    ("Facebook", ("facebook.com", "fb.watch", "fb.com")),
]


def plataforma(url):
    m = re.match(r"^https?://([^/?#]+)", url.strip(), re.I)
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


# ===================== TRANSCRIÇÃO =====================
PASTA_MODELOS = Path(__file__).with_name("modelos")


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


def whisper_disponivel():
    try:
        import faster_whisper  # noqa
        return True
    except ImportError:
        return False


def transcrever_whisper(arquivo, modelo, avisar):
    from faster_whisper import WhisperModel
    PASTA_MODELOS.mkdir(exist_ok=True)
    avisar("Carregando Whisper...", 0)
    wm = WhisperModel(modelo, device="auto", compute_type="int8", download_root=str(PASTA_MODELOS))
    segmentos, inf = wm.transcribe(arquivo, vad_filter=True, beam_size=1)
    saida = []
    for sg in segmentos:
        saida.append((sg.start, sg.text.strip()))
        if inf.duration:
            avisar(f"Transcrevendo {sg.end * 100 / inf.duration:.0f}%", sg.end * 100 / inf.duration)
    return saida, f"Whisper ({modelo}, idioma detectado: {inf.language})"


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


def gerar_transcricao(ydl, item, arquivo, url, modelo, avisar):
    """Cria <arquivo>.md ao lado do vídeo. Retorna o caminho do .md."""
    destino_md = os.path.splitext(arquivo)[0] + ".md"
    falas, fonte = None, None
    leg = escolher_legenda(item)
    if leg:
        avisar("Baixando legenda...", None)
        try:
            texto = ydl.urlopen(leg[0]).read().decode("utf-8", errors="ignore")
            falas = ler_json3(texto) if leg[1] == "json3" else ler_vtt(texto)
            fonte = leg[2]
        except Exception:
            falas = None
    if not falas:
        if whisper_disponivel() and arquivo and os.path.isfile(arquivo):
            falas, fonte = transcrever_whisper(arquivo, modelo, avisar)
        else:
            falas, fonte = [], ("indisponível: o vídeo não tem legenda e o Whisper não está instalado "
                                "(rode instalar_transcricao.bat)")
    Path(destino_md).write_text(montar_md(item, falas, fonte, url), encoding="utf-8")
    return destino_md


def link_valido(url):
    return plataforma(url) is not None


def carregar_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_config(dados):
    try:
        CONFIG.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def abrir_pasta(caminho):
    if os.name == "nt":
        os.startfile(caminho)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho])


class App:
    COR_FUNDO = "#181818"
    COR_CAIXA = "#262626"
    COR_TEXTO = "#ffffff"
    COR_SUAVE = "#aaaaaa"
    COR_DESTAQUE = "#e50914"

    def __init__(self, raiz):
        self.raiz = raiz
        self.eventos = queue.Queue()
        self.fila = queue.Queue()
        self.cfg = carregar_config()
        self.contador = 0

        raiz.title("Baixador YT")
        raiz.geometry("660x600")
        raiz.minsize(600, 560)
        raiz.configure(bg=self.COR_FUNDO)
        icone = Path(__file__).with_name("icone.png")
        if icone.exists():
            try:
                raiz.iconphoto(True, tk.PhotoImage(file=str(icone)))
            except Exception:
                pass

        self.estilo()
        self.montar()
        threading.Thread(target=self.trabalhador, daemon=True).start()
        raiz.after(150, self.processar_eventos)
        raiz.after(300, self.colar_automatico)

    # ---------- visual ----------
    def estilo(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=self.COR_FUNDO, foreground=self.COR_TEXTO, font=("Segoe UI", 10))
        s.configure("TLabel", background=self.COR_FUNDO, foreground=self.COR_TEXTO)
        s.configure("Suave.TLabel", foreground=self.COR_SUAVE)
        s.configure("Titulo.TLabel", font=("Segoe UI", 16, "bold"))
        s.configure("TEntry", fieldbackground=self.COR_CAIXA, foreground=self.COR_TEXTO, insertcolor="white",
                    bordercolor="#444", padding=6)
        s.configure("TCombobox", fieldbackground=self.COR_CAIXA, background=self.COR_CAIXA,
                    foreground=self.COR_TEXTO, arrowcolor="white", padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", self.COR_CAIXA)], foreground=[("readonly", "white")],
              selectbackground=[("readonly", self.COR_CAIXA)])
        s.configure("Vermelho.TButton", background=self.COR_DESTAQUE, foreground="white",
                    font=("Segoe UI", 11, "bold"), padding=(14, 9), borderwidth=0)
        s.map("Vermelho.TButton", background=[("active", "#c40812"), ("disabled", "#555")])
        s.configure("Cinza.TButton", background="#333", foreground="white", padding=(10, 6), borderwidth=0)
        s.map("Cinza.TButton", background=[("active", "#444")])
        s.configure("Treeview", background=self.COR_CAIXA, fieldbackground=self.COR_CAIXA,
                    foreground=self.COR_TEXTO, rowheight=28, borderwidth=0)
        s.configure("Treeview.Heading", background="#333", foreground=self.COR_TEXTO, relief="flat")
        s.map("Treeview", background=[("selected", "#3d3d3d")])
        s.configure("TCheckbutton", background=self.COR_FUNDO, foreground=self.COR_TEXTO)
        s.map("TCheckbutton", background=[("active", self.COR_FUNDO)], indicatorcolor=[("selected", self.COR_DESTAQUE)])
        s.configure("TSpinbox", fieldbackground=self.COR_CAIXA, foreground=self.COR_TEXTO, arrowcolor="white")
        s.configure("Horizontal.TProgressbar", background=self.COR_DESTAQUE, troughcolor="#333", borderwidth=0)

    def montar(self):
        f = ttk.Frame(self.raiz, padding=18)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        ttk.Label(f, text="⬇ Baixador YT", style="Titulo.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Cole o link, escolha a pasta e baixe. Grátis e sem anúncios.",
                  style="Suave.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # link
        ttk.Label(f, text="Link do vídeo  (YouTube, TikTok, Instagram, Twitch, Pinterest, Facebook)").grid(row=2, column=0, sticky="w")
        self.var_link = tk.StringVar()
        self.campo_link = ttk.Entry(f, textvariable=self.var_link)
        self.campo_link.grid(row=3, column=0, sticky="ew", pady=(2, 10))
        self.campo_link.bind("<Return>", lambda e: self.adicionar())
        ttk.Button(f, text="📋 Colar", style="Cinza.TButton", command=self.colar).grid(
            row=3, column=1, sticky="e", padx=(8, 0), pady=(2, 10))

        # pasta
        ttk.Label(f, text="Salvar em").grid(row=4, column=0, sticky="w")
        self.var_pasta = tk.StringVar(value=self.cfg.get("pasta", PASTA_PADRAO))
        ttk.Entry(f, textvariable=self.var_pasta).grid(row=5, column=0, sticky="ew", pady=(2, 10))
        ttk.Button(f, text="📁 Escolher", style="Cinza.TButton", command=self.escolher_pasta).grid(
            row=5, column=1, sticky="e", padx=(8, 0), pady=(2, 10))

        # qualidade + login, lado a lado
        linha = ttk.Frame(f)
        linha.grid(row=6, column=0, columnspan=2, rowspan=2, sticky="ew", pady=(0, 14))
        linha.columnconfigure(0, weight=3)
        linha.columnconfigure(1, weight=2)
        ttk.Label(linha, text="Qualidade").grid(row=0, column=0, sticky="w")
        ttk.Label(linha, text="Login (+18 / Instagram)").grid(row=0, column=1, sticky="w", padx=(10, 0))
        nomes = list(QUALIDADES)
        self.var_qual = tk.StringVar(value=self.cfg.get("qualidade", nomes[0]) if self.cfg.get("qualidade") in nomes else nomes[0])
        ttk.Combobox(linha, textvariable=self.var_qual, values=nomes, state="readonly").grid(
            row=1, column=0, sticky="ew", pady=(2, 0))
        login = self.cfg.get("login", LOGINS[0])
        self.var_login = tk.StringVar(value=login if login in LOGINS else LOGINS[0])
        caixa = ttk.Combobox(linha, textvariable=self.var_login, values=LOGINS, state="readonly")
        caixa.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(2, 0))
        caixa.bind("<<ComboboxSelected>>", self.mudou_login)

        modo = ttk.Frame(f)
        modo.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.var_claude = tk.BooleanVar(value=self.cfg.get("modo_claude", False))
        ttk.Checkbutton(modo, text="📎 Modo Claude (pasta por vídeo, partes de até",
                        variable=self.var_claude, command=self.guardar).pack(side="left")
        self.var_limite = tk.IntVar(value=self.cfg.get("limite_mb", 400))
        ttk.Spinbox(modo, from_=50, to=4000, increment=50, width=6, textvariable=self.var_limite,
                    command=self.guardar).pack(side="left", padx=4)
        ttk.Label(modo, text="MB)").pack(side="left")
        self.var_transc = tk.BooleanVar(value=self.cfg.get("transcricao", False))
        ttk.Checkbutton(modo, text="📝 Transcrição (.md)", variable=self.var_transc,
                        command=self.guardar).pack(side="right")

        botoes = ttk.Frame(f)
        botoes.grid(row=9, column=0, columnspan=2, sticky="ew")
        botoes.columnconfigure(0, weight=1)
        ttk.Button(botoes, text="⬇  BAIXAR", style="Vermelho.TButton", command=self.adicionar).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(botoes, text="📂 Abrir pasta", style="Cinza.TButton", command=self.abrir).grid(
            row=0, column=1, padx=(8, 0), sticky="ns")

        # lista de downloads
        self.lista = ttk.Treeview(f, columns=("titulo", "status"), show="headings", height=6)
        self.lista.heading("titulo", text="Vídeo")
        self.lista.heading("status", text="Status")
        self.lista.column("titulo", width=380)
        self.lista.column("status", width=150, anchor="center")
        self.lista.grid(row=10, column=0, columnspan=2, sticky="nsew", pady=(14, 6))
        f.rowconfigure(10, weight=1)

        self.barra = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.barra.grid(row=11, column=0, columnspan=2, sticky="ew")
        self.var_status = tk.StringVar(value=f"Pronto  •  yt-dlp {yt_dlp.version.__version__}")
        ttk.Label(f, textvariable=self.var_status, style="Suave.TLabel").grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(4, 0))

    # ---------- ações ----------
    def colar(self):
        try:
            texto = self.raiz.clipboard_get().strip()
        except tk.TclError:
            texto = ""
        self.var_link.set(texto)
        self.campo_link.icursor("end")

    def colar_automatico(self):
        # se já tiver um link de vídeo copiado, preenche sozinho
        try:
            texto = self.raiz.clipboard_get().strip()
            if link_valido(texto) and not self.var_link.get():
                self.var_link.set(texto)
        except tk.TclError:
            pass
        self.campo_link.focus_set()

    def escolher_pasta(self):
        atual = self.var_pasta.get()
        pasta = filedialog.askdirectory(initialdir=atual if os.path.isdir(atual) else None,
                                        title="Onde salvar os vídeos?")
        if pasta:
            self.var_pasta.set(os.path.normpath(pasta))
            self.guardar()

    def mudou_login(self, _evento=None):
        if self.var_login.get() == "Arquivo cookies.txt":
            arq = filedialog.askopenfilename(title="Escolha o arquivo cookies.txt",
                                             filetypes=[("cookies", "*.txt"), ("Todos", "*.*")])
            if not arq:
                self.var_login.set(self.cfg.get("login", "Nenhum"))
                return
            self.cfg["cookies_txt"] = arq
        elif self.var_login.get() in ("Chrome", "Edge", "Brave", "Opera"):
            messagebox.showinfo("Baixador YT", f"Feche o {self.var_login.get()} por completo antes de baixar.\n\n"
                                "Se mesmo assim der erro, use o Firefox: é o que funciona melhor.")
        self.guardar()

    def guardar(self):
        self.cfg["pasta"] = self.var_pasta.get()
        self.cfg["qualidade"] = self.var_qual.get()
        self.cfg["login"] = self.var_login.get()
        self.cfg["modo_claude"] = bool(self.var_claude.get())
        self.cfg["transcricao"] = bool(self.var_transc.get())
        self.cfg.setdefault("modelo_whisper", "small")
        try:
            self.cfg["limite_mb"] = max(10, int(self.var_limite.get()))
        except (tk.TclError, ValueError):
            self.cfg["limite_mb"] = 400
        salvar_config(self.cfg)

    def abrir(self):
        pasta = self.var_pasta.get()
        os.makedirs(pasta, exist_ok=True)
        abrir_pasta(pasta)

    def adicionar(self):
        url = self.var_link.get().strip()
        if not link_valido(url):
            messagebox.showwarning("Baixador YT", "Cole um link do YouTube, TikTok, Instagram, Twitch, Pinterest ou Facebook.")
            return
        pasta = self.var_pasta.get().strip()
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError:
            messagebox.showerror("Baixador YT", f"Não consegui usar a pasta:\n{pasta}")
            return
        self.guardar()
        self.contador += 1
        iid = f"d{self.contador}"
        self.lista.insert("", 0, iid=iid, values=(f"[{plataforma(url)}] {url}", "Na fila"))
        modo = (self.cfg["limite_mb"]) if self.cfg["modo_claude"] else None
        transc = self.cfg["modelo_whisper"] if self.cfg["transcricao"] else None
        self.fila.put((iid, url, pasta, self.var_qual.get(), modo, opcoes_login(self.cfg), self.cfg["login"], transc))
        self.var_link.set("")
        self.campo_link.focus_set()

    # ---------- download (em segundo plano) ----------
    def trabalhador(self):
        while True:
            iid, url, pasta, qual, modo, login_opts, login, transc = self.fila.get()
            self.baixar(iid, url, pasta, qual, modo, login_opts, login, transc)

    def baixar(self, iid, url, pasta, qual, limite_mb=None, login_opts=None, login="Nenhum", transc=None):
        enviar = lambda **d: self.eventos.put((iid, d))

        def gancho(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                feito = d.get("downloaded_bytes") or 0
                pct = feito * 100 / total if total else 0
                enviar(status=f"{pct:.0f}%", pct=pct, vel=(d.get("_speed_str") or "").strip(),
                       eta=(d.get("_eta_str") or "").strip())
            elif d["status"] == "finished":
                enviar(status="Juntando...", pct=100)

        opcoes = {
            "outtmpl": os.path.join(pasta, "%(playlist_title,title).80B [%(playlist_id,id)s]",
                                   "%(title).80B%(playlist_index& - |)s%(playlist_index|)s.%(ext)s") if limite_mb
                       else os.path.join(pasta, "%(title).150B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "playlist_items": "1-20",  # posts com vários vídeos (carrossel); nunca um perfil inteiro
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [gancho],
            "windowsfilenames": True,
            "concurrent_fragment_downloads": 4,
        }
        if FFMPEG:
            opcoes["ffmpeg_location"] = FFMPEG
        opcoes.update(QUALIDADES[qual])
        opcoes.update(login_opts or {})

        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                enviar(status="Lendo vídeo...", pct=0)
                info = ydl.extract_info(url, download=False)
                if info.get("is_live"):
                    raise RuntimeError("Isso é uma live acontecendo agora. Espere ela terminar e baixe o VOD "
                                       "(na Twitch: aba Vídeos do canal) ou um clipe.")
                titulo = info.get("title") or info.get("description") or url
                titulo = re.sub(r"\s+", " ", titulo).strip()[:90]
                enviar(titulo=f"[{plataforma(url)}] {titulo}")
                destino = ydl.prepare_filename(info)
                info = ydl.process_ie_result(info, download=True) or info
                if transc:
                    itens = [e for e in (info.get("entries") or []) if e] or [info]
                    for item in itens:
                        downs = item.get("requested_downloads") or [{}]
                        arq = downs[-1].get("filepath") or item.get("filepath") or ydl.prepare_filename(item)
                        try:
                            gerar_transcricao(ydl, item, arq, url, transc,
                                              lambda t, p=None: enviar(status=t, **({"pct": p} if p is not None else {})))
                        except Exception as e:
                            Path(os.path.splitext(arq)[0] + ".md").write_text(
                                montar_md(item, [], f"falhou: {e}", url), encoding="utf-8")
            if limite_mb:
                pasta_video = os.path.dirname(destino)
                arquivos = [os.path.join(pasta_video, x) for x in os.listdir(pasta_video)
                            if x.lower().endswith(EXTS_MIDIA) and " - Parte " not in x]
                if not arquivos:
                    raise RuntimeError("Arquivo baixado não encontrado na pasta do vídeo.")
                partes = []
                for arq in sorted(arquivos):
                    item = next((e for e in (info.get("entries") or []) if e and e.get("title")
                                 and os.path.basename(arq).startswith(e["title"][:20])), info)
                    partes += dividir(arq, item.get("duration"), limite_mb, lambda t: enviar(status=t))
                enviar(status=f"✔ {len(partes)} partes" if len(partes) > 1 else "✔ Concluído",
                       pct=100, fim=True)
                return
            enviar(status="✔ Concluído", pct=100, fim=True)
        except Exception as e:
            msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").split("; please report")[0]
            enviar(status="✘ Erro", erro=explicar_erro(msg, login), fim=True)

    def processar_eventos(self):
        try:
            while True:
                iid, d = self.eventos.get_nowait()
                if not self.lista.exists(iid):
                    continue
                titulo, status = self.lista.item(iid, "values")
                if "titulo" in d:
                    titulo = d["titulo"]
                if "status" in d:
                    status = d["status"]
                self.lista.item(iid, values=(titulo, status))
                if "pct" in d:
                    self.barra["value"] = d["pct"]
                if d.get("vel"):
                    self.var_status.set(f"Baixando: {titulo[:50]}  •  {d['vel']}  •  falta {d.get('eta', '?')}")
                if d.get("fim"):
                    if d.get("erro"):
                        self.var_status.set("Erro: " + d["erro"][:120])
                        messagebox.showerror("Erro ao baixar", f"{titulo}\n\n{d['erro'][:600]}")
                    else:
                        restantes = self.fila.qsize()
                        self.var_status.set("✔ Tudo pronto!" if not restantes else f"Concluído. {restantes} na fila.")
        except queue.Empty:
            pass
        self.raiz.after(150, self.processar_eventos)


if __name__ == "__main__":
    if os.name == "nt":
        try:  # deixa a janela nítida em telas com zoom
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()
