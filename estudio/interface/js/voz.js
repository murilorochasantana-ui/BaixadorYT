/* Estúdio ViceCityDay — aba Voz: mostra o VozLocal (gerador de voz offline, projeto à parte).
   Tudo dentro de uma função para não criar nomes globais (os .js dividem o mesmo escopo). */
(() => {
  "use strict";
  const q = (s) => document.querySelector(s);
  const quadro = q("#voz-quadro");
  const aviso = q("#voz-aviso");
  const textoAviso = q("#voz-aviso-texto");
  const tentar = q("#voz-tentar");
  const status = q("#voz-status");
  let ligando = false;
  let ligado = false;

  function mostrar(situacao, mensagem = "") {
    status.className = "selo";
    if (situacao === "ok") {
      status.textContent = "Ligado";
      status.classList.add("ciano");
      aviso.classList.add("escondido");
      quadro.classList.remove("escondido");
      return;
    }
    quadro.classList.add("escondido");
    aviso.classList.remove("escondido");
    textoAviso.textContent = mensagem; // sempre texto puro (nunca innerHTML)
    tentar.classList.toggle("escondido", situacao !== "erro");
    status.textContent = situacao === "erro" ? "Não abriu" : "Ligando…";
    if (situacao === "erro") status.classList.add("alerta");
  }

  async function ligarVoz(forcar = false) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || ligando || (ligado && !forcar)) return;
    ligando = true;
    mostrar("carregando", "Ligando o VozLocal… Na primeira vez pode levar até 1 minuto.");
    try {
      const r = await api.voz_ligar();
      if (r && r.ok) {
        ligado = true;
        quadro.src = `${r.url}?__theme=dark&t=${Date.now()}`;
        mostrar("ok");
      } else {
        ligado = false;
        mostrar("erro", (r && r.erro) || "O VozLocal não respondeu.");
      }
    } catch (e) {
      ligado = false;
      mostrar("erro", `Não consegui ligar o VozLocal: ${e}`);
    } finally {
      ligando = false;
    }
  }

  q('.aba[data-aba="voz"]').addEventListener("click", () => ligarVoz());
  tentar.addEventListener("click", () => ligarVoz(true));
  q("#voz-recarregar").addEventListener("click", () => ligarVoz(true));
  q("#voz-navegador").addEventListener("click", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    if (!ligado) await ligarVoz();
    if (ligado) api.voz_no_navegador();
  });
})();
