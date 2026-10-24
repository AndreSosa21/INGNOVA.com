"""API HTTP del dashboard: envuelve cosco.motor.api y sirve web/.

    python -m uvicorn cosco.server:app --port 8000      ->  http://localhost:8000

El dashboard consume exactamente el contrato de cosco.motor.api. Lo único que se agrega aquí son las
tres estrategias (mismo motor, otro perfil de pesos): Equilibrada = perfil de la solicitud,
Más económica = Costo, Más confiable = Crítico. Si dos coinciden en proveedor, la segunda muestra el
siguiente distinto. No hay endpoint para asignar: la persona decide (POST /api/decision solo registra).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cosco import gerencia, solicitudes
from cosco.motor import api
from cosco.motor.datos import politicas

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Copiloto de asignación · COSCO")

ESTRATEGIAS = (("equilibrada", None), ("economica", "Costo"), ("confiable", "Crítico"))


class Consulta(BaseModel):
    solicitud: dict
    requisitos: list[dict] = Field(default_factory=list)


class Explicacion(Consulta):
    a: str
    b: str


class Simulacion(Consulta):
    cambio: dict


class Decision(BaseModel):
    solicitud: dict | None = None
    solicitud_id: int | None = None
    requisitos: list[dict] = Field(default_factory=list)
    proveedor_elegido: str
    proveedor_recomendado: str | None = None
    exito_predicho: float | None = None
    motivo: str | None = None
    usuario: str | None = "Operaciones"


class Cierre(BaseModel):
    decision_id: int
    a_tiempo: bool
    tiempo_real_h: float
    costo_final_cop: float
    dano_carga: bool = False
    calificacion_cliente: int = Field(5, ge=1, le=5)


def _estrategias(solicitud: dict, requisitos: list[dict]) -> dict:
    """Corre el embudo con los tres perfiles y elige una opción distinta por estrategia."""
    base = api.consultar_ranking(solicitud, requisitos)
    resultado = {"respuesta": base, "estrategias": {}, "perfiles": {}}
    if base["sin_opcion"]:
        return resultado
    usados: set[str] = set()
    for clave, perfil in ESTRATEGIAS:
        r = base if perfil is None else api.consultar_ranking(dict(solicitud, perfil=perfil), requisitos)
        elegido = next((o for o in r["ranking"] if o["proveedor"] not in usados and not o.get("dominado_por")), None)
        if elegido is None:
            continue
        usados.add(elegido["proveedor"])
        resultado["estrategias"][clave] = dict(elegido, estrategia=clave, coincide_con_primera=elegido["posicion"] != 1)
        resultado["perfiles"][clave] = r["pesos"]
    return resultado


@app.post("/api/ranking")
def ranking(c: Consulta):
    try:
        return _estrategias(c.solicitud, c.requisitos)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/explicar")
def explicar(c: Explicacion):
    return api.explicar_diferencia(c.a, c.b, c.solicitud, c.requisitos)


@app.post("/api/simular")
def simular(c: Simulacion):
    return api.simular_cambio(c.solicitud, c.requisitos, c.cambio)


@app.get("/api/proveedor/{nombre}")
def proveedor(nombre: str):
    try:
        return api.perfil_proveedor(nombre)
    except KeyError as e:
        raise HTTPException(404, f"No hay un proveedor llamado {nombre}") from e


@app.post("/api/decision")
def decision(d: Decision):
    try:
        sid = d.solicitud_id or api.crear_solicitud(d.solicitud)
        return api.registrar_decision(sid, d.proveedor_elegido, d.proveedor_recomendado, d.exito_predicho,
                                      d.motivo, d.usuario, d.requisitos)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/cerrar")
def cerrar(c: Cierre):
    """Registra cómo salió el servicio. El bandido aprende de esto; la solicitud pasa a Cerrada."""
    try:
        return api.cerrar_servicio(c.decision_id, c.a_tiempo, c.tiempo_real_h, c.costo_final_cop, c.dano_carga,
                                   c.calificacion_cliente)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/gerencia")
def tablero_gerencia(meses: int = 6, region: str | None = None, tipo_vehiculo: str | None = None):
    """Tableros de gerencia: precios, tiempos, capacidad, flota y tendencias (ver cosco/gerencia.py)."""
    try:
        return gerencia.tablero(meses, region or None, tipo_vehiculo or None)
    except KeyError as e:
        raise HTTPException(422, f"No existe {e}") from e


@app.get("/api/bandeja")
def bandeja():
    """Solicitudes que llegaron del portal, más recientes primero."""
    return solicitudes.bandeja()


@app.post("/api/solicitudes")
def crear_solicitud(datos: dict):
    """Crea una solicitud en la bandeja desde el dashboard (por ejemplo, la que el Copiloto sacó de un correo)."""
    try:
        return solicitudes.crear(datos)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/solicitudes/{sid}")
def solicitud(sid: int):
    try:
        s = solicitudes.obtener(sid)
    except KeyError as e:
        raise HTTPException(404, f"No existe la solicitud {sid}") from e
    return dict(s, motor=solicitudes.a_dict_motor(s))


@app.post("/api/solicitudes/{sid}/analisis")
def analisis(sid: int):
    solicitudes.marcar_en_analisis(sid)
    return solicitudes.estado_publico(sid)


@app.post("/api/solicitudes/{sid}/transito")
def transito(sid: int):
    try:
        return solicitudes.marcar_en_transito(sid)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


EJEMPLOS = [
    dict(contacto="Ejemplo A", empresa="Cliente de ejemplo", origen="Buenaventura", destino="Bogotá", tipo_carga="Contenedor seco",
         unidades=1, plazo_horas=36, prioridad="Tiempo", fecha="2026-10-25", peso_t=22,
         notas="Caso A: un contenedor seco con plazo corto."),
    dict(contacto="Ejemplo B", empresa="Cliente de ejemplo", origen="Buenaventura", destino="Bogotá", tipo_carga="Contenedor refrigerado",
         unidades=2, plazo_horas=40, prioridad="Carga crítica", fecha="2026-10-26", peso_t=40,
         notas="Caso B: dos refrigerados; nadie cumple solo."),
]


@app.post("/api/ejemplos")
def ejemplos():
    """Crea las dos solicitudes de demostración en la bandeja (para probar sin pasar por el portal)."""
    return [solicitudes.crear(e) for e in EJEMPLOS]


CSV = Path(__file__).resolve().parent.parent / "data" / "csv"


@app.get("/api/catalogo")
def catalogo():
    """Listas para los selectores y las reglas fijas que se muestran como filtros con candado."""
    import pandas as pd

    ciudades = pd.read_csv(CSV / "ciudades.csv")
    cargas = pd.read_csv(CSV / "tipos_carga.csv").fillna("")
    return dict(ciudades=ciudades.nombre.tolist(),
                tipos_carga=[dict(nombre=r.nombre, certificacion=r.certificacion_requerida) for r in cargas.itertuples()],
                prioridades=politicas()["prioridad_a_perfil"], perfiles=list(politicas()["perfiles"]))


@app.get("/api/memoria")
def memoria(proveedor: str | None = None, destino: str | None = None, limite: int = 3):
    """Casos pasados parecidos (memoria del Copiloto). Siempre son historia, nunca predicción."""
    import pandas as pd

    casos = pd.read_csv(CSV / "casos_memoria.csv")
    prov = pd.read_csv(CSV / "proveedores.csv").set_index("id").nombre
    ciu = pd.read_csv(CSV / "ciudades.csv").set_index("id").nombre
    casos["proveedor"] = casos.proveedor_id.map(prov)
    casos["destino"] = casos.destino_id.map(ciu)
    puntos = (casos.proveedor == proveedor).astype(int) * 2 + (casos.destino == destino).astype(int) + casos.importancia / 10
    casos = casos.assign(_p=puntos).sort_values("_p", ascending=False).head(limite)
    return [dict(fecha=str(r.fecha)[:10], titulo=r.titulo, leccion=r.leccion, proveedor=r.proveedor, destino=r.destino)
            for r in casos.itertuples()]


@app.get("/")
def raiz():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
