// Formato es-CO: separador de miles con punto, coma decimal, COP sin símbolo ambiguo.
const n0 = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
const n1 = new Intl.NumberFormat("es-CO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const cop = (v) => (v == null ? "—" : `COP ${n0.format(Math.round(v))}`);
export const num = (v) => (v == null ? "—" : n0.format(v));
export const dec = (v) => (v == null ? "—" : n1.format(v));
export const pct = (p, d = 1) => (p == null ? "—" : `${(p * 100).toFixed(d).replace(".", ",")}%`);
export const pct0 = (p) => pct(p, 0);
export const horas = (h) => (h == null ? "—" : `${n1.format(h)} h`);
export const pts = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${n1.format(Math.abs(v))}`;
export const fechaCorta = (iso) => {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}`;
};
export const sinTildes = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
export const corto = (nombre) => nombre.replace(/\b(S\.A\.S\.|S\.A\.|Colombia|Nacional|Logística|Logística|del Pacífico|Carga)\b/g, "").replace(/\s+/g, " ").trim();

// Plazos pedidos por el cliente: horas enteras cuando lo son ("36 h"), con decimal solo si hace falta.
export const plazo = (h) => (h == null ? "—" : `${Number.isInteger(h) ? n0.format(h) : n1.format(h)} h`);
