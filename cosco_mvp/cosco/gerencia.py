"""Tableros de gerencia: precios, tiempos de tránsito, capacidad, disponibilidad de vehículos y tendencias.

Todo sale de los datos ya cargados por el motor (`cosco.motor.datos.datos`); aquí solo se agregan. El periodo
son los últimos `meses` hasta `hoy` (politicas.toml) y se compara con los `meses` anteriores.

    from cosco import gerencia
    gerencia.tablero(meses=6, region="Andina Centro", tipo_vehiculo="Tractomula 40' (FEU)")
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine

from cosco.db import get_engine
from cosco.db import models as m
from cosco.motor.datos import datos

VEHICULO_POR_DEFECTO = 1  # Tractomula 40' (FEU): la que más mueve el puerto
DIAS_CAPACIDAD = 14
MIN_SERVICIOS_CAMBIO = 12  # por debajo, el cambio de OTD de un proveedor es ruido


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def _resumen(v: pd.DataFrame) -> dict:
    if v.empty:
        return dict(servicios=0, otd=None, costo_km=None, sobrecosto=None, danos=None)
    return dict(servicios=int(len(v)), otd=_r(v.a_tiempo.mean()),
                costo_km=_r((v.costo_final_cop / (v.distancia_km * v.unidades)).median(), 0),
                sobrecosto=_r(v.ratio_costo.mean() - 1), danos=_r(v.dano_carga.mean(), 4))


def _decisiones(engine: Engine, desde: pd.Timestamp) -> dict:
    """Cuánto se siguió la recomendación y cómo salieron los servicios cerrados desde el portal."""
    with engine.connect() as cx:
        filas = cx.execute(select(m.Decision.proveedor_recomendado_id, m.Decision.proveedor_elegido_id,
                                  m.Decision.resultado_a_tiempo, m.Decision.fecha)).all()
    df = pd.DataFrame(filas, columns=["rec", "eleg", "a_tiempo", "fecha"])
    if df.empty:
        return dict(total=0, siguio=0, cerradas=0, cerradas_a_tiempo=0)
    df = df[pd.to_datetime(df.fecha) >= desde]
    cerradas = df[df.a_tiempo.notna()]
    return dict(total=int(len(df)), siguio=int((df.rec == df.eleg).sum()), cerradas=int(len(cerradas)),
                cerradas_a_tiempo=int(cerradas.a_tiempo.astype(bool).sum()))


def tablero(meses: int = 6, region: str | None = None, tipo_vehiculo: str | int | None = None,
            engine: Engine | None = None) -> dict:
    engine = engine or get_engine()
    d = datos(engine)
    hoy = pd.Timestamp(d.hoy)
    desde = hoy - pd.DateOffset(months=meses)
    antes = desde - pd.DateOffset(months=meses)
    region_id = d.id_de("regiones", region) if region else None
    tv = d.id_de("tipos_vehiculo", tipo_vehiculo) if tipo_vehiculo else VEHICULO_POR_DEFECTO
    nombre = d.proveedores.nombre

    v = d.viajes
    if region_id is not None:
        v = v[v.region_destino_id == region_id]
    actual = v[(v.fecha_cargue >= desde) & (v.fecha_cargue < hoy)]
    previo = v[(v.fecha_cargue >= antes) & (v.fecha_cargue < desde)]

    # ---- tendencia de puntualidad: el mercado y cada proveedor, mes a mes
    v12 = v[v.fecha_cargue >= (hoy - pd.DateOffset(months=11)).replace(day=1)]  # 12 meses calendario
    per = v12.fecha_cargue.dt.to_period("M")
    meses_eje = [str(p) for p in pd.period_range(per.min(), per.max(), freq="M")] if len(v12) else []
    mercado = v12.groupby(per).a_tiempo.mean()
    por_prov = v12.groupby([v12.proveedor_id, per]).a_tiempo.agg(["mean", "size"])
    serie = {}
    for pid in v12.proveedor_id.unique():
        s = por_prov.loc[pid]
        serie[nombre[pid]] = [(_r(s.at[pd.Period(mm), "mean"]) if pd.Period(mm) in s.index and s.at[pd.Period(mm), "size"] >= 3
                               else None) for mm in meses_eje]

    # ---- quién cambió: OTD del periodo contra el periodo anterior
    cambios = []
    for pid in d.proveedores.index:
        a, b = actual[actual.proveedor_id == pid], previo[previo.proveedor_id == pid]
        if len(a) == 0:
            continue
        fila = dict(proveedor=nombre[pid], servicios=int(len(a)), otd=_r(a.a_tiempo.mean()),
                    otd_anterior=_r(b.a_tiempo.mean()) if len(b) >= MIN_SERVICIOS_CAMBIO else None)
        fila["cambio"] = _r(fila["otd"] - fila["otd_anterior"]) if fila["otd_anterior"] is not None and len(a) >= MIN_SERVICIOS_CAMBIO else None
        cambios.append(fila)
    cambios.sort(key=lambda f: (f["cambio"] is None, f["cambio"] if f["cambio"] is not None else 0))

    # ---- tiempos de tránsito por corredor (región origen → región destino)
    reg = d.regiones.nombre
    tiempos = []
    for (o, de), g in actual.groupby(["region_origen_id", "region_destino_id"]):
        if len(g) < 10:
            continue
        tiempos.append(dict(corredor=f"{reg[o]} → {reg[de]}", servicios=int(len(g)),
                            p50_h=_r(g.tiempo_real_h.median(), 1), p90_h=_r(g.tiempo_real_h.quantile(0.9), 1),
                            estandar_h=_r(g.estandar_h.median(), 1), otd=_r(g.a_tiempo.mean()),
                            con_imprevisto=_r(g.tuvo_imprevisto.mean())))
    tiempos.sort(key=lambda f: -f["servicios"])

    # ---- precios: costo real por km (mensual) y tarifa vigente por proveedor
    ckm = v12.costo_final_cop / (v12.distancia_km * v12.unidades)
    precio_mes = ckm.groupby(per).median()
    tar = d.tarifas[(d.tarifas.tipo_vehiculo_id == tv) & (d.tarifas.vigente_desde <= d.hoy)]
    tar = tar.sort_values("vigente_desde").groupby("proveedor_id").last()
    real_prov = actual[actual.tipo_vehiculo_id == tv].groupby("proveedor_id").ratio_costo.mean()
    tarifas = sorted([dict(proveedor=nombre[pid], tarifa_km=_r(t.tarifa_km_cop, 0), cargo_fijo=_r(t.cargo_fijo_cop, 0),
                           sobrecosto=_r(real_prov.get(pid) - 1) if pid in real_prov.index else None)
                      for pid, t in tar.iterrows()], key=lambda f: f["tarifa_km"])

    # ---- capacidad: vehículos libres por proveedor y día (próximos 14 días) para el tipo elegido
    disp = d.disponibilidad[(d.disponibilidad.tipo_vehiculo_id == tv) & (d.disponibilidad.fecha >= d.hoy)]
    dias = sorted(disp.fecha.unique())[:DIAS_CAPACIDAD]
    disp = disp[disp.fecha.isin(dias)]
    capacidad = []
    for pid, g in disp.groupby("proveedor_id"):
        g = g.set_index("fecha")
        capacidad.append(dict(proveedor=nombre[pid], totales=int(g.vehiculos_totales.max()),
                              libres=[int(g.vehiculos_disponibles.get(x, 0)) for x in dias]))
    capacidad.sort(key=lambda f: -f["totales"])

    # ---- flota: disponibilidad de hoy por tipo de vehículo
    hoy_disp = d.disponibilidad[d.disponibilidad.fecha == (dias[0] if dias else d.hoy)]
    flota = []
    for t, h in hoy_disp.groupby("tipo_vehiculo_id"):
        flota.append(dict(tipo=d.nombre("tipos_vehiculo", t), proveedores=int(h.proveedor_id.nunique()),
                          totales=int(h.vehiculos_totales.sum()), libres=int(h.vehiculos_disponibles.sum())))
    flota.sort(key=lambda f: -f["totales"])

    return dict(
        hoy=str(d.hoy), meses=meses, desde=str(desde.date()), anterior_desde=str(antes.date()),
        region=reg[region_id] if region_id is not None else None, tipo_vehiculo=d.nombre("tipos_vehiculo", tv),
        opciones=dict(regiones=reg.tolist(), tipos_vehiculo=d.tipos_vehiculo.nombre.tolist()),
        resumen=_resumen(actual), resumen_anterior=_resumen(previo),
        tendencia=dict(meses=meses_eje, mercado=[_r(mercado.get(pd.Period(mm))) for mm in meses_eje], proveedores=serie),
        cambios=cambios, tiempos=tiempos[:8],
        precios=dict(meses=meses_eje, costo_km=[_r(precio_mes.get(pd.Period(mm)), 0) for mm in meses_eje], tarifas=tarifas),
        capacidad=dict(dias=[str(x) for x in dias], filas=capacidad), flota=flota,
        decisiones=_decisiones(engine, desde),
    )
