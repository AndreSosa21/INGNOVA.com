// Vistas del motor por dentro: los viajes del Monte Carlo contra el plazo y el cambio de confiabilidad al cerrar.
// HTML puro + un dibujo en canvas/SVG después de pintar. Los números vienen del servidor; aquí solo se dibujan.
import { esc, num, pct, pct0, plazo } from "./fmt.js";

const quieto = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const yaAnimados = new WeakSet(); // cada respuesta del servidor se anima una sola vez; los repintados la dejan quieta

// ---------------------------------------------------------------- Monte Carlo: un punto por viaje simulado
export const GraficoMC = (ops, plazoH) => {
  const con = ops.filter((o) => o.muestra_mc?.length);
  if (!con.length) return "";
  const n = con[0].escenarios, m = con[0].muestra_mc.length;
  return `<section class="mc" aria-labelledby="h-mc">
    <header><div><h2 id="h-mc">Monte Carlo: este mismo envío, simulado</h2>
      <p class="muted">Cada punto es un viaje simulado con el historial del proveedor en esta ruta, temporada y vehículo (y el del mercado cuando tiene pocos datos).</p></div>
      <div class="mc-n"><span class="muted">viajes simulados por proveedor</span><b class="num" data-mc-n>${num(n)}</b></div></header>
    <div class="mc-grid" style="grid-template-rows:repeat(${con.length}, 64px) 22px">
      ${con.map((o, i) => `<div class="mc-nom"><b>${esc(o.proveedor)}</b><span class="muted">${o.servicios_en_segmento >= 1 ? `${num(o.servicios_en_segmento)} servicios en el segmento` : "Sin historial aquí: usa el mercado"}</span></div>
        ${i === 0 ? `<div class="mc-lienzo" style="grid-row:span ${con.length}"><canvas aria-hidden="true"></canvas></div>` : ""}
        <div class="mc-pct"><b class="num" data-mc-pct="${i}">${pct0(o.p_exito)}</b><span class="muted">éxito</span></div>`).join("")}
      <span></span><div class="mc-eje" data-mc-eje></div><span></span>
    </div>
    <p class="mc-ley muted"><span><i class="ok"></i>Cumple: a tiempo, en presupuesto y sin daño</span><span><i class="mal"></i>No cumple</span><span>Se dibujan ${num(m)} de los ${num(n)} viajes; el porcentaje sale de todos. Plazo ${plazo(plazoH)}.</span></p>
    <p class="sr-only">${con.map((o) => `${o.proveedor}: ${pct0(o.p_exito)} de éxito`).join(". ")}.</p>
  </section>`;
};

let parar = null;
let alRedimensionar = null;
/** Dibuja los puntos dentro de `raiz`. Anima la primera vez que ve `datos`; después pinta el estado final. */
export function dibujarMC(raiz, ops, plazoH, datos) {
  if (parar) { parar(); parar = null; }
  const caja = raiz.querySelector(".mc-lienzo"), cv = caja?.querySelector("canvas");
  if (!cv) return;
  const filas = ops.filter((o) => o.muestra_mc?.length);
  const todos = filas.flatMap((o) => o.muestra_mc.map((p) => p[0])).sort((a, b) => a - b);
  const q = (p) => todos[Math.min(todos.length - 1, Math.floor(p * todos.length))];
  let lo = Math.min(q(0.01), plazoH * 0.9), hi = Math.max(q(0.97), plazoH * 1.15);
  const paso = hi - lo > 60 ? 10 : 5;
  lo = Math.floor(lo / paso) * paso; hi = Math.ceil(hi / paso) * paso;

  // posición vertical fija por punto (pseudoaleatoria, estable entre repintados) y orden de aparición
  const puntos = filas.map((o, k) => o.muestra_mc.map(([h, ok], i) => {
    const r1 = ((i * 9301 + 49297 + k * 233) % 233280) / 233280, r2 = ((i * 4096 + 150889 + k * 71) % 714025) / 714025;
    return { h, ok: !!ok, y: r1, o: r2 };
  }));
  const animar = !quieto() && !yaAnimados.has(datos);
  yaAnimados.add(datos);

  const colorOk = css("--accent"), colorMal = css("--bad"), colorTexto = css("--text");
  const dur = 2600, t0 = performance.now();
  let raf = 0;
  const pintar = (ahora) => {
    const w = caja.clientWidth, alto = caja.clientHeight, dpr = devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(alto * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(alto * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, alto);
    const X = (h) => 8 + ((Math.min(Math.max(h, lo), hi) - lo) / (hi - lo)) * (w - 16);
    const fila = alto / filas.length;
    const t = animar ? (ahora - t0) / dur : 2;
    filas.forEach((o, k) => {
      let vistos = 0, buenos = 0;
      puntos[k].forEach((p, i) => {
        const inicio = (i / puntos[k].length) * 0.85 * (0.85 + 0.15 * p.o) + k * 0.04;
        const edad = (t - inicio) / 0.12;
        if (edad < 0) return;
        vistos++; if (p.ok) buenos++;
        const f = easeOut(Math.min(1, edad)), yFin = k * fila + 12 + p.y * (fila - 24);
        g.globalAlpha = Math.min(1, f * 1.5) * 0.8;
        g.fillStyle = p.ok ? colorOk : colorMal;
        g.beginPath(); g.arc(X(p.h), yFin - (1 - f) * 24, edad < 0.6 && animar ? 4.5 : 3.2, 0, Math.PI * 2); g.fill();
      });
      g.globalAlpha = 1;
      const el = raiz.querySelector(`[data-mc-pct="${k}"]`);
      if (el) el.textContent = t >= 1.05 || !vistos ? pct0(o.p_exito) : pct0(buenos / vistos);
    });
    // línea del plazo, encima de los puntos
    const dx = Math.round(X(plazoH)) + 0.5;
    g.strokeStyle = colorTexto; g.lineWidth = 1.5; g.setLineDash([5, 5]);
    g.beginPath(); g.moveTo(dx, 0); g.lineTo(dx, alto); g.stroke(); g.setLineDash([]);
    g.fillStyle = colorTexto; g.font = `600 12px ${css("--font")}`;
    const etiqueta = `Plazo ${plazo(plazoH)}`, ancho = g.measureText(etiqueta).width;
    const ex = dx + 8 + ancho > w ? dx - 8 - ancho : dx + 8;
    g.fillStyle = css("--raised"); g.fillRect(ex - 4, 2, ancho + 8, 17);
    g.fillStyle = colorTexto; g.fillText(etiqueta, ex, 14);
    const nEl = raiz.querySelector("[data-mc-n]");
    if (nEl && animar) nEl.textContent = num(Math.round(filas[0].escenarios * Math.min(1, t)));
    const eje = raiz.querySelector("[data-mc-eje]");
    if (eje && !eje.dataset.listo) {
      let h = "";
      for (let v = lo; v <= hi; v += paso) h += `<span style="left:${X(v)}px">${v} h</span>`;
      eje.innerHTML = h; eje.dataset.listo = "1";
    }
    if (t < 1.1) raf = requestAnimationFrame(pintar);
  };
  raf = requestAnimationFrame(pintar);
  parar = () => cancelAnimationFrame(raf);
  if (alRedimensionar) removeEventListener("resize", alRedimensionar);
  alRedimensionar = () => { if (!caja.isConnected) return; const e = raiz.querySelector("[data-mc-eje]"); if (e) delete e.dataset.listo; requestAnimationFrame(pintar); };
  addEventListener("resize", alRedimensionar);
}

// ---------------------------------------------------------------- bandido: confiabilidad antes y después del cierre
// Densidad Beta en escala log para que alfa y beta grandes no desborden.
const lgamma = (z) => {
  const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let x = z, y = z, tmp = x + 5.5, ser = 1.000000000190015;
  tmp -= (x + 0.5) * Math.log(tmp);
  for (const ci of c) ser += ci / ++y;
  return -tmp + Math.log(2.5066282746310005 * ser / x);
};
const betaPdf = (x, a, b) => Math.exp((a - 1) * Math.log(x) + (b - 1) * Math.log(1 - x) + lgamma(a + b) - lgamma(a) - lgamma(b));

function curvas(antes, despues) {
  const W = 560, H = 180, base = H - 22;
  const sd = (p) => Math.sqrt((p.alfa * p.beta) / ((p.alfa + p.beta) ** 2 * (p.alfa + p.beta + 1)));
  const media = (p) => p.alfa / (p.alfa + p.beta);
  const lo = Math.max(0.001, Math.min(media(antes) - 4 * sd(antes), media(despues) - 4 * sd(despues)));
  const hi = Math.min(0.999, Math.max(media(antes) + 4 * sd(antes), media(despues) + 4 * sd(despues)));
  const xs = Array.from({ length: 121 }, (_, i) => lo + ((hi - lo) * i) / 120);
  const ya = xs.map((x) => betaPdf(x, antes.alfa, antes.beta)), yd = xs.map((x) => betaPdf(x, despues.alfa, despues.beta));
  const top = Math.max(...ya, ...yd) * 1.08;
  const X = (x) => 10 + ((x - lo) / (hi - lo)) * (W - 20), Y = (y) => base - (y / top) * (base - 8);
  const linea = (ys) => xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join("");
  const paso = hi - lo > 0.3 ? 0.1 : hi - lo > 0.12 ? 0.05 : 0.02;
  let marcas = "";
  for (let v = Math.ceil(lo / paso) * paso; v <= hi + 1e-9; v += paso) marcas += `<text x="${X(v)}" y="${H - 4}" text-anchor="middle">${pct0(v)}</text>`;
  return `<svg class="beta" viewBox="0 0 ${W} ${H}" role="img" aria-label="Creencia del sistema sobre la confiabilidad: antes centrada en ${pct(media(antes))}, ahora en ${pct(media(despues))}">
    <line x1="10" x2="${W - 10}" y1="${base}" y2="${base}" class="eje"/>
    <path d="${linea(ya)}" class="antes"/>
    <path d="${linea(yd)}L${X(hi)},${base}L${X(lo)},${base}Z" class="area"/>
    <path d="${linea(yd)}" class="ahora" pathLength="1"/>
    <line x1="${X(media(antes))}" x2="${X(media(antes))}" y1="${base}" y2="8" class="m-antes"/>
    <line x1="${X(media(despues))}" x2="${X(media(despues))}" y1="${base}" y2="8" class="m-ahora"/>
    ${marcas}</svg>`;
}

/** El resultado de cerrar un servicio: la cifra vieja tachada, la nueva grande y la barra que se mueve. */
export const CambioConfiabilidad = (r) => {
  const sube = r.confiabilidad_nueva >= r.confiabilidad_anterior;
  const delta = (r.confiabilidad_nueva - r.confiabilidad_anterior) * 100;
  return `<div class="conf" data-sube="${sube}" data-conf-antes="${r.confiabilidad_anterior}" data-conf-nueva="${r.confiabilidad_nueva}">
    <div class="conf-num">
      <span class="muted">Confiabilidad de ${esc(r.proveedor)} en este segmento</span>
      <div class="conf-cifras"><s class="num">${pct(r.confiabilidad_anterior)}</s><b class="num" data-conf-n>${pct(r.confiabilidad_nueva)}</b>
        <span class="conf-delta num">${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(1).replace(".", ",")} pts</span></div>
      <div class="conf-barra"><span class="fill" data-conf-fill style="width:${r.confiabilidad_nueva * 100}%"></span><span class="fantasma" style="left:${r.confiabilidad_anterior * 100}%"></span></div>
      <p>${sube ? "Llegó bien, así que el sistema confía un poco más en este proveedor." : "Este resultado le baja la confiabilidad."} El próximo ranking ya usa este resultado.</p>
    </div>
    ${r.bandido_anterior && r.bandido_nuevo ? `<div class="conf-curva"><span class="muted">Lo que cree el bandido sobre ${esc(r.proveedor)} en esta ruta (muestreo de Thompson)</span>${curvas(r.bandido_anterior, r.bandido_nuevo)}
      <p class="conf-ley muted"><span><i class="antes"></i>Antes del cierre</span><span><i class="ahora"></i>Después</span></p></div>` : ""}
  </div>`;
};

/** Mueve la barra y la cifra de la confiabilidad anterior a la nueva, una vez por resultado. */
export function animarConfiabilidad(raiz, resultado) {
  const el = raiz.querySelector(".conf");
  if (!el || quieto() || yaAnimados.has(resultado)) return;
  yaAnimados.add(resultado);
  const a = Number(el.dataset.confAntes), b = Number(el.dataset.confNueva);
  const fill = el.querySelector("[data-conf-fill]"), n = el.querySelector("[data-conf-n]");
  el.classList.add("animando");
  const t0 = performance.now(), dur = 1400;
  const paso = (ahora) => {
    const t = Math.min(1, (ahora - t0 - 300) / dur), f = easeOut(Math.max(0, t)), v = a + (b - a) * f;
    fill.style.width = `${v * 100}%`; n.textContent = pct(v);
    if (t < 1) requestAnimationFrame(paso); else el.classList.remove("animando");
  };
  requestAnimationFrame(paso);
}
