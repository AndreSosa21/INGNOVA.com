// Dashboard del equipo logístico. Flujo: la solicitud llega del portal -> se abre -> se comparan 3 opciones -> la persona elige.
// Estado en un solo objeto; todo número viene del motor (cosco.motor.api vía /api).
import { Api } from "./api.js";
import { esc, cop, pct, pct0, horas, plazo, dec, num, fechaCorta, corto } from "./fmt.js";
import {
  ESTRATEGIAS, nombreDe, FACTORES, TarjetaOpcion, DetalleOpcion, ChipFactor, siguienteEstado, FiltroFijo, ListaDescartados, BarrasContribucion,
  DiferenciaPorFactor, Esqueleto, Estado, GraficoCostoP90, Pasos, SemaforoRiesgo,
} from "./componentes.js";
import { crearCopiloto } from "./copiloto.js";
import { GraficoMC, dibujarMC, CambioConfiabilidad, animarConfiabilidad } from "./simulacion.js";
import { crearGerencia } from "./gerencia.js";

const PRIORIDAD_TXT = { Tiempo: "Lo más rápido", Costo: "Lo más barato", "Carga crítica": "Carga delicada", Equilibrado: "Equilibrado" };
const CHIPS = [
  { clave: "tiempo", nombre: "Tiempo", factor: "tiempo" },
  { clave: "precio", nombre: "Precio", factor: "precio", param: { etiqueta: "Tope de costo P90 en COP", hint: "Tope COP", campo: "tope" } },
  { clave: "confiabilidad", nombre: "Confiabilidad", factor: "confiabilidad", param: { etiqueta: "Confiabilidad mínima en porcentaje", hint: "Mín. %", campo: "min" } },
  { clave: "incidentes", nombre: "Incidentes", factor: "historial", param: { etiqueta: "Días sin incidentes", hint: "Días", campo: "dias" } },
];
const chipsIniciales = () => ({ tiempo: "exijo", precio: "neutral", confiabilidad: "neutral", incidentes: "neutral" });

const S = {
  catalogo: null,
  bandeja: [], bandejaCargada: false, nuevos: new Set(), lista: "por_asignar",
  selId: null, base: null, solicitud: null,
  chips: chipsIniciales(), param: { tope: "", min: "90", dias: "90" }, excluidos: [],
  data: null, status: "vacio", forzado: "normal", error: "",
  asignado: null, decision: null, aviso: null, perfiles: new Map(), abiertos: new Set(), cajon: null,
  cierre: null, // formulario de cierre del servicio: { a_tiempo, tiempo, costo, dano, calif, err, enviando, resultado }
};
let abort = null;
const $ = (s) => document.querySelector(s);
const sheet = $("#sheet"), elLista = $("#lista"), elDetalle = $("#detalle"), elCajon = $("#cajon"), scrim = $("#scrim");

// ---------------------------------------------------------------- utilidades
const hace = (iso) => {
  if (!iso) return "";
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 1) return "ahora";
  if (min < 60) return `hace ${min} min`;
  if (min < 1440) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} d`;
};
const motorDe = (s) => ({ origen: s.origen, destino: s.destino, tipo_carga: s.tipo_carga, unidades: s.unidades, plazo_horas: s.plazo_horas, presupuesto_cop: s.presupuesto_cop, prioridad: s.prioridad, fecha: s.fecha });
const opciones = () => (S.data?.estrategias ? ["equilibrada", "economica", "confiable"].map((k) => S.data.estrategias[k]).filter(Boolean) : []);
const simulando = () => S.base && JSON.stringify(motorDe(S.base)) !== JSON.stringify(S.solicitud);

function requisitos() {
  const r = [], { chips: c, param: p } = S;
  if (c.tiempo === "exijo") r.push({ factor: "tiempo", tipo: "restriccion" });
  else if (c.tiempo === "prefiero") r.push({ factor: "tiempo", tipo: "preferencia", valor: "alta" });
  if (c.precio === "exijo" && Number(p.tope) > 0) r.push({ factor: "precio", tipo: "restriccion", valor: Number(p.tope) });
  else if (c.precio === "prefiero") r.push({ factor: "precio", tipo: "preferencia", valor: "alta" });
  if (c.confiabilidad === "exijo" && Number(p.min) > 0) r.push({ factor: "confiabilidad", tipo: "restriccion", valor: Number(p.min) });
  else if (c.confiabilidad === "prefiero") r.push({ factor: "confiabilidad", tipo: "preferencia", valor: "alta" });
  if (c.incidentes === "exijo" && Number(p.dias) > 0) r.push({ factor: "incidentes", tipo: "restriccion", valor: Number(p.dias) });
  else if (c.incidentes === "prefiero") r.push({ factor: "historial", tipo: "preferencia", valor: "alta" });
  for (const x of S.excluidos) r.push({ factor: "proveedor", tipo: "restriccion", valor: `excluir:${x.nombre}` });
  return r;
}

// ---------------------------------------------------------------- bandeja (llegan del portal)
async function cargarBandeja() {
  try {
    const nueva = await Api.bandeja();
    if (S.bandejaCargada) for (const s of nueva) if (!S.bandeja.some((x) => x.id === s.id)) S.nuevos.add(s.id);
    const cambio = JSON.stringify(nueva) !== JSON.stringify(S.bandeja);
    S.bandeja = nueva;
    S.bandejaCargada = true;
    if (cambio) { pintarLista(); copiloto?.actualizar(); }
  } catch { /* el siguiente sondeo reintenta */ }
}
const porAsignar = () => S.bandeja.filter((s) => s.estado_clave === "pendiente" || s.estado_clave === "en_analisis");
const asignadas = () => S.bandeja.filter((s) => s.estado_clave === "asignada" || s.estado_clave === "en_transito");
const cerradas = () => S.bandeja.filter((s) => s.estado_clave === "atendida");
const PASO = { pendiente: 0, en_analisis: 1, asignada: 2, en_transito: 3, atendida: 4 };
const SIGUIENTE = { asignada: "marcar la salida del vehículo", en_transito: "registrar cómo llegó" };

function pintarLista() {
  const items = { por_asignar: porAsignar, asignadas, cerradas }[S.lista]();
  const filas = items.map((s) => `<button class="fila-sol" type="button" data-act="abrir" data-id="${s.id}" aria-current="${s.id === S.selId}">
      <span class="l1"><span>${esc(s.origen)} a ${esc(s.destino)}</span><time>${hace(s.creada)}</time></span>
      <span class="l2">${num(s.unidades)} × ${esc(s.tipo_carga)} · plazo ${plazo(s.plazo_horas)}</span>
      <span class="l3"><span class="marca" data-e="${esc(s.estado)}"><i></i>${esc(s.estado)}</span><span>${esc(s.codigo)}</span>${S.nuevos.has(s.id) ? '<span class="nueva">Nueva</span>' : ""}${s.proveedor_elegido ? `<span>· ${esc(corto(s.proveedor_elegido))}</span>` : ""}</span>${SIGUIENTE[s.estado_clave] ? `<span class="l4">Siguiente: ${SIGUIENTE[s.estado_clave]}</span>` : ""}</button>`).join("");
  const vacia = S.lista === "por_asignar"
    ? `<div class="lista-vacia"><h2>No hay solicitudes por asignar</h2><p>Cuando un cliente envíe una desde el portal, aparece aquí sola.</p><button class="btn" type="button" data-act="ejemplos">Crear dos de ejemplo</button></div>`
    : S.lista === "asignadas" ? `<div class="lista-vacia"><h2>Nada asignado en curso</h2><p>Las que elijas aparecen aquí hasta que registres cómo llegaron.</p></div>`
    : `<div class="lista-vacia"><h2>Todavía no hay servicios cerrados</h2><p>Al registrar cómo llegó un envío, pasa aquí y el sistema aprende del resultado.</p></div>`;
  elLista.innerHTML = `<div class="lista-head"><h2>Solicitudes</h2><p>${porAsignar().length ? `${porAsignar().length} por asignar` : "Todo al día"}</p></div>
    <div><div class="tabs" role="tablist" style="margin-top:14px">
      <button role="tab" type="button" data-act="lista" data-l="por_asignar" aria-selected="${S.lista === "por_asignar"}">Por asignar ${porAsignar().length}</button>
      <button role="tab" type="button" data-act="lista" data-l="asignadas" aria-selected="${S.lista === "asignadas"}">En curso ${asignadas().length}</button>
      <button role="tab" type="button" data-act="lista" data-l="cerradas" aria-selected="${S.lista === "cerradas"}">Cerradas ${cerradas().length}</button></div>
      <div class="filas" style="max-height:calc(100vh - 170px)">${filas || vacia}</div></div>`;
}

async function abrir(id) {
  const fila = S.bandeja.find((s) => s.id === id);
  if (!fila) return;
  S.selId = id; S.base = fila; S.solicitud = motorDe(fila);
  S.chips = chipsIniciales(); S.excluidos = []; S.aviso = null; S.cajon = null; S.nuevos.delete(id);
  S.asignado = fila.proveedor_elegido ?? null; S.decision = null; S.data = null; S.cierre = null;
  sheet.dataset.vista = "detalle";
  cerrarCajon();
  if (fila.estado_clave === "pendiente") {
    Api.analisis(id).then(() => { fila.estado_clave = "en_analisis"; fila.estado = "En análisis"; pintarLista(); pintarDetalle(); }).catch(() => {});
  }
  pintarLista();
  await refrescar();
}

async function refrescar() {
  if (!S.solicitud) { S.status = "vacio"; pintarDetalle(); return; }
  if (abort) abort.abort();
  abort = new AbortController();
  const previas = S.data?.estrategias ? { ...S.data.estrategias } : null;
  S.status = "cargando";
  pintarDetalle();
  try {
    const d = await Api.ranking(S.solicitud, requisitos(), abort.signal);
    S.data = d;
    S.status = S.forzado === "normal" ? "normal" : S.forzado;
    S.error = "";
    if (S.pendienteCapacidad && previas) {
      const { proveedor } = S.pendienteCapacidad;
      const slot = Object.values(previas).find((o) => o.proveedor === proveedor);
      const nuevo = slot && d.estrategias[slot.estrategia];
      S.aviso = { texto: nuevo
        ? `${proveedor} no tiene capacidad. Para la opción ${nombreDe(nuevo).toLowerCase()} entra ${nuevo.proveedor}: ${pct0(nuevo.p_exito)} de éxito y ${cop(nuevo.costo_esperado_cop)} esperado (antes ${cop(slot.costo_esperado_cop)}).`
        : `${proveedor} no tiene capacidad y no queda un reemplazo individual.`, deshacer: proveedor };
      S.pendienteCapacidad = null;
    }
  } catch (e) {
    if (e.name === "AbortError") return;
    S.status = "error"; S.error = e.message;
  }
  pintarDetalle();
  if (S.cajon) pintarCajon();
  copiloto.actualizar();
}

// ---------------------------------------------------------------- detalle
function hallazgo() {
  const [eq, eco, conf] = ["equilibrada", "economica", "confiable"].map((k) => S.data.estrategias[k]);
  if (!eq) return "Nadie cumple solo con lo que pide el cliente. Abajo está por qué y qué se puede cambiar.";
  const debil = S.data.respuesta.alternativas.length > 0;
  let t = `${debil ? "La mejor disponible es" : "Recomiendo"} <strong>${esc(eq.proveedor)}</strong>: ${pct0(eq.p_exito)} de éxito y ${cop(eq.costo_esperado_cop)} de costo esperado.`;
  if (eco) { const dc = eco.costo_esperado_cop - eq.costo_esperado_cop; t += ` ${esc(corto(eco.proveedor))} ${dc < 0 ? `ahorra ${cop(-dc)}` : `cuesta ${cop(dc)} más`}${eco.p_exito < eq.p_exito ? ` pero baja el éxito ${dec((eq.p_exito - eco.p_exito) * 100)} puntos` : ""}.`; }
  if (conf && conf.etiqueta === "Más confiable") t += ` ${esc(corto(conf.proveedor))} es la más confiable (${pct0(conf.p_exito)}).`;
  if (debil) t += ` Es bajo: antes de elegir, mira abajo qué cambio lo sube.`;
  return t;
}

function encabezado() {
  const b = S.base, s = S.solicitud, r = S.data?.respuesta?.solicitud;
  const indice = PASO[b.estado_clave] ?? 0;
  return `<div class="d-head">
      <div><button class="btn small volver" type="button" data-act="volver">Solicitudes</button>
        <p class="crumb">Solicitudes / ${esc(b.codigo)}</p><h1>${esc(s.origen)} a ${esc(s.destino)}</h1></div>
      ${Pasos(indice, ["Recibida", "En análisis", "Asignada", "En tránsito", "Cerrada"])}</div>
    <div class="hechos"><span><b>${num(s.unidades)} × ${esc(s.tipo_carga)}</b></span>${r ? `<span>${esc(r.tipo_vehiculo)} · ${dec(r.distancia_km)} km</span>` : ""}<span>Cargue <b>${fechaCorta(s.fecha)}</b></span><span>Plazo <b>${plazo(s.plazo_horas)}</b></span><span>Prioridad <b>${PRIORIDAD_TXT[s.prioridad] ?? esc(s.prioridad)}</b></span>${b.contacto ? `<span>Cliente <b>${esc(b.contacto)}${b.empresa ? ` · ${esc(b.empresa)}` : ""}</b></span>` : ""}</div>
    ${b.notas ? `<p class="muted">Nota del cliente: ${esc(b.notas)}</p>` : ""}`;
}

function avisos() {
  let h = "";
  if (S.aviso) h += `<div class="aviso" role="status"><span>${esc(S.aviso.texto)}</span><span style="display:flex;gap:8px"><button class="btn small" type="button" data-act="deshacer">Deshacer</button><button class="btn small ghost" type="button" data-act="cerrar-aviso">Cerrar</button></span></div>`;
  if (S.asignado && S.decision && S.base.estado_clave === "asignada") h += `<div class="aviso ok" role="status"><span><strong>Asignada a ${esc(S.asignado)}.</strong> Decisión #${S.decision.decision_id} registrada${S.decision.cambio_manual ? " con motivo" : ""}. El seguimiento quedó arriba y en la pestaña En curso.</span></div>`;
  if (simulando()) h += `<div class="aviso" role="status"><span>Estás simulando otras condiciones. El pedido del cliente no cambia.</span><button class="btn small" type="button" data-act="restablecer">Volver a lo que pidió el cliente</button></div>`;
  return h;
}

function seccionAjustar() {
  const s = S.solicitud, cat = S.catalogo;
  const pesos = S.data?.respuesta?.pesos ?? {};
  const carga = cat.tipos_carga.find((t) => t.nombre === s.tipo_carga);
  const veh = S.data?.respuesta?.solicitud?.tipo_vehiculo;
  const fijos = [`Opera en ${s.origen} y ${s.destino}`, veh ? `Tiene ${veh}` : "Tiene el vehículo", `Cupo libre el ${fechaCorta(s.fecha)}`, ...(carga?.certificacion ? [`Certificación: ${carga.certificacion}`] : [])];
  const total = Object.values(pesos).reduce((a, b) => a + b, 0) || 1;
  const orden = ["precio", "tiempo", "confiabilidad", "historial", "holgura", "segmento"];
  return `<details class="d" data-d="ajustar" ${S.abiertos.has("ajustar") ? "open" : ""}><summary><span>Ajustar criterios<span class="sub">qué pesa más y qué exiges</span></span></summary><div class="d-body">
    <div class="criterios">
      <div class="fila"><span class="lbl">Qué pesa más</span><div class="seg" style="display:flex;gap:8px;flex-wrap:wrap">${Object.keys(cat.prioridades).map((p) => `<button class="chip" type="button" data-act="prioridad" data-p="${esc(p)}" data-estado="${p === s.prioridad ? "prefiero" : "neutral"}">${PRIORIDAD_TXT[p] ?? p}</button>`).join("")}</div></div>
      <div class="fila"><span class="lbl">Siempre se aplican</span>${fijos.map(FiltroFijo).join("")}</div>
      <div class="fila"><span class="lbl">Lo que tú pesas</span>${CHIPS.map((c) => ChipFactor({ clave: c.clave, nombre: c.nombre, estado: S.chips[c.clave], peso: pesos[c.factor] ?? 0, param: c.param ? { ...c.param, valor: S.param[c.param.campo] } : null })).join("")}</div>
      <p class="muted" style="font-size:13px;margin-left:148px">Neutral usa el peso del perfil. Prefiero pesa más. Exijo descarta a quien no cumpla.</p>
      ${S.excluidos.length ? `<div class="fila"><span class="lbl">Excluidos</span>${S.excluidos.map((x) => `<button class="chip excluido" type="button" data-act="quitar-excluido" data-prov="${esc(x.nombre)}" aria-label="Volver a incluir a ${esc(x.nombre)}">${esc(x.nombre)} · ${esc(x.motivo)}</button>`).join("")}</div>` : ""}
      <div class="fila"><span class="lbl">Pesos aplicados</span><div class="pesos-line" role="img" aria-label="${orden.map((k) => `${FACTORES[k]} ${pct0(pesos[k] ?? 0)}`).join(", ")}">${orden.map((k) => `<i style="width:${((pesos[k] ?? 0) / total) * 100}%;opacity:${0.4 + ((pesos[k] ?? 0) / total) * 1.6}" title="${FACTORES[k]} ${pct0(pesos[k] ?? 0)}"></i>`).join("")}</div>
        <span class="muted" style="font-size:13px">${orden.filter((k) => (pesos[k] ?? 0) > 0).map((k) => `${FACTORES[k]} ${pct0(pesos[k])}`).join(" · ")}</span></div>
    </div>
    <div><p class="sub-h">Probar otras condiciones del envío</p><p class="muted" style="font-size:13px;margin-bottom:10px">Solo para simular. No cambia lo que pidió el cliente.</p>
      <div class="campos">
        <div><label for="f-plazo">Plazo (horas)</label><input id="f-plazo" type="number" min="1" value="${s.plazo_horas}"></div>
        <div><label for="f-fecha">Cargue</label><input id="f-fecha" type="date" value="${s.fecha}"></div>
        <div><label for="f-unidades">Unidades</label><input id="f-unidades" type="number" min="1" max="10" value="${s.unidades}"></div>
      </div></div></div></details>`;
}

function seccionPorque(ops) {
  const p = S.data.respuesta.por_que_no_el_2;
  const factores = ["precio", "tiempo", "confiabilidad", "historial", "holgura", "segmento"].filter((f) => ops.some((o) => (o.aportes[f] ?? 0) > 0));
  return `<details class="d" data-d="porque" ${S.abiertos.has("porque") ? "open" : ""}><summary><span>Por qué estas tres<span class="sub">de dónde sale cada puntaje</span></span></summary><div class="d-body">
    <div class="dos"><div>
      <div class="leyenda" style="margin-bottom:12px">${ops.map((o, i) => `<span><i style="background:${["var(--accent)", "var(--faint)", "var(--control)"][i]}"></i>${nombreDe(o)}: ${esc(corto(o.proveedor))} (${dec(o.puntaje)})</span>`).join("")}</div>
      ${BarrasContribucion(ops, factores)}
      <p class="explica" style="margin-top:12px">Las tres usan el mismo motor y los mismos datos; solo cambia cuánto pesa cada factor.</p></div>
    <div>${p ? `<p class="sub-h">¿Por qué no el segundo?</p><p style="margin-bottom:12px">${esc(p.texto)}</p>${DiferenciaPorFactor(p.por_factor)}${p.contrafactual ? `<p class="explica" style="margin-top:12px">${esc(p.contrafactual)}</p>` : ""}
      <p style="margin-top:12px"><button class="btn small" type="button" data-act="preguntar" data-q="¿Por qué no ${esc(p.pierde)}?">Preguntar al Copiloto</button></p>` : '<p class="muted">Solo hay una opción en el ranking.</p>'}</div></div></div></details>`;
}

function seccionExperta(ops) {
  const d = S.data;
  const filas = [["Puntaje", (o) => dec(o.puntaje)], ["Éxito", (o) => pct0(o.p_exito)], ["A tiempo", (o) => pct0(o.p_a_tiempo)], ["Daño", (o) => pct0(o.p_dano)], ["Costo esperado", (o) => cop(o.costo_esperado_cop)], ["Costo en el peor 10%", (o) => cop(o.costo_p90_cop)], ["Tiempo típico (P50)", (o) => horas(o.tiempo_p50_h)], ["Tiempo hasta (P90)", (o) => horas(o.tiempo_p90_h)], ["Confiabilidad", (o) => pct0(o.confiabilidad)], ["Servicios en el segmento", (o) => num(o.servicios_en_segmento)], ["Libres", (o) => num(o.vehiculos_libres)]];
  return `<details class="d" data-d="experta" ${S.abiertos.has("experta") ? "open" : ""}><summary><span>Vista experta<span class="sub">costo contra tiempo y comparador</span></span></summary><div class="d-body">
    <div>${GraficoCostoP90(d.respuesta.ranking, d.estrategias, S.solicitud.plazo_horas)}<p class="explica" style="margin-top:12px">P90 es el tiempo que el proveedor no pasa en 9 de cada 10 viajes. Abajo y a la izquierda es más barato y más rápido.</p></div>
    <div style="overflow:auto"><table class="tabla"><thead><tr><th>Medida</th>${ops.map((o) => `<th class="r">${nombreDe(o)}<br><span>${esc(corto(o.proveedor))}</span></th>`).join("")}</tr></thead><tbody>${filas.map(([k, f]) => `<tr><td>${k}</td>${ops.map((o) => `<td class="r num">${f(o)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div></details>`;
}

function vistaSinOpcion() {
  const r = S.data.respuesta, cd = r.carga_dividida;
  return `<div class="cuando-no" style="background:var(--raised);border-radius:8px;padding:20px"><h3 style="font-size:18px;font-weight:600;margin-bottom:6px">Ningún proveedor cumple solo</h3><p>Con lo que pide el cliente nadie sale como opción individual. No relajo nada por mi cuenta: ${cd ? "abajo hay una carga dividida y los cambios que abren opciones" : "abajo están los cambios que abren opciones"}.</p></div>
    ${cd || r.alternativas.length ? `<div class="dos">` : ""}${cd ? `<div class="d" style="border:1px solid var(--border);border-radius:8px;padding:20px"><p class="sub-h">Carga dividida</p>
      <table class="tabla"><thead><tr><th>Proveedor</th><th class="r">Unidades</th><th class="r">Éxito</th></tr></thead><tbody>${cd.reparto.map((x) => `<tr><td>${esc(x.proveedor)}</td><td class="r num">${x.unidades}</td><td class="r num">${pct0(x.p_exito)}</td></tr>`).join("")}</tbody></table>
      <p style="margin-top:12px"><strong class="num" style="font-size:24px">${pct0(cd.p_exito_conjunta)}</strong> de éxito conjunto · ${cop(cd.costo_esperado_cop)} esperado · hasta ${horas(cd.tiempo_p90_h)}</p><p class="explica" style="margin-top:8px">${esc(cd.nota)}</p></div>
` : ""}${r.alternativas.length ? bloqueAlternativas(r) : ""}${cd || r.alternativas.length ? "</div>" : ""}`;
}

const CAMBIOS_APLICABLES = ["fecha", "plazo_horas", "presupuesto_cop", "tipo_vehiculo"];
function bloqueAlternativas(r, titulo = "Qué puedes cambiar") {
  return `<div style="border:1px solid var(--border);border-radius:8px;padding:20px"><p class="sub-h">${titulo}</p><ul class="descartados" style="display:block">${r.alternativas.map((a, i) => `<li style="grid-template-columns:1fr auto"><span>${esc(a.descripcion)}${a.p_exito_mejor != null ? `<br><span class="muted num">Mejor: ${esc(a.mejor ?? "carga dividida")} · ${pct0(a.p_exito_mejor)} de éxito</span>` : ""}</span>${CAMBIOS_APLICABLES.some((k) => a.cambio[k]) && !a.cambio.dividir ? `<button class="btn small" type="button" data-act="aplicar-alt" data-i="${i}">Probar</button>` : ""}</li>`).join("")}</ul></div>`;
}

// ---------------------------------------------------------------- servicio: en tránsito y cierre
function previsto() {
  const o = S.data?.respuesta?.ranking?.find((x) => x.proveedor === S.asignado);
  return o ? { p50: o.tiempo_p50_h, p90: o.tiempo_p90_h, costo: o.costo_esperado_cop } : null;
}
function abrirCierre() {
  const p = previsto();
  S.cierre = { a_tiempo: null, tiempo: p ? String(Math.round(p.p50 * 10) / 10) : "", costo: p ? String(Math.round(p.costo / 1000) * 1000) : "", dano: false, calif: "5", err: "", enviando: false, resultado: null };
  if (p) S.cierre.a_tiempo = p.p50 <= S.base.plazo_horas;
}
const siNo = (campo, valor, etiqueta) => `<div class="seg-sn" role="group" aria-label="${etiqueta}">${[[true, "Sí"], [false, "No"]].map(([v, t]) => `<button type="button" data-act="sn" data-campo="${campo}" data-v="${v}" aria-pressed="${valor === v}">${t}</button>`).join("")}</div>`;

function seccionServicio() {
  const b = S.base, c = S.cierre, p = previsto();
  if (!S.asignado || !b.decision_id) return "";
  const estado = b.estado_clave;
  const exito = b.exito_predicho != null ? ` · éxito previsto ${pct0(b.exito_predicho)}` : "";
  let cuerpo;
  if (estado === "atendida") {
    const r = c?.resultado;
    cuerpo = `<div class="serv-res"><p><strong>${b.resultado_a_tiempo ? "Llegó dentro del plazo" : "Llegó tarde"}</strong>${b.resultado_costo_cop != null ? ` · costo final ${cop(b.resultado_costo_cop)}` : ""}.</p>
      ${r ? CambioConfiabilidad(r) : `<p class="muted">El resultado ya entró a la confiabilidad del proveedor en este segmento.</p>`}</div>`;
  } else if (!c) {
    // Línea de seguimiento: lo hecho, y el siguiente paso con su botón a la vista.
    const salio = estado === "en_transito";
    cuerpo = `<ol class="seguir">
      <li data-estado="hecho"><i></i><div><b>Asignada</b><span class="muted">El cliente ya la ve asignada.</span></div></li>
      <li data-estado="${salio ? "hecho" : "actual"}"><i></i><div><b>En tránsito</b>${salio ? `<span class="muted">El vehículo ya salió de ${esc(b.origen)}.</span>`
        : `<span>¿Ya salió el vehículo de ${esc(b.origen)}? Márcalo para que el cliente vea que su carga va en camino.</span><button class="btn primary" type="button" data-act="transito">Sí, salió: marcar en tránsito</button>`}</div></li>
      <li data-estado="${salio ? "actual" : "futuro"}"><i></i><div><b>Cerrada</b><span${salio ? "" : ' class="muted"'}>${salio ? `Cuando llegue a ${esc(b.destino)}, registra el tiempo real y el costo final. El sistema aprende de eso.` : `Cuando llegue a ${esc(b.destino)}, registras cómo le fue.`}</span>
        <button class="btn ${salio ? "primary" : "small ghost"}" type="button" data-act="abrir-cierre">${salio ? "Registrar cómo llegó" : "Ya llegó: registrar cómo llegó"}</button></div></li></ol>`;
  } else {
    const fueraPlazo = Number(c.tiempo) > b.plazo_horas;
    cuerpo = `<form class="cierre" id="form-cierre" novalidate>
      <div class="cierre-campos">
        <div class="campo-c"><label for="c-tiempo">Tiempo real de tránsito (horas)</label><input id="c-tiempo" type="number" min="0" step="0.5" inputmode="decimal" value="${esc(c.tiempo)}">
          <span class="ayuda ${c.tiempo && fueraPlazo ? "mal" : ""}">${c.tiempo ? (fueraPlazo ? `${horas(Number(c.tiempo) - b.plazo_horas)} sobre el plazo de ${plazo(b.plazo_horas)}` : `Dentro del plazo de ${plazo(b.plazo_horas)}`) : `Plazo acordado ${plazo(b.plazo_horas)}`}</span></div>
        <div class="campo-c"><span class="lbl-c" id="l-at">¿Llegó dentro del plazo?</span>${siNo("a_tiempo", c.a_tiempo, "¿Llegó dentro del plazo?")}</div>
        <div class="campo-c"><label for="c-costo">Costo final (COP)</label><input id="c-costo" type="number" min="0" step="1000" inputmode="numeric" value="${esc(c.costo)}">
          <span class="ayuda">${c.costo && p ? (Math.abs(Number(c.costo) - p.costo) < 1000 ? "Igual a lo esperado" : `${Number(c.costo) > p.costo ? `${cop(Number(c.costo) - p.costo)} sobre` : `${cop(p.costo - Number(c.costo))} bajo`} lo esperado`) : "Lo que facturó el proveedor, con extras"}</span></div>
        <div class="campo-c"><span class="lbl-c">¿Hubo daño en la carga?</span>${siNo("dano", c.dano, "¿Hubo daño en la carga?")}</div>
        <div class="campo-c"><label for="c-calif">Calificación del cliente</label><select id="c-calif">${[5, 4, 3, 2, 1].map((n) => `<option value="${n}" ${String(n) === c.calif ? "selected" : ""}>${n} de 5</option>`).join("")}</select></div>
      </div>
      <dl class="kv previsto"><dt class="previsto-t">Lo que se esperaba</dt><dd></dd>
        <dt>Plazo</dt><dd class="num">${plazo(b.plazo_horas)}</dd>
        ${p ? `<dt>Tiempo típico (P50)</dt><dd class="num">${horas(p.p50)}</dd><dt>Tiempo hasta (P90)</dt><dd class="num">${horas(p.p90)}</dd><dt>Costo esperado</dt><dd class="num">${cop(p.costo)}</dd>` : ""}
        ${b.exito_predicho != null ? `<dt>Éxito previsto</dt><dd class="num">${pct0(b.exito_predicho)}</dd>` : ""}</dl>
      <div class="cierre-pie"><p class="muted">Al cerrar, el resultado entra al historial y el sistema actualiza la confiabilidad de ${esc(S.asignado)}.</p>
        <div class="err" role="alert">${esc(c.err)}</div>
        <div class="dialog-btns"><button class="btn" type="button" data-act="cancelar-cierre">Cancelar</button><button class="btn primary" type="submit" ${c.enviando ? "disabled" : ""}>${c.enviando ? "Cerrando…" : "Cerrar servicio"}</button></div></div>
    </form>`;
  }
  return `<section class="servicio" aria-labelledby="h-serv"><header><div><h2 id="h-serv">${estado === "atendida" ? "Servicio cerrado" : estado === "en_transito" ? "En camino" : "Servicio asignado"} con ${esc(S.asignado)}</h2>
      <p class="muted">Decisión #${b.decision_id}${exito}</p></div><span class="marca" data-e="${esc(b.estado)}"><i></i>${esc(b.estado)}</span></header>${cuerpo}</section>`;
}

async function enviarCierre() {
  const c = S.cierre, t = Number(c.tiempo), k = Number(c.costo);
  if (!(t > 0)) c.err = "Escribe cuántas horas tardó.";
  else if (!(k > 0)) c.err = "Escribe el costo final.";
  else if (c.a_tiempo == null) c.err = "Indica si llegó dentro del plazo.";
  else c.err = "";
  if (c.err) { pintarDetalle(); return; }
  c.enviando = true; pintarDetalle();
  try {
    c.resultado = await Api.cerrar({ decision_id: S.base.decision_id, a_tiempo: c.a_tiempo, tiempo_real_h: t, costo_final_cop: k, dano_carga: c.dano, calificacion_cliente: Number(c.calif) });
    Object.assign(S.base, { estado_clave: "atendida", estado: "Cerrada", resultado_a_tiempo: c.a_tiempo, resultado_costo_cop: k });
    S.lista = "cerradas";
    S.perfiles.delete(S.asignado);
    pintarLista(); cargarBandeja();
  } catch (e) { c.err = e.message; }
  c.enviando = false; pintarDetalle();
}

const enCursoDe = (b) => ["en_transito", "atendida"].includes(b?.estado_clave);
function pintarDetalle() {
  if (!S.catalogo) { elDetalle.innerHTML = `<div class="detalle-in">${Esqueleto()}</div>`; return; }
  if (!S.base) {
    elDetalle.innerHTML = `<div class="detalle-in">${Estado("Elige una solicitud", porAsignar().length ? "Abre una de la lista para ver las tres opciones." : "Cuando llegue una desde el portal del cliente, la verás en la lista.", "", "h1")}</div>`;
    return;
  }
  const y = elDetalle.scrollTop;
  let cuerpo;
  if (S.status === "cargando") cuerpo = Esqueleto();
  else if (S.status === "error") cuerpo = Estado("No se pudo calcular", S.error || "El motor no respondió.", '<button class="btn" type="button" data-act="reintentar">Reintentar</button>');
  else if (S.status === "vacio") cuerpo = Estado("No hay opciones para mostrar", "Cambia las condiciones o vuelve a lo que pidió el cliente.");
  else {
    const d = S.data, ops = opciones();
    const debil = !d.respuesta.sin_opcion && d.respuesta.alternativas.length && !enCursoDe(S.base)
      ? `<div style="margin-top:16px">${bloqueAlternativas(d.respuesta, `La mejor opción tiene ${pct0(ops[0].p_exito)} de éxito. Qué la puede mejorar`)}</div>` : "";
    const cuerpoOpc = d.respuesta.sin_opcion ? vistaSinOpcion() : `${GraficoMC(ops, d.respuesta.solicitud.plazo_horas)}<div class="cards">${ops.map((o) => TarjetaOpcion(o, { solicitud: d.respuesta.solicitud, opciones: ops, asignado: S.asignado })).join("")}</div>${debil}`;
    const enCurso = enCursoDe(S.base);
    cuerpo = `${seccionServicio()}${enCurso ? `<p class="sub-h" style="margin:8px 0 -8px">Las opciones que se compararon</p>` : `<p class="hallazgo">${hallazgo()}</p>`}${avisos()}${cuerpoOpc}
      <div class="mas">${seccionAjustar()}${d.respuesta.sin_opcion ? "" : seccionPorque(ops)}<details class="d" data-d="descartados" ${S.abiertos.has("descartados") ? "open" : ""}><summary><span>Descartados<span class="sub">${d.respuesta.descartados.length} proveedores, cada uno con su razón</span></span></summary><div class="d-body">${ListaDescartados(d.respuesta.descartados)}</div></details>${d.respuesta.sin_opcion ? "" : seccionExperta(ops)}</div>`;
  }
  const foco = document.activeElement?.id;
  elDetalle.innerHTML = `<div class="detalle-in">${encabezado()}${S.status === "cargando" ? "" : ""}${cuerpo}</div>`;
  elDetalle.scrollTop = y;
  if (S.status === "normal" && S.data && !S.data.respuesta.sin_opcion) dibujarMC(elDetalle, opciones(), S.data.respuesta.solicitud.plazo_horas, S.data);
  if (S.cierre?.resultado) animarConfiabilidad(elDetalle, S.cierre.resultado);
  if (foco) document.getElementById(foco)?.focus();
}

// ---------------------------------------------------------------- cajón: detalle de una opción
async function perfil(nombre) {
  if (!S.perfiles.has(nombre)) S.perfiles.set(nombre, await Api.proveedor(nombre));
  return S.perfiles.get(nombre);
}
function pintarCajon() {
  const o = S.data?.estrategias?.[S.cajon];
  if (!o) { cerrarCajon(); return; }
  const ctx = { solicitud: S.data.respuesta.solicitud, opciones: opciones(), asignado: S.asignado };
  elCajon.innerHTML = `<div class="cajon-head"><div><p class="muted">${nombreDe(o)}</p><h2>${esc(o.proveedor)}</h2>
      <p style="margin-top:8px;display:flex;gap:12px;align-items:center"><strong class="num" style="font-size:24px;font-weight:400">${pct0(o.p_exito)} de éxito</strong>${SemaforoRiesgo(o.semaforo)}</p></div>
      <button class="btn small ghost" type="button" data-act="cerrar-cajon" aria-label="Cerrar detalle">Cerrar</button></div>
    <div class="cajon-body">${DetalleOpcion(o, ctx, S.perfiles.get(o.proveedor))}</div>
    <div class="cajon-foot"><button class="btn small" type="button" data-act="sin-capacidad" data-prov="${esc(o.proveedor)}" ${S.asignado ? "disabled" : ""}>No tiene capacidad</button><button class="btn small" type="button" data-act="excluir" data-prov="${esc(o.proveedor)}" ${S.asignado ? "disabled" : ""}>Excluir</button><button class="btn primary" type="button" data-act="elegir" data-est="${o.estrategia}" ${S.asignado ? "disabled" : ""}>Elegir esta</button></div>`;
}
function abrirCajon(est) {
  S.cajon = est;
  pintarCajon();
  elCajon.dataset.open = "true"; scrim.dataset.open = "true";
  const o = S.data.estrategias[est];
  perfil(o.proveedor).then(() => { if (S.cajon === est) pintarCajon(); }).catch(() => {});
  elCajon.querySelector("[data-act=cerrar-cajon]")?.focus();
}
function cerrarCajon() { S.cajon = null; elCajon.dataset.open = "false"; scrim.dataset.open = "false"; }

// ---------------------------------------------------------------- elegir
const dlg = $("#dlg-elegir");
let eleccion = null;
function abrirElegir(est) {
  const o = S.data.estrategias[est], rec = S.data.estrategias.equilibrada;
  const distinto = o.proveedor !== rec.proveedor;
  eleccion = { o, rec, distinto };
  $("#elegir-titulo").textContent = `Asignar a ${o.proveedor}`;
  $("#elegir-resumen").textContent = `${pct0(o.p_exito)} de éxito · ${cop(o.costo_esperado_cop)} esperado · hasta ${horas(o.tiempo_p90_h)}. ${distinto ? `La recomendada era ${rec.proveedor}.` : "Es la recomendada."}${simulando() ? " Ojo: estás simulando otras condiciones." : ""}`;
  $("#elegir-oblig").textContent = distinto ? "(obligatorio: elegiste distinto a la recomendada)" : "(opcional)";
  $("#elegir-motivo").value = est === "economica" ? "Eligió la estrategia económica" : est === "confiable" ? "Eligió la estrategia más confiable" : "";
  $("#elegir-err").textContent = "";
  dlg.showModal();
  $("#elegir-motivo").focus();
}
$("#elegir-cancelar").onclick = () => dlg.close();
$("#form-elegir").onsubmit = async (ev) => {
  ev.preventDefault();
  const motivo = $("#elegir-motivo").value.trim();
  if (eleccion.distinto && !motivo) { $("#elegir-err").textContent = "Escribe el motivo: sin él no se registra la decisión."; return; }
  $("#elegir-ok").disabled = true;
  try {
    const r = await Api.decision({ solicitud_id: S.selId, requisitos: requisitos(), proveedor_elegido: eleccion.o.proveedor, proveedor_recomendado: eleccion.rec.proveedor, exito_predicho: eleccion.o.p_exito, motivo: motivo || null });
    S.asignado = eleccion.o.proveedor; S.decision = r;
    Object.assign(S.base, { estado_clave: "asignada", estado: "Asignada", proveedor_elegido: S.asignado, decision_id: r.decision_id, exito_predicho: eleccion.o.p_exito });
    S.lista = "asignadas"; // la solicitud se mueve de pestaña: la lista la sigue
    dlg.close(); cerrarCajon(); pintarLista(); pintarDetalle(); copiloto.actualizar();
    cargarBandeja();
  } catch (e) { $("#elegir-err").textContent = e.message; }
  $("#elegir-ok").disabled = false;
};

// ---------------------------------------------------------------- acciones (también las usa el Copiloto)
const abrirSeccion = (k) => { S.abiertos.add(k); pintarDetalle(); document.querySelector(`[data-d="${k}"]`)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); };
const acciones = {
  excluir(nombre, motivo = "excluido") { if (!S.excluidos.some((x) => x.nombre === nombre)) S.excluidos.push({ nombre, motivo }); if (!S.base?.proveedor_elegido) S.asignado = null; cerrarCajon(); refrescar(); },
  quitarExcluido(nombre) { S.excluidos = S.excluidos.filter((x) => x.nombre !== nombre); refrescar(); },
  prioridad(p) { S.solicitud.prioridad = p; S.abiertos.add("ajustar"); refrescar(); },
  solicitud(parcial) { Object.assign(S.solicitud, parcial); S.abiertos.add("ajustar"); refrescar(); },
  tab(t) { abrirSeccion(t === "experta" ? "experta" : "porque"); },
  async crear(datos) {
    const r = await Api.crear(datos);
    S.lista = "por_asignar";
    await cargarBandeja();
    abrir(r.id);
  },
};
const copiloto = crearCopiloto({ estado: S, opciones, requisitos, acciones, catalogoListo: () => !!S.catalogo });

function clic(ev) {
  const b = ev.target.closest("[data-act]");
  if (!b) return;
  const a = b.dataset.act;
  if (a === "abrir") abrir(Number(b.dataset.id));
  else if (a === "lista") { S.lista = b.dataset.l; pintarLista(); }
  else if (a === "volver") { sheet.dataset.vista = "lista"; }
  else if (a === "ejemplos") Api.ejemplos().then(async (r) => { await cargarBandeja(); abrir(r[0].id); });
  else if (a === "chip") { const k = b.dataset.clave; S.chips[k] = siguienteEstado(S.chips[k]); S.abiertos.add("ajustar"); if (!S.base?.proveedor_elegido) S.asignado = null; refrescar(); }
  else if (a === "prioridad") acciones.prioridad(b.dataset.p);
  else if (a === "elegir") abrirElegir(b.dataset.est);
  else if (a === "detalle") abrirCajon(b.dataset.est);
  else if (a === "cerrar-cajon") cerrarCajon();
  else if (a === "excluir") acciones.excluir(b.dataset.prov);
  else if (a === "sin-capacidad") { S.pendienteCapacidad = { proveedor: b.dataset.prov }; acciones.excluir(b.dataset.prov, "sin capacidad"); }
  else if (a === "quitar-excluido") acciones.quitarExcluido(b.dataset.prov);
  else if (a === "deshacer") { const p = S.aviso?.deshacer; S.aviso = null; if (p) acciones.quitarExcluido(p); }
  else if (a === "cerrar-aviso") { S.aviso = null; pintarDetalle(); }
  else if (a === "restablecer") { S.solicitud = motorDe(S.base); refrescar(); }
  else if (a === "reintentar") refrescar();
  else if (a === "aplicar-alt") { const alt = S.data.respuesta.alternativas[Number(b.dataset.i)]; acciones.solicitud(Object.fromEntries(CAMBIOS_APLICABLES.filter((k) => alt.cambio[k]).map((k) => [k, alt.cambio[k]]))); }
  else if (a === "preguntar") copiloto.preguntar(b.dataset.q);
  else if (a === "transito") Api.transito(S.selId).then((e) => { Object.assign(S.base, { estado_clave: "en_transito", estado: e.estado }); pintarLista(); pintarDetalle(); cargarBandeja(); }).catch((e) => { S.aviso = { texto: e.message }; pintarDetalle(); });
  else if (a === "abrir-cierre") { abrirCierre(); pintarDetalle(); document.getElementById("c-tiempo")?.focus(); }
  else if (a === "cancelar-cierre") { S.cierre = null; pintarDetalle(); }
  else if (a === "sn") { S.cierre[b.dataset.campo] = b.dataset.v === "true"; pintarDetalle(); }
}
for (const el of [elLista, elDetalle, elCajon]) el.addEventListener("click", clic);
scrim.addEventListener("click", cerrarCajon);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && S.cajon) cerrarCajon(); });
elDetalle.addEventListener("toggle", (e) => { const k = e.target.dataset?.d; if (k) e.target.open ? S.abiertos.add(k) : S.abiertos.delete(k); }, true);
elDetalle.addEventListener("input", (ev) => {
  const t = ev.target, c = S.cierre;
  if (!c) return;
  if (t.id === "c-tiempo") { c.tiempo = t.value; if (Number(t.value) > 0) c.a_tiempo = Number(t.value) <= S.base.plazo_horas; }
  else if (t.id === "c-costo") c.costo = t.value;
  else if (t.id === "c-calif") c.calif = t.value;
});
elDetalle.addEventListener("submit", (ev) => { if (ev.target.id === "form-cierre") { ev.preventDefault(); enviarCierre(); } });
elDetalle.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.closest("#form-cierre")) { if (t.id === "c-tiempo" || t.id === "c-costo") pintarDetalle(); return; }
  if (t.id === "f-unidades") acciones.solicitud({ unidades: Math.max(1, Number(t.value) || 1) });
  else if (t.id === "f-plazo") acciones.solicitud({ plazo_horas: Math.max(1, Number(t.value) || 36) });
  else if (t.id === "f-fecha" && t.value) acciones.solicitud({ fecha: t.value });
  else if (t.dataset.param) { S.param[CHIPS.find((x) => x.clave === t.dataset.param).param.campo] = t.value; refrescar(); }
});
$("#estado-datos").addEventListener("change", (ev) => {
  S.forzado = ev.target.value;
  if (S.forzado === "normal") refrescar();
  else { S.status = S.forzado; S.error = S.forzado === "error" ? "Simulación de error: el motor no respondió." : ""; pintarDetalle(); }
});

// ---------------------------------------------------------------- pantallas: Solicitudes y Gerencia (#gerencia)
const elGerencia = $("#gerencia");
const gerencia = crearGerencia(elGerencia);
function ruta() {
  const g = location.hash === "#gerencia";
  sheet.hidden = g; elGerencia.hidden = !g;
  for (const a of document.querySelectorAll("[data-ruta]")) a.toggleAttribute("aria-current", a.dataset.ruta === (g ? "gerencia" : "solicitudes"));
  for (const a of document.querySelectorAll("[data-ruta][aria-current]")) a.setAttribute("aria-current", "page");
  $("#crumb").innerHTML = g ? "<strong>Gerencia</strong> · Operaciones Colombia" : "<strong>Asignación de transporte</strong> · Operaciones Colombia";
  if (g) { cerrarCajon(); gerencia.mostrar(); }
}
window.addEventListener("hashchange", ruta);
ruta();

(async function iniciar() {
  pintarLista(); pintarDetalle();
  try { S.catalogo = await Api.catalogo(); } catch { S.status = "error"; S.error = "No pude cargar el catálogo. ¿Está corriendo el servidor?"; pintarDetalle(); return; }
  await cargarBandeja();
  pintarLista(); pintarDetalle();
  const id = Number(new URLSearchParams(location.search).get("sol"));
  const primera = (id && S.bandeja.find((s) => s.id === id)) || null;
  if (primera) abrir(primera.id);
  setInterval(cargarBandeja, 3000);
  setInterval(() => { if (S.lista) pintarLista(); }, 30000);
})();
