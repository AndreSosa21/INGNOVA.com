// Pantalla de Gerencia: precios, tiempos de tránsito, capacidad, flota y tendencias de desempeño (GET /api/gerencia).
// Pregunta de la pantalla: ¿cómo vienen los proveedores y dónde está el riesgo de capacidad? Todo número viene del servidor.
import { Api } from "./api.js";
import { esc, cop, num, dec, pct, pct0, horas, fechaCorta, corto } from "./fmt.js";

const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const DIA = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const mesCorto = (m) => MES[Number(m.slice(5, 7)) - 1];
const UMBRAL_CAMBIO = 0.03; // menos de 3 puntos de OTD es ruido: va en gris
const CUPO_CRITICO = 0.15;  // menos del 15 % de la flota libre ese día
// Los SVG se dibujan cerca de su ancho real para que el texto de los ejes no encoja ni crezca con la pantalla.
const MOVIL = matchMedia("(max-width: 560px)"), APILADO = matchMedia("(max-width: 1100px)");
const anchoDe = (escritorio) => (MOVIL.matches ? 360 : APILADO.matches ? 720 : escritorio);

// ---------------------------------------------------------------- gráficos (SVG propio, mismo trazo que CartaControl)
function escala(vals, paso) {
  const v = vals.filter((x) => x != null);
  const lo = Math.floor((Math.min(...v) - paso / 4) / paso) * paso, hi = Math.ceil((Math.max(...v) + paso / 4) / paso) * paso;
  const ticks = [];
  for (let t = lo; t <= hi + 1e-9; t += paso) ticks.push(t);
  return { lo, hi, ticks };
}

/** Líneas mes a mes; `series` = [{ valores, color, ancho, nombre }]. Un null corta la línea. */
function Lineas(meses, series, { paso, etiqueta, alto = 220, ancho = 720, ariaLabel }) {
  const W = ancho, H = alto, m = { l: 52, r: 12, t: 12, b: 26 };
  const { lo, hi, ticks } = escala(series.flatMap((s) => s.valores), paso);
  const X = (i) => m.l + (i / Math.max(meses.length - 1, 1)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
  const traza = (vals) => vals.reduce((d, v, i) => (v == null ? d : `${d}${i && vals[i - 1] != null ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`), "");
  return `<svg class="carta" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(ariaLabel)}">
    ${ticks.map((t) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#eef1f3"/><text x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${etiqueta(t)}</text>`).join("")}
    ${meses.map((mm, i) => (i % 2 === 0 || i === meses.length - 1) && !(i === meses.length - 2 && i % 2 === 0) ? `<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${mesCorto(mm)}</text>` : "").join("")}
    ${series.map((s) => `<path d="${traza(s.valores)}" fill="none" stroke="${s.color}" stroke-width="${s.ancho}" stroke-linejoin="round"/>
      ${s.valores.map((v, i) => (v == null ? "" : `<circle cx="${X(i)}" cy="${Y(v)}" r="${s.punto ?? 0}" fill="${s.color}"><title>${esc(s.nombre)} · ${mesCorto(meses[i])} ${meses[i].slice(0, 4)}: ${etiqueta(v, true)}</title></circle>`)).join("")}`).join("")}
  </svg>`;
}

// ---------------------------------------------------------------- bloques
function delta(a, b, { bueno, formato, umbral }) {
  if (a == null || b == null) return `<span class="kpi-d">—</span>`;
  const d = a - b;
  const signo = Math.abs(d) < umbral ? "neutro" : (d > 0) === (bueno === "sube") ? "bien" : "mal";
  return `<span class="kpi-d" data-s="${signo}">${d > 0 ? "+" : d < 0 ? "−" : "±"}${formato(Math.abs(d))}</span>`;
}

function Resumen(t) {
  const a = t.resumen, b = t.resumen_anterior, dc = t.decisiones;
  const rel = (x, y) => (x == null || y == null || !y ? null : x / y - 1);
  const celdas = [
    ["Servicios", num(a.servicios), delta(a.servicios, b.servicios, { bueno: "sube", formato: num, umbral: Infinity })],
    ["Llegaron a tiempo", pct(a.otd), delta(a.otd, b.otd, { bueno: "sube", formato: (v) => `${dec(v * 100)} pts`, umbral: 0.01 })],
    ["Costo real por km", `${cop(a.costo_km)}`, delta(rel(a.costo_km, b.costo_km), 0, { bueno: "baja", formato: (v) => pct(v), umbral: 0.01 })],
    ["Sobrecosto contra lo cotizado", pct(a.sobrecosto), delta(a.sobrecosto, b.sobrecosto, { bueno: "baja", formato: (v) => `${dec(v * 100)} pts`, umbral: 0.005 })],
    ["Carga con daño", pct(a.danos, 2), delta(a.danos, b.danos, { bueno: "baja", formato: (v) => `${dec(v * 100)} pts`, umbral: 0.001 })],
    ["Siguieron la recomendación", dc.total ? `${num(dc.siguio)} <small>de ${num(dc.total)}</small>` : "0", `<span class="kpi-d">${dc.cerradas ? `${num(dc.cerradas_a_tiempo)} de ${num(dc.cerradas)} cerradas a tiempo` : "sin servicios cerrados aún"}</span>`],
  ];
  return `<div class="kpis" role="list">${celdas.map(([k, v, d]) => `<div role="listitem"><span class="kpi-k">${k}</span><b class="kpi-v num">${v}</b>${d}</div>`).join("")}</div>
    <p class="kpi-nota">Cambios frente a los ${t.meses} meses anteriores (${fechaLarga(t.anterior_desde)} a ${fechaLarga(t.desde)}).${t.region ? ` Solo envíos con destino ${esc(t.region)}.` : ""}</p>`;
}

function Tendencia(t, sel) {
  const serie = t.tendencia.proveedores[sel];
  const series = [{ nombre: "Mercado", valores: t.tendencia.mercado, color: "#626a70", ancho: 1.5, punto: 2.5 }];
  if (serie) series.push({ nombre: sel, valores: serie, color: "#1b6c80", ancho: 2.5, punto: 3.5 });
  return `<section class="bloque b-tend" aria-labelledby="h-tend">
    <header><div><h2 id="h-tend">Puntualidad mes a mes</h2><p class="muted">% de servicios que llegaron dentro del plazo, últimos 12 meses</p></div>
      <div class="leyenda"><span><i style="background:#626a70"></i>Mercado</span>${serie ? `<span><i style="background:#1b6c80"></i>${esc(sel)}</span>` : ""}</div></header>
    ${Lineas(t.tendencia.meses, series, { paso: 0.05, alto: MOVIL.matches ? 220 : 300, ancho: anchoDe(720), etiqueta: (v) => pct0(v), ariaLabel: `Puntualidad mensual del mercado${serie ? ` y de ${sel}` : ""}` })}
    <p class="muted nota-g">Un mes con menos de 3 servicios del proveedor queda sin punto.</p>
  </section>`;
}

function Cambios(t, sel, todos) {
  const filas = t.cambios.filter((c) => c.cambio != null);
  const vista = todos ? filas : filas.slice(0, 6);
  const sinBase = t.cambios.filter((c) => c.cambio == null);
  return `<section class="bloque b-camb" aria-labelledby="h-camb">
    <header><div><h2 id="h-camb">Quién cambió</h2><p class="muted">Puntualidad de los últimos ${t.meses} meses contra los ${t.meses} anteriores</p></div></header>
    ${filas.length ? `<ul class="camb">${vista.map((c) => {
      const s = Math.abs(c.cambio) < UMBRAL_CAMBIO ? "neutro" : c.cambio > 0 ? "bien" : "mal";
      return `<li><button type="button" data-g="prov" data-p="${esc(c.proveedor)}" aria-pressed="${c.proveedor === sel}">
        <span class="n">${esc(c.proveedor)}<small>${num(c.servicios)} servicios · ${pct0(c.otd_anterior)} a ${pct0(c.otd)}</small></span>
        <span class="kpi-d" data-s="${s}">${c.cambio > 0 ? "+" : c.cambio < 0 ? "−" : "±"}${dec(Math.abs(c.cambio) * 100)} pts</span></button></li>`;
    }).join("")}</ul>
    ${filas.length > 6 ? `<button class="btn small ghost" type="button" data-g="todos">${todos ? "Ver menos" : `Ver los ${filas.length}`}</button>` : ""}` : `<p class="vacio-b">Nadie tiene servicios suficientes en los dos periodos para comparar.</p>`}
    ${sinBase.length ? `<p class="muted nota-g">Sin base para comparar: ${sinBase.map((c) => esc(corto(c.proveedor))).join(", ")}.</p>` : ""}
  </section>`;
}

function Tiempos(t) {
  const max = Math.max(...t.tiempos.map((x) => x.p90_h), 1);
  return `<section class="bloque b-tiem" aria-labelledby="h-tiem">
    <header><div><h2 id="h-tiem">Tiempos de tránsito por corredor</h2><p class="muted">Los 8 corredores con más servicios en el periodo</p></div>
      <div class="leyenda"><span><i style="background:#1b6c80"></i>De lo típico (P50) al peor 10% (P90)</span><span><i class="tick"></i>Tiempo estándar de la ruta</span></div></header>
    ${t.tiempos.length ? `<div class="tabla-marco"><table class="tabla"><thead><tr><th>Corredor</th><th class="r">Servicios</th><th class="r">Típico</th><th class="r">P90</th><th class="rango-h">Del típico al P90</th><th class="r">A tiempo</th><th class="r">Con imprevisto</th></tr></thead><tbody>
      ${t.tiempos.map((x) => `<tr><td>${esc(x.corredor)}</td><td class="r num">${num(x.servicios)}</td><td class="r num">${horas(x.p50_h)}</td><td class="r num">${horas(x.p90_h)}</td>
        <td class="rango-c"><span class="rango" role="img" aria-label="De ${horas(x.p50_h)} a ${horas(x.p90_h)}; estándar ${horas(x.estandar_h)}"><i style="left:${(x.p50_h / max) * 100}%;width:${((x.p90_h - x.p50_h) / max) * 100}%"></i><b style="left:${(x.estandar_h / max) * 100}%"></b></span></td>
        <td class="r num">${pct0(x.otd)}</td><td class="r num">${pct0(x.con_imprevisto)}</td></tr>`).join("")}
    </tbody></table></div>` : `<p class="vacio-b">Ningún corredor tiene 10 servicios o más en este periodo.</p>`}
  </section>`;
}

function Precios(t) {
  const tar = t.precios.tarifas, max = Math.max(...tar.map((x) => x.tarifa_km), 1);
  const ultimo = t.precios.costo_km.filter((x) => x != null).at(-1);
  return `<section class="bloque b-prec" aria-labelledby="h-prec">
    <header><div><h2 id="h-prec">Precios</h2><p class="muted">Tarifa vigente por km · ${esc(t.tipo_vehiculo)}</p></div></header>
    ${tar.length ? `<ul class="barlist">${tar.map((x) => `<li><span class="n">${esc(corto(x.proveedor))}</span><span class="track"><i style="width:${(x.tarifa_km / max) * 100}%"></i></span>
      <span class="v num">${cop(x.tarifa_km)}</span><span class="s num" ${x.sobrecosto != null && x.sobrecosto > 0.08 ? 'data-s="mal"' : ""} title="Sobrecosto real contra lo cotizado en el periodo">${x.sobrecosto == null ? "—" : `+${dec(x.sobrecosto * 100)}%`}</span></li>`).join("")}</ul>
      <p class="muted nota-g">La última columna es lo que terminó costando de más frente a lo cotizado, en el periodo.</p>` : `<p class="vacio-b">Nadie tiene tarifa vigente para ${esc(t.tipo_vehiculo)}.</p>`}
    <div class="sub-bloque"><p class="sub-h">Costo real por km del mercado <span class="muted num">· ${mesCorto(t.precios.meses.at(-1) ?? "2026-10")}: ${cop(ultimo)}</span></p>
      ${Lineas(t.precios.meses, [{ nombre: "Costo real por km", valores: t.precios.costo_km, color: "#131416", ancho: 1.5, punto: 2.5 }], { paso: 250, alto: MOVIL.matches ? 130 : 150, ancho: anchoDe(460), etiqueta: (v, largo) => (largo ? cop(v) : `${dec(v / 1000)} mil`), ariaLabel: "Costo real por km del mercado, mes a mes" })}</div>
  </section>`;
}

function Capacidad(t) {
  const c = t.capacidad;
  return `<section class="bloque b-cap" aria-labelledby="h-cap">
    <header><div><h2 id="h-cap">Capacidad los próximos ${c.dias.length} días</h2><p class="muted">Vehículos libres por día · ${esc(t.tipo_vehiculo)}</p></div>
      <div class="leyenda"><span><i style="background:#1b6c80;opacity:.55"></i>Más oscuro, más libres</span><span><i style="background:var(--bad-bg);border:1px solid var(--bad)"></i>Menos del 15% de su flota</span></div></header>
    ${c.filas.length ? `<div class="tabla-marco"><table class="matriz"><thead><tr><th>Proveedor</th>${c.dias.map((d) => { const f = new Date(`${d}T12:00`); return `<th class="${[0, 6].includes(f.getDay()) ? "fin" : ""}"><span>${DIA[f.getDay()]}</span>${fechaCorta(d)}</th>`; }).join("")}</tr></thead><tbody>
      ${c.filas.map((r) => `<tr><th scope="row">${esc(corto(r.proveedor))}<small>${num(r.totales)} en flota</small></th>${r.libres.map((l, i) => {
        const p = r.totales ? l / r.totales : 0, o = 0.12 + p * 0.6;
        return `<td data-c="${p < CUPO_CRITICO ? "bajo" : o >= 0.5 ? "osc" : ""}" style="${p < CUPO_CRITICO ? "" : `--p:${o.toFixed(2)}`}" title="${esc(r.proveedor)} · ${fechaCorta(c.dias[i])}: ${l} de ${r.totales} libres">${l}</td>`;
      }).join("")}</tr>`).join("")}
    </tbody><tfoot><tr><th scope="row">Todos<small>${num(c.filas.reduce((a, r) => a + r.totales, 0))} en flota</small></th>${c.dias.map((_, i) => `<td class="tot">${num(c.filas.reduce((a, r) => a + r.libres[i], 0))}</td>`).join("")}</tr></tfoot></table></div>` : `<p class="vacio-b">Nadie reportó cupo de ${esc(t.tipo_vehiculo)} para estos días.</p>`}
  </section>`;
}

function Flota(t) {
  return `<section class="bloque b-flota" aria-labelledby="h-flota">
    <header><div><h2 id="h-flota">Disponibilidad de vehículos hoy</h2><p class="muted">Libres de toda la flota, por tipo · ${fechaLarga(t.hoy)}</p></div></header>
    <ul class="barlist flota">${t.flota.map((f) => {
      const p = f.totales ? f.libres / f.totales : 0;
      return `<li><span class="n">${esc(f.tipo)}<small>${num(f.proveedores)} proveedores</small></span><span class="track"><i style="width:${p * 100}%" ${p < CUPO_CRITICO ? 'data-s="mal"' : ""}></i></span><span class="v num">${num(f.libres)} <small>de ${num(f.totales)}</small></span></li>`;
    }).join("")}</ul>
  </section>`;
}

const fechaLarga = (iso) => { const [y, m, d] = iso.split("-"); return `${Number(d)} ${MES[Number(m) - 1]} ${y}`; };

function hallazgo(t) {
  const peor = t.cambios.find((c) => c.cambio != null && c.cambio <= -0.05);
  const justa = [...t.flota].filter((f) => f.totales).sort((a, b) => a.libres / a.totales - b.libres / b.totales)[0];
  const partes = [];
  if (peor) partes.push(`<strong>${esc(peor.proveedor)}</strong> bajó su puntualidad de ${pct0(peor.otd_anterior)} a ${pct0(peor.otd)} frente a los ${t.meses} meses anteriores, con ${num(peor.servicios)} servicios en el periodo.`);
  else partes.push(`Ningún proveedor bajó su puntualidad 5 puntos o más frente a los ${t.meses} meses anteriores.`);
  if (justa && justa.libres / justa.totales < 0.25) partes.push(`Hoy solo quedan ${num(justa.libres)} de ${num(justa.totales)} ${esc(justa.tipo)} libres.`);
  return { texto: partes.join(" "), proveedor: peor?.proveedor };
}

// ---------------------------------------------------------------- pantalla
export function crearGerencia(el) {
  const G = { meses: 6, region: "", tipo_vehiculo: "", t: null, estado: "vacio", error: "", sel: null, todos: false };

  const filtros = () => {
    const o = G.t?.opciones;
    const sel = (id, k, etiqueta, vals, todas) => `<div class="filtro"><label for="${id}">${etiqueta}</label><select id="${id}" data-f="${k}">${todas ? `<option value="">${todas}</option>` : ""}${vals.map(([v, n]) => `<option value="${esc(v)}" ${String(G[k]) === String(v) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>`;
    return `<div class="filtros">${sel("g-meses", "meses", "Periodo", [[3, "Últimos 3 meses"], [6, "Últimos 6 meses"], [12, "Últimos 12 meses"]])}
      ${sel("g-region", "region", "Destino", (o?.regiones ?? []).map((r) => [r, r]), "Todas las regiones")}
      ${sel("g-tipo", "tipo_vehiculo", "Vehículo", (o?.tipos_vehiculo ?? []).map((r) => [r, r]), G.t ? null : "Tractomula 40' (FEU)")}</div>`;
  };

  function pintar() {
    const y = el.scrollTop;
    const t = G.t;
    let cuerpo;
    if (G.estado === "error") cuerpo = `<div class="bloque"><p>No pude cargar los tableros: ${esc(G.error)}</p><p style="margin-top:12px"><button class="btn" type="button" data-g="reintentar">Reintentar</button></p></div>`;
    else if (!t) cuerpo = `<div class="ger-grid" aria-busy="true">${["b-kpi", "b-tend", "b-camb", "b-tiem", "b-prec", "b-cap", "b-flota"].map((c) => `<div class="bloque ${c}"><div class="sk" style="height:18px;width:30%"></div><div class="sk" style="height:${c === "b-kpi" ? 48 : 180}px;margin-top:14px"></div></div>`).join("")}</div>`;
    else {
      cuerpo = `<div class="ger-grid" ${G.estado === "cargando" ? 'aria-busy="true" style="opacity:.6"' : ""}>
        <section class="bloque b-kpi" aria-label="Resumen del periodo">${Resumen(t)}</section>
        ${Tendencia(t, G.sel)}${Cambios(t, G.sel, G.todos)}${Tiempos(t)}${Flota(t)}${Precios(t)}${Capacidad(t)}</div>`;
    }
    el.innerHTML = `<div class="ger-in">
      <div class="ger-head"><div><h1>Gerencia</h1>
        <p class="hallazgo">${t ? hallazgo(t).texto : "Cargando el desempeño de los proveedores…"}</p>
        <p class="muted fresco">${t ? `Datos al ${fechaLarga(t.hoy)} · periodo desde el ${fechaLarga(t.desde)}` : ""}</p></div>${filtros()}</div>
      ${cuerpo}</div>`;
    el.scrollTop = y;
  }

  async function cargar() {
    G.estado = "cargando";
    pintar();
    try {
      const t = await Api.gerencia({ meses: G.meses, region: G.region, tipo_vehiculo: G.tipo_vehiculo });
      G.t = t; G.estado = "normal"; G.tipo_vehiculo = t.tipo_vehiculo;
      if (!G.sel || !t.tendencia.proveedores[G.sel]) G.sel = hallazgo(t).proveedor ?? t.cambios[0]?.proveedor ?? null;
    } catch (e) { G.estado = "error"; G.error = e.message; }
    pintar();
  }

  for (const q of [MOVIL, APILADO]) q.addEventListener("change", () => { if (G.t) pintar(); });
  el.addEventListener("change", (ev) => {
    const k = ev.target.dataset.f;
    if (!k) return;
    G[k] = k === "meses" ? Number(ev.target.value) : ev.target.value;
    cargar();
  });
  el.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-g]");
    if (!b) return;
    if (b.dataset.g === "prov") { G.sel = b.dataset.p; pintar(); }
    else if (b.dataset.g === "todos") { G.todos = !G.todos; pintar(); }
    else if (b.dataset.g === "reintentar") cargar();
  });

  return { mostrar() { if (!G.t && G.estado !== "cargando") cargar(); } };
}
