// Copiloto: explica y simula con las funciones del motor; nunca asigna. Respuestas de 4 líneas como máximo,
// con el dato citado y, cuando corresponde, un botón que modifica el dashboard.
import { Api } from "./api.js";
import { esc, cop, pct0, pct, dec, sinTildes, corto } from "./fmt.js";
import { sacrificios, nombreDe } from "./componentes.js";

const $ = (s) => document.querySelector(s);
const NUM = { un: 1, uno: 1, una: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5 };
const MESES = { enero: 1, febrero: 2, marzo: 3, abril: 4, mayo: 5, junio: 6, julio: 7, agosto: 8, septiembre: 9, octubre: 10, noviembre: 11, diciembre: 12 };
const CARGAS = [
  [/refrigerad|reefer|cadena de frio|\bfrio\b/, "Contenedor refrigerado"],
  [/peligros|\bimo\b/, "Mercancía peligrosa (IMO)"],
  [/granel/, "Granel líquido"],
  [/extradimension|sobredimension/, "Carga extradimensionada"],
  [/paletiz|carga suelta/, "Carga suelta / paletizada"],
  [/alto valor/, "Alto valor"],
  [/contenedor|\bseco/, "Contenedor seco"],
];
const ESTADO_TXT = {
  reposo: "En reposo. Explica y simula; no asigna.",
  pensando: "Pensando…",
  alerta: "Hay algo que conviene mirar.",
  no_sabe: "No tengo ese dato.",
};

export function crearCopiloto(ctx) {
  const S = ctx.estado;
  const mensajes = [];
  let estadoVisual = "reposo";
  let inicial = false;

  const btn = $("#abrir-copiloto"), panel = $("#panel-copiloto"), cuerpo = $("#pc-body"), input = $("#pc-input");

  function avatar(e) {
    estadoVisual = e;
    for (const el of [$("#av-panel"), btn.querySelector(".av")]) el.dataset.estado = e;
    $("#av-estado-txt").textContent = ESTADO_TXT[e];
  }
  function abrir(v) {
    panel.dataset.open = String(v);
    btn.setAttribute("aria-expanded", String(v));
    if (v) {
      if (!inicial) { inicial = true; resumenInicial(); }
      input.focus();
    } else btn.focus();
  }
  btn.onclick = () => abrir(panel.dataset.open !== "true");
  $("#cerrar-copiloto").onclick = () => abrir(false);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.dataset.open === "true") abrir(false); });

  // ------------------------------------------------ utilidades de datos
  const eq = () => S.data?.estrategias?.equilibrada;
  const rankeados = () => S.data?.respuesta?.ranking ?? [];
  const descartados = () => S.data?.respuesta?.descartados ?? [];
  const sol = () => S.data?.respuesta?.solicitud ?? S.solicitud;
  const STOP = new Set(["carga", "colombia", "express", "transportes", "logistica", "nacional", "unidos", "norte", "valle", "pacifico", "freight", "trucking", "s.a.s."]);
  function nombrar(q) {
    const nq = sinTildes(q);
    const todos = [...new Set([...rankeados().map((o) => o.proveedor), ...descartados().map((d) => d.proveedor)])];
    let mejor = null, largo = 0;
    for (const n of todos) {
      for (const t of sinTildes(n).split(/\s+/)) {
        if (t.length >= 4 && !STOP.has(t) && nq.includes(t) && t.length > largo) { mejor = n; largo = t.length; }
      }
    }
    return mejor;
  }
  const estrategiaDe = (q) => {
    const nq = sinTildes(q);
    if (/economic|barat/.test(nq)) return "economica";
    if (/confiable/.test(nq)) return "confiable";
    if (/equilibrad/.test(nq)) return "equilibrada";
    return null;
  };
  const opcionDe = (nombre) => rankeados().find((o) => o.proveedor === nombre) ?? null;
  const motivoDescarte = (nombre) => descartados().find((d) => d.proveedor === nombre);

  // ------------------------------------------------ mensajes
  function pintarMensajes() {
    cuerpo.innerHTML = mensajes.map((m, i) => {
      if (m.rol === "yo") return `<div class="msg yo"><p>${esc(m.texto)}</p></div>`;
      if (m.pensando) return `<div class="msg ia"><p class="muted">Pensando…</p></div>`;
      return `<div class="msg ia">${m.html ?? m.lineas.slice(0, 4).map((l) => `<p>${esc(l)}</p>`).join("")}
        ${m.fuente ? `<span class="fuente">${esc(m.fuente)}</span>` : ""}${m.nota ? `<span class="nota">${esc(m.nota)}</span>` : ""}
        ${m.accion ? `<button class="btn small accion" type="button" data-i="${i}">${esc(m.accion.etiqueta)}</button>` : ""}</div>`;
    }).join("");
    cuerpo.scrollTop = cuerpo.scrollHeight;
  }
  cuerpo.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]");
    if (b) ejecutar(mensajes[Number(b.dataset.i)].accion);
  });
  function ejecutar(a) {
    const A = ctx.acciones;
    if (a.tipo === "excluir") A.excluir(a.payload.proveedor, "excluido desde el Copiloto");
    else if (a.tipo === "tab") A.tab(a.payload);
    else if (a.tipo === "solicitud") A.solicitud(a.payload);
    else if (a.tipo === "crear") A.crear(a.payload).catch(() => {});
    else if (a.tipo === "prioridad") A.prioridad(a.payload);
    abrir(false);
  }

  // ------------------------------------------------ resumen y sugeridas
  function resumenInicial() {
    const r = S.data?.respuesta;
    if (!r) { mensajes.push({ rol: "ia", lineas: ["Todavía no hay una solicitud calculada."], estado: "reposo" }); pintarMensajes(); return; }
    const lineas = [];
    let nota = "";
    if (r.sin_opcion) {
      const lib = r.descartados.find((d) => /libre/i.test(d.motivo));
      if (lib) lineas.push(`Ojo: ${lib.proveedor} ${lib.motivo}.`);
      if (r.carga_dividida) lineas.push(`Si divides la carga, el éxito conjunto es ${pct(r.carga_dividida.p_exito_conjunta)}.`);
      lineas.push("Nadie cumple solo. No cambio nada por mi cuenta.");
    } else {
      const med = Object.values(S.data.estrategias).filter((o) => o.semaforo !== "verde");
      if (med.length) med.slice(0, 3).forEach((o) => lineas.push(`${corto(o.proveedor)} (${nombreDe(o).toLowerCase()}): ${o.senales[0] ?? "riesgo " + o.semaforo}.`));
      else lineas.push("Las tres opciones están en verde. No veo nada que te frene.");
      nota = "Decides tú; yo explico y simulo.";
    }
    mensajes.push({ rol: "ia", lineas, nota, fuente: "Fuente: consultar_ranking", estado: "alerta" });
    pintarMensajes();
    avatar(alertas() ? "alerta" : "reposo");
  }
  const alertas = () => (!S.data || S.status !== "normal" ? 0 : S.data.respuesta.sin_opcion ? 1 : Object.values(S.data.estrategias).filter((o) => o.semaforo !== "verde").length);

  function sugeridas() {
    const el = $("#pc-sugeridas");
    el.innerHTML = "";
    if (!S.data || S.status !== "normal") return;
    const qs = [];
    if (S.data.respuesta.sin_opcion) qs.push("¿Qué restricción puedo relajar?", "¿Hay casos parecidos?");
    else {
      const seg = rankeados()[1];
      if (seg) qs.push(`¿Por qué no ${corto(seg.proveedor)}?`);
      if (eq()) qs.push(`¿Qué pasa si ${corto(eq().proveedor)} falla?`, "¿Hay casos parecidos?");
    }
    el.innerHTML = qs.map((q) => `<button class="preg" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  }
  $("#pc-sugeridas").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) preguntar(b.dataset.q); });

  // ------------------------------------------------ respuestas
  async function responder(q) {
    const nq = sinTildes(q);
    if (!S.data) return { lineas: ["Todavía no hay opciones calculadas; espera un momento."], estado: "no_sabe" };
    if (q.length > 70 && /\d/.test(q) && esCorreo(q)) return correo(q);

    const nombre = nombrar(q);
    if (/por ?que no|porque no/.test(nq) && nombre) {
      const d = motivoDescarte(nombre);
      if (d && !opcionDe(nombre)) return { lineas: [`${nombre} está descartado.`, d.motivo + "."], fuente: "Fuente: descartados del embudo", estado: "reposo" };
      const base = eq();
      if (!base) return sinOpcion();
      if (base.proveedor === nombre) return { lineas: [`${nombre} es la opción equilibrada preseleccionada.`], estado: "reposo" };
      const r = await Api.explicar(S.solicitud, ctx.requisitos(), base.proveedor, nombre);
      if (r.error) return { lineas: [r.error], estado: "no_sabe" };
      return { lineas: [r.texto, r.contrafactual].filter(Boolean), fuente: "Fuente: explicar_diferencia", accion: { tipo: "tab", payload: "porque", etiqueta: "Ver el desglose" }, estado: "reposo" };
    }
    if (/sacrific/.test(nq)) {
      const o = (nombre && opcionDe(nombre)) || S.data.estrategias[estrategiaDe(q)] || eq();
      if (!o) return sinOpcion();
      return { lineas: [`Con ${corto(o.proveedor)}:`, ...sacrificios(o, Object.values(S.data.estrategias))], fuente: "Fuente: comparación de las tres opciones", estado: "reposo" };
    }
    if (/falla|incumpl|no cumple|fallar/.test(nq)) {
      const o = (nombre && opcionDe(nombre)) || eq();
      if (!o) return sinOpcion();
      const r = await Api.simular(S.solicitud, ctx.requisitos(), { excluir: [o.proveedor] });
      const sig = r.top3_despues[0];
      const lineas = sig
        ? [`Si ${corto(o.proveedor)} falla, el primero pasa a ser ${corto(sig.proveedor)}.`, `Éxito ${pct0(sig.p_exito)} (antes ${pct0(o.p_exito)}) y costo esperado ${cop(sig.costo_esperado_cop)} (antes ${cop(o.costo_esperado_cop)}).`]
        : [`Si ${corto(o.proveedor)} falla, nadie más cumple solo.`];
      const m = await memoriaDe(o.proveedor);
      return { lineas, nota: m ? `Caso parecido, no es predicción: ${m}` : "", fuente: "Fuente: simular_cambio", accion: sig ? { tipo: "excluir", payload: { proveedor: o.proveedor }, etiqueta: `Excluir a ${corto(o.proveedor)} y ver el cambio` } : null, estado: "reposo" };
    }
    if (/compar/.test(nq)) {
      const a = (nombre && opcionDe(nombre)) || eq();
      const b = rankeados().find((o) => o.proveedor !== a?.proveedor);
      if (!a || !b) return sinOpcion();
      const r = await Api.explicar(S.solicitud, ctx.requisitos(), a.proveedor, b.proveedor);
      if (r.error) return { lineas: [r.error], estado: "no_sabe" };
      return { lineas: [r.texto, r.contrafactual].filter(Boolean), fuente: "Fuente: explicar_diferencia", accion: { tipo: "tab", payload: "experta", etiqueta: "Abrir comparador" }, estado: "reposo" };
    }
    if (/por ?que (esta|esa|es|la)|por que .*(equilibrad|economic|confiable)/.test(nq) || (/por ?que/.test(nq) && nombre)) {
      const o = (nombre && opcionDe(nombre)) || S.data.estrategias[estrategiaDe(q)] || eq();
      if (!o) return sinOpcion();
      return { lineas: [`${corto(o.proveedor)} sale con ${dec(o.puntaje)} puntos y ${pct0(o.p_exito)} de éxito.`, ...o.razones.map((x) => x[0].toUpperCase() + x.slice(1) + "."), o.senales[0] ? `Ojo: ${o.senales[0]}.` : ""].filter(Boolean), fuente: "Fuente: razones del motor", accion: { tipo: "tab", payload: "porque", etiqueta: "Ver el desglose" }, estado: o.semaforo === "verde" ? "reposo" : "alerta" };
    }
    if (/relaj|restriccion|flexibil|dividir|divido/.test(nq)) {
      const r = S.data.respuesta;
      if (r.sin_opcion && r.alternativas.length) {
        const a = r.alternativas.find((x) => x.cambio.fecha || x.cambio.plazo_horas) ?? r.alternativas[0];
        const lineas = r.alternativas.slice(0, 2).map((x) => `${x.descripcion}: ${pct0(x.p_exito_mejor)} de éxito.`);
        return { lineas, fuente: "Fuente: alternativas del motor", accion: a.cambio.fecha || a.cambio.plazo_horas ? { tipo: "solicitud", payload: { ...(a.cambio.fecha ? { fecha: a.cambio.fecha } : {}), ...(a.cambio.plazo_horas ? { plazo_horas: a.cambio.plazo_horas } : {}) }, etiqueta: "Aplicar la primera" } : null, estado: "alerta" };
      }
      const ex = Object.entries(S.chips).filter(([, v]) => v === "exijo").map(([k]) => k);
      return { lineas: ["Hoy ninguna condición te deja sin opción.", ex.length ? `Estás exigiendo: ${ex.join(", ")}.` : "No exiges nada además de las reglas fijas."], fuente: "Fuente: restricciones activas", estado: "reposo" };
    }
    if (/caso|parecid|pasado|antes|historia|memoria/.test(nq)) {
      const o = (nombre && opcionDe(nombre)) || eq();
      const m = await Api.memoria(o?.proveedor, sol().destino);
      if (!m.length) return { lineas: ["No tengo casos parecidos guardados."], estado: "no_sabe" };
      return { lineas: m.slice(0, 2).map((c) => `${c.fecha}: ${c.titulo}.`), nota: "Es historia, no una predicción.", fuente: "Fuente: memoria de casos", estado: "reposo" };
    }
    if (/urgente|rapido|cuanto antes/.test(nq)) return { lineas: ["Puedo poner el peso en tiempo."], accion: { tipo: "prioridad", payload: "Tiempo", etiqueta: "Priorizar rapidez" }, estado: "reposo" };
    if (/barato|economic|costo/.test(nq) && /prioriz|pon|cambia/.test(nq)) return { lineas: ["Puedo poner el peso en el costo."], accion: { tipo: "prioridad", payload: "Costo", etiqueta: "Priorizar costo" }, estado: "reposo" };
    return { lineas: ["No tengo ese dato.", "Puedo explicar una opción, comparar dos proveedores, simular una falla o buscar casos pasados."], estado: "no_sabe" };
  }
  const sinOpcion = () => ({ lineas: ["Ahora mismo nadie cumple solo, así que no hay una opción que explicar.", "Pregúntame qué restricción puedo relajar."], estado: "alerta" });
  async function memoriaDe(prov) {
    try { const m = await Api.memoria(prov, sol().destino); return m[0] ? `${m[0].fecha}, ${m[0].titulo}` : ""; } catch { return ""; }
  }

  // ------------------------------------------------ correo del cliente
  const esCorreo = (q) => (S.catalogo.ciudades.filter((c) => sinTildes(q).includes(sinTildes(c))).length >= 2);
  function correo(q) {
    const nq = sinTildes(q);
    const ciudades = S.catalogo.ciudades.map((c) => ({ c, i: nq.indexOf(sinTildes(c)) })).filter((x) => x.i >= 0).sort((a, b) => a.i - b.i);
    const hallados = [];
    const frase = (re) => { const m = q.match(re); return m ? m[0] : null; };
    const origenRe = new RegExp(`(?:desde|de|saliendo de)\\s+${ciudades[0].c}`, "i");
    hallados.push(["Origen", ciudades[0].c, frase(origenRe) ?? ciudades[0].c, { origen: ciudades[0].c }]);
    hallados.push(["Destino", ciudades[1].c, frase(new RegExp(`(?:a|hacia|para|hasta)\\s+${ciudades[1].c}`, "i")) ?? ciudades[1].c, { destino: ciudades[1].c }]);
    const carga = CARGAS.find(([re]) => re.test(nq));
    if (carga) hallados.push(["Carga", carga[1], frase(carga[0]) ?? carga[1], { tipo_carga: carga[1] }]);
    const mu = nq.match(/(\d+|un|una|dos|tres|cuatro|cinco)\s*(?:x\s*)?(?:contenedor|unidad|camion|tractomula|viaje)/);
    if (mu) hallados.push(["Unidades", mu[1], mu[0], { unidades: NUM[mu[1]] ?? Number(mu[1]) }]);
    const mh = nq.match(/(\d+)\s*(?:horas|hrs|h)\b/), md = nq.match(/(\d+)\s*dias?/);
    if (mh) hallados.push(["Plazo", `${mh[1]} h`, mh[0], { plazo_horas: Number(mh[1]) }]);
    else if (md) hallados.push(["Plazo", `${Number(md[1]) * 24} h`, md[0], { plazo_horas: Number(md[1]) * 24 }]);
    const mf = nq.match(/(\d{1,2})\s*de\s*(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)/) ;
    const mf2 = nq.match(/\b(\d{1,2})\/(\d{1,2})\b/);
    const f = mf ? [Number(mf[1]), MESES[mf[2]], mf[0]] : mf2 ? [Number(mf2[1]), Number(mf2[2]), mf2[0]] : null;
    if (f) hallados.push(["Cargue", `${String(f[0]).padStart(2, "0")}/${String(f[1]).padStart(2, "0")}`, f[2], { fecha: `2026-${String(f[1]).padStart(2, "0")}-${String(f[0]).padStart(2, "0")}` }]);
    if (/urgente|cuanto antes|lo antes posible/.test(nq)) hallados.push(["Prioridad", "Lo más rápido", frase(/urgente|cuanto antes|lo antes posible/i), { prioridad: "Tiempo" }]);
    else if (/economic|barato|menor costo/.test(nq)) hallados.push(["Prioridad", "Lo más barato", frase(/econ[oó]mic\w*|barat\w*|menor costo/i), { prioridad: "Costo" }]);
    else if (/delicad|critic|vacuna|farmac/.test(nq)) hallados.push(["Prioridad", "Carga crítica", frase(/delicad\w*|cr[ií]tic\w*|vacuna\w*|farmac\w*/i), { prioridad: "Carga crítica" }]);
    const falta = !hallados.some((h) => h[0] === "Plazo") ? "¿Cuál es la hora o el día límite de entrega?" : !hallados.some((h) => h[0] === "Cargue") ? "¿Qué día se carga?" : "";
    const payload = Object.assign({}, ...hallados.map((h) => h[3]));
    const html = `<p>Leí el correo y propongo esta solicitud. No creo nada hasta que confirmes.</p>
      <div class="chips-fuente">${hallados.map((h) => `<div><span class="chipf">${h[0]}: ${esc(h[1])}</span><q>${esc(h[2])}</q></div>`).join("")}</div>
      ${falta ? `<p>${esc(falta)}</p>` : ""}`;
    const completa = hallados.some((h) => h[0] === "Plazo") && hallados.some((h) => h[0] === "Cargue");
    const cuerpo = { tipo_carga: "Contenedor seco", unidades: 1, prioridad: "Equilibrado", ...payload, contacto: "Correo pegado en el Copiloto", notas: q.slice(0, 240) };
    return { html, accion: completa ? { tipo: "crear", payload: cuerpo, etiqueta: "Confirmar y crear la solicitud" } : null, fuente: "Fuente: texto del correo", estado: "reposo" };
  }

  // ------------------------------------------------ flujo
  async function preguntar(q) {
    abrirSiHaceFalta();
    mensajes.push({ rol: "yo", texto: q });
    mensajes.push({ rol: "ia", pensando: true });
    avatar("pensando");
    pintarMensajes();
    let r;
    try { r = await responder(q); } catch (e) { r = { lineas: ["No pude consultar el motor.", e.message], estado: "no_sabe" }; }
    mensajes.pop();
    mensajes.push({ rol: "ia", ...r });
    avatar(r.estado ?? "reposo");
    pintarMensajes();
  }
  function abrirSiHaceFalta() { if (panel.dataset.open !== "true") { inicial = true; abrir(true); } }
  $("#pc-form").addEventListener("submit", (e) => { e.preventDefault(); const v = input.value.trim(); if (v) { input.value = ""; preguntar(v); } });

  function actualizar() {
    const n = alertas();
    const dot = $("#n-alertas");
    dot.hidden = n === 0;
    dot.textContent = n;
    dot.setAttribute("aria-label", `${n} cosas por mirar`);
    if (estadoVisual !== "pensando") avatar(n ? "alerta" : "reposo");
    sugeridas();

  }
  return { preguntar, actualizar };
}
