"""Solicitudes que llegan del portal del cliente y se atienden en el dashboard (misma BD, dos aplicaciones).

Estados de `solicitudes.estado`: pendiente (Recibida) -> en_analisis -> asignada -> atendida (Cerrada).
Nota: por convención del seeder, `solicitudes.fecha_solicitud` guarda la fecha de CARGUE; la hora en que llegó
la solicitud está en `solicitudes_portal.creada`.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import aliased

from cosco.db import get_engine
from cosco.db import models as m
from cosco.db.migrar import crear_faltantes
from cosco.motor import api
from cosco.motor.datos import politicas

ESTADO_PUBLICO = {"pendiente": "Recibida", "en_analisis": "En análisis", "asignada": "Asignada", "atendida": "Cerrada"}
PASOS = ["Recibida", "En análisis", "Asignada", "En tránsito", "Cerrada"]


def _engine(engine: Engine | None) -> Engine:
    return engine or get_engine()


def hoy() -> date:
    return politicas()["fechas"]["hoy"]


def crear(datos: dict, engine: Engine | None = None) -> dict:
    """Valida lo mínimo, guarda la solicitud (fase operacion) y los datos de contacto."""
    engine = _engine(engine)
    crear_faltantes(engine)
    if datos["origen"] == datos["destino"]:
        raise ValueError("El origen y el destino no pueden ser el mismo.")
    if int(datos["unidades"]) < 1:
        raise ValueError("Pide al menos una unidad.")
    fecha = date.fromisoformat(datos["fecha"])
    if fecha < hoy():
        raise ValueError("La fecha de cargue no puede ser anterior a hoy.")
    if float(datos["plazo_horas"]) <= 0:
        raise ValueError("El plazo de entrega debe ser mayor a cero.")
    sid = api.crear_solicitud(dict(datos, unidades=int(datos["unidades"]), plazo_horas=float(datos["plazo_horas"])), engine)
    with engine.begin() as cx:
        cx.execute(m.SolicitudPortal.__table__.insert().values(
            solicitud_id=sid, creada=datetime.now(), contacto=datos.get("contacto") or "Sin nombre",
            empresa=datos.get("empresa"), email=datos.get("email"), notas=datos.get("notas")))
    return estado_publico(sid, engine)


def estado_publico(sid: int, engine: Engine | None = None) -> dict:
    """Lo que ve el cliente: el código y en qué paso va. No incluye proveedores ni precios."""
    engine = _engine(engine)
    with engine.connect() as cx:
        s = cx.execute(select(m.Solicitud.estado).where(m.Solicitud.id == sid)).first()
    if s is None:
        raise KeyError(sid)
    paso = ESTADO_PUBLICO.get(s.estado, "Recibida")
    return dict(id=sid, codigo=f"SOL-{sid}", estado=paso, pasos=PASOS, indice=PASOS.index(paso))


def _fila(r, nombres) -> dict:
    return dict(
        id=r.id, codigo=f"SOL-{r.id}", estado=ESTADO_PUBLICO.get(r.estado, r.estado), estado_clave=r.estado,
        origen=r.origen, destino=r.destino, tipo_carga=r.tipo_carga, tipo_vehiculo=r.tipo_vehiculo,
        unidades=r.unidades, plazo_horas=r.plazo_horas, presupuesto_cop=r.presupuesto_cop, prioridad=r.prioridad,
        fecha=r.fecha_solicitud.date().isoformat(), peso_t=r.peso_t,
        creada=r.creada.isoformat(timespec="seconds") if r.creada else None,
        contacto=r.contacto, empresa=r.empresa, email=r.email, notas=r.notas)


def _consulta():
    o, d = aliased(m.Ciudad), aliased(m.Ciudad)
    return (select(m.Solicitud.id, m.Solicitud.estado, m.Solicitud.unidades, m.Solicitud.plazo_horas, m.Solicitud.presupuesto_cop,
                   m.Solicitud.prioridad, m.Solicitud.fecha_solicitud, m.Solicitud.peso_t,
                   o.nombre.label("origen"), d.nombre.label("destino"), m.TipoCarga.nombre.label("tipo_carga"),
                   m.TipoVehiculo.nombre.label("tipo_vehiculo"), m.SolicitudPortal.creada, m.SolicitudPortal.contacto,
                   m.SolicitudPortal.empresa, m.SolicitudPortal.email, m.SolicitudPortal.notas)
            .join(o, o.id == m.Solicitud.origen_id).join(d, d.id == m.Solicitud.destino_id)
            .join(m.TipoCarga, m.TipoCarga.id == m.Solicitud.tipo_carga_id)
            .join(m.TipoVehiculo, m.TipoVehiculo.id == m.Solicitud.tipo_vehiculo_id)
            .outerjoin(m.SolicitudPortal, m.SolicitudPortal.solicitud_id == m.Solicitud.id)
            .where(m.Solicitud.fase == "operacion"))


def bandeja(engine: Engine | None = None) -> list[dict]:
    """Solicitudes del portal (más recientes primero), por asignar y asignadas."""
    engine = _engine(engine)
    crear_faltantes(engine)
    with engine.connect() as cx:
        filas = cx.execute(_consulta().order_by(m.Solicitud.id.desc()).limit(60)).all()
        elegidos = _elegidos(cx, [r.id for r in filas])
    return [dict(_fila(r, None), proveedor_elegido=elegidos.get(r.id)) for r in filas]


def _elegidos(cx, ids: list[int]) -> dict[int, str]:
    """Proveedor que eligió la persona de operaciones en cada solicitud ya asignada (la última decisión)."""
    if not ids:
        return {}
    filas = cx.execute(select(m.Decision.solicitud_id, m.Proveedor.nombre).join(m.Proveedor, m.Proveedor.id == m.Decision.proveedor_elegido_id)
                       .where(m.Decision.solicitud_id.in_(ids)).order_by(m.Decision.id)).all()
    return {f.solicitud_id: f.nombre for f in filas}


def obtener(sid: int, engine: Engine | None = None) -> dict:
    engine = _engine(engine)
    with engine.connect() as cx:
        r = cx.execute(_consulta().where(m.Solicitud.id == sid)).first()
        elegido = _elegidos(cx, [sid]).get(sid)
    if r is None:
        raise KeyError(sid)
    return dict(_fila(r, None), proveedor_elegido=elegido)


def a_dict_motor(s: dict) -> dict:
    """La solicitud tal como la espera cosco.motor.api."""
    return dict(origen=s["origen"], destino=s["destino"], tipo_carga=s["tipo_carga"], unidades=s["unidades"],
                plazo_horas=s["plazo_horas"], presupuesto_cop=s["presupuesto_cop"], prioridad=s["prioridad"], fecha=s["fecha"])


def marcar_en_analisis(sid: int, engine: Engine | None = None) -> None:
    """Pasa de Recibida a En análisis cuando alguien del equipo la abre. No pisa asignada ni atendida."""
    engine = _engine(engine)
    with engine.begin() as cx:
        cx.execute(update(m.Solicitud).where((m.Solicitud.id == sid) & (m.Solicitud.estado == "pendiente"))
                   .values(estado="en_analisis"))
