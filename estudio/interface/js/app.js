/* Estúdio ViceCityDay — interface (Fase 1A: aba Baixar) */
"use strict";

const $ = (s) => document.querySelector(s);
const estado = { avancado: "", previa: null, formato: null, pedidoPrevia: 0, itens: new Map() };
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
function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}
function avisar(titulo, texto) {
  $("#modal-titulo").textContent = titulo;
  $("#modal-texto").textContent = texto;
  $("#modal").classList.remove("escondido");
  $("#modal-ok").focus();
}
$("#modal-ok").addEventListener("click", () => $("#modal").classList.add("escondido"));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("#modal").classList.add("escondido");
});

const RE_LINK = /^https?:\/\/[^\s]+$/i;

// ---------- abas ----------
document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".aba").forEach((x) => x.classList.toggle("ativa", x === b));
  document.querySelectorAll(".tela").forEach((t) => t.classList.toggle("ativa", t.id === `tela-${b.dataset.aba}`));
}));

// ---------- início ----------
window.addEventListener("pywebviewready", iniciar);

async function iniciar() {
  api = window.pywebview.api;
  const ini = await api.estado_inicial();
  const cfg = ini.cfg;
  estado.avancado = ini.avancado;

  $("#qualidade").replaceChildren(...ini.qualidades.map((q) => el("option", { value: q, textContent: q })));
  $("#qualidade").value = ini.qualidades.includes(cfg.qualidade) ? cfg.qualidade : ini.qualidades[0];
  $("#login").replaceChildren(...ini.logins.map((l) => el("option", { value: l, textContent: l })));
  $("#login").value = cfg.login || "Nenhum";
  $("#pasta").value = ini.pasta_downloads;
  $("#modo-claude").checked = !!cfg.modo_claude;
  $("#limite").value = cfg.limite_mb || 400;
  $("#transcricao").checked = !!cfg.transcricao;
  atualizarAvancado();

  const avisos = [];
  if (!ini.ffmpeg) avisos.push("ffmpeg não encontrado");
  if (!ini.whisper) avisos.push("Whisper não instalado");
  $("#versao").textContent = `yt-dlp ${ini.versao_ytdlp}` + (avisos.length ? ` • ${avisos.join(" • ")}` : "");
  $("#versao").title = avisos.length ? "Rode o instalar.bat / instalar_transcricao.bat da pasta estudio." : "";

  if (ini.link_colado) { $("#link").value = ini.link_colado; pedirPrevia(); }
  $("#link").focus();
}

// ---------- link e prévia ----------
let espera = null;
$("#link").addEventListener("input", () => {
  clearTimeout(espera);
  espera = setTimeout(pedirPrevia, 600);
});
$("#link").addEventListener("keydown", (e) => { if (e.key === "Enter") baixar(); });
$("#btn-colar").addEventListener("click", async () => {
  $("#link").value = await api.colar();
  pedirPrevia();
});

async function pedirPrevia() {
  const url = $("#link").value.trim();
  const caixa = $("#previa");
  if (!RE_LINK.test(url)) {
    estado.previa = null; estado.formato = null;
    caixa.classList.add("escondido");
    preencherFormatos();
    return;
  }
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

function mostrarPrevia() {
  const p = estado.previa;
  if (!p) return;
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

  const escolhida = $("#qualidade").value;
  const tam = el("div", { className: "tamanhos" });
  for (const [nome, b] of Object.entries(p.tamanhos)) {
    const cls = nome === escolhida ? "esc" : "";
    tam.append(el("div", { className: cls, textContent: nome }),
      el("div", { className: cls, textContent: b ? "≈ " + bytes(b) : "tamanho desconhecido" }));
  }
  const partes = [topo, tam];
  const sel = p.tamanhos[escolhida] || (estado.formato && estado.formato.tamanho);
  if (sel && sel > p.aviso_gb * 1024 ** 3) {
    partes.push(el("div", { className: "aviso-grande",
      textContent: `⚠ Essa qualidade baixa cerca de ${bytes(sel)}. Confira se tem espaço no disco, ` +
        `ou escolha 720p / "Para edição" para um arquivo menor.` }));
  } else if (p.grande && !sel) {
    partes.push(el("div", { className: "aviso-grande", textContent: `⚠ Alguma qualidade passa de ${p.aviso_gb} GB.` }));
  }
  if (p.ao_vivo) {
    partes.push(el("div", { className: "aviso-grande",
      textContent: "Essa live está acontecendo agora. Espere ela terminar para baixar o VOD." }));
  }
  $("#previa").replaceChildren(...partes);
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
      "Cole um link: a lista de formatos aparece depois da prévia.";
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
for (const id of ["#modo-claude", "#transcricao", "#limite"]) {
  $(id).addEventListener("change", () => api.salvar_config({
    modo_claude: $("#modo-claude").checked, transcricao: $("#transcricao").checked,
    limite_mb: Number($("#limite").value) || 400,
  }));
}

// ---------- baixar ----------
$("#btn-baixar").addEventListener("click", baixar);

async function baixar() {
  const url = $("#link").value.trim();
  const qualidade = $("#qualidade").value;
  const f = estado.formato;
  const r = await api.baixar({
    url, qualidade, pasta: $("#pasta").value.trim(),
    formato_avancado: qualidade === estado.avancado && f ? { id: f.id, tem_video: f.tem_video, tem_audio: f.tem_audio } : null,
    modo_claude: $("#modo-claude").checked,
    limite_mb: Number($("#limite").value) || 400,
    transcricao: $("#transcricao").checked,
  });
  if (!r.ok) { avisar("Não deu para baixar", r.erro); return; }
  $("#link").value = "";
  estado.previa = null; estado.formato = null;
  $("#previa").classList.add("escondido");
  preencherFormatos();
  $("#link").focus();
}

// ---------- fila (eventos vindos do Python) ----------
function itemDaFila(id) {
  let it = estado.itens.get(id);
  if (it) return it;
  const titulo = el("div", { className: "item-titulo" });
  const status = el("div", { className: "item-status" });
  const barra = el("div");
  const detalhe = el("div", { className: "item-detalhe" });
  const acoes = el("div", { className: "item-acoes escondido" });
  const li = el("li", { className: "item" }, el("div", { className: "item-topo" }, titulo, status),
    el("div", { className: "barra" }, barra), detalhe, acoes);
  $("#fila").prepend(li);
  it = { li, titulo, status, barra, detalhe, acoes, fim: false };
  estado.itens.set(id, it);
  $("#fila-vazia").classList.add("escondido");
  return it;
}

function atualizarResumo() {
  const todos = [...estado.itens.values()];
  const ativos = todos.filter((i) => !i.fim).length;
  $("#fila-resumo").textContent = ativos ? `${ativos} em andamento/na fila` :
    (todos.length ? "✔ Tudo pronto!" : "Nada na fila");
}

window.estudio = {
  receber(lote) {
    for (const ev of lote) {
      if (ev.tipo !== "download") continue;
      const it = itemDaFila(ev.id);
      if (ev.titulo) { it.titulo.textContent = ev.titulo; it.titulo.title = ev.titulo; }
      if (ev.status) it.status.textContent = ev.status;
      if (ev.pct != null) it.barra.style.width = `${Math.max(0, Math.min(100, ev.pct))}%`;
      if (ev.vel) it.detalhe.textContent = `${ev.vel} • falta ${ev.eta || "?"}`;
      if (ev.fim) {
        it.fim = true;
        if (ev.erro) {
          it.li.classList.add("erro");
          it.detalhe.textContent = ev.erro.split("\n")[0];
          avisar("Erro ao baixar", `${it.titulo.textContent}\n\n${ev.erro}`);
        } else {
          it.li.classList.add("ok");
          it.barra.style.width = "100%";
          const n = (ev.arquivos || []).length;
          it.detalhe.textContent = n > 1 ? `${n} arquivos salvos` : "Salvo";
          const bPasta = el("button", { className: "btn cinza", textContent: "📂 Abrir pasta" });
          bPasta.addEventListener("click", () => api.abrir_pasta(ev.pasta));
          it.acoes.replaceChildren(bPasta);
          if (n) {
            const bArq = el("button", { className: "btn cinza", textContent: "🔎 Mostrar no Explorer" });
            bArq.addEventListener("click", () => api.mostrar_arquivo(ev.arquivos[0]));
            it.acoes.append(bArq);
          }
          it.acoes.classList.remove("escondido");
        }
      }
    }
    atualizarResumo();
  },
};
