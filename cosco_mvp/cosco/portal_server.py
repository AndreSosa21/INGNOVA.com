"""Portal del cliente (aplicación aparte del dashboard, otro puerto).

    python -m uvicorn cosco.portal_server:app --port 8002     ->  http://localhost:8002

El cliente crea la solicitud y sigue su estado. Escribe en la misma BD que el dashboard del equipo
(python -m uvicorn cosco.server:app --port 8001), que la recibe en su bandeja.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cosco import solicitudes
from cosco.motor.datos import politicas, precargar

RAIZ = Path(__file__).resolve().parent.parent
app = FastAPI(title="Portal del cliente · COSCO")


@app.on_event("startup")
def _precargar():
    precargar()


class Pedido(BaseModel):
    contacto: str
    empresa: str | None = None
    email: str | None = None
    origen: str
    destino: str
    tipo_carga: str
    unidades: int
    peso_t: float = 0
    fecha: str
    plazo_horas: float
    prioridad: str = "Equilibrado"
    presupuesto_cop: float | None = None
    notas: str | None = None


@app.get("/api/catalogo")
def catalogo():
    import pandas as pd

    csv = RAIZ / "data" / "csv"
    ciudades = pd.read_csv(csv / "ciudades.csv").nombre.tolist()
    cargas = pd.read_csv(csv / "tipos_carga.csv").fillna("")
    return dict(ciudades=ciudades, hoy=str(solicitudes.hoy()), prioridades=list(politicas()["prioridad_a_perfil"]),
                tipos_carga=[dict(nombre=r.nombre, certificacion=r.certificacion_requerida) for r in cargas.itertuples()])


@app.post("/api/solicitudes")
def crear(p: Pedido):
    try:
        return solicitudes.crear(p.model_dump())
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/solicitudes/{sid}")
def estado(sid: int):
    try:
        return solicitudes.estado_publico(sid)
    except KeyError as e:
        raise HTTPException(404, f"No existe la solicitud {sid}") from e


@app.get("/")
def raiz():
    return FileResponse(RAIZ / "portal" / "index.html")


app.mount("/shared", StaticFiles(directory=RAIZ / "web" / "css"), name="shared")
app.mount("/", StaticFiles(directory=RAIZ / "portal"), name="portal")
