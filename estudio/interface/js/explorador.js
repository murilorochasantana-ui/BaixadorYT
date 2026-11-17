/* Estúdio ViceCityDay — Fase 2: explorador de arquivos ao vivo.
   Usa $, el, botao, perguntar, avisar, bytes, duracao e dataHora do app.js.
   REGRA DE SEGURANÇA: nomes de arquivo, títulos e textos vêm da internet (YouTube etc.). Nada disso
   entra como HTML: tudo vai por textContent / nós criados com el(). */
"use strict";

const ex = {
  iniciado: false, nos: new Map(), sel: null, progresso: new Map(), tokenPrevia: 0,
  raizes: [], vigia: false, primeiraCarga: true,
};
const norm = (p) => String(p || "").replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
const ICONES = { pasta: "📁", video: "🎬", audio: "🎵", imagem: "🖼️", texto: "📝", json: "🧾", parcial: "⏳", outro: "📄" };

// ---------- markdown seguro (só negrito, código, títulos e listas; nenhum HTML é interpretado) ----------
function mdInline(texto, pai) {
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let ultimo = 0, m;
  while ((m = re.exec(texto))) {
    if (m.index > ultimo) pai.append(texto.slice(ultimo, m.index));
    const bruto = m[0];
    pai.append(el(bruto.startsWith("**") ? "strong" : "code", { textContent: bruto.replace(/^(\*\*|`)|(\*\*|`)$/g, "") }));
    ultimo = m.index + bruto.length;
  }
  if (ultimo < texto.length) pai.append(texto.slice(ultimo));
}
function renderMd(texto) {
  const raiz = el("div", { className: "md" });
  let lista = null, par = [];
  const fechar = () => {
    if (par.length) { const p = el("p"); mdInline(par.join(" "), p); raiz.append(p); par = []; }
    lista = null;
  };
  for (const linha of texto.split(/\r?\n/)) {
    const h = /^(#{1,3})\s+(.*)$/.exec(linha), li = /^\s*[-*]\s+(.*)$/.exec(linha);
    if (h) { fechar(); const t = el("h" + h[1].length); mdInline(h[2], t); raiz.append(t); }
    else if (li) {
      if (par.length) fechar();
      if (!lista) { lista = el("ul"); raiz.append(lista); }
      const item = el("li"); mdInline(li[1], item); lista.append(item);
    } else if (!linha.trim()) fechar();
    else { lista = null; par.push(linha.trim()); }
  }
  fechar();
  return raiz;
}

// ---------- árvore ----------
function metaDoItem(item) {
  if (item.pasta) return "";
  const pct = ex.progresso.get(norm(item.caminho));
  if (item.parcial && pct != null) return `${Math.round(pct)}%`;
  return item.tamanho != null ? bytes(item.tamanho) : "";
}

function preencherLinha(no) {
  const it = no.item, l = no.linha;
  l.classList.toggle("parcial", it.parcial);
  l.title = `${it.caminho}\n${dataHora(new Date(it.mtime * 1000).toISOString())}`;
  no.icone.textContent = it.pasta ? (no.expandido ? "📂" : "📁") : (ICONES[it.tipo] || "📄");
  no.seta.textContent = it.pasta ? (no.expandido ? "▾" : "▸") : "";
  // nome cortado no MEIO: o final (parte, trecho, extensão) é o que diferencia os arquivos de uma live
  const FIM = 22;
  no.nomeIni.textContent = it.nome.length > FIM + 8 ? it.nome.slice(0, -FIM) : it.nome;
  no.nomeFim.textContent = it.nome.length > FIM + 8 ? it.nome.slice(-FIM) : "";
  no.meta.textContent = metaDoItem(it);
  const pct = ex.progresso.get(norm(it.caminho));
  no.barra.classList.toggle("escondido", !(it.parcial && pct != null));
  if (pct != null) no.barra.firstChild.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function criarNo(item) {
  const seta = el("span", { className: "no-seta" }), icone = el("span", { className: "no-icone" });
  const nomeIni = el("span", { className: "ini" }), nomeFim = el("span", { className: "fim" });
  const nome = el("span", { className: "no-nome" }, nomeIni, nomeFim), meta = el("span", { className: "no-meta" });
  const barra = el("span", { className: "no-barra escondido" }, el("div"));
  const linha = el("div", { className: "no-linha", role: "treeitem" }, seta, icone, nome, barra, meta);
  const li = el("li", {}, linha);
  const no = { item, li, linha, seta, icone, nome, nomeIni, nomeFim, meta, barra, expandido: false, carregado: false, filhos: null };
  if (item.pasta) { no.filhos = el("ul", { className: "escondido" }); li.append(no.filhos); }
  li.__no = no;
  ex.nos.set(norm(item.caminho), no);
  linha.addEventListener("click", () => { $("#arvore").focus({ preventScroll: true }); selecionar(no); if (item.pasta) alternar(no); });
  linha.addEventListener("dblclick", () => { if (!item.pasta) api.abrir_arquivo(item.caminho); });
  preencherLinha(no);
  return no;
}

function removerNo(no) {
  const base = norm(no.item.caminho);
  for (const k of [...ex.nos.keys()]) if (k === base || k.startsWith(base + "\\")) ex.nos.delete(k);
  if (ex.sel && (norm(ex.sel.item.caminho) === base || norm(ex.sel.item.caminho).startsWith(base + "\\"))) {
    ex.sel = null;
    previaVazia("Esse arquivo foi removido ou movido.");
  }
  no.li.remove();
}

function reconciliar(no, itens) {
  const ul = no.filhos;
  [...ul.querySelectorAll(":scope > .no-aviso")].forEach((x) => x.remove());
  const existentes = new Map([...ul.children].filter((c) => c.__no).map((c) => [norm(c.__no.item.caminho), c.__no]));
  const ordem = [];
  for (const item of itens) {
    const k = norm(item.caminho);
    let filho = existentes.get(k);
    if (filho) {
      existentes.delete(k);
      const mudou = filho.item.tamanho !== item.tamanho || filho.item.mtime !== item.mtime;
      filho.item = item;
      preencherLinha(filho);
      if (mudou && ex.sel === filho) atualizarPreviaParcial(filho);
    } else {
      filho = criarNo(item);
      if (!ex.primeiraCarga) filho.linha.classList.add("novo");   // apareceu agora: destaca por 2 s
    }
    ordem.push(filho.li);
  }
  existentes.forEach((f) => removerNo(f));
  ul.append(...ordem);
}

async function carregarPasta(no) {
  const r = await api.listar_pasta(no.item.caminho);
  if (!r.ok) {
    if (r.sumiu && no.li.parentElement) { removerNo(no); return; }
    no.filhos.replaceChildren(el("li", { className: "no-aviso", textContent: r.erro }));
    return;
  }
  reconciliar(no, r.itens);
  if (r.truncado) no.filhos.append(el("li", { className: "no-aviso", textContent: "⚠ Pasta muito grande: mostrando só os primeiros itens." }));
  else if (!r.itens.length) no.filhos.append(el("li", { className: "no-aviso", textContent: "(vazia)" }));
  no.carregado = true;
}

async function alternar(no, forcar) {
  no.expandido = forcar != null ? forcar : !no.expandido;
  no.filhos.classList.toggle("escondido", !no.expandido);
  preencherLinha(no);
  if (no.expandido && !no.carregado) await carregarPasta(no);
}

function visiveis() {
  return [...document.querySelectorAll("#arvore .no-linha")].filter((l) => l.offsetParent !== null);
}

function selecionar(no) {
  if (ex.sel) ex.sel.linha.classList.remove("sel");
  ex.sel = no;
  no.linha.classList.add("sel");
  no.linha.scrollIntoView({ block: "nearest" });
  mostrarPrevia(no.item.caminho);
}

$("#arvore").addEventListener("keydown", (e) => {
  const lista = visiveis();
  const atual = ex.sel ? lista.indexOf(ex.sel.linha) : -1;
  const ir = (i) => { const l = lista[Math.max(0, Math.min(lista.length - 1, i))]; if (l) selecionar(l.parentElement.__no); };
  if (e.key === "ArrowDown") { e.preventDefault(); ir(atual + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); ir(atual - 1); }
  else if (e.key === "ArrowRight" && ex.sel && ex.sel.item.pasta) { e.preventDefault(); alternar(ex.sel, true); }
  else if (e.key === "ArrowLeft" && ex.sel) {
    e.preventDefault();
    if (ex.sel.item.pasta && ex.sel.expandido) alternar(ex.sel, false);
    else { const pai = ex.sel.li.parentElement.closest("li"); if (pai && pai.__no) selecionar(pai.__no); }
  } else if (e.key === "Enter" && ex.sel) { e.preventDefault(); api.abrir_arquivo(ex.sel.item.caminho); }
  else if (e.key === "Delete" && ex.sel) { e.preventDefault(); paraLixeira(ex.sel.item); }
});

// ---------- prévia ----------
function previaVazia(texto) {
  $("#previa-arq").replaceChildren(el("div", { className: "vazio", textContent: texto || "Clique num arquivo para ver a prévia." }));
}

function linhaInfo(dl, rotulo, valor) {
  if (valor == null || valor === "") return;
  dl.append(el("dt", { textContent: rotulo }), el("dd", { textContent: valor }));
}

const CODECS = { h264: "H.264", hevc: "H.265 (HEVC)", av1: "AV1", vp9: "VP9", vp8: "VP8", mpeg4: "MPEG-4", aac: "AAC",
  opus: "Opus", mp3: "MP3", vorbis: "Vorbis", flac: "FLAC", ac3: "AC-3", pcm_s16le: "WAV (PCM)" };
const nomeCodec = (c) => CODECS[c] || (c ? c.toUpperCase() : "");

function textoBitrate(b) { return b ? `${(b / 1e6).toFixed(1).replace(".", ",")} Mbps` : ""; }

function montarInfo(d) {
  const dl = el("dl", { className: "prev-info" });
  linhaInfo(dl, "Tipo", { pasta: "Pasta", video: "Vídeo", audio: "Áudio", imagem: "Imagem", texto: "Texto",
    json: "Dados (JSON)", parcial: "Em andamento", outro: "Arquivo" }[d.tipo]);
  if (d.pasta) linhaInfo(dl, "Itens", d.n_itens != null ? `${d.n_itens}` : "");
  else linhaInfo(dl, "Tamanho", d.tamanho != null ? bytes(d.tamanho) : "");
  linhaInfo(dl, "Modificado", dataHora(new Date(d.mtime * 1000).toISOString()));
  const m = d.midia;
  if (m && m.valido) {
    linhaInfo(dl, "Duração", m.duracao ? duracao(m.duracao) : "");
    if (m.video) linhaInfo(dl, "Vídeo", [nomeCodec(m.video.codec), m.video.largura && `${m.video.largura}×${m.video.altura}`,
      m.video.fps && `${String(m.video.fps).replace(".", ",")} fps`].filter(Boolean).join(" · "));
    if (m.audio) linhaInfo(dl, "Áudio", [nomeCodec(m.audio.codec), m.audio.hz && `${(m.audio.hz / 1000).toLocaleString("pt-BR")} kHz`,
      m.audio.canais && (m.audio.canais === 2 ? "estéreo" : m.audio.canais === 1 ? "mono" : `${m.audio.canais} canais`)].filter(Boolean).join(" · "));
    linhaInfo(dl, "Taxa", textoBitrate(m.bitrate));
  }
  return dl;
}

function montarAcoes(d) {
  const a = el("div", { className: "prev-acoes" });
  a.append(botao(d.pasta ? "📂 Abrir pasta" : "▶ Abrir", "destaque", async () => {
    const r = await api.abrir_arquivo(d.caminho); if (!r.ok) avisar("Não deu para abrir", r.erro);
  }));
  a.append(botao("🔎 Mostrar no Explorer", "cinza", async () => {
    const r = await api.mostrar_no_explorer(d.caminho); if (!r.ok) avisar("Não deu", r.erro);
  }));
  a.append(botao("🗑 Lixeira", "perigo", () => paraLixeira(d)));
  for (const [rotulo, fase] of [["✂️ Editar", 3], ["📅 Mandar pro cronograma", 6], ["💬 Mandar pro chat do Claude", 4]]) {
    const b = el("button", { className: "btn cinza", textContent: `${rotulo} (em breve)`, disabled: true });
    b.title = `Chega na Fase ${fase}`;
    a.append(b);
  }
  return a;
}

async function mostrarPrevia(caminho) {
  const meu = ++ex.tokenPrevia;
  $("#previa-arq").replaceChildren(el("div", { className: "carregando" }, el("div", { className: "girando" }), "Lendo o arquivo…"));
  const r = await api.info_arquivo(caminho);
  if (meu !== ex.tokenPrevia) return;
  if (!r.ok) { previaVazia(r.erro); if (r.sumiu && ex.sel) { const n = ex.sel; ex.sel = null; removerNo(n); } return; }
  const d = r.info;
  const caixa = el("div", {});
  caixa.append(el("div", { className: "prev-cab" }, el("div", { className: "prev-nome", textContent: d.nome }),
    el("div", { className: "prev-caminho", textContent: d.caminho })));

  const mostrarVideo = (url, aviso) => {
    if (aviso) caixa.append(el("div", { className: "prev-aviso info", textContent: aviso }));
    const m = el(d.tipo === "audio" ? "audio" : "video", { className: "prev-midia", controls: true, preload: "metadata", src: url });
    m.addEventListener("error", () => semPrevia("O Estúdio não conseguiu tocar esse arquivo aqui."), { once: true });
    caixa.append(m);
  };
  const semPrevia = (motivo) => {
    caixa.querySelectorAll(".prev-midia, .prev-aviso").forEach((x) => x.remove());
    const aviso = el("div", { className: "prev-aviso", id: "prev-gerar" }, motivo + " ");
    if (d.tipo === "video") aviso.append(botao("Gerar prévia leve (540p)", "cinza", () => gerarPrevia(d.caminho)));
    caixa.insertBefore(aviso, caixa.children[1]);
  };

  if (d.tipo === "video" || d.tipo === "audio") {
    if (d.midia && d.midia.valido === false) {
      caixa.append(el("div", { className: "prev-aviso", textContent: "Esse arquivo parece incompleto ou danificado: não achei vídeo nem áudio nele." }));
    } else if (d.url) mostrarVideo(d.url);
    else if (d.url_previa) mostrarVideo(d.url_previa, "Prévia leve (540p, só os primeiros 10 minutos). O arquivo original não foi alterado.");
    else if (d.tipo === "video") semPrevia(`Esse formato (.${d.ext}) não toca direto no Estúdio.`);
  } else if (d.tipo === "imagem") {
    caixa.append(el("img", { className: "prev-imagem", src: d.url, alt: "" }));
  } else if (d.tipo === "texto" || d.tipo === "json") {
    const corpo = el("div", { className: "prev-texto" });
    if (d.ext === "md") corpo.append(renderMd(d.texto)); else corpo.append(el("pre", { textContent: d.texto }));
    caixa.append(corpo);
    if (d.truncado) caixa.append(el("div", { className: "prev-aviso", textContent: "Arquivo grande: mostrando só o começo. Use ▶ Abrir para ver tudo." }));
  } else if (d.tipo === "parcial") {
    const pct = ex.progresso.get(norm(d.caminho));
    caixa.append(el("div", { className: "prev-aviso info", id: "prev-parcial",
      textContent: "⏳ Ainda sendo baixado/gerado" + (pct != null ? ` — ${Math.round(pct)}%` : "") + ". O nome final aparece quando terminar." }));
  }
  caixa.append(montarInfo(d), montarAcoes(d));
  $("#previa-arq").replaceChildren(caixa);
}

function atualizarPreviaParcial(no) {
  if (no.item.tipo !== "parcial") return;
  const aviso = $("#prev-parcial");
  if (!aviso) return;
  const pct = ex.progresso.get(norm(no.item.caminho));
  aviso.textContent = `⏳ Ainda sendo baixado/gerado — ${no.item.tamanho != null ? bytes(no.item.tamanho) : ""}` +
    (pct != null ? ` (${Math.round(pct)}%)` : "") + ". O nome final aparece quando terminar.";
}

async function gerarPrevia(caminho) {
  const aviso = $("#prev-gerar");
  if (aviso) aviso.replaceChildren(el("div", { className: "prev-gerando" }, el("div", { className: "girando" }), "Gerando a prévia… 0%"));
  const r = await api.gerar_previa(caminho);
  if (!r.ok) avisar("Não deu", r.erro);
}

async function paraLixeira(item) {
  const pasta = item.pasta;
  const texto = el("div", {},
    el("div", { textContent: `${pasta ? "A pasta" : "O arquivo"} "${item.nome}" vai para a Lixeira do Windows.` }),
    el("div", { className: "suave pequeno", textContent: pasta ? "Tudo que está dentro dela vai junto. " : "" }),
    el("div", { className: "suave pequeno", textContent: "Dá para restaurar pela Lixeira. Nada é apagado de vez." }));
  const ok = await perguntar("Mandar para a Lixeira?", texto,
    [{ rotulo: "Cancelar", valor: false }, { rotulo: "🗑 Mandar para a Lixeira", classe: "perigo", valor: true }]);
  if (!ok) return;
  const r = await api.mover_para_lixeira(item.caminho);
  if (!r.ok) { avisar("Não deu para mandar para a Lixeira", r.erro); return; }
  const no = ex.nos.get(norm(item.caminho));
  if (no) removerNo(no);          // some na hora (o vigia confirma depois)
}

// ---------- eventos do Python ----------
async function recarregarPastas(lista) {
  for (const p of lista) {
    const no = ex.nos.get(norm(p));
    if (!no || !no.item.pasta) continue;
    if (no.expandido) await carregarPasta(no); else no.carregado = false;   // fechada: relê só quando abrir
  }
}

window.explorador = {
  progresso(caminho, pct) {
    if (pct == null) return;
    ex.progresso.set(norm(caminho), pct);
    const no = ex.nos.get(norm(caminho));
    if (no) { preencherLinha(no); if (ex.sel === no) atualizarPreviaParcial(no); }
  },
  alterados(pastas) { if (ex.iniciado) recarregarPastas(pastas); },
  previaEvento(ev) {
    if (!ex.sel || norm(ex.sel.item.caminho) !== norm(ev.caminho)) return;
    if (ev.estado === "gerando") {
      const g = document.querySelector("#prev-gerar .prev-gerando");
      if (g) g.lastChild.textContent = `Gerando a prévia… ${Math.round(ev.pct || 0)}%`;
    } else if (ev.estado === "pronta") mostrarPrevia(ex.sel.item.caminho);
    else if (ev.estado === "erro") { const a = $("#prev-gerar"); if (a) a.textContent = ev.erro; }
  },
};

// ---------- início (só na primeira vez que a aba abre) ----------
async function iniciarExplorador() {
  if (ex.iniciando) return;
  ex.iniciando = true;
  try { await montarExplorador(); } finally { ex.iniciando = false; }
}

async function montarExplorador() {
  const r = await api.explorador_raizes();
  ex.vigia = r.vigia;
  const erro = $("#arq-erro");
  if (r.erro) {
    $("#arq-corpo").classList.add("escondido");
    erro.replaceChildren(el("div", { textContent: r.erro, style: "white-space:pre-wrap;margin-bottom:12px" }),
      botao("📁 Escolher a pasta do canal", "destaque", async () => {
        const novo = await api.escolher_pasta_canal();
        if (novo && !novo.erro) { ex.iniciado = false; iniciarExplorador(); }
      }));
    erro.classList.remove("escondido");
    return;
  }
  erro.classList.add("escondido");
  $("#arq-corpo").classList.remove("escondido");
  $("#arq-subtitulo").textContent = r.vigia ? "As pastas do canal, ao vivo: o que está baixando aparece aqui na hora."
    : "⚠ Sem atualização automática (rode o atualizar.bat). Use ↻ Atualizar para reler as pastas.";
  ex.raizes = r.raizes;
  ex.nos.clear();
  $("#arvore").replaceChildren();
  ex.primeiraCarga = true;
  for (const raiz of r.raizes) {
    const no = criarNo({ nome: raiz.nome, caminho: raiz.caminho, pasta: true, tipo: "pasta", tamanho: null, mtime: Date.now() / 1000, parcial: false });
    $("#arvore").append(no.li);
    await alternar(no, true);
    await abrirSubpastasUsuais(no);
  }
  ex.primeiraCarga = false;
  ex.iniciado = true;
}

/* Abre sozinhas as pastas de trabalho (lives e cortes prontos) para o usuário já ver o que importa. */
async function abrirSubpastasUsuais(raizNo) {
  for (const filho of raizNo.filhos.querySelectorAll(":scope > li")) {
    const no = filho.__no;
    if (no && no.item.pasta && /^(videoslives)$/i.test(no.item.nome)) await alternar(no, true);
  }
}

document.querySelector('.aba[data-aba="arquivos"]').addEventListener("click", () => { if (!ex.iniciado) iniciarExplorador(); });
$("#arq-atualizar").addEventListener("click", async () => {
  for (const no of [...ex.nos.values()]) if (no.item.pasta && no.expandido) await carregarPasta(no);
});
$("#arq-abrir-raiz").addEventListener("click", () => { if (ex.raizes[0]) api.abrir_arquivo(ex.raizes[0].caminho); });
