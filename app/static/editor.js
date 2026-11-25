{
const ID = RIGEL.id, $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const mmss = t => { t = Math.max(0, t || 0); return String(Math.floor(t / 60)).padStart(2, "0") + ":" + (t % 60).toFixed(1).padStart(4, "0"); };
const OCUPADO = ["fila", "baixando", "analisando", "renderizando"];
const NOMES = {fila:"Na fila", baixando:"Baixando", analisando:"Analisando", revisao:"Em revisão", renderizando:"Renderizando", pronto:"Pronto", erro:"Erro"};
const CORES = {pronto:"lima", revisao:"amar", erro:"verm"};
const CAT = {chamada:"Chamada", tela_final:"Tela final", manual:"Manual"};
const LOOKS = [["docu","Docu-reality","linear-gradient(90deg,#2a1a10,#c08a52,#f0d6a8)"],["neutro","Neutro","linear-gradient(90deg,#1b1d22,#8a8d93,#e9eaec)"],["original","Original","linear-gradient(90deg,#0b2a4a,#3d7bff,#ffd23f)"]];
let J = null, sel = null, fonte = "previa", modo = "rapido", poll = null, srcAtual = "";
const v = $("#v");

async function api(url, corpo) {
  const r = await fetch(url, corpo === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(corpo)});
  if (r.status === 401) { location.href = "/entrar"; return null; }
  return r.json();
}

function cortesAtivos() {
  if (!J || !J.cortes) return [];
  const l = J.cortes.filter(c => c.ativo).map(c => [c.t0, c.t1]);
  if (J.usar_silencios !== false) (J.silencios || []).forEach(s => l.push([s.t0, s.t1]));
  l.sort((a, b) => a[0] - b[0]);
  const m = [];
  for (const [a, b] of l) { if (m.length && a <= m[m.length - 1][1]) m[m.length - 1][1] = Math.max(m[m.length - 1][1], b); else m.push([a, b]); }
  return m;
}

/* ---------------- estado e topo */
function desenhar() {
  const e = J.etapa;
  $("#etapa").textContent = NOMES[e] || e;
  $("#etapa").className = "pilula " + (CORES[e] || "azul");
  $("#prog").style.width = (OCUPADO.includes(e) ? Math.max(4, J.progresso || 0) : e === "pronto" ? 100 : 0) + "%";
  $("#bt-render").disabled = !J.midia || OCUPADO.includes(e);
  $("#bt-render").textContent = e === "pronto" && innerWidth > 900 ? "Renderizar de novo" : "Renderizar";
  $$("#fontes button")[2].disabled = e !== "pronto" && !J.saida;
  const sobre = $("#sobre");
  if (!J.midia) { sobre.hidden = false; sobre.innerHTML = `<div><b>${NOMES[e] || e}…</b><br>${e === "erro" ? esc(J.erro) : "O Rigel está transcrevendo e procurando as chamadas. Em CPU leva perto da duração do vídeo."}</div>`; }
  else sobre.hidden = true;
  if (J.midia) {
    const dur = J.midia.duracao, corte = cortesAtivos().reduce((s, [a, b]) => s + b - a, 0);
    $("#durs").textContent = `Original ${mmss(dur)} · editado ≈ ${mmss(dur - corte)}`;
  }
  fonteVideo(); timeline(); listaCortes(); ajustes(); exportar(); chat();
  clearTimeout(poll);
  if (OCUPADO.includes(e) || J.clipes === "gerando" || J.clipes === "fila") poll = setTimeout(atualizar, 2500);
}

async function atualizar() { const d = await api("/api/job/" + ID); if (d) { J = d; desenhar(); } }

/* ---------------- vídeo */
function fonteVideo() {
  if (!J.midia) return;
  const src = fonte === "final" && J.saida ? `/job/${ID}/arquivo/${J.saida}?v=${J.renderizado_em || 0}` : `/job/${ID}/original`;
  if (src !== srcAtual) { const t = fonte === "final" ? 0 : v.currentTime; srcAtual = src; v.src = src; v.currentTime = t; }
  $$("#fontes button").forEach(b => b.classList.toggle("on", b.dataset.f === fonte));
  $("#tl").style.opacity = fonte === "final" ? .35 : 1;
}
$$("#fontes button").forEach(b => b.onclick = () => { if (!b.disabled) { fonte = b.dataset.f; fonteVideo(); } });
$("#play").onclick = () => v.paused ? v.play() : v.pause();
v.onplay = () => $("#play").textContent = "❚❚";
v.onpause = () => $("#play").textContent = "▶";
v.ontimeupdate = () => {
  $("#tc").textContent = mmss(v.currentTime);
  if (fonte === "previa" && !v.paused) {
    for (const [a, b] of cortesAtivos()) if (v.currentTime >= a && v.currentTime < b - 0.05) { v.currentTime = b; break; }
  }
  if (J && J.midia && fonte !== "final") $("#cab").style.left = (v.currentTime / J.midia.duracao * 100) + "%";
};
document.addEventListener("keydown", e => { if (e.code === "Space" && !/TEXTAREA|INPUT|SELECT/.test(e.target.tagName)) { e.preventDefault(); $("#play").click(); } });

/* ---------------- timeline */
function timeline() {
  if (!J.midia) return;
  const dur = J.midia.duracao, z = +$("#zoom").value;
  $("#tlin").style.width = (z * 100) + "%";
  $("#tr-v").style.backgroundImage = `url(/job/${ID}/arquivo/tira.jpg)`;
  $("#tr-a").style.backgroundImage = `url(/job/${ID}/arquivo/onda.png)`;
  const largura = $("#tl").clientWidth * z, passos = [1,2,5,10,15,30,60,120,300,600,900,1800];
  const passo = passos.find(p => largura / (dur / p) > 70) || 3600;
  let r = ""; for (let t = 0; t < dur; t += passo) r += `<span style="left:${t / dur * 100}%">${mmss(t).replace(/\.0$/, "")}</span>`;
  $("#regua").innerHTML = r;
  const pct = (a, b) => `left:${a / dur * 100}%;width:${Math.max(0.15, (b - a) / dur * 100)}%`;
  let mk = "", sb = "";
  if (J.usar_silencios !== false) (J.silencios || []).forEach(s => { mk += `<span class="mk silencio" style="${pct(s.t0, s.t1)}"></span>`; sb += `<span class="sombra silencio" style="${pct(s.t0, s.t1)}"></span>`; });
  (J.cortes || []).forEach(c => {
    mk += `<span class="mk ${c.tipo} ${c.ativo ? "" : "off"} ${sel === c.id ? "sel" : ""}" data-id="${c.id}" style="${pct(c.t0, c.t1)}" title="${esc(c.texto)}"></span>`;
    if (c.ativo) sb += `<span class="sombra" style="${pct(c.t0, c.t1)}"></span>`;
  });
  $("#tr-cortes").innerHTML = `<span class="nome">Cortes</span>` + mk;
  $("#sombras").innerHTML = sb;
  $$("#tr-cortes .mk[data-id]").forEach(m => m.onclick = e => { e.stopPropagation(); selecionar(m.dataset.id, true); });
}
$("#tlin").onclick = e => {
  if (!J.midia || fonte === "final") return;
  const r = $("#tlin").getBoundingClientRect();
  v.currentTime = Math.max(0, (e.clientX - r.left) / r.width * J.midia.duracao);
};
$("#zoom").oninput = () => timeline();
const ro = new ResizeObserver(() => J && timeline()); ro.observe($("#tl"));

function selecionar(id, rolar) {
  sel = id;
  const c = J.cortes.find(x => x.id === id);
  if (c) { if (fonte === "final") fonte = "original", fonteVideo(); v.currentTime = Math.max(0, c.t0 - 1.5); }
  timeline(); listaCortes();
  if (rolar) { abrir("cortes"); const el = document.querySelector(`.item[data-id="${id}"]`); el && el.scrollIntoView({block: "nearest", behavior: "smooth"}); }
}

/* ---------------- painel de cortes */
function listaCortes() {
  const el = $("#aba-cortes");
  if (!J.cortes) { el.innerHTML = `<p class="mu">Os cortes aparecem aqui depois da análise.</p>`; return; }
  const sil = J.silencios || [], tsil = sil.reduce((s, x) => s + x.t1 - x.t0, 0);
  let h = `<div class="linha"><span><b>Pausas longas</b><br><span class="mu" style="font-size:12px">${sil.length} trechos · ${tsil.toFixed(0)} s</span></span>
    <label class="chave"><input type="checkbox" id="ch-sil" ${J.usar_silencios !== false ? "checked" : ""}><i></i></label></div>
    <div class="titulo-sec">${J.cortes.length} cortes · ligado = sai do vídeo</div>`;
  J.cortes.forEach((c, i) => {
    h += `<div class="item ${c.ativo ? "" : "off"} ${sel === c.id ? "sel" : ""}" data-id="${c.id}">
      <span class="n">${i + 1}</span>
      ${c.quadro ? `<img src="/job/${ID}/arquivo/quadros/${c.quadro}" alt="" loading="lazy">` : `<span style="width:76px;aspect-ratio:16/9;border-radius:10px;background:var(--c3);display:grid;place-items:center;color:var(--azul);font-size:18px">✂</span>`}
      <span class="t"><small>${mmss(c.t0)}–${mmss(c.t1)}<br><span style="color:${c.tipo === "chamada" ? "var(--rosa)" : c.tipo === "manual" ? "var(--azul)" : "var(--amar)"}">${esc(c.categoria || CAT[c.tipo] || c.tipo)}</span></small><q>${esc(c.texto)}</q></span>
      <label class="chave" onclick="event.stopPropagation()"><input type="checkbox" data-c="${c.id}" ${c.ativo ? "checked" : ""}><i></i></label></div>`;
  });
  if (!J.cortes.length) h += `<p class="mu">Nenhuma chamada encontrada. Peça cortes ao Rigel, ex.: “corta de 01:20 a 01:35”.</p>`;
  el.innerHTML = h;
  $("#ch-sil").onchange = e => salvar({usar_silencios: e.target.checked});
  $$("#aba-cortes .item").forEach(it => it.onclick = () => selecionar(it.dataset.id));
  $$("#aba-cortes input[data-c]").forEach(x => x.onchange = () => salvar({id: x.dataset.c, ativo: x.checked}));
}
async function salvar(d) { const r = await api(`/api/job/${ID}/corte`, d); if (r) { J = r; desenhar(); } }

/* ---------------- ajustes */
function ajustes() {
  const el = $("#aba-ajustes");
  el.innerHTML = `<div class="titulo-sec">Cor</div><div class="opcoes">${LOOKS.map(([k, n, g]) =>
      `<button class="op ${J.look === k ? "on" : ""}" data-look="${k}"><div class="amostra" style="background:${g}"></div><b>${n}</b></button>`).join("")}</div>
    <div class="titulo-sec">Saída</div><div class="opcoes duas">
      <button class="op ${J.destino !== "youtube" ? "on" : ""}" data-dest="playout"><b>Playout Órion</b><span>1080p25 · −23 LUFS</span></button>
      <button class="op ${J.destino === "youtube" ? "on" : ""}" data-dest="youtube"><b>YouTube</b><span>1080p25 · −14 LUFS</span></button></div>
    <div class="titulo-sec">Sempre aplicado</div>
    <p class="mu" style="font-size:13px;margin:0">Voz tratada (passa-alta, redução de ruído, compressor), punch-in de 110% alternado nos cortes de chamada para disfarçar o salto, 1080p 25 fps.</p>
    <p class="mu" style="font-size:12px">O look Docu-reality ainda precisa da sua aprovação num vídeo real.</p>`;
  $$("[data-look]").forEach(b => b.onclick = () => salvar({look: b.dataset.look}));
  $$("[data-dest]").forEach(b => b.onclick = () => salvar({destino: b.dataset.dest}));
}

/* ---------------- exportar */
function exportar() {
  const el = $("#aba-exportar"), arq = n => `/job/${ID}/arquivo/${n}`;
  if (!J.saida) { el.innerHTML = `<p class="mu">Renderize primeiro. Aqui saem o vídeo final e os projetos editáveis para Filmora, CapCut, DaVinci e Premiere.</p>`; return; }
  const linha = (cor, ic, t, d, botao) => `<div class="exp"><span class="ic" style="background:${cor}">${ic}</span><span class="tx"><b>${t}</b>${d}</span>${botao}</div>`;
  const cl = J.clipes;
  const botaoClipes = cl === "pronto" ? `<a class="btn" href="${arq("rigel_clipes_capcut.zip")}" download>Baixar</a>`
    : (cl === "gerando" || cl === "fila") ? `<span class="pilula azul">${J.progresso_clipes || 0}%</span>` : `<button class="btn sec" id="bt-clipes">Gerar</button>`;
  el.innerHTML =
    `<div class="titulo-sec">Vídeo pronto</div>` +
    linha("var(--lima);color:#141a05", "MP4", "Vídeo final", `<span class="mu">${mmss(J.duracao_final)} · ${J.destino === "youtube" ? "YouTube" : "Playout Órion"}</span>`, `<a class="btn" href="${arq(J.saida)}" download>Baixar</a>`) +
    linha("var(--c3)", "SRT", "Legenda do vídeo editado", `<span class="mu">Já no tempo dos cortes</span>`, `<a class="btn sec" href="${arq("rigel_legenda.srt")}" download>Baixar</a>`) +
    `<div class="titulo-sec" style="margin-top:16px">Continuar em outro editor</div>` +
    linha("var(--azul)", "XML", "Filmora · DaVinci · Premiere", `<span class="mu">Timeline com os cortes. Ao abrir, aponte para o vídeo original.</span>`, `<a class="btn sec" href="${arq("rigel_filmora_davinci_premiere.xml")}" download>XML</a>`) +
    linha("var(--rosa)", "ZIP", "CapCut", `<span class="mu">Clipes numerados 001, 002… Arraste todos, em ordem, para a timeline.</span>`, botaoClipes) +
    linha("var(--c3)", "EDL", "DaVinci (EDL)", `<span class="mu">Alternativa ao XML</span>`, `<a class="btn sec" href="${arq("rigel_davinci.edl")}" download>EDL</a>`) +
    linha("var(--c3)", "SRC", "Vídeo original", `<span class="mu">Necessário para religar o XML/EDL</span>`, `<a class="btn sec" href="/job/${ID}/original?baixar=1" download>Baixar</a>`) +
    `<details style="margin-top:8px"><summary class="mu" style="cursor:pointer;font-size:13px">Como abrir em cada editor</summary><p class="mu" style="font-size:13px">
      <b>Filmora:</b> Arquivo → Importar → Importar arquivo XML; se pedir mídia, aponte para o vídeo original.<br>
      <b>DaVinci Resolve:</b> File → Import → Timeline → escolha o XML (ou o EDL).<br>
      <b>Premiere:</b> Arquivo → Importar → o XML.<br>
      <b>CapCut:</b> descompacte o ZIP, selecione os clipes em ordem e arraste para a timeline.</p></details>`;
  const b = $("#bt-clipes"); if (b) b.onclick = async () => { const r = await api(`/api/job/${ID}/clipes`, {}); if (r) { J = r; desenhar(); } };
}

/* ---------------- Rigel (chat) */
const CHIPS = {rapido: ["ajuda", "lista", "sem pausas", "corta os primeiros 10 segundos", "mantém todas as chamadas", "desfaz", "renderiza"],
               ia: ["Tem mais alguma chamada que você não marcou?", "Deixa o começo mais curto", "Resume o vídeo em 3 frases"]};
function chat() {
  const m = (J.chat || []).map(x => `<div class="msg ${x.de} ${x.modo === "ia" ? "ia" : ""}">${esc(x.texto)}${x.uso ? `<span class="uso">${esc(x.uso.modelo)} · ${x.uso.entrada}+${x.uso.saida} tokens cobrados na sua conta</span>` : ""}</div>`).join("");
  const box = $("#msgs"), fim = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  if (box.dataset.n != (J.chat || []).length) { box.innerHTML = m || `<div class="msg rigel">Oi! Eu sou o Rigel. Escreva “ajuda” para ver o que eu entendo.</div>`; box.dataset.n = (J.chat || []).length; if (fim || true) box.scrollTop = box.scrollHeight; }
}
function chips() { $("#chips").innerHTML = CHIPS[modo].map(c => `<button type="button">${esc(c)}</button>`).join(""); $$("#chips button").forEach(b => b.onclick = () => enviar(b.textContent)); }
function trocarModo(m) {
  modo = m;
  $$(".modo button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
  const av = $("#aviso-ia");
  if (m === "ia") {
    av.hidden = false;
    av.innerHTML = RIGEL.temIA ? `Conversa com IA ligada: cada mensagem é cobrada na <b>sua</b> conta ${esc(RIGEL.iaNome)}. Para voltar ao grátis, toque em “Comandos”.`
      : `Para conversar com IA, configure a <b>sua própria</b> chave em <a href="/config" style="text-decoration:underline">Configurações</a>. O custo cai na conta de quem configurar.`;
    $("#modo-legenda").textContent = "Conversa com IA · paga";
    $("#txt").placeholder = "Peça em linguagem livre…";
  } else {
    av.hidden = true; $("#modo-legenda").textContent = "Comandos rápidos · grátis"; $("#txt").placeholder = "Ex.: corta de 02:10 a 02:30";
  }
  chips();
}
$$(".modo button").forEach(b => b.onclick = () => trocarModo(b.dataset.m));
async function enviar(texto) {
  texto = (texto || "").trim(); if (!texto || !J.midia) return;
  if (modo === "ia" && !RIGEL.temIA) { trocarModo("ia"); return; }
  $("#txt").value = "";
  J.chat = [...(J.chat || []), {de: "voce", modo, texto}, {de: "rigel", modo, texto: modo === "ia" ? "Pensando…" : "…"}]; chat();
  const r = await api(`/api/job/${ID}/mensagem`, {texto, modo}); if (r) { J = r; desenhar(); }
}
$("#form-msg").onsubmit = e => { e.preventDefault(); enviar($("#txt").value); };
$("#txt").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar($("#txt").value); } };

/* ---------------- abas (desktop e celular) */
function abrir(aba) {
  $$(".esq .abas button").forEach(b => b.classList.toggle("on", b.dataset.aba === aba));
  ["cortes", "ajustes", "exportar"].forEach(a => $("#aba-" + a).hidden = a !== aba);
  if (matchMedia("(max-width:900px)").matches) celular(aba);
}
function celular(p) {
  $$("#abas-cel button").forEach(b => b.classList.toggle("on", b.dataset.p === p));
  $("#p-rigel").classList.toggle("mostra", p === "rigel");
  $("#p-esq").classList.toggle("mostra", p !== "rigel");
  if (p !== "rigel") { ["cortes", "ajustes", "exportar"].forEach(a => $("#aba-" + a).hidden = a !== p); }
}
$$(".esq .abas button").forEach(b => b.onclick = () => abrir(b.dataset.aba));
$$("#abas-cel button").forEach(b => b.onclick = () => celular(b.dataset.p));
$("#bt-render").onclick = async () => { const r = await api(`/api/job/${ID}/renderizar`, {}); if (r) { J = r; desenhar(); } };

trocarModo("rapido");
atualizar();
}
