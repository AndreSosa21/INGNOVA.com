// Componentes: funciones puras que devuelven HTML a partir de datos del contrato. Sin cálculo de negocio.
import { esc, cop, pct, pct0, horas, plazo, dec, num, pts, fechaCorta, corto } from "./fmt.js";

export const ESTRATEGIAS = {
  equilibrada: { nombre: "Equilibrada", frase: "Pesos del perfil de este envío" },
  economica: { nombre: "Más económica", frase: "Prioriza el precio" },
  confiable: { nombre: "Más confiable", frase: "Prioriza el historial y la puntualidad" },
};
/** El nombre de la tarjeta lo mide el servidor: "Alternativa" cuando la etiqueta de la estrategia no sería cierta. */
export const nombreDe = (o) => o.etiqueta ?? ESTRATEGIAS[o.estrategia].nombre;
const iconoDe = (o) => ICONOS[o.etiqueta === "Alternativa" ? "alternativa" : o.estrategia];
const ICONOS = {
  alternativa: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h9"/></svg>',
  equilibrada: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M5 8h14"/><path d="M5 8l-2.5 6a3 3 0 0 0 5 0L5 8zM19 8l-2.5 6a3 3 0 0 0 5 0L19 8z"/></svg>',
  economica: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M8.5 12h7"/></svg>',
  confiable: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/></svg>',
};
export const FACTORES = {
  precio: "Precio", tiempo: "Tiempo de tránsito", confiabilidad: "Confiabilidad reciente", historial: "Historial y calidad",
  holgura: "Capacidad libre", segmento: "Desempeño en este segmento", exito: "Éxito simulado",
};
const SEMAFORO = {
  verde: ["Riesgo bajo", '<svg viewBox="0 0 10 10" aria-hidden="true"><circle cx="5" cy="5" r="4.5" fill="currentColor"/></svg>'],
  amarillo: ["Riesgo medio", '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 .8l4.6 8.4H.4z" fill="currentColor"/></svg>'],
  rojo: ["Riesgo alto", '<svg viewBox="0 0 10 10" aria-hidden="true"><rect x=".8" y=".8" width="8.4" height="8.4" fill="currentColor"/></svg>'],
};
export const SemaforoRiesgo = (s) => `<span class="semaforo" data-s="${esc(s)}">${SEMAFORO[s]?.[1] ?? ""}${SEMAFORO[s]?.[0] ?? esc(s)}</span>`;

export const Pasos = (indice, pasos = ["Recibida", "En análisis", "Asignada"]) =>
  `<ol class="pasos" aria-label="Estado de la solicitud">${pasos.map((p, i) => `<li data-estado="${i < indice ? "hecho" : i === indice ? "actual" : "futuro"}" ${i === indice ? 'aria-current="step"' : ""}><i></i>${p}</li>`).join("")}</ol>`;

export const FiltroFijo = (texto) =>
  `<span class="chip fijo" title="Regla fija: no se puede quitar"><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>${esc(texto)}</span>`;

const ESTADOS_CHIP = ["neutral", "prefiero", "exijo"];
export const siguienteEstado = (e) => ESTADOS_CHIP[(ESTADOS_CHIP.indexOf(e) + 1) % 3];
export const ChipFactor = ({ clave, nombre, estado, peso, param }) => {
  const input = estado === "exijo" && param
    ? `<input class="param" type="number" inputmode="decimal" data-param="${clave}" value="${param.valor ?? ""}" placeholder="${esc(param.hint)}" aria-label="${esc(param.etiqueta)}">` : "";
  return `<span style="display:inline-flex;gap:6px;align-items:center"><button class="chip" type="button" data-act="chip" data-clave="${clave}" data-estado="${estado}" aria-label="${esc(nombre)}: ${estado}. Cambiar">${esc(nombre)} <span class="estado">${estado} · peso ${pct0(peso)}</span></button>${input}</span>`;
};

export const MedidorCapacidad = (libres, pide) => {
  const total = Math.min(Math.max(libres, pide, 4), 10);
  let h = "";
  for (let i = 0; i < total; i++) h += `<i class="${i < pide ? "pide" : i < libres ? "on" : ""}"></i>`;
  return `<div class="medidor" role="img" aria-label="${libres} libres, ${pide} pedidos">${h}</div>`;
};

export const ListaDescartados = (lista) => {
  const ETAPA = { filtro: "Regla fija", capacidad: "Sin cupo", restriccion: "Tu condición", pareto: "Superado por otro" };
  if (!lista.length) return `<p class="muted">Nadie quedó fuera.</p>`;
  return `<ul class="descartados">${lista.map((d) => `<li><strong>${esc(d.proveedor)}</strong><span class="etapa">${ETAPA[d.etapa] ?? esc(d.etapa)}</span><span>${esc(d.motivo)}</span></li>`).join("")}</ul>`;
};

export const BarrasContribucion = (opciones, factores) => {
  const max = Math.max(...opciones.flatMap((o) => factores.map((f) => o.aportes[f] ?? 0)), 1);
  return `<div class="contrib">${factores.map((f) => `<div class="fila"><span class="k">${FACTORES[f]}</span><div class="barras">${opciones.map((o, i) => `<div class="barra" data-i="${i}"><span class="track"><span class="fill" style="width:${((o.aportes[f] ?? 0) / max) * 100}%"></span></span><span class="n num">${dec(o.aportes[f] ?? 0)}</span></div>`).join("")}</div></div>`).join("")}</div>`;
};

export const DiferenciaPorFactor = (porFactor) => {
  const items = Object.entries(porFactor).filter(([, v]) => v !== 0);
  const max = Math.max(...items.map(([, v]) => Math.abs(v)), 1);
  return `<div class="dif">${items.sort((a, b) => b[1] - a[1]).map(([k, v]) => {
    const w = (Math.abs(v) / max) * 50;
    const style = v >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`;
    return `<div class="d"><span class="muted">${FACTORES[k] ?? k}</span><span class="eje"><i style="${style}"></i></span><span class="num" style="text-align:right">${pts(v)} pts</span></div>`;
  }).join("")}</div>`;
};

/** Lo que se sacrifica frente a las otras opciones; sale de los datos de las tres tarjetas. */
export function sacrificios(opcion, todas) {
  const otras = todas.filter((o) => o.proveedor !== opcion.proveedor);
  const mejorCosto = otras.reduce((m, o) => (o.costo_esperado_cop < m.costo_esperado_cop ? o : m), opcion);
  const mejorT = otras.reduce((m, o) => (o.tiempo_p90_h < m.tiempo_p90_h ? o : m), opcion);
  const mejorE = otras.reduce((m, o) => (o.p_exito > m.p_exito ? o : m), opcion);
  const cand = [];
  if (mejorCosto !== opcion) cand.push([(opcion.costo_esperado_cop - mejorCosto.costo_esperado_cop) / mejorCosto.costo_esperado_cop, `Pagas ${cop(opcion.costo_esperado_cop - mejorCosto.costo_esperado_cop)} más que con ${corto(mejorCosto.proveedor)}.`]);
  if (mejorT !== opcion) cand.push([(opcion.tiempo_p90_h - mejorT.tiempo_p90_h) / mejorT.tiempo_p90_h, `Tarda hasta ${dec(opcion.tiempo_p90_h - mejorT.tiempo_p90_h)} h más que ${corto(mejorT.proveedor)} (P90).`]);
  if (mejorE !== opcion) cand.push([mejorE.p_exito - opcion.p_exito, `${dec((mejorE.p_exito - opcion.p_exito) * 100)} puntos menos de éxito que ${corto(mejorE.proveedor)}.`]);
  const frases = cand.filter((c) => c[0] > 0.0005).sort((a, b) => b[0] - a[0]).slice(0, 2).map((c) => c[1]);
  return frases.length ? frases : ["Frente a las otras dos no pierdes en costo, tiempo ni éxito."];
}
export const incompleto = (o) => o.confianza === "baja" || (o.datos_propios != null && o.datos_propios < 0.3) || o.servicios_en_segmento < 15;

/** La opción en la pantalla principal: tres números, una razón, un sacrificio, y dos acciones. */
export function TarjetaOpcion(o, ctx) {
  const nombre = nombreDe(o);
  const sel = ctx.asignado === o.proveedor;
  return `<article class="card" data-est="${o.estrategia}" data-reco="${o.estrategia === "equilibrada"}" data-sel="${sel}" aria-label="${nombre}: ${esc(o.proveedor)}">
    <div class="c-top">
      <div class="c-est">${iconoDe(o)}${nombre}${o.estrategia === "equilibrada" ? '<span class="c-reco">Recomendada</span>' : ""}</div>
      <h3 class="c-prov">${esc(o.proveedor)}</h3>
    </div>
    <div class="c-exito"><div class="big num" title="Probabilidad de que salga bien: a tiempo, sin daño y dentro del presupuesto">${pct0(o.p_exito)}<small>de éxito</small></div>${SemaforoRiesgo(o.semaforo)}</div>
    <div class="c-num">
      <div><span>Costo esperado</span><b class="num">${cop(o.costo_esperado_cop)}</b></div>
      <div><span>Tarda hasta</span><b class="num">${horas(o.tiempo_p90_h)} <small>plazo ${plazo(ctx.solicitud.plazo_horas)}</small></b></div>
      <div><span>Vehículos libres</span><b class="num">${num(o.vehiculos_libres)}</b></div>
    </div>
    <div class="c-razon">
      <p><span>Por qué está aquí</span>${esc(o.razones[0] ? o.razones[0][0].toUpperCase() + o.razones[0].slice(1) : "Cumple las condiciones del envío")}.</p>
      <p><span>Qué sacrificas</span>${esc(sacrificios(o, ctx.opciones)[0])}</p>
    </div>
    <div class="c-acc">
      <button class="btn ${o.estrategia === "equilibrada" ? "primary" : ""}" type="button" data-act="elegir" data-est="${o.estrategia}" ${ctx.asignado ? "disabled" : ""}>Elegir</button>
      <button class="btn" type="button" data-act="detalle" data-est="${o.estrategia}">Ver detalle</button>
    </div>
  </article>`;
}

/** Cajón con todo lo de una opción: los 7 factores, de dónde sale el puntaje, señales y la ficha del proveedor. */
export function DetalleOpcion(o, ctx, perfil) {
  const s = ctx.solicitud;
  const margen = s.plazo_horas - o.tiempo_p90_h;
  const [ic0, ic1] = o.intervalo_confiabilidad;
  const seg = perfil ? (() => {
    const mismo = (x) => x.segmento.endsWith(`· ${s.tipo_carga}`);
    const f = perfil.fortalezas.find(mismo) ?? perfil.fortalezas[0], w = perfil.debilidades.find(mismo) ?? perfil.debilidades[0];
    const t = (x) => `${esc(x.segmento)}: ${pct0(x.confiabilidad)} frente a ${pct0(x.mercado)} del mercado`;
    return f || w ? `${f ? `<b>Fuerte</b><span class="sub">${t(f)}</span>` : ""}${w ? `<b>Débil</b><span class="sub">${t(w)}</span>` : ""}` : '<span class="sub">Nada se separa del mercado.</span>';
  })() : '<span class="sub">Cargando perfil…</span>';
  const factores = Object.keys(o.aportes).filter((f) => f !== "exito" && o.aportes[f] > 0);
  return `<div>
    <ul class="factores">
      <li><span class="k">Precio</span><span><b class="num">${cop(o.costo_esperado_cop)}</b><span class="sub">esperado · en el peor 10% de los casos ${cop(o.costo_p90_cop)}</span></span></li>
      <li><span class="k">Tiempo de tránsito</span><span><b class="num">Típico ${horas(o.tiempo_p50_h)} · hasta ${horas(o.tiempo_p90_h)}</b><span class="sub">${margen >= 0 ? `Deja ${horas(margen)} de margen sobre el plazo de ${plazo(s.plazo_horas)}` : `Pasa ${horas(-margen)} del plazo de ${plazo(s.plazo_horas)} en el peor 10%`}</span></span></li>
      <li><span class="k">Vehículo disponible</span><span><b>${esc(s.tipo_vehiculo)}</b><span class="sub num">${num(o.vehiculos_libres)} libres el ${fechaCorta(s.fecha)}</span></span></li>
      <li><span class="k">Capacidad</span><span><b class="num">pides ${num(s.unidades)} · hay ${num(o.vehiculos_libres)}</b>${MedidorCapacidad(o.vehiculos_libres, s.unidades)}</span></li>
      <li><span class="k">Desempeño histórico</span><span><b class="num">${pct0(o.p_a_tiempo)} a tiempo</b><span class="sub num">daño ${pct(o.p_dano)} · ${num(o.servicios_en_segmento)} servicios en este segmento${incompleto(o) ? '<span class="dato-inc">dato incompleto</span>' : ""}</span></span></li>
      <li><span class="k">Confiabilidad</span><span><b class="num">${pct(o.confiabilidad)}</b><span class="sub num">rango probable ${pct0(ic0)} a ${pct0(ic1)}</span></span></li>
      <li><span class="k">Fortalezas y debilidades</span><span>${seg}</span></li>
    </ul>
    <h3>De dónde sale el puntaje (${dec(o.puntaje)} de 100)</h3>
    ${BarrasContribucion([o], factores)}
    ${o.senales.length ? `<h3>Señales</h3><ul class="lista-simple">${o.senales.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <h3>Cómo le ha ido en los últimos meses</h3>
    ${perfil ? CartaControl(perfil.carta_control_otd) + (perfil.riesgos.length ? `<ul class="lista-simple" style="margin-top:8px">${perfil.riesgos.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : "") : '<div class="sk" style="height:160px"></div>'}
    <h3>Preguntar al Copiloto</h3>
    <div class="preguntas">
      <button class="preg" type="button" data-act="preguntar" data-q="¿Qué sacrificas con ${esc(o.proveedor)}?">¿Qué sacrificas?</button>
      <button class="preg" type="button" data-act="preguntar" data-q="¿Qué pasa si ${esc(o.proveedor)} falla?">¿Y si falla?</button>
      <button class="preg" type="button" data-act="preguntar" data-q="Compara ${esc(o.proveedor)} con la siguiente opción">Comparar con…</button>
    </div>
  </div>`;
}

export const Esqueleto = () =>
  `<div class="cards" aria-busy="true" aria-label="Calculando opciones">${[0, 1, 2].map(() => `<div class="card sk-card"><div class="sk" style="height:16px;width:40%"></div><div class="sk" style="height:22px;width:70%"></div><div class="sk" style="height:34px;width:40%"></div>${'<div class="sk" style="height:14px"></div>'.repeat(5)}</div>`).join("")}</div>`;

export const Estado = (titulo, texto, boton, h = "h2") => `<div class="vacio"><${h}>${esc(titulo)}</${h}><p>${esc(texto)}</p>${boton ?? ""}</div>`;

export function GraficoCostoP90(ranking, estrategias, plazo) {
  const W = 640, H = 300, m = { l: 74, r: 24, t: 14, b: 38 };
  const xs = ranking.map((o) => o.tiempo_p90_h).concat(plazo);
  const ys = ranking.map((o) => o.costo_esperado_cop);
  const x0 = Math.floor(Math.min(...xs) - 2), x1 = Math.ceil(Math.max(...xs) + 2);
  const y0 = Math.floor(Math.min(...ys) / 250000) * 250000 - 250000, y1 = Math.ceil(Math.max(...ys) / 250000) * 250000 + 250000;
  const X = (v) => m.l + ((v - x0) / (x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const tY = [0, 1, 2, 3, 4].map((i) => y0 + ((y1 - y0) * i) / 4), tX = [0, 1, 2, 3, 4].map((i) => x0 + ((x1 - x0) * i) / 4);
  const marca = { equilibrada: "#1b6c80", economica: "#131416", confiable: "#626a70" };
  const porProv = Object.fromEntries(Object.values(estrategias).map((o) => [o.proveedor, o.estrategia]));
  return `<svg class="scatter" viewBox="0 0 ${W} ${H}" role="img" aria-label="Costo esperado contra tiempo P90 por proveedor" width="100%">
    ${tY.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#eef1f3"/><text x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${(t / 1e6).toFixed(2).replace(".", ",")} M</text>`).join("")}
    ${tX.map((t) => `<text x="${X(t)}" y="${H - m.b + 16}" text-anchor="middle">${t.toFixed(0)} h</text>`).join("")}
    <line x1="${X(plazo)}" x2="${X(plazo)}" y1="${m.t}" y2="${H - m.b}" stroke="#131416" stroke-dasharray="4 3"/>
    <text x="${X(plazo) + 4}" y="${m.t + 10}">Plazo ${plazo} h</text>
    ${ranking.map((o) => {
      const est = porProv[o.proveedor];
      const cx = X(o.tiempo_p90_h), cy = Y(o.costo_esperado_cop);
      const mk = est ? `<circle cx="${cx}" cy="${cy}" r="7" fill="${marca[est]}"/>` : `<rect x="${cx - 4.5}" y="${cy - 4.5}" width="9" height="9" fill="#fff" stroke="#626a70" stroke-width="1.5"/>`;
      return `${mk}<text class="pt-lbl" x="${cx + 11}" y="${cy + 4}">${esc(corto(o.proveedor))}</text>`;
    }).join("")}
    <text x="${(W + m.l) / 2}" y="${H - 2}" text-anchor="middle">Tiempo hasta el que llega (más a la izquierda es más rápido)</text>
  </svg>
  <div class="leyenda">${Object.values(estrategias).map((o) => `<span><i style="background:${marca[o.estrategia]}"></i>${nombreDe(o)}</span>`).join("")}<span><i style="background:#fff;border:1.5px solid #626a70"></i>Otras del ranking</span></div>`;
}

export function CartaControl(carta) {
  const W = 480, H = 180, m = { l: 40, r: 16, t: 14, b: 28 };
  const vals = carta.flatMap((c) => [c.otd, c.limite_inferior]);
  const lo = Math.floor((Math.min(...vals) - 0.03) * 20) / 20, hi = Math.min(1, Math.ceil((Math.max(...vals) + 0.02) * 20) / 20);
  const X = (i) => m.l + (i / Math.max(carta.length - 1, 1)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
  const linea = carta.map((c, i) => `${i ? "L" : "M"}${X(i)},${Y(c.otd)}`).join(" ");
  const lim = carta.map((c, i) => `${i ? "L" : "M"}${X(i)},${Y(c.limite_inferior)}`).join(" ");
  const ticks = [0, 1, 2, 3].map((i) => lo + ((hi - lo) * i) / 3);
  return `<svg class="carta" viewBox="0 0 ${W} ${H}" role="img" aria-label="Puntualidad mes a mes con su límite de control">
    ${ticks.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#eef1f3"/><text x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end">${(t * 100).toFixed(0)}%</text>`).join("")}
    <path d="${lim}" fill="none" stroke="#626a70" stroke-dasharray="4 3" stroke-width="1.2"/>
    <path d="${linea}" fill="none" stroke="#1b6c80" stroke-width="2"/>
    ${carta.map((c, i) => {
      const fuera = c.otd < c.limite_inferior;
      return `${fuera ? `<rect x="${X(i) - 5}" y="${Y(c.otd) - 5}" width="10" height="10" fill="#b3261e"/><text class="fuera-lbl" x="${X(i)}" y="${Y(c.otd) + 20}" text-anchor="middle">fuera</text>` : `<circle cx="${X(i)}" cy="${Y(c.otd)}" r="3.2" fill="#1b6c80"/>`}<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${c.mes.slice(5)}</text>`;
    }).join("")}
  </svg>
  <div class="leyenda"><span><i style="background:#1b6c80"></i>% a tiempo del mes</span><span><i style="background:#fff;border:1.5px dashed #626a70"></i>Límite de control</span><span><i style="background:#b3261e"></i>Mes fuera del límite</span></div>`;
}
