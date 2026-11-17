---
name: "vicecityday-cortes"
description: "Use para tirar e editar cortes verticais de lives (GTA 6 ou outros jogos) no estilo do canal ViceCityDay, a partir de vídeos na pasta D:\\ViceCityDay."
---

# Cortes ViceCityDay

Canal de cortes de GTA 6 (YouTube "ViceCityDay" e TikTok @vicecityday_gta). O usuário quer 3 a 5 cortes bons por live, prontos pra postar. Responder sempre em português.

## Estrutura de pastas (D:\ViceCityDay)
- `VideosLives\` — lives brutas, cada uma numa subpasta (já divididas em partes de até 400 MB).
- `Ediçao\sfx\` — efeitos organizados e com volume igualado (usar estes). Catálogo em `LEIA-ME_catalogo.txt`. Tipos: impacto_*, whoosh_*, acerto*, ding_*, brilho_ding, plateia_aplausos, erro_*, dinheiro_cash, caixa_registradora, moedas, relogio_tique, tensao_bomba_relogio, alarme, violino_energia, teclado_digitando, meme_cabra.
- `Ediçao\Musicas\` — músicas de fundo synthwave do Pixabay (uso livre).
- `Ediçao\Efeitos sonoros\` — originais brutos do usuário. NÃO usar: compilações, músicas conhecidas (Titanic, Naruto, Sexy Sax, músicas do TikTok) e gravações de tela, por risco de direitos autorais.
- `Cortes\3-prontos\` — onde salvar os cortes finalizados (cada corte com um `.txt` de legenda do post).
- `teriler GTA\` — trailer "Grand Theft Auto VI: An Extended Look", usado como imagem de fundo nos cortes de podcast.

## 1. Trazer a live
- Pedir acesso à pasta `D:\ViceCityDay` (device_request_folder_access) se ainda não tiver, listar `VideosLives\` e puxar com device_stage_files.
- Limite: 400 MB por arquivo e 500 MB por chamada (puxar uma parte por vez). Se o arquivo for maior, pedir ao usuário para dividir no Prompt de Comando:
  `ffmpeg -i "ARQUIVO.mkv" -c copy -map 0 -f segment -segment_time 600 -reset_timestamps 1 "parte_%02d.mkv"`
  Dica pra ele: baixar/gravar em 720p evita isso.
- Vídeo de teste (não GTA) nunca é postado.
- **Chat da live (opcional, ajuda muito)**: se a live foi no YouTube, pedir ao usuário para baixar o replay do chat no PC e colocar na pasta da live:
  `yt-dlp --skip-download --write-subs --sub-langs live_chat -o chat "LINK_DA_LIVE"`
  Gera `chat.live_chat.json`. Cada linha é um JSON com `replayChatItemAction.videoOffsetTimeMsec`. Contar mensagens a cada 10 s; é pico de chat quando tem ≥ 8 mensagens e ≥ 2,5× a mediana dos 5 min em volta.

## 2. Preparar ferramentas (o ambiente não persiste entre chats)
- Transcrição: `pip install --break-system-packages sherpa-onnx`. O HuggingFace é bloqueado; baixar do GitHub:
  - `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-small.tar.bz2` (extrair)
  - `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx`
- Fonte: `https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-Black.ttf` e `...-ExtraBold.ttf` (usar raw.githubusercontent, não github.com/raw).
- Extrair áudio mono 16 kHz de cada parte e transcrever em background com VAD (min_silence 0.25 s, max_speech 8 s), whisper small int8, language='pt', num_threads=2. Roda ~3–5x tempo real: avisar o usuário que 2 h de live levam ~30–40 min.
- Detector de rosto: `pip install --break-system-packages opencv-python-headless` e baixar `https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades/haarcascade_frontalface_default.xml` (o OpenCV 5 não traz os cascades; o modelo YuNet do opencv_zoo não baixa aqui).
- **Picos de volume com base local** (método do Clipper do GTA 6): RMS por segundo em dB; ignorar os 20% mais silenciosos; o "normal" de cada minuto é a mediana dos 5 min em volta; pico = excesso ≥ max(8 dB, percentil 98 do excesso). Funciona melhor que comparar com a média da live inteira.
- **Montar blocos de 12 min** da transcrição, cada linha `[hh:mm:ss] fala` com marcas `[ALTO +NdB]` e `[CHAT N×]`. Ler um bloco por vez. Marca sozinha não é momento: confirmar pela fala.

## 3. Escolher os momentos (o mais importante)
Nota de 0 a 5, um ponto por critério. Só vira corte o que tiver **4 ou mais**:
1. **Pico de reação real**: grito, gargalhada, susto (pico de volume ≥ ~9 dB acima da mediana da parte).
2. **Algo acontecendo na tela** no mesmo momento (explosão, queda, morte, acidente, resultado visível).
3. **Entende-se sem contexto**, no máximo com a frase do texto âncora.
4. **Tem fim/punchline** claro.
5. **Duração de 15 a 40 s** sem enrolação (máx. ~60 s).

Como achar: ler os blocos de 12 min, olhar onde tem `[ALTO]`/`[CHAT]` e confirmar pela fala, depois montar contact sheet (ffmpeg `fps`, `tile`, timestamp com drawtext) e **olhar os quadros** antes de decidir. Se a live não tiver nada com nota 4+, dizer isso ao usuário em vez de forçar corte ruim.

**O que vale corte** (o que as pessoas compartilham): primeira reação a algo do jogo (mapa, personagem, gráfico); descoberta absurda ou detalhe que ninguém viu; surto, grito, raiva, susto; falha engraçada, bug, morte ridícula; opinião forte ou polêmica; previsão (ótima perto do lançamento); história ou piada que fecha sozinha. Em podcast: informação útil e nova (como jogar antes, preço, desempenho, recordes).

**Jogar fora**: o que precisa de contexto de antes; o que começa com enrolação ("é…", "então…", "tipo assim", "voltando…"); leitura de doação, propaganda, conversa sobre a própria live, pausa, tela de carregamento; fala picada ou que a transcrição não deixa entender. Normalmente um bloco tem de 0 a 3 momentos bons: não inventar pra encher.

**Registrar cada candidato** num JSON por bloco, com nota de 0 a 100 (90+ = qualquer pessoa para de rolar o feed; abaixo de 70, descartar), além dos 5 critérios acima:
`{"inicio":"01:12:03","fim":"01:12:41","nota":88,"tipo":"primeira reação","titulo":"...","porque":"...","post":"..."}`
Depois juntar todos, ordenar pela nota, tirar os que se sobrepõem e ficar com os N melhores. Contar ao usuário: "achei X momentos possíveis e fiquei com os N melhores".

**Cortar no ponto certo**: começar 1–2 s antes da frase ou do grito que prende (nunca no meio de uma palavra) e terminar logo depois da reação/conclusão. Pode juntar 2–4 trechos do mesmo assunto pra tirar enrolação (jump cut).

**Título (texto âncora)**: até ~45 letras, MAIÚSCULO, sem spoiler do final; usar o nome/apelido do streamer quando ajudar ("CASIMIRO NÃO ACREDITOU…").

**Texto âncora tem que ser verdade**: confirmar nos quadros o que ele afirma (ex.: "tirou 22 no dado" só se aparecer 22). Se não der pra confirmar, mudar a frase ou descartar o corte.

## 4. Layout aprovado (1080×1920, 60 fps)
- **Câmera do streamer**: 0–680 px (≈35%). Descobrir a posição da webcam olhando um quadro da live (varia por streamer); cortar com zoom no rosto (proporção ≈1,59:1) e escalar pra 1080×680.
- **Fundo**: o próprio jogo escalado pra cobrir 1080×1440 a partir de y=480, `boxblur=25:2`, `eq=brightness=-0.18`.
- **Jogo**: recorte 4:3 (em fonte 1280×720: 960×720) mostrando ~75% da largura, escalado pra 1080×810 em y=795. Deslocar o recorte pra não aparecer a webcam da live dentro do jogo.
- Sem barra ou quadrado roxo.
- **Texto âncora**: só texto, Montserrat Black ~80 px, branco, borda preta grossa (~9), centralizado em y≈690, no máximo 2 linhas, MAIÚSCULO. Entra com "pop" de escala (40%→108%→100% em 200 ms) e **some aos 5 s** (encolhe + transparente). Tom do canal: engraçado, curto, pode usar "KKKKKKK".
- **Legenda**: estilo palavra por palavra, Montserrat Black ~92 px, branca com borda preta 8 e sombra, palavra falada em amarelo (`&H00E6FF&`), grupos de até 3 palavras e ~15 caracteres, pop de entrada, centralizada em y≈1700 (no fundo desfocado, sem cobrir o jogo). Distribuir o tempo do segmento entre as palavras proporcional ao tamanho. Corrigir erros óbvios da transcrição.
- **Marca**: "@ViceCityDay" Montserrat ExtraBold 40 px, rosa claro, em y≈1870.
- **Zoom no rosto**: nos 2–3 picos de volume do corte, zoom de 1,28× na câmera por ~1,2 s (`zoompan` com d=1). Seguir a skill de ffmpeg: escalar a câmera antes do zoompan (ex.: 3240×2040) pra não tremer.

## 4b. Formato podcast / conversa (sem gameplay)
- Tela dividida: **quem está falando em cima** (1080×960) e **cenas do trailer embaixo** (1080×960), sem áudio do trailer.
- Em cima: detectar trocas de câmera (ffmpeg `select='gt(scene,0.25)'`), e em cada cena achar o rosto (Haar em 3–4 quadros, maior rosto, mediana do centro x) e recortar 810×720 centrado nele → 1080×960. Zoom 1,12× nos picos de volume.
- Embaixo: do trailer, usar janelas de 3 s sem corte de cena no meio, claras (brilho médio ≥ 55, mínimo ≥ 40), com movimento (diferença média entre quadros ≥ 2) e textura (desvio ≥ 25). Excluir os comerciais de TV dentro do jogo (~435–478 s do Extended Look). Embaralhar, sem repetir dentro do mesmo corte; recorte 810×720 centralizado → 1080×960.
- Título logo acima da divisão (y≈850) por 5 s; legenda amarela logo abaixo (y≈1075); crédito "via CANAL • Trailer: Rockstar Games" em y≈1830; @ViceCityDay em y≈1870.
- Música: volume 0,055 com ducking (`sidechaincompress`), só se a live não tiver música durante a fala.
- Corrigir erros comuns da transcrição: "GTACI"/"GT6" → GTA 6, "JT" → GTA, "P5 Pro"/"Play 5 Pro" → PS5 Pro, "Tiktu" → Take-Two.
- Fatos ditos no podcast (números, datas) que forem pro título: conferir com uma busca rápida; se for estimativa, não chamar de oficial.

**Sem câmera do streamer** (corte de gameplay puro): jogo inteiro no meio (largura 1080) com o próprio jogo desfocado de fundo.

**Achar a webcam automaticamente** (lives de gameplay): procurar rosto em ~14 quadros do trecho, ficar com os rostos perto da mediana (distância < 8% da largura); a caixa da câmera é ~3,2× a largura do rosto, centrada nele (um pouco acima do centro vertical). Se achar menos de 3 rostos, usar o layout sem câmera.

## 5. Efeitos sonoros
- Usar os arquivos de `D:\ViceCityDay\Ediçao\sfx` (puxar só os que o corte vai usar). Se o usuário baixar o pacote do ElevenLabs (flow "ViceCityDay - Pacote de efeitos sonoros": pop, whoosh, boom, fail, vitoria, susto, risada, scratch), ele também vai pra essa pasta. O que faltar (ex.: pop), sintetizar com numpy: pop (sweep senoidal curto), whoosh (ruído com banda subindo), boom (grave descendente), fail ("uón uón" descendente), scratch.
- Música de fundo (principalmente em cortes de podcast/conversa): faixa de `Ediçao\Musicas`, volume bem baixo (~-28 dB sob a voz) com ducking (`sidechaincompress`) quando alguém fala.
- Pop na entrada do texto âncora (~0,55 vol). Whoosh 0,35 s antes de cada zoom e boom no zoom. Fail/vitória/susto/risada só quando combinar com o que acontece.
- Mixar com `amix=normalize=0` e finalizar com `loudnorm=I=-14:TP=-1.5:LRA=11`.

## 6. Extras (usar quando o momento for forte)
- Abertura com o pico (2–4 s) + texto curto ("ESPERA...") + flash branco com whoosh, depois a história desde o começo.
- Replay final em câmera lenta 0,6× com etiqueta vermelha "REPLAY", voz mais grave, scratch e fail. Não salva momento fraco.

## 7. Exportar e conferir
- libx264 veryfast CRF 20–21, `format=yuv420p`, AAC 160k, `+faststart`. Ao juntar trechos, usar o filtro concat re-encodando.
- Conferir: extrair 3–5 quadros (início, texto âncora, zoom, final), checar se o rosto aparece, se o texto não corta e se o áudio está nivelado.
- **Legenda mais sincronizada**: antes de montar a legenda final, transcrever de novo só o trecho do corte com VAD de frases curtas (max_speech ~2,5 s), pra ter tempos a cada ~2 s em vez de blocos de 8 s.
- **Legenda do post**: pra cada corte, gravar um `.txt` com o mesmo nome do vídeo contendo: título, 1–2 frases + 4 a 6 hashtags (sempre `#gta6`) e o crédito "Corte da live de NOME: LINK" (se o usuário passou o link).
- Copiar pra `/mnt/user-data/outputs`, mandar com SendUserFile e gravar em `D:\ViceCityDay\Cortes\3-prontos` com device_commit_files (usar o fileUuid se o stagedPath falhar).
- Nome do arquivo: `vicecityday_<tema_curto>.mp4`.

## 8. Postagem
- Pelo vidIQ (Metricool é do canal de animação, plano grátis só 1 marca). Contas: YouTube "ViceCityDay" e TikTok "vicecityday_gta". A conta TikTok "Universo3D" também aparece no vidIQ: nunca postar nela.
- Mesmo vídeo e mesmo horário nas duas plataformas. Melhores horários: 10h, 16h, 18h (America/Sao_Paulo). Sem rótulo de IA.
- Sempre mostrar o rascunho e esperar o "pode postar" do usuário.
- Dar crédito ao streamer (nome no título ou legenda) e preferir streamers que liberam cortes.