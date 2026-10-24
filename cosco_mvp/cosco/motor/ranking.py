"""El embudo completo para una solicitud: filtros → Monte Carlo → restricciones → Pareto → bandido → puntaje
→ semáforo → top 3 explicado. Si nadie pasa, la cascada dice qué relajar; si el cupo no alcanza, propone
dividir la carga.

Todo lo que sale de aquí es JSON simple (dict, list, str, float), para que lo usen igual el dashboard y el
asistente LLM.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from cosco.motor import bandido, filtros
from cosco.motor.datos import Datos, a_fecha, distancia_km, horas_estandar, peso_recencia, politicas, riesgo_corredor
from cosco.motor.montecarlo import ResultadoMC, Ruta, simular

FACTORES = ["precio", "tiempo", "confiabilidad", "historial", "holgura", "segmento", "exito"]
NOMBRE_FACTOR = {
    "precio": "precio", "tiempo": "tiempo de tránsito", "confiabilidad": "confiabilidad reciente",
    "historial": "historial de incidentes y calidad", "holgura": "holgura de capacidad",
    "segmento": "desempeño en este segmento", "exito": "probabilidad de éxito (Monte Carlo)",
}
# qué factor pierde su peso cuando el requisito se vuelve restricción
FACTOR_DE_RESTRICCION = {"tiempo": "tiempo", "precio": "precio", "confiabilidad": "confiabilidad",
                         "incidentes": "historial"}
# tolerancia de la normalización: diferencias menores a esto no separan mucho a los candidatos
TOLERANCIA = {"precio": 0.15, "tiempo": 0.15, "confiabilidad": 0.10, "historial": 0.25, "holgura": 1.0,
              "segmento": 0.10, "exito": 0.10}
MENOR_ES_MEJOR = {"precio", "tiempo"}


# ====================================================================== entrada
@dataclass
class Solicitud:
    origen_id: int
    destino_id: int
    tipo_carga_id: int
    tipo_vehiculo_id: int
    unidades: int
    plazo_h: float
    presupuesto_cop: float | None
    perfil: str
    fecha: date
    id: int | None = None


@dataclass
class Requisitos:
    plazo_h: float | None = None           # restricción de fecha límite (horas)
    precio_max: float | None = None        # restricción de precio máximo (COP, total)
    confiabilidad_min: float | None = None
    sin_incidentes_dias: int | None = None
    excluir: set[int] = field(default_factory=set)
    solo: set[int] = field(default_factory=set)
    pesos: dict[str, float] = field(default_factory=dict)  # preferencias: peso nuevo por factor


def armar_solicitud(d: Datos, s: dict | int) -> Solicitud:
    """Acepta el id de una solicitud de la BD o un dict con nombres (lo que arma el formulario o el agente)."""
    pol = politicas()
    if isinstance(s, (int, np.integer)):
        f = d.solicitudes.loc[int(s)]
        return Solicitud(int(f.origen_id), int(f.destino_id), int(f.tipo_carga_id), int(f.tipo_vehiculo_id),
                         int(f.unidades), float(f.plazo_horas),
                         None if pd.isna(f.presupuesto_cop) else float(f.presupuesto_cop),
                         pol["prioridad_a_perfil"][f.prioridad], a_fecha(f.fecha_solicitud), int(s))
    o, de = d.id_de("ciudades", s["origen"]), d.id_de("ciudades", s["destino"])
    tc = d.id_de("tipos_carga", s["tipo_carga"])
    if s.get("tipo_vehiculo"):
        tv = d.id_de("tipos_vehiculo", s["tipo_vehiculo"])
    else:  # el vehículo preferido para esa carga
        comp = d.compatibilidad[d.compatibilidad.tipo_carga_id == tc].sort_values("preferencia")
        tv = int(comp.tipo_vehiculo_id.iloc[0])
    perfil = s.get("perfil") or pol["prioridad_a_perfil"].get(s.get("prioridad", "Equilibrado"), "Equilibrado")
    perfil = {"Crítico": "Critico"}.get(perfil, perfil)
    if perfil not in pol["perfiles"]:
        raise ValueError(f"Perfil '{perfil}' no existe. Opciones: {', '.join(pol['perfiles'])}")
    fecha = a_fecha(s["fecha"]) if s.get("fecha") else d.hoy + timedelta(days=1)
    plazo = s.get("plazo_horas")
    if plazo is None:  # sin plazo: el estándar de la ruta + 25 %
        plazo = round(_ruta(d, o, de, tc, tv, 1, 0, None, fecha).estandar_h * 1.25)
    return Solicitud(o, de, tc, tv, int(s.get("unidades", 1)), float(plazo), s.get("presupuesto_cop"), perfil, fecha,
                     s.get("id"))


def armar_requisitos(d: Datos, sol: Solicitud, lista: list[dict] | None) -> Requisitos:
    """Lista de requisitos como los guarda requisitos_solicitud: {factor, tipo, valor}."""
    r = Requisitos()
    for q in lista or []:
        factor, tipo, valor = q["factor"], q.get("tipo", "restriccion"), q.get("valor")
        if tipo == "preferencia":
            if factor not in FACTORES:
                raise ValueError(f"Preferencia sobre '{factor}': los factores son {', '.join(FACTORES)}")
            r.pesos[factor] = _peso_preferencia(d, sol, factor, valor)
        elif factor == "tiempo":
            r.plazo_h = float(valor) if valor is not None else sol.plazo_h
        elif factor == "precio":
            r.precio_max = float(valor) if valor is not None else sol.presupuesto_cop
        elif factor == "confiabilidad":
            r.confiabilidad_min = float(valor) if float(valor) <= 1 else float(valor) / 100
        elif factor == "incidentes":
            r.sin_incidentes_dias = int(valor or politicas()["restricciones"]["dias_incidentes"])
        elif factor == "proveedor":
            accion, nombre = str(valor).split(":", 1)
            (r.excluir if accion == "excluir" else r.solo).add(d.id_de("proveedores", nombre))
        else:
            raise ValueError(f"Restricción desconocida: {factor}")
    return r


def _peso_preferencia(d: Datos, sol: Solicitud, factor: str, valor) -> float:
    base = politicas()["perfiles"][sol.perfil].get(factor, 0.0) or 0.10
    if isinstance(valor, str):
        return base * {"alta": 1.5, "muy alta": 2.0, "baja": 0.5, "ninguna": 0.0}.get(valor.lower(), 1.0)
    return float(valor)


def pesos_finales(sol: Solicitud, req: Requisitos) -> tuple[dict[str, float], list[str]]:
    """Pesos del perfil + preferencias; un factor que pasa a restricción pierde su peso y este se reparte."""
    w = {f: politicas()["perfiles"][sol.perfil].get(f, 0.0) for f in FACTORES}
    w.update(req.pesos)
    sin_peso = []
    for nombre, valor in (("tiempo", req.plazo_h), ("precio", req.precio_max),
                          ("confiabilidad", req.confiabilidad_min), ("incidentes", req.sin_incidentes_dias)):
        if valor is not None:
            sin_peso.append(FACTOR_DE_RESTRICCION[nombre])
    for f in sin_peso:
        w[f] = 0.0
    total = sum(w.values())
    return {f: w[f] / total for f in FACTORES}, sin_peso


# ====================================================================== evaluación por proveedor
@dataclass
class Evaluado:
    proveedor_id: int
    nombre: str
    revision: filtros.Revision
    beta: bandido.Beta
    mc: ResultadoMC
    crudos: dict[str, float]
    extra: dict
    norm: dict[str, float] = field(default_factory=dict)
    puntaje: float = 0.0
    aportes: dict[str, float] = field(default_factory=dict)
    dominado_por: int | None = None
    explorado: bool = False
    alerta_critica: bool = False
    senales: list[str] = field(default_factory=list)
    semaforo: str = "verde"


def _ruta(d: Datos, o: int, de: int, tc: int, tv: int, unidades: int, plazo: float, presupuesto, fecha) -> Ruta:
    co, cd = d.ciudades.loc[o], d.ciudades.loc[de]
    dist = distancia_km(co, cd)
    vel = float(d.tipos_vehiculo.at[tv, "velocidad_kmh"]) * 0.94
    return Ruta(o, de, int(cd.region_id), tc, tv, unidades, plazo, presupuesto, fecha.month, dist,
                horas_estandar(dist, (co.factor_terreno + cd.factor_terreno) / 2, vel),
                riesgo_corredor(co.riesgo_vial, cd.riesgo_vial))


def _estadisticas_proveedor(d: Datos, pid: int, tv: int, seg: str, otd_propio: float) -> dict:
    v = d.viajes[d.viajes.proveedor_id == pid]
    seis = v[v.edad_dias <= 182]
    imp = d.imprevistos[d.imprevistos.proveedor_id == pid]
    imp6 = imp[(pd.Timestamp(d.hoy) - imp.fecha_cargue).dt.days <= 182]
    reaccion = float((imp6 if len(imp6) >= 3 else imp).tiempo_reaccion_h.mean()) if len(imp) else 4.0
    flota = d.vehiculos[(d.vehiculos.proveedor_id == pid) & (d.vehiculos.tipo_vehiculo_id == tv)].puntaje_estado.mean()
    conductores = d.conductores[d.conductores.proveedor_id == pid].puntaje_total.mean()
    tasa_imp = float(seis.tuvo_imprevisto.mean()) if len(seis) else float(v.tuvo_imprevisto.mean())
    tasa_dano = float(seis.dano_carga.mean()) if len(seis) else float(v.dano_carga.mean())
    historial = np.mean([
        np.clip(1 - tasa_imp / 0.4, 0, 1), np.clip(1 - tasa_dano / 0.05, 0, 1),
        flota / 100, conductores / 100, np.clip(1 - reaccion / 10, 0, 1),
    ])
    # desempeño en el segmento frente a su propio promedio (encogido hacia su promedio con peso 5)
    vs = v[v.segmento == seg]
    w = peso_recencia(vs.edad_dias, politicas()["bandido"]["vida_media_meses"])
    otd_seg = float((np.sum(w * vs.a_tiempo) + 5 * otd_propio) / (np.sum(w) + 5))
    # carta de control: OTD de los últimos 3 meses frente a los 9 anteriores
    rec, ant = v[v.edad_dias <= 91], v[(v.edad_dias > 91) & (v.edad_dias <= 365)]
    otd_rec = float(rec.a_tiempo.mean()) if len(rec) >= 15 else None
    otd_ant = float(ant.a_tiempo.mean()) if len(ant) >= 30 else None
    return dict(historial=float(historial), otd_segmento=otd_seg, otd_propio=otd_propio,
                servicios_segmento=int(len(vs)), servicios_total=int(len(v)),
                tasa_imprevistos_6m=tasa_imp, tasa_danos_6m=tasa_dano, reaccion_real_h=reaccion,
                reaccion_declarada_h=float(d.proveedores.at[pid, "tiempo_reaccion_prom_h"]),
                estado_flota=float(flota), puntaje_conductores=float(conductores),
                otd_3m=otd_rec, otd_9m_previos=otd_ant,
                imprevistos_recientes=int(((pd.Timestamp(d.hoy) - imp.fecha_cargue).dt.days <= 90).sum()))


def _otd_propio(d: Datos, pid: int) -> float:
    v = d.viajes[d.viajes.proveedor_id == pid]
    if v.empty:
        return 0.8
    w = peso_recencia(v.edad_dias, politicas()["bandido"]["vida_media_meses"])
    return float(np.sum(w * v.a_tiempo) / np.sum(w))


def _evaluar(d: Datos, sol: Solicitud, req: Requisitos, n: int, rng: np.random.Generator):
    """Corre filtros, Monte Carlo y restricciones. Devuelve (candidatos, parciales, descartados)."""
    plazo = req.plazo_h if req.plazo_h is not None else sol.plazo_h
    presupuesto = req.precio_max if req.precio_max is not None else sol.presupuesto_cop
    ruta = _ruta(d, sol.origen_id, sol.destino_id, sol.tipo_carga_id, sol.tipo_vehiculo_id, sol.unidades, plazo,
                 presupuesto, sol.fecha)
    pr = politicas()["restricciones"]
    candidatos, parciales, descartados = [], [], []
    for pid, prov in d.proveedores.iterrows():
        nombre = prov.nombre
        if (not prov.activo or pd.Timestamp(prov.fecha_inicio_cosco).date() > sol.fecha or pid in req.excluir
                or (req.solo and pid not in req.solo)):
            motivo = ("inactivo" if not prov.activo else "excluido por la persona" if pid in req.excluir or req.solo
                      else "todavía no trabaja con COSCO en esa fecha")
            descartados.append(dict(proveedor=nombre, etapa="filtro", motivo=motivo))
            continue
        rev = filtros.revisar(d, pid, sol.origen_id, sol.destino_id, sol.tipo_carga_id, sol.tipo_vehiculo_id,
                              sol.unidades, sol.fecha)
        if not rev.pasa and not rev.cupo_parcial:
            descartados.append(dict(proveedor=nombre, etapa="filtro", motivo=rev.motivo))
            continue
        beta = bandido.posterior(d, pid, ruta.segmento)
        otd = _otd_propio(d, pid)
        extra = _estadisticas_proveedor(d, pid, sol.tipo_vehiculo_id, ruta.segmento, otd)
        unidades_mc = sol.unidades if rev.pasa else 1
        ruta_p = replace(ruta, unidades=unidades_mc,
                         presupuesto_cop=None if presupuesto is None else presupuesto * unidades_mc / sol.unidades)
        mc = simular(d, pid, ruta_p, beta, rev.tarifa, rng, n)
        crudos = dict(precio=mc.costo_esperado / unidades_mc * sol.unidades, tiempo=mc.tiempo_p90,
                      confiabilidad=beta.media, historial=extra["historial"],
                      holgura=float(np.clip((rev.disponibles - sol.unidades) / max(sol.unidades, 1), 0, 3)),
                      segmento=extra["otd_segmento"] - extra["otd_propio"], exito=mc.p_exito)
        ev = Evaluado(pid, nombre, rev, beta, mc, crudos, extra)

        motivo = None
        if req.plazo_h is not None and mc.p_a_tiempo < pr["prob_minima_plazo"]:
            motivo = (f"solo {mc.p_a_tiempo:.0%} de probabilidad de llegar en {req.plazo_h:.0f} h "
                      f"(se exige {pr['prob_minima_plazo']:.0%})")
        elif req.precio_max is not None and mc.costo_p90 / unidades_mc * sol.unidades > req.precio_max:
            motivo = f"costo P90 de {_cop(mc.costo_p90 / unidades_mc * sol.unidades)} supera el máximo de {_cop(req.precio_max)}"
        elif req.confiabilidad_min is not None and beta.media < req.confiabilidad_min:
            motivo = f"confiabilidad reciente {beta.media:.0%} por debajo del mínimo {req.confiabilidad_min:.0%}"
        elif req.sin_incidentes_dias is not None and _incidentes(d, pid, req.sin_incidentes_dias) > 0:
            motivo = f"tuvo {_incidentes(d, pid, req.sin_incidentes_dias)} imprevistos en los últimos {req.sin_incidentes_dias} días"
        if motivo:
            descartados.append(dict(proveedor=nombre, etapa="restriccion", motivo=motivo))
            continue
        (candidatos if rev.pasa else parciales).append(ev)
        if not rev.pasa:
            descartados.append(dict(proveedor=nombre, etapa="capacidad", motivo=rev.motivo))
    return candidatos, parciales, descartados, ruta


def _incidentes(d: Datos, pid: int, dias: int) -> int:
    imp = d.imprevistos[d.imprevistos.proveedor_id == pid]
    return int(((pd.Timestamp(d.hoy) - imp.fecha_cargue).dt.days <= dias).sum())


# ====================================================================== puntaje, Pareto, bandido, semáforo
def normalizar(valores: np.ndarray, factor: str) -> np.ndarray:
    """0 a 1 entre los candidatos (1 = el mejor). La tolerancia evita que diferencias mínimas parezcan enormes."""
    lo, hi = valores.min(), valores.max()
    tol = TOLERANCIA[factor] * (lo if factor in MENOR_ES_MEJOR else 1)
    rango = max(hi - lo, tol, 1e-9)
    f = 1 - (valores - lo) / rango if factor in MENOR_ES_MEJOR else 1 - (hi - valores) / rango
    return np.clip(f, 0, 1)


def puntuar(evs: list[Evaluado], pesos: dict[str, float]) -> None:
    if not evs:
        return
    for f in FACTORES:
        norm = normalizar(np.array([e.crudos[f] for e in evs]), f)
        for e, x in zip(evs, norm):
            e.norm[f] = float(x)
    for e in evs:
        e.aportes = {f: round(100 * pesos[f] * e.norm[f], 1) for f in FACTORES}
        e.puntaje = round(sum(e.aportes.values()), 1)


def pareto(evs: list[Evaluado]) -> None:
    """Marca a quien otro supera o iguala en costo esperado, tiempo P90 y % de éxito (y supera en al menos uno).

    Un proveedor con alerta crítica (p. ej. pocos datos en carga crítica) no deja por fuera a nadie.
    """
    for a in evs:
        for b in evs:
            if a is b or b.alerta_critica:
                continue
            ca, cb = (a.crudos["precio"], a.crudos["tiempo"], -a.mc.p_exito), (b.crudos["precio"], b.crudos["tiempo"], -b.mc.p_exito)
            if all(y <= x for x, y in zip(ca, cb)) and any(y < x for x, y in zip(ca, cb)):
                if a.dominado_por is None or b.puntaje > _por_id(evs, a.dominado_por).puntaje:
                    a.dominado_por = b.proveedor_id


def _por_id(evs: list[Evaluado], pid: int) -> Evaluado:
    return next(e for e in evs if e.proveedor_id == pid)


def ordenar(evs: list[Evaluado], sol: Solicitud, rng: np.random.Generator) -> list[Evaluado]:
    """No dominados primero, por puntaje. Thompson desempata a los que están a menos del 5 % del primero."""
    pb = politicas()["bandido"]
    # quien tiene una alerta crítica (p. ej. casi seguro se pasa del presupuesto) va después de los demás
    clave = lambda e: (e.alerta_critica, -e.puntaje)  # noqa: E731
    libres = sorted([e for e in evs if e.dominado_por is None], key=clave)
    dominados = sorted([e for e in evs if e.dominado_por is not None], key=clave)
    explorar = sol.perfil != "Critico" or pb["explorar_en_critico"]
    if explorar and len(libres) > 1:
        corte = libres[0].puntaje * (1 - pb["banda_desempate"])
        empatados = [e for e in libres if e.puntaje >= corte and not e.alerta_critica]
        empatados = empatados if empatados and empatados[0] is libres[0] else []
        if len(empatados) > 1:
            muestra = {e.proveedor_id: rng.beta(e.beta.alfa, e.beta.beta) for e in empatados}
            nuevo = sorted(empatados, key=lambda e: -muestra[e.proveedor_id])
            if nuevo[0] is not empatados[0]:
                nuevo[0].explorado = True
            libres = nuevo + libres[len(empatados):]
    return libres + dominados


def semaforo(e: Evaluado, sol: Solicitud, participacion: dict[int, float], referencia: dict[str, float]) -> None:
    """Señales de riesgo. Las de variabilidad y daño se comparan con la mediana de los candidatos de esta solicitud."""
    ps = politicas()["semaforo"]
    s, critica = [], False
    p_tarde = 1 - e.mc.p_a_tiempo
    if p_tarde > ps["prob_tarde_max"]:
        s.append(f"{p_tarde:.0%} de probabilidad de pasarse del plazo")
        critica |= p_tarde > 0.5
    if e.mc.p_sobre_presupuesto > ps["prob_sobre_presupuesto_max"]:
        s.append(f"supera el presupuesto en {e.mc.p_sobre_presupuesto:.0%} de los escenarios")
        critica |= e.mc.p_sobre_presupuesto > 0.5
    if e.extra["servicios_segmento"] >= 5 and e.extra["otd_propio"] - e.extra["otd_segmento"] > ps["debilidad_segmento_pts"]:
        s.append(f"débil en este segmento ({e.extra['otd_segmento']:.0%} a tiempo vs. {e.extra['otd_propio']:.0%} en general)")
    if e.extra["otd_3m"] is not None and e.extra["otd_9m_previos"] is not None and \
            e.extra["otd_9m_previos"] - e.extra["otd_3m"] > ps["caida_otd_pts"]:
        s.append(f"OTD en caída: {e.extra['otd_3m']:.0%} en 3 meses vs. {e.extra['otd_9m_previos']:.0%} antes")
    if e.mc.tiempo_p90 / e.mc.tiempo_p50 > max(ps["p90_sobre_p50_max"], 1.15 * referencia["dispersion"]):
        s.append(f"tiempo muy variable (P90 {e.mc.tiempo_p90:.0f} h vs. P50 {e.mc.tiempo_p50:.0f} h)")
    if e.extra["servicios_segmento"] < ps["servicios_minimos"]:
        s.append(f"pocos datos en este segmento ({e.extra['servicios_segmento']} servicios)")
        critica |= sol.perfil == "Critico" and e.extra["servicios_segmento"] < ps["servicios_minimos_critico"]
    if e.revision.pasa and e.revision.disponibles - sol.unidades <= 0:
        s.append("capacidad al límite: usaría todos sus vehículos libres")
    if e.mc.p_dano > max(ps["prob_dano_min"], 1.3 * referencia["dano"]):
        s.append(f"{e.mc.p_dano:.1%} de probabilidad de daño a la carga (mediana {referencia['dano']:.1%})")
        critica |= sol.perfil == "Critico" and e.mc.p_dano > 2 * referencia["dano"]
    if participacion.get(e.proveedor_id, 0) > ps["concentracion_max"]:
        s.append(f"concentración: tiene {participacion[e.proveedor_id]:.0%} de los servicios de los últimos 90 días")
    e.senales = s
    e.alerta_critica = critica
    e.semaforo = "rojo" if critica or len(s) >= 2 else "amarillo" if s else "verde"


def participacion_90d(d: Datos) -> tuple[dict[int, float], float]:
    v = d.viajes[d.viajes.edad_dias <= 90]
    cuota = v.proveedor_id.value_counts(normalize=True)
    return {int(k): float(x) for k, x in cuota.items()}, float((cuota ** 2).sum() * 10_000)


# ====================================================================== explicaciones
def _cop(x: float) -> str:
    return f"COP {x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")


def _frase_factor(e: Evaluado, f: str) -> str:
    return {
        "precio": f"costo esperado {_cop(e.crudos['precio'])}",
        "tiempo": f"llega en {e.mc.tiempo_p90:.0f} h en el 90 % de los casos",
        "confiabilidad": f"cumple {e.beta.media:.0%} a tiempo últimamente en este segmento",
        "historial": f"buen historial (imprevistos {e.extra['tasa_imprevistos_6m']:.0%}, "
                     f"reacción real {e.extra['reaccion_real_h']:.1f} h)",
        "holgura": f"tiene {e.revision.disponibles} vehículos libres",
        "segmento": f"en este segmento cumple {e.extra['otd_segmento']:.0%} vs. {e.extra['otd_propio']:.0%} en general",
        "exito": f"{e.mc.p_exito:.0%} de probabilidad de cumplir todo (plazo, presupuesto y sin daño)",
    }[f]


def razones(e: Evaluado, evs: list[Evaluado]) -> list[str]:
    """Los 2 factores donde más aporta frente al promedio de los candidatos."""
    prom = {f: np.mean([x.aportes[f] for x in evs]) for f in FACTORES}
    mejores = sorted(FACTORES, key=lambda f: -(e.aportes[f] - prom[f]))[:2]
    return [_frase_factor(e, f) for f in mejores if e.aportes[f] - prom[f] > 0.5] or [_frase_factor(e, mejores[0])]


def diferencia(a: Evaluado, b: Evaluado, evs: list[Evaluado], pesos: dict[str, float]) -> dict:
    """Por qué A va antes que B, y qué tendría que cambiar B para pasar a A."""
    difs = sorted(((f, a.aportes[f] - b.aportes[f]) for f in FACTORES), key=lambda x: -abs(x[1]))
    a_favor = [f"{NOMBRE_FACTOR[f]} (+{x:.1f} pts)" for f, x in difs if x > 0.5]
    en_contra = [f"{NOMBRE_FACTOR[f]} ({x:.1f} pts)" for f, x in difs if x < -0.5]
    texto = f"{a.nombre} saca {a.puntaje - b.puntaje:.1f} puntos más que {b.nombre}"
    if a_favor:
        texto += f" por {', '.join(a_favor[:3])}"
    if en_contra:
        texto += f"; {b.nombre} gana en {', '.join(en_contra[:2])}"
    return dict(texto=texto + ".", gana=a.nombre, pierde=b.nombre, puntos=round(a.puntaje - b.puntaje, 1),
                por_factor={f: round(x, 1) for f, x in difs}, contrafactual=contrafactual(a, b, evs, pesos))


def contrafactual(a: Evaluado, b: Evaluado, evs: list[Evaluado], pesos: dict[str, float]) -> str | None:
    """Cuánto tendría que bajar B su precio (o su tiempo P90) para quedar por encima de A."""
    if b.puntaje >= a.puntaje:
        return None
    for f, frase in (("precio", "bajara su precio"), ("tiempo", "redujera su tiempo P90")):
        if pesos[f] == 0:
            continue
        valores = np.array([e.crudos[f] for e in evs])
        ib = evs.index(b)
        for pct in range(1, 61):
            v = valores.copy()
            v[ib] = valores[ib] * (1 - pct / 100)
            norm = normalizar(v, f)
            puntos = {e.proveedor_id: e.puntaje - 100 * pesos[f] * (e.norm[f] - norm[i]) for i, e in enumerate(evs)}
            if puntos[b.proveedor_id] > puntos[a.proveedor_id]:
                return f"Si {b.nombre} {frase} {pct} %, quedaría por encima de {a.nombre}."
    return f"Ni bajando 60 % su precio o su tiempo, {b.nombre} pasaría a {a.nombre}."


def _a_dict(e: Evaluado, evs: list[Evaluado], posicion: int | None) -> dict:
    lo, hi = e.beta.intervalo90()
    return dict(
        posicion=posicion, proveedor_id=e.proveedor_id, proveedor=e.nombre, puntaje=e.puntaje,
        p_exito=round(e.mc.p_exito, 3), p_a_tiempo=round(e.mc.p_a_tiempo, 3), p_dano=round(e.mc.p_dano, 4),
        p_sobre_presupuesto=round(e.mc.p_sobre_presupuesto, 3), confianza=e.beta.confianza(),
        confiabilidad=round(e.beta.media, 3), intervalo_confiabilidad=[round(lo, 3), round(hi, 3)],
        costo_esperado_cop=round(e.crudos["precio"], -3), costo_p90_cop=round(e.mc.costo_p90 * e.crudos["precio"] / e.mc.costo_esperado, -3),
        tiempo_p50_h=round(e.mc.tiempo_p50, 1), tiempo_p90_h=round(e.mc.tiempo_p90, 1),
        vehiculos_libres=e.revision.disponibles, aportes=e.aportes,
        semaforo=e.semaforo, senales=e.senales, razones=razones(e, evs) if evs else [],
        dominado_por=None if e.dominado_por is None else _por_id(evs, e.dominado_por).nombre,
        explorado=e.explorado, servicios_en_segmento=e.extra["servicios_segmento"],
        datos_propios=round(e.mc.peso_propio, 2),
    )


# ====================================================================== carga dividida y cascada
def dividir(d: Datos, sol: Solicitud, candidatos: list[Evaluado], parciales: list[Evaluado],
            pesos: dict[str, float]) -> dict | None:
    """Reparte las unidades entre 2 o 3 proveedores, en orden de puntaje. El éxito exige que todos cumplan."""
    pool = [e for e in candidatos + parciales if e.revision.disponibles > 0]
    if sol.unidades < 2 or len(pool) < 2 or not parciales:
        return None
    copia = [replace(e, norm={}, aportes={}) for e in pool]
    puntuar(copia, pesos)
    copia.sort(key=lambda e: (e.alerta_critica, -e.puntaje))
    reparto, faltan = [], sol.unidades
    for e in copia:
        if faltan == 0 or len(reparto) == 3:
            break
        u = min(e.revision.disponibles, faltan)
        if e.revision.pasa and u == sol.unidades:  # uno solo lo puede todo: no es una división
            u = sol.unidades - 1
        reparto.append((e, u))
        faltan -= u
    if faltan > 0 or len(reparto) < 2:
        return None
    exito = np.ones_like(reparto[0][0].mc.exito)
    tiempos = np.zeros_like(reparto[0][0].mc.tiempos)
    costos = np.zeros_like(reparto[0][0].mc.costos)
    for e, u in reparto:
        por_unidad = e.mc.costos / (sol.unidades if e.revision.pasa else 1)
        exito &= e.mc.exito
        tiempos = np.maximum(tiempos, e.mc.tiempos)
        costos = costos + por_unidad * u
    return dict(
        reparto=[dict(proveedor=e.nombre, unidades=u, p_exito=round(e.mc.p_exito, 3)) for e, u in reparto],
        p_exito_conjunta=round(float(exito.mean()), 3), costo_esperado_cop=round(float(costos.mean()), -3),
        tiempo_p90_h=round(float(np.quantile(tiempos, 0.9)), 1),
        nota="El envío solo cumple si cumplen todos; por eso el % conjunto es menor que el de cada uno.",
    )


def cascada(d: Datos, sol: Solicitud, req: Requisitos, parciales: list[Evaluado], rng, piso: float = 0.0) -> list[dict]:
    """Nadie cumple (o el mejor cumple mal, `piso` > 0): probar una relajación a la vez y decir qué mejora."""
    alternativas = []

    pesos, _ = pesos_finales(sol, req)

    def probar(descripcion: str, s2: Solicitud, r2: Requisitos, cambio: dict):
        c, p, _, _ = _evaluar(d, s2, r2, 1000, rng)
        if c and max(e.mc.p_exito for e in c) >= piso:
            mejor = max(c, key=lambda e: e.mc.p_exito)
            alternativas.append(dict(cambio=cambio, descripcion=f"{descripcion}, aparecen {len(c)} proveedor(es)",
                                     proveedores=[e.nombre for e in c], mejor=mejor.nombre,
                                     p_exito_mejor=round(mejor.mc.p_exito, 3)))
            return True
        div = dividir(d, s2, c, p, pesos)
        if div and div["p_exito_conjunta"] >= max(piso, 0.01):
            quienes = " y ".join(f"{x['proveedor']} ({x['unidades']})" for x in div["reparto"])
            alternativas.append(dict(cambio=dict(cambio, dividir=True),
                                     descripcion=f"{descripcion} y se divide la carga entre {quienes}",
                                     proveedores=[x["proveedor"] for x in div["reparto"]], mejor=None,
                                     p_exito_mejor=div["p_exito_conjunta"], carga_dividida=div))
            return True
        return False

    comp = d.compatibilidad[(d.compatibilidad.tipo_carga_id == sol.tipo_carga_id)
                            & (d.compatibilidad.tipo_vehiculo_id != sol.tipo_vehiculo_id)].sort_values("preferencia")
    for tv in comp.tipo_vehiculo_id:
        nombre = d.nombre("tipos_vehiculo", tv)
        if probar(f"Si se usa {nombre} en vez de {d.nombre('tipos_vehiculo', sol.tipo_vehiculo_id)}",
                  replace(sol, tipo_vehiculo_id=int(tv)), req, dict(tipo_vehiculo=nombre)):
            break
    for dias in range(1, 8):
        f = sol.fecha + timedelta(days=dias)
        if probar(f"Si el cargue se mueve al {f:%d/%m} (+{dias} día{'s' if dias > 1 else ''})",
                  replace(sol, fecha=f), req, dict(fecha=f.isoformat())):
            break
    if req.plazo_h is not None:
        for extra in (12, 24, 48):
            if probar(f"Si el plazo se amplía {extra} h", sol, replace(req, plazo_h=req.plazo_h + extra),
                      dict(plazo_horas=req.plazo_h + extra)):
                break
    elif piso:  # el plazo del cliente no era restricción, pero con él el mejor cumple mal: probar ampliarlo
        for extra in (12, 24, 48):
            if probar(f"Si el plazo se amplía {extra} h", replace(sol, plazo_h=sol.plazo_h + extra), req,
                      dict(plazo_horas=sol.plazo_h + extra)):
                break
    if req.precio_max is not None:
        for pct in (10, 20, 30):
            if probar(f"Si el precio máximo sube {pct} %", sol, replace(req, precio_max=req.precio_max * (1 + pct / 100)),
                      dict(precio_max_cop=round(req.precio_max * (1 + pct / 100), -3))):
                break
    elif piso and sol.presupuesto_cop is not None:
        for pct in (10, 20, 30, 40):
            nuevo = round(sol.presupuesto_cop * (1 + pct / 100), -3)
            if probar(f"Si el presupuesto sube {pct} %", replace(sol, presupuesto_cop=nuevo), req,
                      dict(presupuesto_cop=nuevo)):
                break
    if req.confiabilidad_min is not None:
        for menos in (0.05, 0.10):
            probar(f"Si la confiabilidad mínima baja a {req.confiabilidad_min - menos:.0%}", sol,
                   replace(req, confiabilidad_min=req.confiabilidad_min - menos),
                   dict(confiabilidad_min=round(req.confiabilidad_min - menos, 2))) and None
            if alternativas and "confiabilidad_min" in alternativas[-1]["cambio"]:
                break
    if req.sin_incidentes_dias is not None:
        probar("Si se acepta a proveedores con imprevistos recientes", sol, replace(req, sin_incidentes_dias=None),
               dict(sin_incidentes=False))
    alternativas.sort(key=lambda a: -(a["p_exito_mejor"] or 0))
    if not alternativas:
        alternativas.append(dict(cambio={}, proveedores=[], mejor=None, p_exito_mejor=None, descripcion=(
            "Ningún proveedor de la red puede atenderla ni relajando una condición a la vez. Opciones: partir el envío "
            "en varias fechas, combinar dos cambios o cotizar con un proveedor fuera de la red.")))
    return alternativas


# ====================================================================== entrada principal
def _semilla(sol: Solicitud, req: Requisitos) -> int:
    clave = json.dumps([sol.__dict__, {k: sorted(v) if isinstance(v, set) else v for k, v in req.__dict__.items()}],
                       default=str, sort_keys=True)
    return int(hashlib.sha256(clave.encode()).hexdigest()[:8], 16)


@dataclass
class Ranking:
    solicitud: Solicitud
    requisitos: Requisitos
    pesos: dict[str, float]
    ordenados: list[Evaluado]
    parciales: list[Evaluado]
    descartados: list[dict]
    ruta: Ruta
    division: dict | None
    alternativas: list[dict]
    hhi: float
    nombres: dict = field(default_factory=dict)

    def a_dict(self, top: int | None = None) -> dict:
        d_sol = self.solicitud
        lista = [_a_dict(e, self.ordenados, i + 1) for i, e in enumerate(self.ordenados)]
        top3 = lista[:3]
        explicacion = None
        if len(self.ordenados) >= 2:
            explicacion = diferencia(self.ordenados[0], self.ordenados[1], self.ordenados, self.pesos)
        return dict(
            solicitud=dict(id=d_sol.id, **self.nombres, origen_id=d_sol.origen_id, destino_id=d_sol.destino_id,
                           tipo_carga_id=d_sol.tipo_carga_id, tipo_vehiculo_id=d_sol.tipo_vehiculo_id,
                           unidades=d_sol.unidades, plazo_horas=d_sol.plazo_h, presupuesto_cop=d_sol.presupuesto_cop,
                           perfil=d_sol.perfil, fecha=d_sol.fecha.isoformat(), distancia_km=float(self.ruta.distancia_km),
                           tiempo_estandar_h=round(float(self.ruta.estandar_h), 1)),
            pesos={f: round(w, 3) for f, w in self.pesos.items()},
            restricciones=_restricciones_dict(self.requisitos),
            top3=top3, ranking=lista if top is None else lista[:top],
            por_que_no_el_2=explicacion, descartados=self.descartados,
            carga_dividida=self.division, alternativas=self.alternativas,
            hhi_90d=round(self.hhi), sin_opcion=not self.ordenados,
        )


def _restricciones_dict(r: Requisitos) -> dict:
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in r.__dict__.items() if v not in (None, set(), {})}


def calcular(d: Datos, solicitud: dict | int | Solicitud, requisitos: list[dict] | Requisitos | None = None,
             n: int | None = None, semilla: int | None = None) -> Ranking:
    sol = solicitud if isinstance(solicitud, Solicitud) else armar_solicitud(d, solicitud)
    req = requisitos if isinstance(requisitos, Requisitos) else armar_requisitos(d, sol, requisitos)
    rng = np.random.default_rng(semilla if semilla is not None else _semilla(sol, req))
    pesos, _ = pesos_finales(sol, req)
    candidatos, parciales, descartados, ruta = _evaluar(d, sol, req, n or politicas()["montecarlo"]["escenarios"], rng)
    puntuar(candidatos, pesos)
    participacion, hhi = participacion_90d(d)
    todos = candidatos + parciales
    referencia = dict(dispersion=float(np.median([e.mc.tiempo_p90 / e.mc.tiempo_p50 for e in todos])) if todos else 1.0,
                      dano=float(np.median([e.mc.p_dano for e in todos])) if todos else 0.0)
    for e in todos:
        semaforo(e, sol, participacion, referencia)
    pareto(candidatos)
    for e in candidatos:
        if e.dominado_por is not None:
            b = _por_id(candidatos, e.dominado_por)
            descartados.append(dict(proveedor=e.nombre, etapa="pareto",
                                    motivo=f"{b.nombre} es igual o mejor en costo, tiempo P90 y % de éxito"))
    ordenados = ordenar(candidatos, sol, rng)
    division = dividir(d, sol, candidatos, parciales, pesos)
    mejor_exito = max((e.mc.p_exito for e in ordenados), default=0.0)
    # sin opción, o la mejor cumple mal (< 60 %): proponer qué cambiar, exigiendo que la alternativa mejore de verdad
    alternativas = (cascada(d, sol, req, parciales, rng, piso=0.0 if not ordenados else max(0.6, mejor_exito + 0.15))
                    if not ordenados or mejor_exito < 0.6 else [])
    nombres = dict(origen=d.nombre("ciudades", sol.origen_id), destino=d.nombre("ciudades", sol.destino_id),
                   tipo_carga=d.nombre("tipos_carga", sol.tipo_carga_id),
                   tipo_vehiculo=d.nombre("tipos_vehiculo", sol.tipo_vehiculo_id))
    return Ranking(sol, req, pesos, ordenados, parciales, descartados, ruta, division, alternativas, hhi, nombres)
