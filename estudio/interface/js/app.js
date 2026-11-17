/* Estúdio ViceCityDay — interface (Fase 1B: aba Baixar com fila, trecho e histórico) */
"use strict";

const $ = (s) => document.querySelector(s);
const estado = {
  avancado: "", previa: null, formato: null, pedidoPrevia: 0, itens: new Map(),
  links: [], inicioAuto: false, temHistorico: false, linkAtual: "", enviando: false,
};
let api = null;

// ---------- utilidades ----------
function bytes(n) {
  if (!n) return "?";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  const casas = i >= 3 ? 2 : 0;
  return `${n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })} ${u[i]}`;
}
function duracao(s) {
  if (!s) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const p = (v) => String(v).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}
/* só para estimar o tamanho do trecho na prévia (quem valida de verdade é o Python) */
function segundos(txt) {
  txt = (txt || "").trim();
  if (!txt) return null;
  if (/^\d+(:\d{1,2}){0,2}$/.test(txt)) return txt.split(":").reduce((a, p) => a * 60 + Number(p), 0);
  return null;
}
function dataHora(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}
function botao(texto, classe, acao) {
  const b = el("button", { className: `btn ${classe}`, textContent: texto });
  b.addEventListener("click", acao);
  return b;
}

// ---------- janela de aviso / pergunta ----------
function perguntar(titulo, conteudo, botoes) {
  return new Promise((resolver) => {
    $("#modal-titulo").textContent = titulo;
    const caixa = $("#modal-texto");
    caixa.replaceChildren(typeof conteudo === "string" ? document.createTextNode(conteudo) : conteudo);
    const fechar = (valor) => { $("#modal").classList.add("escondido"); document.removeEventListener("keydown", esc); resolver(valor); };
    const esc = (e) => { if (e.key === "Escape") fechar(null); };
    document.addEventListener("keydown", esc);
    $("#modal-botoes").replaceChildren(...botoes.map((b) => botao(b.rotulo, b.classe || "cinza", () => fechar(b.valor))));
    $("#modal").classList.remove("escondido");
    $("#modal-botoes").lastChild.focus();
  });
}
const avisar = (titulo, texto) => perguntar(titulo, texto, [{ rotulo: "OK", classe: "destaque", valor: true }]);

// ---------- abas ----------
document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".aba").forEach((x) => x.classList.toggle("ativa", x === b));
  document.querySelectorAll(".tela").forEach((t) => t.classList.toggle("ativa", t.id === `tela-${b.dataset.aba}`));
}));
document.querySelectorAll(".aba-fila").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".aba-fila").forEach((x) => x.classList.toggle("ativa", x === b));
  $("#painel-fila").classList.toggle("escondido", b.dataset.painel !== "fila");
  $("#painel-historico").classList.toggle("escondido", b.dataset.painel !== "historico");
  if (b.dataset.painel === "historico") carregarHistorico();
}));

// ---------- início ----------
window.addEventListener("pywebviewready", iniciar);

async function iniciar() {
  api = window.pywebview.api;
  const ini = await api.estado_inicial();
  const cfg = ini.cfg;
  estado.avancado = ini.avancado;
  estado.temHistorico = ini.historico;

  $("#qualidade").replaceChildren(...ini.qualidades.map((q) => el("option", { value: q, textContent: q })));
  $("#qualidade").value = ini.qualidades.includes(cfg.qualidade) ? cfg.qualidade : ini.qualidades[0];
  $("#login").replaceChildren(...ini.logins.map((l) => el("option", { value: l, textContent: l })));
  $("#login").value = cfg.login || "Nenhum";
  $("#pasta").value = ini.pasta_downloads;
  $("#modo-claude").checked = !!cfg.modo_claude;
  $("#limite").value = cfg.limite_mb || 400;
  $("#transcricao").checked = !!cfg.transcricao;
  $("#miniatura").checked = cfg.miniatura !== false;
  $("#paralelos").value = String(cfg.downloads_paralelos || 2);
  $("#notificacao").checked = cfg.notificacao !== false;
  atualizarAvancado();

  const avisos = [];
  if (!ini.ffmpeg) avisos.push("ffmpeg não encontrado");
  if (!ini.whisper) avisos.push("Whisper não instalado");
  if (!ini.imita_navegador) avisos.push("TikTok vai falhar: rode o atualizar.bat");
  $("#versao").textContent = `yt-dlp ${ini.versao_ytdlp}` + (avisos.length ? ` • ${avisos.join(" • ")}` : "");
  $("#versao").title = avisos.length ? "Rode o atualizar.bat / instalar_transcricao.bat da pasta estudio." : "";

  if (ini.link_colado) { $("#link").value = ini.link_colado; ajustarAltura(); analisarLink(); }
  $("#link").focus();
}

// ---------- link(s), ?t= e prévia ----------
let espera = null;
function ajustarAltura() {
  const t = $("#link");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 2, 130) + "px";
}
$("#link").addEventListener("input", () => {
  ajustarAltura();
  clearTimeout(espera);
  espera = setTimeout(analisarLink, 500);
});
$("#link").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); baixar(); }   // Shift+Enter = nova linha
});
$("#btn-colar").addEventListener("click", async () => {
  const atual = $("#link").value.trim();
  const colado = await api.colar();
  $("#link").value = atual ? `${atual}\n${colado}` : colado;   // colar de novo acrescenta outro link
  ajustarAltura();
  analisarLink();
});

async function analisarLink() {
  const texto = $("#link").value;
  const r = await api.analisar_link(texto);
  estado.links = r.links;
  const info = $("#link-info");
  info.classList.remove("alerta");
  if (r.links.length > 1) {
    info.textContent = `${r.links.length} links: todos vão para a fila com as mesmas opções.` +
      (r.invalidos.length ? `  ⚠ Não reconheci ${r.invalidos.length}: ${r.invalidos.slice(0, 3).join(", ")}` : "");
    info.classList.remove("escondido");
  } else if (!r.links.length && texto.trim()) {
    info.textContent = "⚠ Isso não parece um link do YouTube, TikTok, Instagram, Twitch, Pinterest ou Facebook.";
    info.classList.add("alerta");
    info.classList.remove("escondido");
  } else {
    info.classList.add("escondido");
  }

  // início vindo do ?t= do link: só quando o link MUDA (editar o Início à mão tira o aviso)
  const linkAgora = r.links.length === 1 ? r.links[0] : "";
  if (linkAgora !== estado.linkAtual) {
    estado.linkAtual = linkAgora;
    ajudaTrechoPadrao();
    if (r.inicio_link) {
      $("#trecho-ativo").checked = true;
      $("#trecho-inicio").value = r.inicio_texto;
      estado.inicioAuto = true;
      $("#trecho-ajuda").textContent = `O início (${r.inicio_texto}) veio do ?t= do link. Apague se quiser o vídeo inteiro.`;
    } else if (estado.inicioAuto) {
      $("#trecho-ativo").checked = false;
      $("#trecho-inicio").value = "";
      estado.inicioAuto = false;
    }
  }
  atualizarTrecho();

  if (r.links.length === 1) pedirPrevia(r.links[0]);
  else { estado.previa = null; estado.formato = null; $("#previa").classList.add("escondido"); preencherFormatos(); }
}

async function pedirPrevia(url) {
  const caixa = $("#previa");
  if (estado.previa && estado.previa.url === url) return;
  const meu = ++estado.pedidoPrevia;
  caixa.classList.remove("escondido");
  caixa.replaceChildren(el("div", { className: "carregando" }, el("div", { className: "girando" }),
    "Lendo informações do vídeo…"));
  const r = await api.previa(url);
  if (meu !== estado.pedidoPrevia) return; // o link mudou enquanto lia
  if (!r.ok) {
    estado.previa = null;
    caixa.replaceChildren(el("div", { className: "erro-texto", textContent: r.erro }));
    preencherFormatos();
    return;
  }
  estado.previa = r.dados;
  estado.formato = null;
  mostrarPrevia();
  preencherFormatos();
}

function fracaoTrecho() {
  const p = estado.previa;
  if (!$("#trecho-ativo").checked || !p || !p.duracao) return 1;
  const ini = segundos($("#trecho-inicio").value) || 0;
  const fim = segundos($("#trecho-fim").value) ?? p.duracao;
  const f = (Math.min(fim, p.duracao) - ini) / p.duracao;
  return f > 0 && f <= 1 ? f : 1;
}

function mostrarPrevia() {
  const p = estado.previa;
  if (!p || estado.links.length !== 1) return;
  const selos = el("div", { className: "selos" });
  if (p.plataforma) selos.append(el("span", { className: "selo", textContent: p.plataforma }));
  if (p.duracao) selos.append(el("span", { className: "selo", textContent: "⏱ " + duracao(p.duracao) }));
  if (p.itens > 1) selos.append(el("span", { className: "selo", textContent: `${p.itens} itens` }));
  if (p.tem_legenda) selos.append(el("span", { className: "selo ciano", textContent: "legenda disponível" }));
  if (p.ao_vivo) selos.append(el("span", { className: "selo alerta", textContent: "AO VIVO agora" }));

  const info = el("div", {},
    el("div", { className: "previa-titulo", textContent: p.titulo }),
    el("div", { className: "suave pequeno", textContent: p.canal || "" }),
    selos);
  const topo = el("div", { className: "previa-topo" });
  if (p.miniatura) topo.append(el("img", { src: p.miniatura, alt: "", referrerPolicy: "no-referrer" }));
  topo.append(info);

  const fr = fracaoTrecho();
  const escolhida = $("#qualidade").value;
  const tam = el("div", { className: "tamanhos" });
  if (fr < 1) tam.append(el("div", { className: "esc", textContent: "Tamanho estimado do trecho" }), el("div"));
  for (const [nome, b] of Object.entries(p.tamanhos)) {
    const cls = nome === escolhida ? "esc" : "";
    tam.append(el("div", { className: cls, textContent: nome }),
      el("div", { className: cls, textContent: b ? "≈ " + bytes(b * fr) : "tamanho desconhecido" }));
  }
  const partes = [topo, tam];
  const sel = (p.tamanhos[escolhida] || (estado.formato && estado.formato.tamanho) || 0) * fr;
  if (sel && sel > p.aviso_gb * 1024 ** 3) {
    partes.push(el("div", { className: "aviso-grande",
      textContent: `⚠ Isso vai baixar cerca de ${bytes(sel)}. Confira se tem espaço no disco, ` +
        `ou escolha 720p / "Para edição" (ou baixe só um trecho) para um arquivo menor.` }));
  }
  if (p.ao_vivo) {
    partes.push(el("div", { className: "aviso-grande",
      textContent: "Essa live está acontecendo agora. Espere ela terminar para baixar o VOD." }));
  }
  $("#previa").replaceChildren(...partes);
}

// ---------- trecho ----------
function ajudaTrechoPadrao() {
  $("#trecho-ajuda").textContent = "Aceita 17:44, 1:02:30 ou segundos (1064).";
}
function atualizarTrecho() {
  $("#trecho").classList.toggle("escondido", !$("#trecho-ativo").checked);
  if ($("#trecho-ativo").checked && estado.links.length > 1) {
    $("#trecho-ajuda").textContent = "⚠ O trecho só funciona com um link por vez.";
  } else if (estado.links.length > 1 || !estado.inicioAuto) {
    ajudaTrechoPadrao();
  }
  mostrarPrevia();
}
$("#trecho-ativo").addEventListener("change", () => { estado.inicioAuto = false; atualizarTrecho(); });
for (const id of ["#trecho-inicio", "#trecho-fim"]) {
  $(id).addEventListener("input", () => { estado.inicioAuto = false; ajudaTrechoPadrao(); mostrarPrevia(); });
}

// ---------- qualidade / avançado ----------
$("#qualidade").addEventListener("change", () => {
  atualizarAvancado();
  mostrarPrevia();
  api.salvar_config({ qualidade: $("#qualidade").value });
});

function atualizarAvancado() {
  $("#avancado").classList.toggle("escondido", $("#qualidade").value !== estado.avancado);
}

function preencherFormatos() {
  const tabela = $("#tabela-formatos");
  const p = estado.previa;
  if (!p || !p.formatos.length) {
    tabela.replaceChildren();
    $("#avancado-ajuda").textContent = p ? "Esse vídeo não informou os formatos." :
      (estado.links.length > 1 ? "O modo Avançado funciona com um link por vez." :
        "Cole um link: a lista de formatos aparece depois da prévia.");
    return;
  }
  $("#avancado-ajuda").textContent = "Clique num formato. Formatos só de vídeo são juntados com o melhor áudio.";
  const cab = el("thead", {}, el("tr", {}, ...["ID", "Resolução", "FPS", "Vídeo", "Áudio", "Ext", "Tamanho", "Obs."]
    .map((t) => el("th", { textContent: t }))));
  const corpo = el("tbody");
  for (const f of p.formatos) {
    const tr = el("tr", {}, ...[f.id, f.resolucao, f.fps || "", f.vcodec || "—", f.acodec || "—", f.ext,
      f.tamanho ? bytes(f.tamanho) : "?", f.nota].map((t) => el("td", { textContent: t })));
    tr.addEventListener("click", () => {
      estado.formato = f;
      corpo.querySelectorAll("tr").forEach((x) => x.classList.toggle("selecionado", x === tr));
      mostrarPrevia();
    });
    corpo.append(tr);
  }
  tabela.replaceChildren(cab, corpo);
}

// ---------- outras opções ----------
$("#login").addEventListener("change", async () => {
  const r = await api.mudar_login($("#login").value);
  $("#login").value = r.login;
  if (r.aviso) avisar("Login", r.aviso);
  estado.previa = null; // com outro login a prévia pode mudar
});
$("#btn-escolher").addEventListener("click", async () => {
  const p = await api.escolher_pasta($("#pasta").value);
  if (p) $("#pasta").value = p;
});
$("#btn-abrir").addEventListener("click", () => api.abrir_pasta($("#pasta").value));
for (const id of ["#modo-claude", "#transcricao", "#limite", "#miniatura"]) {
  $(id).addEventListener("change", () => api.salvar_config({
    modo_claude: $("#modo-claude").checked, transcricao: $("#transcricao").checked,
    limite_mb: Number($("#limite").value) || 400, miniatura: $("#miniatura").checked,
  }));
}
$("#paralelos").addEventListener("change", () => api.salvar_config({ downloads_paralelos: Number($("#paralelos").value) }));
$("#notificacao").addEventListener("change", () => api.salvar_config({ notificacao: $("#notificacao").checked }));

// ---------- baixar ----------
$("#btn-baixar").addEventListener("click", () => baixar());

async function baixar(forcar = null) {
  if (estado.enviando) return;            // Enter + clique (ou clique duplo) não manda duas vezes
  estado.enviando = true;
  $("#btn-baixar").disabled = true;
  try {
    await enviarDownload(forcar);
  } finally {
    estado.enviando = false;
    $("#btn-baixar").disabled = false;
  }
}

async function enviarDownload(forcar) {
  const qualidade = $("#qualidade").value;
  const f = estado.formato;
  const r = await api.baixar({
    texto: $("#link").value, qualidade, pasta: $("#pasta").value.trim(), forcar,
    formato_avancado: qualidade === estado.avancado && f ? { id: f.id, tem_video: f.tem_video, tem_audio: f.tem_audio } : null,
    modo_claude: $("#modo-claude").checked,
    limite_mb: Number($("#limite").value) || 400,
    transcricao: $("#transcricao").checked,
    miniatura: $("#miniatura").checked,
    trecho: { ativo: $("#trecho-ativo").checked, inicio: $("#trecho-inicio").value, fim: $("#trecho-fim").value },
  });
  if (r.duplicados) { const escolha = await perguntarRepetidos(r); if (escolha) await enviarDownload(escolha); return; }
  if (!r.ok) { avisar("Não deu para baixar", r.erro); return; }

  $("#link").value = "";
  ajustarAltura();
  estado.previa = null; estado.formato = null; estado.links = []; estado.linkAtual = "";
  if (estado.inicioAuto) { $("#trecho-ativo").checked = false; $("#trecho-inicio").value = ""; estado.inicioAuto = false; }
  atualizarTrecho();
  $("#previa").classList.add("escondido");
  const info = $("#link-info");
  const msgs = [];
  if (r.ids.length) msgs.push(`✔ ${r.ids.length} na fila.`);
  if (r.pulados) msgs.push(r.pulados === 1 ? "1 já tinha sido baixado e foi pulado." :
    `${r.pulados} já tinham sido baixados e foram pulados.`);
  if (r.invalidos && r.invalidos.length) msgs.push(r.invalidos.length === 1 ? "⚠ Ignorei 1 texto que não é link aceito." :
    `⚠ Ignorei ${r.invalidos.length} textos que não são links aceitos.`);
  info.textContent = msgs.join(" ");
  info.classList.toggle("escondido", !msgs.length);
  info.classList.toggle("alerta", !!(r.invalidos && r.invalidos.length));
  preencherFormatos();
  $("#link").focus();
}

async function perguntarRepetidos(r) {
  const lista = el("ul", { className: "lista-repetidos" },
    ...r.duplicados.slice(0, 8).map((d) => el("li", { textContent: `${d.titulo} — baixado em ${dataHora(d.quando)}` })));
  const um = r.total === 1;
  const texto = el("div", {},
    document.createTextNode(um ? "Você já baixou esse vídeo antes:" :
      `${r.duplicados.length} de ${r.total} links você já baixou antes:`), lista);
  const botoes = um
    ? [{ rotulo: "Cancelar", valor: null }, { rotulo: "Baixar de novo", classe: "destaque", valor: "todos" }]
    : [{ rotulo: "Cancelar", valor: null }, { rotulo: "Baixar todos de novo", valor: "todos" },
      { rotulo: "Pular os repetidos", classe: "destaque", valor: "pular" }];
  return perguntar("Já baixado", texto, botoes);
}

// ---------- fila (eventos vindos do Python) ----------
function itemDaFila(id) {
  let it = estado.itens.get(id);
  if (it) return it;
  const titulo = el("div", { className: "item-titulo" });
  const status = el("div", { className: "item-status" });
  const barra = el("div");
  const detalhe = el("div", { className: "item-detalhe" });
  const acoes = el("div", { className: "item-acoes" });
  const aviso = el("div", { className: "item-aviso escondido" });
  const li = el("li", { className: "item" }, el("div", { className: "item-topo" }, titulo, status),
    el("div", { className: "barra" }, barra), detalhe, aviso, acoes);
  $("#fila").prepend(li);
  it = { id, li, titulo, status, barra, detalhe, aviso, acoes, estado: "fila", ultimo: {} };
  estado.itens.set(id, it);
  $("#fila-vazia").classList.add("escondido");
  return it;
}

/* Ação de um botão da fila: 1 clique, resposta na hora ("Pausando…") e todos os botões do item
   ficam desativados até o Python confirmar a mudança de estado (aí os botões são refeitos). */
function acao(it, texto, classe, rotuloEsperando, funcao) {
  const b = botao(texto, classe, async () => {
    it.acoes.querySelectorAll("button").forEach((x) => { x.disabled = true; });
    b.textContent = rotuloEsperando;
    const aceito = await funcao(it.id);
    if (!aceito) {   // não deu (ex.: ainda encerrando o download anterior): volta os botões
      botoesDoItem(it);
      it.detalhe.textContent = "Aguarde um instante e tente de novo: ainda estou encerrando o download anterior.";
    }
  });
  return b;
}

function botoesDoItem(it) {
  const ev = it.ultimo;
  const b = [];
  if (it.estado === "fila" || it.estado === "baixando") {
    b.push(acao(it, "⏸ Pausar", "cinza", "Pausando…", api.pausar));
    b.push(acao(it, "✖ Cancelar", "perigo", "Cancelando…", api.cancelar));
  } else if (it.estado === "pausado") {
    b.push(acao(it, "▶ Retomar", "destaque", "Retomando…", api.retomar));
    b.push(acao(it, "✖ Cancelar", "perigo", "Cancelando…", api.cancelar));
  } else if (it.estado === "erro" || it.estado === "cancelado") {
    b.push(acao(it, "↻ Tentar de novo", "cinza", "Colocando na fila…", api.retomar));
  } else if (it.estado === "ok") {
    if (ev.pasta) b.push(botao("📂 Abrir pasta", "cinza", () => api.abrir_pasta(ev.pasta)));
    if (ev.arquivos && ev.arquivos.length) b.push(botao("🔎 Mostrar no Explorer", "cinza", () => api.mostrar_arquivo(ev.arquivos[0])));
  }
  it.acoes.replaceChildren(...b);
}

function atualizarResumo() {
  const todos = [...estado.itens.values()];
  const ativos = todos.filter((i) => i.estado === "fila" || i.estado === "baixando").length;
  const baixando = todos.filter((i) => i.estado === "baixando").length;
  const pausados = todos.filter((i) => i.estado === "pausado").length;
  let txt = todos.length ? "✔ Tudo pronto!" : "Nada na fila";
  if (ativos) txt = `${baixando} baixando • ${ativos - baixando} esperando`;
  if (pausados) txt += ` • ${pausados} pausado(s)`;
  $("#fila-resumo").textContent = txt;
  $("#fila-contador").textContent = ativos;
  $("#fila-contador").classList.toggle("escondido", !ativos);
}

let recarregar = null;
window.estudio = {
  receber(lote) {
    let terminou = false;
    for (const ev of lote) {
      if (ev.tipo === "arquivos") { window.explorador && window.explorador.alterados(ev.pastas); continue; }
      if (ev.tipo === "previa") { window.explorador && window.explorador.previaEvento(ev); continue; }
      if (ev.tipo !== "download") continue;
      if (ev.arquivo_parcial && window.explorador) window.explorador.progresso(ev.arquivo_parcial, ev.pct);
      const it = itemDaFila(ev.id);
      if (ev.titulo) { it.titulo.textContent = ev.titulo; it.titulo.title = ev.titulo; }
      if (ev.status) it.status.textContent = ev.status;
      if (ev.pct != null) it.barra.style.width = `${Math.max(0, Math.min(100, ev.pct))}%`;
      if (ev.vel) it.detalhe.textContent = `${ev.vel} • falta ${ev.eta || "?"}`;
      if (ev.aviso) { it.aviso.textContent = `ℹ ${ev.aviso}`; it.aviso.title = ev.aviso_tecnico || ""; it.aviso.classList.remove("escondido"); }
      Object.assign(it.ultimo, ev);
      if (ev.estado && ev.estado !== it.estado || !it.acoes.childElementCount) {
        it.estado = ev.estado;
        it.li.className = `item ${ev.estado}`;
        if (ev.estado === "fila") it.detalhe.textContent = "";
        if (ev.estado === "pausado") it.detalhe.textContent = "Pausado: o que já baixou fica guardado para continuar depois.";
        if (ev.estado === "cancelado") it.detalhe.textContent = "Cancelado: os pedaços baixados foram apagados.";
        if (ev.estado === "ok") {
          const n = (ev.arquivos || []).length;
          it.detalhe.textContent = n > 1 ? `${n} arquivos salvos` : "Salvo";
          it.barra.style.width = "100%";
        }
        if (ev.estado === "erro" && ev.erro) {
          it.detalhe.textContent = ev.erro.split("\n")[0];
          avisar("Erro ao baixar", `${it.titulo.textContent}\n\n${ev.erro}`);
        }
        if (ev.fim) terminou = true;
        botoesDoItem(it);          // só refaz os botões quando o estado muda (senão o clique se perde)
      }
    }
    atualizarResumo();
    if (terminou && !$("#painel-historico").classList.contains("escondido")) {
      clearTimeout(recarregar);
      recarregar = setTimeout(carregarHistorico, 400);
    }
  },
};

// ---------- histórico ----------
const NOMES_STATUS = { ok: "Concluído", erro: "Erro", cancelado: "Cancelado", interrompido: "Interrompido",
  pausado: "Pausado", fila: "Na fila", baixando: "Baixando" };
let esperaBusca = null;
$("#busca-historico").addEventListener("input", () => {
  clearTimeout(esperaBusca);
  esperaBusca = setTimeout(carregarHistorico, 300);
});

function textoTrecho(t) {
  if (!t) return "";
  const [a, b] = t.split("-");
  return `trecho ${duracao(Number(a)) || "0:00"}–${b ? duracao(Number(b)) : "fim"}`;
}

async function carregarHistorico() {
  if (!estado.temHistorico) {
    $("#historico").replaceChildren();
    $("#historico-vazio").textContent = "O histórico não pôde ser aberto neste PC.";
    $("#historico-vazio").classList.remove("escondido");
    return;
  }
  const linhas = await api.historico($("#busca-historico").value);
  $("#historico-vazio").textContent = $("#busca-historico").value ? "Nada encontrado." : "Nada no histórico ainda.";
  $("#historico-vazio").classList.toggle("escondido", linhas.length > 0);
  $("#historico").replaceChildren(...linhas.map((h) => {
    const meta = [dataHora(h.criado_em), h.qualidade, textoTrecho(h.trecho), h.pasta].filter(Boolean).join(" • ");
    const acoes = el("div", { className: "item-acoes" });
    if (h.pasta && h.status === "ok") acoes.append(botao("📂 Pasta", "cinza", () => api.abrir_pasta(h.pasta)));
    const refazer = h.status === "interrompido" ? "▶ Retomar" : "⬇ Baixar de novo";
    if (!["fila", "baixando", "pausado"].includes(h.status)) {
      acoes.append(botao(refazer, "cinza", async () => {
        const r = await api.baixar_de_novo(h.id);
        if (!r.ok) avisar("Não deu", r.erro);
        else document.querySelector('.aba-fila[data-painel="fila"]').click();
      }));
      acoes.append(botao("🗑 Tirar da lista", "perigo", async () => { await api.apagar_do_historico(h.id); carregarHistorico(); }));
    }
    const li = el("li", { className: "item" },
      el("div", { className: "item-topo" },
        el("div", { className: "item-titulo", textContent: `[${h.plataforma || "?"}] ${h.titulo || h.url}`, title: h.url }),
        el("span", { className: `selo-status ${h.status}`, textContent: NOMES_STATUS[h.status] || h.status })),
      el("div", { className: "hist-meta", textContent: meta }),
      h.status === "erro" && h.erro ? el("div", { className: "hist-meta", textContent: h.erro.split("\n")[0] }) : null,
      acoes);
    return li;
  }));
}
