# Baixador YT — documento do projeto

> Contexto completo para continuar o desenvolvimento no Claude Code.
> Dono: criador do canal **ViceCityDay** (cortes/Shorts de GTA 6 para YouTube e TikTok).
> Idioma do app, das mensagens e dos comentários no código: **português do Brasil**.

---

## 1. O que é

Um baixador de vídeos **grátis, sem anúncios e sem limite de tamanho**, feito para alimentar o fluxo de produção de cortes do canal ViceCityDay.

O usuário cola o link, escolhe a pasta e a qualidade e clica em **BAIXAR**. O app também pode:
- dividir vídeos grandes em partes que caibam no limite de upload do Claude (400 MB);
- gerar a transcrição do vídeo em `.md`.

Os vídeos baixados vão para `D:\ViceCityDay` e depois são transformados em cortes verticais pelo Claude, com a skill `vicecityday-cortes`.

**Motor:** [yt-dlp](https://github.com/yt-dlp/yt-dlp), mais ffmpeg, mais Deno (runtime JS que o yt-dlp exige para o YouTube desde a versão 2025.11.12).

---

## 2. Estrutura

```
BaixadorYT/
├── estudio/                    ← VERSÃO NOVA em construção (ver seção 10). Não substitui o app/ ainda.
├── docs/contexto_canal.md      ← histórico do canal (modelo de edição, cronograma, regras de postagem)
├── app/                        ← PRODUTO PRINCIPAL (app de janela, Tkinter)
│   ├── BaixadorYT.pyw          ← tudo do app (~700 linhas, arquivo único)
│   ├── instalar.bat            ← Python (winget) + yt-dlp[default] + imageio-ffmpeg + Deno + atalho na Área de Trabalho
│   ├── atualizar.bat           ← pip install -U "yt-dlp[default]"
│   ├── instalar_transcricao.bat← pip install faster-whisper (opcional)
│   ├── icone.png
│   ├── LEIA-ME.txt             ← manual do usuário
│   ├── config.json             ← (gerado em runtime) preferências salvas
│   ├── bin/ffmpeg.exe          ← (gerado) cópia do ffmpeg do imageio-ffmpeg, se não houver no PATH
│   └── modelos/                ← (gerado) modelos do Whisper
│
├── extensao/                   ← versão antiga/alternativa: extensão Chrome MV3 (só YouTube)
│   ├── manifest.json, background.js, content.js, content.css, popup.html, popup.js, icones/
│
└── servidor/                   ← servidor local que a extensão usa (127.0.0.1:8765)
    ├── servidor.py, instalar.bat, iniciar.bat, iniciar_escondido.vbs, instalar.sh, iniciar.sh
```

O **app** é o que o usuário usa no dia a dia. A **extensão + servidor** foi a primeira versão: ainda funciona, mas só para YouTube, e não tem Modo Claude, login nem transcrição.

---

## 3. Ambiente do usuário

- **Windows**, Python 3.12 instalado pelo winget e executado com `pythonw` (sem console).
- Pastas do canal:
  ```
  D:\ViceCityDay\
  ├── VideosLives\          ← lives brutas (o app costuma salvar aqui)
  ├── Ediçao\
  │   ├── sfx\              ← efeitos sonoros (pop, whoosh, boom, fail, vitória, susto, risada, scratch)
  │   ├── Musicas\
  │   ├── Efeitos sonoros originais\
  │   └── logo_vcd_news.png ← marca d'água "VCD NEWS"
  └── Cortes\3-prontos\     ← cortes finalizados
  ```
- Editores que o usuário pode usar: CapCut, Premiere.
- O usuário não é programador: tudo precisa funcionar com duplo clique em `.bat` e ter mensagens claras em português.

---

## 4. Funcionalidades atuais do app (`app/BaixadorYT.pyw`)

### 4.1 Interface (Tkinter + ttk, tema escuro, destaque vermelho `#e50914`)
- Campo **Link do vídeo**, com botão **📋 Colar**. Se houver um link válido na área de transferência quando o app abre, ele cola sozinho.
- Campo **Salvar em**, com botão **📁 Escolher**. O padrão é `D:\ViceCityDay` e o app lembra a última pasta usada.
- **Qualidade** e **Login (+18 / Instagram)** lado a lado.
- Linha de opções: **📎 Modo Claude** (com limite em MB) e **📝 Transcrição (.md)**.
- Botões **⬇ BAIXAR** e **📂 Abrir pasta**.
- Lista (Treeview) com a fila de downloads (`[Plataforma] Título | Status`), barra de progresso e linha de status (velocidade e tempo restante).
- `Enter` no campo de link adiciona o link à fila.

### 4.2 Plataformas (`PLATAFORMAS`, `plataforma(url)`)
YouTube, TikTok, Instagram, Twitch, Pinterest e Facebook. A validação é por domínio (inclui `youtu.be`, `vm.tiktok.com`, `clips.twitch.tv`, `pin.it`, `pinterest.com.br`, `fb.watch`, `m.facebook.com`). Links de outros sites são recusados.

### 4.3 Qualidades (`QUALIDADES`)
| Opção | format do yt-dlp | Saída |
|---|---|---|
| 🏆 Melhor | `bv*+ba/b` | `mp4/mkv` (pode vir VP9/AV1) |
| 🎬 1080p | `bv*[height<=1080]+ba/b[height<=1080]/b` | `mp4/mkv` |
| 📱 720p | `bv*[height<=720]+ba/b[height<=720]/b` | `mp4/mkv` |
| ✂️ Para edição (H.264) | `bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b` | `mp4` (CapCut/Premiere) |
| 🎵 Só áudio | `ba/b` + FFmpegExtractAudio | MP3 320k |

### 4.4 Login (`LOGINS`, `opcoes_login`, `mudou_login`)
- Opções: Nenhum, Firefox, Chrome, Edge, Brave, Opera e Arquivo cookies.txt.
- Os navegadores usam `cookiesfrombrowser` do yt-dlp. O arquivo usa `cookiefile`.
- **Cuidado:** desde a versão 127, o Chrome e o Edge no Windows usam *app-bound encryption* e o yt-dlp frequentemente não consegue ler os cookies deles. Por isso o app recomenda o Firefox ou o cookies.txt (extensão "Get cookies.txt LOCALLY").
- É necessário para: vídeos +18 do YouTube, o Instagram (quase sempre) e posts privados do Facebook.

### 4.5 Modo Claude (`dividir`)
- Cria uma pasta por vídeo: `%(playlist_title,title).80B [%(playlist_id,id)s]/%(title).80B%(playlist_index& - |)s%(playlist_index|)s.%(ext)s`.
- Se o arquivo passar do limite (padrão 400 MB, configurável), ele é dividido com `ffmpeg -f segment -c copy` (sem recodificar), no formato `Nome - Parte 01.mp4`, `Parte 02`… O número de partes é `ceil(tamanho / (limite*0.92))`. Se alguma parte passar do limite, o app refaz com mais partes (até 8 tentativas). Por fim, apaga o original.
- Motivo: o Claude só consegue receber do PC arquivos de no máximo 400 MB.
- Testado com um vídeo de 60 MB e limite de 20 MB: deu 4 partes de cerca de 15 MB, todas com áudio e vídeo.

### 4.6 Transcrição (`escolher_legenda`, `ler_json3`, `ler_vtt`, `transcrever_whisper`, `montar_md`, `gerar_transcricao`)
- Gera `<nome do vídeo>.md` ao lado do vídeo, **antes** da divisão em partes.
- Ordem de fontes:
  1. legenda manual (na língua do vídeo, depois `pt*`, depois qualquer uma);
  2. legenda automática original (`*-orig`), em json3 > vtt > srt, baixada com `ydl.urlopen`;
  3. **faster-whisper** local (modelo em `config.json → modelo_whisper`, padrão `small`, `int8`, `vad_filter=True`, `beam_size=1`);
  4. se nada disso estiver disponível, um `.md` explicando como instalar o Whisper.
- Formato do `.md`: título, metadados (link, canal, duração, data, fonte da transcrição) e parágrafos de cerca de 30 s com `**[mm:ss]**`.
- O leitor de VTT remove as repetições típicas das legendas automáticas do YouTube.
- Se a transcrição falhar, o download **não** falha: o `.md` é gravado com o erro.

### 4.7 Fila e threads
- `self.fila` (queue) é consumida por uma única thread `trabalhador`, então os downloads acontecem um de cada vez.
- A thread manda eventos para `self.eventos`. A UI lê os eventos a cada 150 ms (`processar_eventos`). O Tkinter nunca é acessado fora da thread principal.
- O item da fila é uma tupla: `(iid, url, pasta, qualidade, limite_mb|None, login_opts, login, modelo_whisper|None)`.

### 4.8 Erros (`explicar_erro`)
Converte os erros do yt-dlp em mensagens em português com a solução: restrição de idade, "not a bot", login exigido ou rate-limit (Instagram/Facebook), vídeo privado, Pin sem vídeo, navegador aberto, falha de DPAPI/app-bound, navegador não encontrado e live em andamento. Se o erro não for reconhecido, mostra a mensagem original e sugere rodar o `atualizar.bat`.

### 4.9 Outros detalhes
- `noplaylist=True` e `playlist_items="1-20"` (o carrossel do Instagram baixa todos os itens, mas nunca um perfil inteiro).
- `windowsfilenames=True` e `concurrent_fragment_downloads=4`.
- Lives em andamento (`is_live`) são recusadas com uma mensagem.
- ffmpeg: usa o do PATH; se não houver, copia o do `imageio_ffmpeg` para `app/bin/ffmpeg.exe`.
- `config.json` guarda: `pasta`, `qualidade`, `login`, `cookies_txt`, `modo_claude`, `limite_mb`, `transcricao`, `modelo_whisper`.

---

## 5. Extensão + servidor (legado)

- **Extensão MV3:** mostra um botão flutuante "⬇ Baixar" em `/watch` e `/shorts` (escuta `yt-navigate-finish`), com menu de qualidades e avisos de progresso na página. O `background.js` faz `fetch` para `http://127.0.0.1:8765`.
- **servidor.py:** usa `ThreadingHTTPServer` e só escuta em `127.0.0.1`. Endpoints: `GET /ping`, `GET /status?id=`, `POST /baixar {url, qualidade}` e `POST /abrir-pasta`.
- **Segurança do servidor:** os POSTs só são aceitos se o `Origin` começar com `chrome-extension://`, `moz-extension://` ou `extension://`. Requisições com `Origin` de sites comuns são recusadas com 403, e só URLs do YouTube são aceitas. Isso já foi testado. **Mantenha essas proteções** se o servidor for reaproveitado.
- O servidor salva em `D:\ViceCityDay` (a constante `PASTA_DESTINO` fica no topo do arquivo).

---

## 6. Limitações conhecidas / o que NÃO foi testado

- Downloads reais **não foram testados**: o ambiente onde o app foi escrito não tinha acesso ao YouTube nem às outras plataformas. O que foi testado: a interface (Xvfb), a validação de links, as proteções do servidor, a divisão em partes com ffmpeg, os leitores de legenda e o `.md` gerado.
- O Whisper não foi executado de ponta a ponta (o download do modelo pelo HuggingFace estava bloqueado). Na primeira execução no PC do usuário, ele baixa cerca de 460 MB (`small`).
- Os mp4 da opção "Melhor" podem conter VP9/AV1 e Opus, que alguns editores não abrem. Para edição, a opção certa é "Para edição (H.264)".
- O Instagram e o Facebook mudam com frequência: dependem do yt-dlp atualizado e de login.
- Não há como cancelar ou pausar um download, nem histórico.
- O app não é um executável: depende do Python instalado.

---

## 7. Roadmap (ideias priorizadas)

### 🔥 Prioridade alta — fluxo do canal

**7.1 Baixar só um trecho**
- Campos opcionais **Início** e **Fim** (aceitando `hh:mm:ss`, `mm:ss` ou segundos). Também deveria aceitar `?t=1064` do link como início.
- Implementação: `download_ranges=yt_dlp.utils.download_range_func(None, [(ini, fim)])` e `force_keyframes_at_cuts=True`.
- Também cortar a transcrição para o mesmo trecho.

**7.2 Vigiar canais (download automático)**
- Uma aba "Canais vigiados": lista de URLs (canal do YouTube, `twitch.tv/<canal>/videos`, perfil do TikTok), com uma qualidade e uma pasta para cada um (padrão `D:\ViceCityDay\VideosLives`).
- Verificação periódica com `extract_flat="in_playlist"` e `playlistend=10`, comparando com o histórico (`download_archive` do yt-dlp, um arquivo `.txt`).
- Opção de iniciar com o Windows (atalho em `shell:startup`) e minimizar para a bandeja (`pystray`).
- Ignorar lives em andamento e baixar o VOD quando a live terminar.

**7.3 Já sair no formato vertical / modelo ViceCityDay**
- Opção "Vertical 9:16" depois do download (crop central ou fundo desfocado).
- Opção "Modelo ViceCityDay": câmera do streamer em cima (~35%), jogo largo embaixo, fundo desfocado, marca d'água `Ediçao\logo_vcd_news.png`, @ViceCityDay no rodapé. Sem barra ou quadrado roxo.
- Ideal: integrar com o pipeline da skill `vicecityday-cortes` em vez de duplicar a lógica.

**7.4 Prévia antes de baixar**
- Ao colar um link, chamar `extract_info(download=False)` em segundo plano e mostrar miniatura, título, duração e tamanho estimado por qualidade (soma de `filesize`/`filesize_approx` dos formatos escolhidos).
- Avisar quando o vídeo for passar de alguns GB.

### ⚙️ Uso diário
- **7.5 Vários links de uma vez:** colar uma lista (um link por linha) e tudo entra na fila.
- **7.6 Pausar, cancelar e retomar:** cancelar com uma flag checada no `progress_hook` (lançar exceção) e retomar com `continuedl=True` (yt-dlp usa `.part`).
- **7.7 Histórico:** SQLite ou JSON com data, link, título, pasta e status. Aviso de duplicado. Botão para baixar de novo.
- **7.8 Miniatura:** `writethumbnail=True` e conversão para `.jpg` (`FFmpegThumbnailsConvertor`).
- **7.9 Downloads em paralelo:** 2 ou 3 threads de trabalho, com configuração.

### ✨ Acabamento
- **7.10 Executável:** PyInstaller (`--onedir --windowed`) com ffmpeg e Deno embutidos, instalador (Inno Setup) e atualização automática do yt-dlp dentro do app.
- **7.11 Notificação do Windows** ao terminar (`win10toast`/`plyer`), e som opcional.
- **7.12 Tela de configurações:** modelo do Whisper, limite padrão, pasta padrão por plataforma, tema.
- **7.13 Extensão para os 6 sites:** atualizar a extensão para mandar links ao app (ou ao servidor) a partir do TikTok, Instagram etc.

### 🔌 Integrações possíveis
- **Skill `vicecityday-cortes`:** depois de baixar uma live com transcrição, gerar automaticamente uma lista de momentos candidatos a corte (a partir do `.md` com timestamps) e entregar para a skill.
- **Agendamento de postagens:** os cortes prontos em `Cortes\3-prontos` podem ir para uma ferramenta de agendamento. O usuário posta 3 cortes por dia, talvez 5 no lançamento do GTA 6.
- **Legendas para os cortes:** reaproveitar a transcrição (timestamps palavra por palavra do Whisper: `word_timestamps=True`) para gerar a legenda amarela palavra por palavra usada nos cortes.

---

## 8. Convenções

- Interface, mensagens de erro, comentários e nomes de variáveis em **português**.
- Erros sempre amigáveis, explicando **o que fazer** (ver `explicar_erro`).
- Nunca travar a interface: o trabalho pesado fica em threads e a comunicação com a UI acontece só pela `queue`.
- Não salvar senhas. O login é feito só por cookies do navegador ou arquivo cookies.txt.
- Preferir sempre `pip install -U "yt-dlp[default,curl-cffi]"`. O `default` inclui o `yt-dlp-ejs`, necessário para o YouTube junto com o Deno. O `curl-cffi` permite ao yt-dlp se passar por um navegador (*impersonation*), e o **TikTok exige isso**: sem ele, todo vídeo do TikTok falha com "Unexpected response from webpage request", mesmo com login. Descoberto em 17/11/2026 com o yt-dlp 2026.10.26. O `explicar_erro` dos dois apps já traduz esse erro e manda rodar o `atualizar.bat`.
- Manter tudo funcionando com duplo clique, sem terminal.
- **Git e GitHub:** o repositório remoto é `origin` = https://github.com/murilorochasantana-ui/BaixadorYT.git, branch `main`. **Depois de cada commit de fase, fazer `git push origin main`.** Commits em português, um por fase (ou correção).
- **Nunca enviar ao GitHub** (o `.gitignore` já cobre, mas confira antes de cada push com `git status --ignored` e `git ls-files`): `cookies.txt`, `config.json`, tokens, chaves de API, o JSON de credenciais do Google (`client_secret*.json`), a pasta `modelos/` do Whisper, `ffmpeg.exe`/`bin/` e qualquer vídeo ou áudio. Chaves e tokens ficam só no Cofre do Windows (`keyring`).
- Antes de entregar uma mudança, testar a interface e a lógica isolada (ex.: `dividir`, os leitores de legenda). O arquivo `.pyw` pode ser importado com `importlib.machinery.SourceFileLoader`.

## 10. Estúdio ViceCityDay (Baixador YT 2.0, pasta `estudio/`)

Plano completo aprovado (Fase 0): `C:\Users\muril\.claude\plans\c-users-muril-downloads-prompt-claude-c-dynamic-crab.md`.
**Ordem das fases:** 1A → 1B → 2 (explorador) → 1C (Twitch ao vivo) → 6 (cronograma) → 3 (editor) → 4 (chat Claude) → 5 (métricas) → 7 (acabamento). Uma fase por vez, commit no fim de cada uma.

### Arquitetura
- **Python + interface web numa janela** (`pywebview` 6.x + WebView2). Sem Node, sem build: HTML/CSS/JS puros em `estudio/interface/` (bibliotecas JS futuras ficam salvas em `interface/vendor/`, sem CDN).
- `Estudio.pyw` (entrada) → `ponte.py` (classe `Ponte`, métodos chamados pelo JS; o pywebview roda cada chamada numa thread própria). Atributos da Ponte começam com `_` para não serem expostos ao JS.
- Python → página: eventos numa `queue`, entregues em lotes a cada 150 ms com `window.estudio.receber(lote)`.
- `estudio/nucleo/`: lógica sem interface, copiada do `app/BaixadorYT.pyw` com os mesmos nomes (`dividir`, `explicar_erro`, `QUALIDADES`, `LOGINS`, `opcoes_login`, `ler_json3`, `ler_vtt`, `escolher_legenda`, `montar_md`…) e novidades: `config.py`, `previa.py`, `qualidades.py` (modo Avançado), `downloads.py` (`Gerenciador` + `Pedido`), `sistema.py` (área de transferência, Explorer).
- **Dados do usuário fora do OneDrive:** `%LOCALAPPDATA%\EstudioViceCityDay\` (`config.json`, `modelos/` do Whisper, `navegador/`). No 1º uso importa `app/config.json`. `ESTUDIO_DADOS` troca a pasta (usado nos testes).
- **Caminhos do canal só em `nucleo/config.py`** (`pasta_raiz` = `D:\ViceCityDay` + `subpastas`). Use `config.pasta_do_canal(cfg, "lives"|"prontos"|"sfx"|...)`.

### Fase 1A (feita)
- Janela nova com abas (só "Baixar" funciona; as outras mostram "Chega na Fase X").
- Prévia automática ao colar o link: miniatura, canal, duração, legenda disponível, tamanho estimado por qualidade (usa `ydl._select_formats` + `build_format_selector`, o mesmo seletor do download; MP3/WAV estimados pelo bitrate de saída) e aviso acima de `aviso_gb` (padrão 3 GB).
- Qualidades novas: 4K, 1440p, M4A, WAV, só vídeo e **Avançado** (tabela com os formatos reais; formato só de vídeo vira `ID+ba/ID`).
- Transcrição grava `.md` **e** `.json` (`segmentos[].palavras[]` com `inicio`/`fim`/`palavra`; `palavras_precisas` = true quando vem do Whisper ou da legenda automática json3 com `tOffsetMs`; senão o tempo é repartido pelo tamanho das palavras).
- Whisper com `word_timestamps=True`.
- `estudio/instalar.bat`, `atualizar.bat` e `instalar_transcricao.bat` usam `py -3.12` (o PC também tem Python 3.15).
### Fase 1B (feita)
- **Vários links:** o campo virou `textarea` (Enter baixa, Shift+Enter quebra linha; "Colar" acrescenta). `plataformas.separar_links` separa válidos e inválidos e tira repetidos do mesmo vídeo usando `chave_do_link` (`youtube:<id>`, `tiktok:<id>`, `twitch:<id>`…). Avançado e trecho só aceitam um link.
- **Fila (`downloads.Gerenciador`)** com estados `fila → baixando → ok | erro | pausado | cancelado`. Pausar e cancelar durante o download marcam `pedir[id]`; os ganchos (`progress_hooks`, `postprocessor_hooks` e o `avisar` da transcrição/divisão) chamam `_checar` e lançam `Interrompido`.
  - **Pausar** guarda o `.part`, e **Retomar** põe o mesmo `Pedido` de volta na fila (`continuedl=True` continua do `.part`; testado: pausou em 30%, voltou em 39%).
  - **Cancelar** apaga `.part`, `-Frag*`, `.ytdl` e os formatos `.fNNN.` ainda não juntados.
  - **Paralelo:** N threads de trabalho (`downloads_paralelos`, 1 a 4, padrão 2). Diminuir não interrompe quem já está baixando.
- **Whisper uma vez por vez:** `transcricao.TRAVA_WHISPER`. Quem espera mostra "Esperando outra transcrição terminar…" e continua podendo ser pausado ou cancelado.
- **Trecho** (`nucleo/tempos.py`): aceita 17:44, 1:02:30, 1064, 17m44s e o `?t=`/`start=`/`#t=` do link, que preenche o Início sozinho.
  - Usa `download_ranges` + `force_keyframes_at_cuts`, e o nome ganha ` (trecho 17m44s-20m00s)` (sem ":", que o Windows não aceita).
  - A legenda da plataforma é cortada com `legendas.cortar_segmentos`, com os tempos recomeçando do zero para bater com o arquivo; o Whisper já transcreve só o trecho.
  - O `.json` traz `"trecho": {"inicio", "fim"}` em segundos do vídeo original.
- **Histórico** (`nucleo/historico.py`): SQLite em `%LOCALAPPDATA%\EstudioViceCityDay\estudio.db`, guardando o pedido em JSON (sem login).
  - Ao abrir, o que estava em andamento vira `interrompido` (botão "▶ Retomar").
  - **Repetido** = mesmo `chave` + mesmo trecho com status `ok`. A interface pergunta: Baixar de novo / Pular os repetidos / Cancelar (`forcar` = `todos` | `pular`).
- **Miniatura:** `writethumbnail` + `FFmpegThumbnailsConvertor` (jpg, `before_dl`), somado aos pós-processadores de áudio sem sobrescrever.
- **Notificação** (`nucleo/notificacao.py`): toast pelo PowerShell (`-EncodedCommand`, sem instalar nada), com o AppID do PowerShell, então aparece como "Windows PowerShell". Na Fase 7, com o instalador, ganha nome próprio. Avisa em ok e erro; pausar e cancelar não avisam.
- O YouTube deu 403 no formato só-áudio 140 do vídeo de teste "Me at the zoo" (coisa do YouTube, não do Estúdio).

### Correções depois do teste da 1B (feitas)
- **Trecho rápido (`nucleo/trecho.py`):** NÃO usar o `download_ranges` do yt-dlp. Com `force_keyframes_at_cuts` ele **recodifica o trecho inteiro** (external.py: sem `-c copy`), fica preso em `proc.wait()` sem progresso nem cancelamento, e o ffmpeg lendo o YouTube direto leva 403. São três caminhos:
  - **`indice`** (MP4/M4A por https com tamanho, ou seja, o YouTube): lê o começo do arquivo (`moov` + `sidx`), escolhe os segmentos do trecho e baixa só esses bytes em blocos de 4 MB, 6 ao mesmo tempo, pelo `ydl.urlopen` (mesma conexão e cabeçalhos do yt-dlp). Os blocos ficam em `<nome>.trecho-tmp/` com um `plano.json`: pausar e retomar reaproveita os blocos.
  - **`hls`** (Twitch): o ffmpeg lê só os segmentos (`-ss`/`-t` antes do `-i`, `-c copy`) em processo próprio, com `-progress pipe:1`.
  - **`inteiro`** (TikTok etc., sem tamanho conhecido): baixa inteiro pelo yt-dlp numa pasta temporária e corta.
- **Corte local:** sempre `-c copy`, começando no **quadro-chave antes do início** (`quadro_chave_antes` via ffprobe `-read_intervals`). O trecho pode começar alguns segundos antes (2–5 s); o início real vai para a transcrição (`"trecho"` no `.json`).
- **YouTube `available_at`:** os formatos só são liberados ~3–4 s depois de lidos. Antes disso, qualquer pedido leva **403**. `esperar_liberacao` mostra "Preparando o trecho... (N s)".
- **Medido no PC do usuário:** 1 h de live em 720p = 360 MB em 17 s (antes ~40 min); 2 min de VOD da Twitch em 5 s; cancelar em 0,2–0,8 s sem sobrar ffmpeg nem arquivo.
- **Processos:** `ffmpeg.rodar_cancelavel` (checa a cada 0,25 s e encerra o processo com `taskkill /T`) é usado no trecho, no corte e na divisão do Modo Claude. Cancelar apaga a pasta `.trecho-tmp`, os `.part`, os `.fNNN.` e os `.temp.` da junção.
- **Sem entrada duplicada:** `Gerenciador.ja_na_fila` (mesmo vídeo + trecho em fila/baixando/pausado) faz a ponte recusar. O conjunto `rodando` impede retomar enquanto a thread ainda encerra. Na interface, o BAIXAR fica travado enquanto envia.
- **Botões com 1 clique:** a causa era o `botoesDoItem` recriar os botões a cada evento de progresso, e o clique caía num elemento removido. Agora os botões só são refeitos quando o estado muda, e o botão clicado mostra "Pausando…"/"Cancelando…" desativado.
- **MP4 por padrão:** `qualidades.ORDEM_FORMATOS = ("res", "fps", "vcodec:h264", "acodec:aac", "ext:mp4:m4a")` como `format_sort`, tanto no download quanto na prévia, para a estimativa bater. Preferir só "mp4" escolhia AV1, que o CapCut abre mal.
- **Aviso do `?t=`:** só é preenchido quando o link muda, e editar o Início tira o aviso.

### Antes da Fase 2 (feito)
- **Plano B do trecho:** se o método rápido falha de qualquer jeito (403, índice diferente, rede caindo, arquivo estranho), `Trecho.baixar` volta sozinho para o `download_ranges` do yt-dlp (`_ytdlp`, mais lento, com corte exato) e emite o evento `aviso` ("O método rápido de trecho falhou…"; o motivo técnico vai no tooltip, campo `aviso_tecnico`). Pausar/cancelar (`Interrompido`, agora em `nucleo/controle.py`) NUNCA dispara o plano B. O yt-dlp roda numa thread: ao cancelar, `ffmpeg.matar_ffmpegs_filhos` encerra só os ffmpeg filhos deste processo. Testado com yt-dlp falso (403, lixo no índice, queda de rede, cancelar, MP3) e no YouTube de verdade com a falha forçada.
- **Regra de testes reais:** usar SEMPRE `D:\ViceCityDay\_testes` (nunca `VideosLives`) e apagar o que baixar ao terminar. O usuário vê essa pasta na árvore. Os `.part` que ficaram em `VideosLives` eram dos testes dele (cancelamentos anteriores à correção); nenhum arquivo meu chegou lá, pois os testes de velocidade foram para a pasta temporária da sessão. O `.mkv.part` do HEXATOMBE foi para a Lixeira; o `.mp4.part` do POSSO PERGUNTAR estava em uso pelo Estúdio aberto e ficou.

### Fase 2 (feita): explorador de arquivos ao vivo (aba "Arquivos")
- **Backend `nucleo/explorador.py`:** `listar` (uma pasta por vez, pastas primeiro, ignora `desktop.ini`/`$…`), `descrever` (ffprobe com cache, texto até 400 KB, JSON formatado), `para_lixeira`, `gerar_previa` e `Vigia` (watchdog).
- **Segurança (regra do projeto):** todo caminho vindo da interface passa por `explorador.dentro_de` (realpath + normcase; recusa `..` e pastas que só começam igual). As raízes são a pasta do canal e a de downloads (se for outra). A Lixeira recusa raiz, `VideosLives`/`Ediçao`/`Cortes`/`sfx`… (`pastas_protegidas`: a estrutura do canal e as pastas de 1º nível). Usa `send2trash`: **nunca apaga direto**. Mas apagar uma pasta de uma live inteira é permitido (com confirmação).
- **Vigia:** watchdog recursivo; agrupa as mudanças em avisos de no máximo 1 a cada 0,8 s com a lista de pastas (`{"tipo":"arquivos","pastas":[…]}`). A interface relê só as pastas abertas; pasta fechada só relê ao abrir; itens novos piscam por 2 s. Sem watchdog instalado: aviso na tela e botão ↻.
- **Progresso do `.part`:** os eventos de download carregam `arquivo_parcial` (o `tmpfilename` do yt-dlp, ou a pasta `.trecho-tmp` no trecho) e `pct`. A árvore mostra a barra e a prévia do `.part` mostra o tamanho e a %. Partes do Modo Claude, `.md`, `.json` e `.jpg` aparecem sozinhos pelo vigia.
- **Prévia:** vídeo/áudio/imagem por `servidor_midia.py` (http 127.0.0.1, porta aleatória, senha aleatória na URL, confere o cabeçalho Host contra DNS rebinding, só entrega o que `dentro_de` permite, aceita `Range`; o AV1 4K tocou e pulou para o meio). `.mkv`/`.avi`/`.ts` não tocam no WebView2: botão "Gerar prévia leve (540p)" (H.264/AAC, só os primeiros 10 min, cache em `%LOCALAPPDATA%\EstudioViceCityDay\previas`, máx. 15, original intocado). Informações: tamanho, data, duração, codec de vídeo/áudio, resolução, fps, taxa.
- **XSS (regra do projeto):** nomes de arquivo, títulos e transcrições vêm da internet e a página tem acesso à `Ponte` (poderia mandar arquivos para a Lixeira). Por isso a prévia de `.md` usa um renderizador próprio que **só cria nós de texto** (`textContent`; nada de `innerHTML`, sem links, sem HTML). Testado com `<script>`, `<img onerror>`, `javascript:` e `<iframe>` dentro do `.md`: aparecem como texto e nada executa. **Nunca usar `innerHTML` com conteúdo de arquivo, título ou transcrição.**
- Botões Abrir, Mostrar no Explorer e Lixeira funcionam. "Editar", "Mandar pro cronograma" e "Mandar pro chat" aparecem desativados com "(em breve)". Teclado: setas, Enter (abrir) e Delete (Lixeira, com confirmação).
- `instalar.bat`/`atualizar.bat` agora instalam `watchdog` e `send2trash`.
- **Testado de verdade (janela real, pywebview com roteiro):** árvore com a pasta do canal, `.md` do usuário formatado, MP4 AV1 4K tocando, `.mkv` virando prévia 540p, download novo aparecendo sozinho em `_testes` com barra de 25%→41%→53%, arquivos finais surgindo, `.jpg` indo de verdade para a Lixeira e `VideosLives` recusada.
- Testes: `testes/test_explorador.py` (41: classificação, caminhos, listagem, Lixeira, vigia real, servidor com Range/senha/host, prévia, ponte). Total: 154.
- **Ainda não feito:** abrir sozinha só `VideosLives` (as outras pastas começam fechadas); pasta do canal diferente do padrão só pelo botão da tela (a tela de Configurações é da Fase 7); a lista da Lixeira não é mostrada no app.

### Bug da prévia depois da Fase 2 (corrigido)
- A prévia ficava presa em "Lendo informações do vídeo…". O Python respondia em ~3 s; o problema estava no JS: o `explorador.js` declarava **outra função global `mostrarPrevia`**, que substituía a da aba Baixar (os dois scripts dividem o mesmo escopo global). A do explorador virou `mostrarPreviaArquivo`. **Regra:** antes de criar uma função global no JS, procure se o nome já existe nos outros `.js`.
- Limite de tempo: `Ponte.previa` roda o yt-dlp numa thread e desiste depois de `LIMITE_PREVIA` (30 s), com `MSG_PREVIA_DEMOROU` (conferir a internet, rodar o `atualizar.bat`, BAIXAR funciona sem prévia). A prévia também usa `socket_timeout: 15`, e o JS tem uma segunda trava de 40 s.

### Fase 1C (feita): lives da Twitch em andamento (`nucleo/gravacao.py`)
- **Live com VOD:** para links da Twitch, a prévia e o download usam `live_from_start: True`. Com isso, o yt-dlp troca `twitch.tv/<canal>` pelo VOD que está sendo gerado (`twitch:vod`, `is_live` = True). Esse VOD é uma playlist HLS do tipo **EVENT** que vai crescendo, e o caminho `hls` do `trecho.py` (ffmpeg `-ss`/`-t`) funciona sem mudança. `tipo_live(info)` → `None` | `"vod"` | `"gravar"` | `"outra"`. A prévia manda `live_com_vod`/`live_sem_vod`. Com VOD, a interface liga o trecho sozinha e mostra quanto da live já passou. Sem trecho, o download recusa com `MSG_LIVE_TRECHO`.
- **Live sem VOD:** a prévia mostra o botão "🔴 Gravar a partir de agora" (`Pedido.gravar`, sem `live_from_start`). Na fila aparecem "⏹ Parar e salvar" (`Gerenciador.parar` → `pedir = "parar"`, que o `_checar` **não** trata como interrupção; Pausar numa gravação vira Parar) e Cancelar (apaga tudo).
- **Gravação sem o ffmpeg lendo a live:** a Twitch encaixa **~30 s de anúncio no começo** para quem não é inscrito ou Turbo. Com o ffmpeg lendo direto, a primeira gravação de teste foi **só anúncio**. Agora `gravar_live` lê a playlist a cada 2 s e baixa os segmentos novos pelo `ydl.urlopen`. Ele **pula os de anúncio** (título do `#EXTINF` diferente de `live`, por exemplo `Amazon|…`) e grava em `.ts` com flush (se o PC desligar, o arquivo continua abrindo). No fim, passa para `.mp4` com `-c copy`; se a passagem falhar, entrega o `.ts`. Durante o anúncio, aparece "📺 Esperando o anúncio da Twitch acabar…". Nome: `<título> [id] (gravado dd-mm HHhMM).mp4`.
- Gravações não passam pelo aviso de repetido. Canal fora do ar → "Esse canal não está ao vivo agora…" (`explicar_erro`).
- **Testado de verdade (17/11, live do Gaules no ar havia ~46 h, em `_testes`, tudo apagado depois):** prévia em 2,7 s com `live_com_vod`; trecho de 2 min na hora 10 do VOD em andamento, em 720p, em 12,5 s; gravação de 60 s → pulou 30 s de anúncio, salvou 30 s de live em 720p (quadro conferido) 0,3 s depois do Parar; `xqc` fora do ar → mensagem em português.
- Testes: `testes/test_fase1c.py` (12). Inclui uma "live" HLS local (sem `ENDLIST`, com segmentos `Amazon|…`) lida por `file://`, além do limite da prévia. Total: 166.
- **Fica para depois:** YouTube ao vivo; mid-roll da Twitch no meio da gravação (os segmentos são pulados, então fica um corte de tempo no `.mp4`); a playlist de uma gravação muito longa pode expirar (o token da Twitch), e aí a gravação para sozinha e salva o que já tem depois de 10 falhas seguidas.

## Modelo do Claude por fase (regra do usuário)
**Cada fase começa numa sessão NOVA do Claude Code, já aberta com o modelo certo** (não continuar uma fase na sessão da anterior). No fim de cada fase, lembrar em destaque qual modelo usar na próxima.
**Próximas fases, nesta ordem:** 6 (cronograma) → 3 (editor) → 4 (chat com o Claude) → 5 (métricas) → 7 (acabamento).
- **Opus 5.5:** fases 6, 3 e 4.
- **Sonnet 5.5:** fases 5 e 7.
- YouTube ao vivo fica para depois (não tem fase marcada).

### Problemas descobertos na 1A (corrigidos no Estúdio e no `app/` antigo)
- **faster-whisper 1.2.1 + PyAV 19 são incompatíveis** (`av.open(... metadata_errors=...)` dá TypeError). Nenhum dos dois apps usa mais o PyAV: `carregar_audio` lê o áudio com o ffmpeg (mono, 16 kHz, s16le → numpy) e entrega o array ao Whisper.
- **O PC tem placa NVIDIA, mas não tem as bibliotecas CUDA** (`cublas64_12.dll`): `device="auto"` quebra. Os dois apps tentam `auto` e caem para `cpu` sozinhos.
- O ícone da janela no Windows precisa ser `.ico` (`estudio/recursos/icone.ico`, gerado do `app/icone.png`). Um `.png` derruba a janela.
- `Start-Process -WindowStyle Hidden` esconde a janela do pywebview; para testar, abra com `pythonw.exe` normalmente.

### Testes
- `cd estudio` e depois `py -3.12 -m pytest testes -q`. São 166 testes (a 1C trouxe `test_fase1c.py`; a Fase 2 trouxe `test_explorador.py`; o plano B do trecho entrou em `test_trecho.py`; ao todo inclui `test_trecho.py`: vídeos DASH gerados no PC + yt-dlp falso que responde a `Range`). A 1B testa a fila com um `YoutubeDL` falso (`test_fase1b.py`, classe `YDLFalso`), que segura o download até o teste liberar. A 1A tem 48 testes: plataformas, erros, config, qualidades, opções do yt-dlp, leitores de legenda, palavras, `.md`/`.json`, divisão com ffmpeg real, leitura de áudio, queda para CPU e estimativa de tamanho com o seletor real do yt-dlp).
- Interface sem o Python: `.claude/launch.json` → "interface-estudio" (servidor estático) e um `window.pywebview.api` falso no console.
- Testado de verdade na 1A: prévia + download do YouTube (720p, estimativa de 476 KB contra 475 KB reais), `.md`/`.json` pela legenda, Whisper `tiny` com tempo de cada palavra (caindo para a CPU), Modo Claude dividindo em 2 partes e a janela abrindo com o config antigo importado.

## 9. Observação legal

Baixar vídeos pode violar os termos de uso das plataformas. O uso pretendido é: vídeos do próprio usuário, conteúdo liberado, ou material usado como fonte para cortes editados com crédito ao autor.
