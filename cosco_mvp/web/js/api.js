// Cliente del contrato de cosco.motor.api (vía cosco/server.py). La UI no calcula nada: solo consume esto.
async function post(url, cuerpo, señal) {
  const r = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(cuerpo), signal: señal });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
  return r.json();
}
async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
  return r.json();
}
export const Api = {
  catalogo: () => get("/api/catalogo"),
  bandeja: () => get("/api/bandeja"),
  analisis: (id) => post(`/api/solicitudes/${id}/analisis`, {}),
  crear: (datos) => post("/api/solicitudes", datos),
  ejemplos: () => post("/api/ejemplos", {}),
  ranking: (solicitud, requisitos, señal) => post("/api/ranking", { solicitud, requisitos }, señal),
  explicar: (solicitud, requisitos, a, b) => post("/api/explicar", { solicitud, requisitos, a, b }),
  simular: (solicitud, requisitos, cambio) => post("/api/simular", { solicitud, requisitos, cambio }),
  proveedor: (nombre) => get(`/api/proveedor/${encodeURIComponent(nombre)}`),
  memoria: (proveedor, destino) => get(`/api/memoria?proveedor=${encodeURIComponent(proveedor || "")}&destino=${encodeURIComponent(destino || "")}`),
  decision: (cuerpo) => post("/api/decision", cuerpo),
};
