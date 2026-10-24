"""Funciones del motor: el contrato con el dashboard y con el asistente LLM (que las usa como herramientas).

    consultar_ranking(solicitud, requisitos)     el embudo completo
    explicar_diferencia(a, b, solicitud, ...)    "por qué no el #2" y el contrafactual
    simular_cambio(solicitud, requisitos, cambio) "¿y si...?": plazo, presupuesto, fecha, pesos
    perfil_proveedor(nombre)                     fortalezas, debilidades, carta de control y riesgos
    registrar_decision(...)                      guarda lo que eligió la persona y por qué
    cerrar_servicio(...)                         guarda el resultado real y actualiza el bandido

El agente no tiene función para asignar: la decisión siempre la toma la persona de operaciones.
Todas devuelven JSON simple. `solicitud` puede ser el id de una solicitud de la BD o un dict con nombres:
    {"origen": "Buenaventura", "destino": "Bogotá", "tipo_carga": "Contenedor refrigerado", "unidades": 2,
     "plazo_horas": 40, "presupuesto_cop": 18e6, "prioridad": "Tiempo", "fecha": "2026-10-27"}
`requisitos` es una lista como la tabla requisitos_solicitud:
    [{"factor": "tiempo", "tipo": "restriccion", "valor": 40},
     {"factor": "precio", "tipo": "preferencia", "valor": "alta"}]
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from cosco.db import get_engine
from cosco.db import models as m
from cosco.motor import bandido
from cosco.motor.datos import Datos, datos, politicas
from cosco.motor.filtros import tarifa_vigente
from cosco.motor.ranking import FACTORES, _ruta, armar_requisitos, armar_solicitud, calcular, diferencia


def _d(engine: Engine | None) -> Datos:
    return datos(engine)


# ====================================================================== consulta
def consultar_ranking(solicitud: dict | int, requisitos: list[dict] | None = None, top: int | None = None,
                      engine: Engine | None = None, muestra: int = 0) -> dict:
    """Top 3 explicado, ranking completo, descartados con su motivo, carga dividida y alternativas.

    `muestra` > 0 agrega a cada proveedor esa cantidad de viajes simulados (para el gráfico del dashboard)."""
    return calcular(_d(engine), solicitud, requisitos).a_dict(top, muestra)


def explicar_diferencia(a: str, b: str, solicitud: dict | int, requisitos: list[dict] | None = None,
                        engine: Engine | None = None) -> dict:
    """Por qué A queda por encima de B en esta solicitud (puntos por factor) y qué tendría que cambiar B."""
    d = _d(engine)
    r = calcular(d, solicitud, requisitos)
    ida, idb = d.id_de("proveedores", a), d.id_de("proveedores", b)
    por_id = {e.proveedor_id: e for e in r.ordenados}
    faltan = [d.nombre("proveedores", i) for i in (ida, idb) if i not in por_id]
    if faltan:
        motivos = {x["proveedor"]: x["motivo"] for x in r.descartados}
        return dict(error="No están los dos en el ranking", detalle={n: motivos.get(n, "sin dato") for n in faltan})
    ea, eb = por_id[ida], por_id[idb]
    if eb.puntaje > ea.puntaje:
        ea, eb = eb, ea
    return diferencia(ea, eb, r.ordenados, r.pesos)


def simular_cambio(solicitud: dict | int, requisitos: list[dict] | None, cambio: dict,
                   engine: Engine | None = None) -> dict:
    """Corre el ranking antes y después del cambio y dice qué se movió.

    cambio admite: plazo_horas, presupuesto_cop, fecha, unidades, tipo_vehiculo, perfil,
    pesos {factor: peso}, excluir [proveedores].
    """
    d = _d(engine)
    antes = calcular(d, solicitud, requisitos)
    sol2 = armar_solicitud(d, solicitud)
    req_lista = list(requisitos or [])
    for k in ("plazo_horas", "presupuesto_cop", "fecha", "unidades", "tipo_vehiculo", "perfil"):
        if k in cambio:
            base = _solicitud_a_dict(d, sol2)
            base[k] = cambio[k]
            sol2 = armar_solicitud(d, base)
    if "plazo_horas" in cambio:  # si el plazo era restricción, la restricción se mueve con él
        req_lista = [dict(q, valor=cambio["plazo_horas"]) if q["factor"] == "tiempo" and q.get("tipo") != "preferencia"
                     else q for q in req_lista]
    if "presupuesto_cop" in cambio:
        req_lista = [dict(q, valor=cambio["presupuesto_cop"]) if q["factor"] == "precio" and q.get("tipo") != "preferencia"
                     else q for q in req_lista]
    for f, w in (cambio.get("pesos") or {}).items():
        req_lista.append(dict(factor=f, tipo="preferencia", valor=w))
    for nombre in cambio.get("excluir") or []:
        req_lista.append(dict(factor="proveedor", tipo="restriccion", valor=f"excluir:{nombre}"))
    despues = calcular(d, sol2, armar_requisitos(d, sol2, req_lista))

    pos_antes = {e.nombre: i + 1 for i, e in enumerate(antes.ordenados)}
    pos_despues = {e.nombre: i + 1 for i, e in enumerate(despues.ordenados)}
    movimientos = []
    for nombre in sorted(set(pos_antes) | set(pos_despues), key=lambda n: pos_despues.get(n, 99)):
        a, b = pos_antes.get(nombre), pos_despues.get(nombre)
        if a != b:
            movimientos.append(dict(proveedor=nombre, antes=a, despues=b))
    da, dd = antes.a_dict(), despues.a_dict()
    primero_a = da["top3"][0]["proveedor"] if da["top3"] else None
    primero_d = dd["top3"][0]["proveedor"] if dd["top3"] else None
    resumen = (f"El #1 sigue siendo {primero_d}." if primero_a == primero_d
               else f"El #1 cambia de {primero_a or 'nadie'} a {primero_d or 'nadie'}.")
    return dict(cambio=cambio, resumen=resumen, top3_antes=da["top3"], top3_despues=dd["top3"],
                movimientos=movimientos, alternativas_despues=dd["alternativas"],
                carga_dividida_despues=dd["carga_dividida"], pesos_despues=dd["pesos"])


def _solicitud_a_dict(d: Datos, s) -> dict:
    return dict(origen=d.nombre("ciudades", s.origen_id), destino=d.nombre("ciudades", s.destino_id),
                tipo_carga=d.nombre("tipos_carga", s.tipo_carga_id),
                tipo_vehiculo=d.nombre("tipos_vehiculo", s.tipo_vehiculo_id), unidades=s.unidades,
                plazo_horas=s.plazo_h, presupuesto_cop=s.presupuesto_cop, perfil=s.perfil, fecha=s.fecha, id=s.id)


# ====================================================================== perfil del proveedor
def perfil_proveedor(nombre: str, engine: Engine | None = None) -> dict:
    d = _d(engine)
    pid = d.id_de("proveedores", nombre)
    p = d.proveedores.loc[pid]
    v = d.viajes[d.viajes.proveedor_id == pid]
    imp = d.imprevistos[d.imprevistos.proveedor_id == pid]

    segs = []
    for seg, g in v.groupby("segmento"):
        if len(g) < 10:
            continue
        b = bandido.posterior(d, pid, seg)
        reg, tc = map(int, seg.split("|"))
        segs.append(dict(segmento=f"hacia {d.nombre('regiones', reg)} · {d.nombre('tipos_carga', tc)}",
                         servicios=int(len(g)), confiabilidad=round(b.media, 3),
                         mercado=round(bandido.tasa_mercado(d.viajes, seg), 3)))
    segs.sort(key=lambda x: x["confiabilidad"] - x["mercado"])
    debiles = [s for s in segs if s["confiabilidad"] < s["mercado"] - 0.03][:3]
    fuertes = [s for s in reversed(segs) if s["confiabilidad"] > s["mercado"] + 0.03][:3]

    mensual = (v.assign(mes=v.fecha_cargue.dt.to_period("M").astype(str)).groupby("mes")
               .agg(servicios=("a_tiempo", "size"), otd=("a_tiempo", "mean")).tail(12))
    centro = float(v.a_tiempo.mean())
    carta = [dict(mes=mes, servicios=int(f.servicios), otd=round(float(f.otd), 3),
                  limite_inferior=round(float(max(0.0, centro - 3 * np.sqrt(centro * (1 - centro) / f.servicios))), 3))
             for mes, f in mensual.iterrows()]
    fuera = [c["mes"] for c in carta if c["otd"] < c["limite_inferior"]]

    certs = d.prov_cert[d.prov_cert.proveedor_id == pid].merge(
        d.certificaciones, left_on="certificacion_id", right_index=True)
    flota = (d.vehiculos[d.vehiculos.proveedor_id == pid].groupby("tipo_vehiculo_id")
             .agg(vehiculos=("placa", "size"), estado_promedio=("puntaje_estado", "mean")))
    reaccion_real = float(imp.tiempo_reaccion_h.mean()) if len(imp) else None
    riesgos = []
    if fuera:
        riesgos.append(f"OTD por debajo del límite de control en {', '.join(fuera)}")
    if reaccion_real and reaccion_real > 1.15 * p.tiempo_reaccion_prom_h:
        riesgos.append(f"reacción real {reaccion_real:.1f} h vs. {p.tiempo_reaccion_prom_h:.1f} h declarada")
    if len(v) < 30:
        riesgos.append(f"pocos datos: {len(v)} servicios con COSCO")
    riesgos += [f"débil {s['segmento']} ({s['confiabilidad']:.0%} vs. {s['mercado']:.0%} del mercado)" for s in debiles]
    return dict(
        proveedor=p.nombre, ciudad_base=d.nombre("ciudades", p.ciudad_base_id),
        trabaja_con_cosco_desde=str(p.fecha_inicio_cosco), servicios=int(len(v)),
        otd_historico=round(centro, 3), otd_ultimos_90d=round(float(v[v.edad_dias <= 90].a_tiempo.mean()), 3) if (v.edad_dias <= 90).any() else None,
        puntaje_cosco=float(p.puntaje_desempeno_cosco), reaccion_declarada_h=float(p.tiempo_reaccion_prom_h),
        reaccion_real_h=None if reaccion_real is None else round(reaccion_real, 1),
        tasa_imprevistos=round(float(v.tuvo_imprevisto.mean()), 3), tasa_danos=round(float(v.dano_carga.mean()), 4),
        cobertura=[d.nombre("regiones", r) for r in d.cobertura[d.cobertura.proveedor_id == pid].region_id],
        certificaciones=[dict(nombre=c.nombre, vence=str(c.vence)) for c in certs.itertuples()],
        flota=[dict(tipo=d.nombre("tipos_vehiculo", t), vehiculos=int(f.vehiculos), estado=round(float(f.estado_promedio)))
               for t, f in flota.iterrows()],
        fortalezas=fuertes, debilidades=debiles, carta_control_otd=carta, riesgos=riesgos,
    )


# ====================================================================== escritura: decisión y cierre
def crear_solicitud(solicitud: dict, engine: Engine | None = None) -> int:
    """Guarda una solicitud nueva (de operación) y devuelve su id."""
    engine = engine or get_engine()
    d = _d(engine)
    s = armar_solicitud(d, solicitud)
    with engine.begin() as cx:
        r = cx.execute(insert(m.Solicitud).values(
            fecha_solicitud=datetime.combine(s.fecha, datetime.min.time()), cliente_id=int(solicitud.get("cliente_id", 1)),
            origen_id=s.origen_id, destino_id=s.destino_id, tipo_carga_id=s.tipo_carga_id,
            tipo_vehiculo_id=s.tipo_vehiculo_id, unidades=s.unidades, peso_t=float(solicitud.get("peso_t", 0)),
            plazo_horas=s.plazo_h, presupuesto_cop=s.presupuesto_cop,
            prioridad={v: k for k, v in politicas()["prioridad_a_perfil"].items()}[s.perfil],
            fase="operacion", estado="pendiente"))
        return int(r.inserted_primary_key[0])


def registrar_decision(solicitud_id: int, proveedor_elegido: str, proveedor_recomendado: str | None = None,
                       exito_predicho: float | None = None, motivo: str | None = None, usuario: str | None = None,
                       requisitos: list[dict] | None = None, engine: Engine | None = None) -> dict:
    """Guarda lo que eligió la persona (y sus requisitos confirmados). Si eligió otro, el motivo es obligatorio."""
    engine = engine or get_engine()
    d = _d(engine)
    elegido = d.id_de("proveedores", proveedor_elegido)
    recomendado = d.id_de("proveedores", proveedor_recomendado) if proveedor_recomendado else None
    if recomendado and recomendado != elegido and not motivo:
        raise ValueError("Cuando se elige un proveedor distinto al recomendado hay que dar el motivo.")
    ahora = datetime.now()
    with engine.begin() as cx:
        r = cx.execute(insert(m.Decision).values(
            fecha=ahora, solicitud_id=solicitud_id, proveedor_recomendado_id=recomendado,
            proveedor_elegido_id=elegido, exito_predicho=exito_predicho, motivo=motivo, usuario=usuario))
        for q in requisitos or []:
            cx.execute(insert(m.RequisitoSolicitud).values(
                solicitud_id=solicitud_id, factor=q["factor"], tipo=q.get("tipo", "restriccion"),
                valor=None if q.get("valor") is None else str(q["valor"]), confirmado_por=usuario, fecha=ahora))
        cx.execute(update(m.Solicitud).where(m.Solicitud.id == solicitud_id).values(estado="asignada"))
    return dict(decision_id=int(r.inserted_primary_key[0]), solicitud_id=solicitud_id,
                proveedor_elegido=d.nombre("proveedores", elegido), cambio_manual=bool(recomendado and recomendado != elegido))


def cerrar_servicio(decision_id: int, a_tiempo: bool, tiempo_real_h: float, costo_final_cop: float,
                    dano_carga: bool = False, calificacion_cliente: int = 5, engine: Engine | None = None) -> dict:
    """Guarda el resultado real: un servicio nuevo en el historial, el resultado en la decisión y el bandido al día."""
    engine = engine or get_engine()
    d = datos(engine, recargar=True)  # la solicitud puede ser nueva
    with engine.connect() as cx:
        dec = cx.execute(select(m.Decision).where(m.Decision.id == decision_id)).mappings().one()
    if dec["resultado_a_tiempo"] is not None:
        raise ValueError(f"La decisión {decision_id} ya tiene su servicio cerrado.")
    sol = armar_solicitud(d, int(dec["solicitud_id"]))
    pid = int(dec["proveedor_elegido_id"])
    ruta = _ruta(d, sol.origen_id, sol.destino_id, sol.tipo_carga_id, sol.tipo_vehiculo_id, sol.unidades,
                 sol.plazo_h, sol.presupuesto_cop, sol.fecha)
    tarifa = tarifa_vigente(d, pid, sol.tipo_vehiculo_id, sol.fecha) or (0.0, 0.0)
    antes = bandido.posterior(d, pid, ruta.segmento)
    flota = d.vehiculos[(d.vehiculos.proveedor_id == pid) & (d.vehiculos.tipo_vehiculo_id == sol.tipo_vehiculo_id)]
    conductor = d.conductores[d.conductores.proveedor_id == pid].index[0]
    with engine.begin() as cx:
        cx.execute(insert(m.Servicio).values(
            solicitud_id=sol.id, proveedor_id=pid, vehiculo_id=int(flota.index[0]), conductor_id=int(conductor),
            fecha_cargue=datetime.combine(sol.fecha, datetime.min.time()) + timedelta(hours=8),
            distancia_km=ruta.distancia_km, unidades=sol.unidades, tiempo_planeado_h=round(ruta.estandar_h, 1),
            tiempo_real_h=tiempo_real_h, a_tiempo=a_tiempo,
            costo_cotizado_cop=round((tarifa[0] * ruta.distancia_km + tarifa[1]) * sol.unidades, -3),
            costo_final_cop=costo_final_cop, tuvo_imprevisto=False, dano_carga=dano_carga,
            calificacion_cliente=calificacion_cliente))
        cx.execute(update(m.Decision).where(m.Decision.id == decision_id).values(
            resultado_a_tiempo=a_tiempo, resultado_costo_cop=costo_final_cop))
        cx.execute(update(m.Solicitud).where(m.Solicitud.id == sol.id).values(estado="atendida"))
    d = datos(engine, recargar=True)
    b = bandido.posterior(d, pid, ruta.segmento)
    guardar_estado_bandit(engine, [dict(proveedor_id=pid, segmento=ruta.segmento, alfa=b.alfa, beta=b.beta)])
    return dict(decision_id=decision_id, proveedor=d.nombre("proveedores", pid), segmento=ruta.segmento,
                confiabilidad_anterior=round(antes.media, 3), confiabilidad_nueva=round(b.media, 3),
                servicios_en_segmento=round(b.n_efectivo, 1),
                bandido_anterior=dict(alfa=round(antes.alfa, 2), beta=round(antes.beta, 2)),
                bandido_nuevo=dict(alfa=round(b.alfa, 2), beta=round(b.beta, 2)))


def guardar_estado_bandit(engine: Engine | None = None, filas: list[dict] | None = None) -> int:
    """Guarda α y β en estado_bandit (todas las combinaciones si `filas` es None). Es un caché: se puede recalcular."""
    engine = engine or get_engine()
    if filas is None:
        filas = bandido.tabla_estado(_d(engine)).to_dict("records")
    ahora = datetime.now()
    with engine.begin() as cx:
        for f in filas:
            cx.execute(m.EstadoBandit.__table__.delete().where(
                (m.EstadoBandit.proveedor_id == f["proveedor_id"]) & (m.EstadoBandit.segmento == f["segmento"])))
        if filas:
            cx.execute(insert(m.EstadoBandit), [dict(f, alfa=float(f["alfa"]), beta=float(f["beta"]), actualizado=ahora)
                                                for f in filas])
    return len(filas)


__all__ = ["consultar_ranking", "explicar_diferencia", "simular_cambio", "perfil_proveedor", "crear_solicitud",
           "registrar_decision", "cerrar_servicio", "guardar_estado_bandit", "FACTORES"]
