// Portal del cliente: tres pasos para pedir el transporte y un seguimiento en vivo (sondeo cada 2 s).
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hoja = $("#hoja");

const PRIORIDADES = {
  Tiempo: ["Lo más rápido", "Que llegue cuanto antes"],
  Costo: ["Lo más barato", "El menor costo posible"],
  "Carga crítica": ["Carga delicada", "Que llegue seguro, aunque cueste más"],
  Equilibrado: ["Equilibrado", "Un balance entre costo, tiempo y seguridad"],
};
const PLAZOS = [24, 36, 48, 72, 96];
const PASOS = ["Qué y por dónde", "Cuándo", "Tus datos"];

const S = {
  paso: 0, catalogo: null, enviado: null, error: "", enviando: false, timer: null,
  d: { origen: "", destino: "", tipo_carga: "", unidades: 1, peso_t: 20, fecha: "", plazo_horas: 48, plazoOtro: false, prioridad: "Equilibrado", presupuesto: "", contacto: "", empresa: "", email: "", notas: "" },
  errores: {},
};
const fmtFecha = (iso) => { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; };

// ---------------------------------------------------------------- validación por paso
function validar(paso) {
  const d = S.d, e = {};
  if (paso === 0) {
    if (!d.origen) e.origen = "Elige de dónde sale la carga.";
    if (!d.destino) e.destino = "Elige a dónde llega.";
    if (d.origen && d.origen === d.destino) e.destino = "El destino debe ser distinto del origen.";
    if (!d.tipo_carga) e.tipo_carga = "Elige el tipo de carga.";
    if (!(d.unidades >= 1)) e.unidades = "Pide al menos una unidad.";
  } else if (paso === 1) {
    if (!d.fecha) e.fecha = "Elige el día de cargue.";
    else if (d.fecha < S.catalogo.hoy) e.fecha = `El cargue no puede ser antes de hoy (${fmtFecha(S.catalogo.hoy)}).`;
    if (!(Number(d.plazo_horas) > 0)) e.plazo_horas = "Escribe en cuántas horas debe llegar.";
  } else if (paso === 2) {
    if (!d.contacto.trim()) e.contacto = "Dinos quién pide.";
    if (d.email && !/^\S+@\S+\.\S+$/.test(d.email)) e.email = "Revisa el correo.";
  }
  S.errores = e;
  return !Object.keys(e).length;
}
const err = (k) => (S.errores[k] ? `<p class="error" id="e-${k}" role="alert">${esc(S.errores[k])}</p>` : "");
const inv = (k) => (S.errores[k] ? `aria-invalid="true" aria-describedby="e-${k}"` : "");

// ---------------------------------------------------------------- vistas
const progreso = () => `<ol class="progreso" aria-label="Pasos del pedido">${PASOS.map((p, i) => `<li data-estado="${i < S.paso ? "hecho" : i === S.paso ? "actual" : "futuro"}" ${i === S.paso ? 'aria-current="step"' : ""}>${i + 1}. ${p}</li>`).join("")}</ol>`;
const opciones = (lista, v, ph) => `<option value="">${ph}</option>` + lista.map((x) => `<option ${x === v ? "selected" : ""}>${esc(x)}</option>`).join("");

function paso0() {
  const d = S.d, c = S.catalogo;
  const carga = c.tipos_carga.find((t) => t.nombre === d.tipo_carga);
  return `<div><h2>¿Qué mueves y por dónde?</h2><p class="sub">Tres datos y seguimos.</p></div>
  <div class="dos-col">
    <div class="campo"><label for="origen">Sale de</label><select id="origen" data-k="origen" ${inv("origen")}>${opciones(c.ciudades, d.origen, "Elige una ciudad")}</select>${err("origen")}</div>
    <div class="campo"><label for="destino">Llega a</label><select id="destino" data-k="destino" ${inv("destino")}>${opciones(c.ciudades, d.destino, "Elige una ciudad")}</select>${err("destino")}</div>
  </div>
  <div class="campo"><label for="tipo_carga">Tipo de carga</label><select id="tipo_carga" data-k="tipo_carga" ${inv("tipo_carga")}>${opciones(c.tipos_carga.map((t) => t.nombre), d.tipo_carga, "Elige el tipo de carga")}</select>
    ${carga?.certificacion ? `<p class="ayuda">Este tipo de carga exige un transportista con la certificación «${esc(carga.certificacion)}». Nosotros lo tenemos en cuenta.</p>` : ""}${err("tipo_carga")}</div>
  <div class="dos-col">
    <div class="campo"><span class="etq" id="l-unidades">Cuántas unidades</span>
      <div class="cantidad" role="group" aria-labelledby="l-unidades"><button type="button" data-mas="-1" aria-label="Una menos">−</button><input id="unidades" data-k="unidades" type="number" min="1" max="10" value="${d.unidades}" aria-label="Unidades"><button type="button" data-mas="1" aria-label="Una más">+</button></div>
      <p class="ayuda">Contenedores o viajes.</p>${err("unidades")}</div>
    <div class="campo"><label for="peso">Peso aproximado (toneladas)</label><input id="peso" data-k="peso_t" type="number" min="0" step="0.5" value="${d.peso_t}"><p class="ayuda">Opcional.</p></div>
  </div>
  <div class="acciones"><span></span><button class="btn primary" type="submit">Continuar</button></div>`;
}

function paso1() {
  const d = S.d;
  return `<div><h2>¿Para cuándo?</h2><p class="sub">El día que cargamos y en cuánto tiempo debe llegar.</p></div>
  <div class="campo"><label for="fecha">Día de cargue</label><input id="fecha" data-k="fecha" type="date" min="${S.catalogo.hoy}" value="${d.fecha}" ${inv("fecha")}>${err("fecha")}</div>
  <div class="campo"><span class="etq" id="l-plazo">Tiempo máximo de entrega</span>
    <div class="opciones" role="radiogroup" aria-labelledby="l-plazo">${PLAZOS.map((h) => `<label class="opc"><input type="radio" name="plazo" value="${h}" ${!d.plazoOtro && Number(d.plazo_horas) === h ? "checked" : ""}><span>${h} horas</span></label>`).join("")}
      <label class="opc"><input type="radio" name="plazo" value="otro" ${d.plazoOtro ? "checked" : ""}><span>Otro</span></label></div>
    ${d.plazoOtro ? `<input id="plazo_otro" data-k="plazo_horas" type="number" min="1" value="${d.plazo_horas}" aria-label="Horas máximas de entrega" style="max-width:160px" ${inv("plazo_horas")}>` : ""}${err("plazo_horas")}</div>
  <div class="campo"><span class="etq" id="l-prio">Qué es lo más importante</span>
    <div class="prio" role="radiogroup" aria-labelledby="l-prio">${S.catalogo.prioridades.map((p) => `<label class="opc"><input type="radio" name="prioridad" value="${esc(p)}" ${d.prioridad === p ? "checked" : ""}><span><b>${PRIORIDADES[p]?.[0] ?? esc(p)}</b><small>${PRIORIDADES[p]?.[1] ?? ""}</small></span></label>`).join("")}</div></div>
  <div class="campo"><label for="presupuesto">Presupuesto máximo (COP)</label><input id="presupuesto" data-k="presupuesto" type="number" min="0" step="100000" value="${d.presupuesto}" placeholder="Opcional"><p class="ayuda">Si lo escribes, no recomendaremos a quien lo supere.</p></div>
  <div class="acciones"><button class="btn" type="button" data-atras>Atrás</button><button class="btn primary" type="submit">Continuar</button></div>`;
}

function paso2() {
  const d = S.d, c = S.catalogo;
  const filas = [["Ruta", `${d.origen} a ${d.destino}`], ["Carga", `${d.unidades} × ${d.tipo_carga}`], ["Cargue", fmtFecha(d.fecha)], ["Entrega máxima", `${d.plazo_horas} horas`], ["Lo más importante", PRIORIDADES[d.prioridad]?.[0] ?? d.prioridad], ...(d.presupuesto ? [["Presupuesto", `COP ${Number(d.presupuesto).toLocaleString("es-CO")}`]] : [])];
  return `<div><h2>Tus datos y confirmación</h2><p class="sub">Revisa el pedido y dinos a quién escribirle.</p></div>
  <div class="resumen">${filas.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join("")}</div>
  <div class="dos-col">
    <div class="campo"><label for="contacto">Tu nombre</label><input id="contacto" data-k="contacto" type="text" autocomplete="name" value="${esc(d.contacto)}" ${inv("contacto")}>${err("contacto")}</div>
    <div class="campo"><label for="empresa">Empresa</label><input id="empresa" data-k="empresa" type="text" autocomplete="organization" value="${esc(d.empresa)}"></div>
  </div>
  <div class="campo"><label for="email">Correo</label><input id="email" data-k="email" type="email" autocomplete="email" value="${esc(d.email)}" ${inv("email")}>${err("email")}</div>
  <div class="campo"><label for="notas">Algo más que debamos saber</label><textarea id="notas" data-k="notas" rows="3">${esc(d.notas)}</textarea></div>
  ${S.error ? `<p class="error" role="alert">${esc(S.error)}</p>` : ""}
  <div class="acciones"><button class="btn" type="button" data-atras>Atrás</button><button class="btn primary" type="submit" ${S.enviando ? "disabled" : ""}>${S.enviando ? "Enviando…" : "Enviar solicitud"}</button></div>`;
}

function seguimiento() {
  const e = S.enviado, d = S.d;
  const detalle = ["Ya la tenemos. Un equipo logístico la va a revisar.", "Estamos comparando transportistas para tu envío.", "Ya hay un transportista asignado.", "Tu carga va en camino.", "Servicio cerrado."];
  return `<div class="seguimiento"><div><p class="sub" style="margin:0 0 4px">Solicitud recibida</p><p class="codigo num">${esc(e.codigo)}</p>
      <p class="sub">${esc(d.origen)} a ${esc(d.destino)} · ${d.unidades} × ${esc(d.tipo_carga)} · cargue ${fmtFecha(d.fecha)}</p></div>
    <ol class="est-vivo" aria-label="Estado de la solicitud" aria-live="polite">${e.pasos.map((p, i) => `<li data-estado="${i < e.indice ? "hecho" : i === e.indice ? "actual" : "futuro"}" ${i === e.indice ? 'aria-current="step"' : ""}><span>${p}${i === e.indice ? `<small>${detalle[i]}</small>` : ""}</span></li>`).join("")}</ol>
    <div class="acciones"><span class="sub" style="margin:0">Esta página se actualiza sola.</span><button class="btn" type="button" data-otra>Hacer otra solicitud</button></div></div>`;
}

function pintar() {
  if (!S.catalogo) { hoja.innerHTML = `<p class="sub">Cargando…</p>`; return; }
  if (S.enviado) { hoja.innerHTML = seguimiento(); return; }
  hoja.innerHTML = `${progreso()}<form novalidate id="form">${[paso0, paso1, paso2][S.paso]()}</form>`;
  const foco = hoja.querySelector('[aria-invalid="true"]'); if (foco) foco.focus();
}

// ---------------------------------------------------------------- eventos
hoja.addEventListener("input", (ev) => {
  const t = ev.target, k = t.dataset.k;
  if (!k) return;
  S.d[k] = t.type === "number" ? (t.value === "" ? "" : Number(t.value)) : t.value;
  if (k === "plazo_horas") S.d.plazoOtro = true;
});
hoja.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.name === "plazo") { S.d.plazoOtro = t.value === "otro"; if (!S.d.plazoOtro) S.d.plazo_horas = Number(t.value); pintar(); $(S.d.plazoOtro ? "#plazo_otro" : "#form")?.focus?.(); }
  else if (t.name === "prioridad") S.d.prioridad = t.value;
  else if (t.dataset.k === "tipo_carga" || t.dataset.k === "origen" || t.dataset.k === "destino") { S.d[t.dataset.k] = t.value; S.errores = {}; pintar(); document.getElementById(t.id)?.focus(); }
});
hoja.addEventListener("click", (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  if (b.dataset.mas) { S.d.unidades = Math.min(10, Math.max(1, Number(S.d.unidades || 1) + Number(b.dataset.mas))); pintar(); }
  else if (b.hasAttribute("data-atras")) { S.paso = Math.max(0, S.paso - 1); S.errores = {}; pintar(); }
  else if (b.hasAttribute("data-otra")) reiniciar();
});
hoja.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!validar(S.paso)) { pintar(); return; }
  if (S.paso < 2) { S.paso += 1; S.errores = {}; pintar(); window.scrollTo({ top: 0 }); return; }
  S.enviando = true; S.error = ""; pintar();
  const d = S.d;
  try {
    const r = await fetch("/api/solicitudes", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
      contacto: d.contacto.trim(), empresa: d.empresa || null, email: d.email || null, origen: d.origen, destino: d.destino, tipo_carga: d.tipo_carga,
      unidades: Number(d.unidades), peso_t: Number(d.peso_t) || 0, fecha: d.fecha, plazo_horas: Number(d.plazo_horas), prioridad: d.prioridad,
      presupuesto_cop: d.presupuesto ? Number(d.presupuesto) : null, notas: d.notas || null }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "No pudimos enviar la solicitud.");
    S.enviado = j; S.enviando = false; pintar(); window.scrollTo({ top: 0 });
    sondear();
  } catch (e) { S.enviando = false; S.error = e.message; pintar(); }
});

function sondear() {
  clearInterval(S.timer);
  S.timer = setInterval(async () => {
    try {
      const r = await fetch(`/api/solicitudes/${S.enviado.id}`);
      if (!r.ok) return;
      const nuevo = await r.json();
      if (nuevo.indice !== S.enviado.indice) { S.enviado = nuevo; pintar(); }
    } catch { /* se reintenta en 2 s */ }
  }, 2000);
}
function reiniciar() {
  clearInterval(S.timer);
  S.enviado = null; S.paso = 0; S.error = ""; S.errores = {};
  S.d = { ...S.d, origen: "", destino: "", tipo_carga: "", unidades: 1, peso_t: 20, fecha: "", plazo_horas: 48, plazoOtro: false, prioridad: "Equilibrado", presupuesto: "", notas: "" };
  pintar();
}

(async function () {
  pintar();
  try { S.catalogo = await (await fetch("/api/catalogo")).json(); } catch { hoja.innerHTML = `<p class="error" role="alert">No pudimos cargar el portal. Intenta de nuevo en un momento.</p>`; return; }
  pintar();
})();
