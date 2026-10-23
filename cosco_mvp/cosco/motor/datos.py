"""Carga de datos para el motor: lee las tablas una vez y arma los marcos que usan las capas.

Todo se lee de la BD (Supabase o SQLite) y se guarda en memoria: ~11.000 servicios caben de sobra y así
cada consulta del ranking tarda menos de un segundo.
"""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from cosco.db import get_engine

RUTA_POLITICAS = Path(__file__).resolve().parents[1] / "politicas.toml"


@lru_cache(maxsize=1)
def politicas() -> dict:
    with open(RUTA_POLITICAS, "rb") as f:
        return tomllib.load(f)


def horas_estandar(dist_km: float, terreno: float, vel_kmh: float) -> float:
    """Tiempo de tránsito de referencia (el mismo cálculo de plazos que usa COSCO): manejo + descansos + trámites."""
    conduccion = dist_km * terreno / vel_kmh
    return conduccion + math.floor(conduccion / 10) * 8 + 6


def distancia_km(c1: pd.Series, c2: pd.Series) -> float:
    if c1.name == c2.name:
        return 25.0
    la1, lo1, la2, lo2 = map(math.radians, (c1.lat, c1.lon, c2.lat, c2.lon))
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(d)) * 1.38, 1)


def riesgo_corredor(r1: float, r2: float) -> float:
    return 0.6 * max(r1, r2) + 0.4 * (r1 + r2) / 2


def peso_recencia(edad_dias: np.ndarray | pd.Series, vida_media_meses: float) -> np.ndarray:
    return np.power(0.5, np.maximum(np.asarray(edad_dias, float), 0) / 30.44 / vida_media_meses)


@dataclass
class Datos:
    """Tablas de la BD indexadas por id, más el marco `viajes` (servicios + ruta + métricas derivadas)."""

    hoy: date
    ciudades: pd.DataFrame
    regiones: pd.DataFrame
    tipos_vehiculo: pd.DataFrame
    tipos_carga: pd.DataFrame
    compatibilidad: pd.DataFrame
    proveedores: pd.DataFrame
    certificaciones: pd.DataFrame
    prov_cert: pd.DataFrame
    cobertura: pd.DataFrame
    vehiculos: pd.DataFrame
    conductores: pd.DataFrame
    tarifas: pd.DataFrame
    disponibilidad: pd.DataFrame
    solicitudes: pd.DataFrame
    viajes: pd.DataFrame
    imprevistos: pd.DataFrame
    evaluaciones: pd.DataFrame
    cupo_ilimitado: bool = False  # backtest: no hay dato de cupo para fechas pasadas

    # ---- búsquedas por nombre (el agente y el dashboard trabajan con nombres)
    def id_de(self, tabla: str, nombre_o_id) -> int:
        if isinstance(nombre_o_id, (int, np.integer)):
            return int(nombre_o_id)
        df = getattr(self, tabla)
        clave = str(nombre_o_id).strip().lower()
        m = df.index[df.nombre.str.lower() == clave]
        if len(m) == 0:  # coincidencia parcial ("Antioquia" → "Antioquia Freight")
            m = df.index[df.nombre.str.lower().str.contains(clave, regex=False)]
        if len(m) != 1:
            raise ValueError(f"No encuentro '{nombre_o_id}' en {tabla}" + (f" (hay {len(m)} parecidos)" if len(m) else ""))
        return int(m[0])

    def nombre(self, tabla: str, id_: int) -> str:
        return str(getattr(self, tabla).at[int(id_), "nombre"])


def _leer(engine: Engine, tabla: str, indice: str | None = "id") -> pd.DataFrame:
    df = pd.read_sql_table(tabla, engine)
    return df.set_index(indice) if indice else df


def cargar_datos(engine: Engine | None = None, hoy: date | None = None) -> Datos:
    engine = engine or get_engine()
    pol = politicas()
    hoy = hoy or pol["fechas"]["hoy"]

    ciudades = _leer(engine, "ciudades")
    tipos_vehiculo = _leer(engine, "tipos_vehiculo")
    solicitudes = _leer(engine, "solicitudes")
    solicitudes["fecha_solicitud"] = pd.to_datetime(solicitudes.fecha_solicitud)
    servicios = _leer(engine, "servicios")
    servicios["fecha_cargue"] = pd.to_datetime(servicios.fecha_cargue)
    imprevistos = _leer(engine, "imprevistos")
    imprevistos = imprevistos.join(servicios[["proveedor_id", "fecha_cargue"]], on="servicio_id")
    servicios["retraso_imprevisto_h"] = imprevistos.groupby("servicio_id").retraso_h.sum().reindex(
        servicios.index).fillna(0.0)

    # viajes = servicios + datos de la solicitud y de la ruta
    sol = solicitudes[["origen_id", "destino_id", "tipo_carga_id", "tipo_vehiculo_id", "plazo_horas",
                       "presupuesto_cop", "unidades"]].rename(columns={"unidades": "unidades_solicitud"})
    v = servicios.join(sol, on="solicitud_id")
    co, cd = ciudades.loc[v.origen_id], ciudades.loc[v.destino_id]
    terreno = (co.factor_terreno.values + cd.factor_terreno.values) / 2
    vel = tipos_vehiculo.loc[v.tipo_vehiculo_id, "velocidad_kmh"].values * 0.94
    v["region_destino_id"] = cd.region_id.values
    v["region_origen_id"] = co.region_id.values
    v["riesgo"] = 0.6 * np.maximum(co.riesgo_vial.values, cd.riesgo_vial.values) + 0.2 * (
        co.riesgo_vial.values + cd.riesgo_vial.values)
    v["estandar_h"] = [horas_estandar(d, t, s) for d, t, s in zip(v.distancia_km, terreno, vel)]
    v["ratio_tiempo"] = v.tiempo_real_h / v.estandar_h
    v["ratio_costo"] = v.costo_final_cop / v.costo_cotizado_cop
    v["mes"] = v.fecha_cargue.dt.month
    v["edad_dias"] = (pd.Timestamp(hoy) - v.fecha_cargue).dt.total_seconds() / 86400
    v["segmento"] = v.region_destino_id.astype(str) + "|" + v.tipo_carga_id.astype(str)

    disp = _leer(engine, "disponibilidad")
    disp["fecha"] = pd.to_datetime(disp.fecha).dt.date
    prov_cert = _leer(engine, "proveedor_certificaciones", None)
    prov_cert["vence"] = pd.to_datetime(prov_cert.vence).dt.date
    tarifas = _leer(engine, "tarifas")
    tarifas["vigente_desde"] = pd.to_datetime(tarifas.vigente_desde).dt.date
    evaluaciones = _leer(engine, "evaluaciones_mensuales")
    evaluaciones["mes"] = pd.to_datetime(evaluaciones.mes).dt.date

    return Datos(
        hoy=hoy, ciudades=ciudades, regiones=_leer(engine, "regiones"), tipos_vehiculo=tipos_vehiculo,
        tipos_carga=_leer(engine, "tipos_carga"), compatibilidad=_leer(engine, "compatibilidad_carga", None),
        proveedores=_leer(engine, "proveedores"), certificaciones=_leer(engine, "certificaciones"),
        prov_cert=prov_cert, cobertura=_leer(engine, "cobertura", None), vehiculos=_leer(engine, "vehiculos"),
        conductores=_leer(engine, "conductores"), tarifas=tarifas, disponibilidad=disp, solicitudes=solicitudes,
        viajes=v, imprevistos=imprevistos, evaluaciones=evaluaciones,
    )


_CACHE: dict[str, Datos] = {}


def datos(engine: Engine | None = None, recargar: bool = False) -> Datos:
    """Datos en memoria, cargados una vez por BD. `recargar=True` después de cerrar servicios."""
    engine = engine or get_engine()
    clave = str(engine.url)
    if recargar or clave not in _CACHE:
        _CACHE[clave] = cargar_datos(engine)
    return _CACHE[clave]


def a_fecha(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return pd.Timestamp(x).date()
