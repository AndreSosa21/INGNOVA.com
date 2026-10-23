"""Backtest con la verdad oculta: ¿cuánto mejora el sistema frente a cómo se decidía antes?

El motor aprende solo con lo que pasó antes de cada mes de prueba (21 meses de entrenamiento y se actualiza
cada mes) y decide las solicitudes de los últimos 3 meses. El resultado de CADA política se simula con los
parámetros reales de los proveedores (la verdad oculta del seeder), con los mismos números aleatorios por
solicitud, así que la comparación es justa. Con datos reales esto no se puede hacer.

Políticas:
  historica      el proveedor que eligió el equipo (precio + costumbre)
  mas_barata     el de tarifa más baja entre los que pueden
  mcdm_estatico  puntaje multicriterio con datos declarados (tarifa, OTD y puntaje COSCO), sin aprendizaje
  sistema        el #1 del motor completo
  oraculo        quien de verdad tenía más éxito (solo se puede calcular con la verdad oculta): el techo

    python -m cosco.validacion.backtest            # ~2 min, guarda data/backtest.csv y data/backtest_resumen.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace

import numpy as np
import pandas as pd

from cosco.db import RAIZ, get_engine
from cosco.db import seed
from cosco.db.archetypes import PROVEEDORES
from cosco.motor import filtros
from cosco.motor.datos import Datos, cargar_datos, politicas
from cosco.motor.ranking import armar_solicitud, calcular

POLITICAS = ["historica", "mas_barata", "mcdm_estatico", "sistema", "oraculo"]


def recortar(d: Datos, corte: pd.Timestamp) -> Datos:
    """Los datos como se veían el día `corte`: solo viajes anteriores y edades medidas desde ese día."""
    v = d.viajes[d.viajes.fecha_cargue < corte].copy()
    v["edad_dias"] = (corte - v.fecha_cargue).dt.total_seconds() / 86400
    imp = d.imprevistos[d.imprevistos.fecha_cargue < corte]
    return replace(d, viajes=v, imprevistos=imp, hoy=corte.date(), cupo_ilimitado=True)


class Verdad:
    """Simula un servicio con los parámetros ocultos del seeder (los mismos que generaron el historial)."""

    def __init__(self, semilla: int = 2026):
        self.gen = seed.Generador(10_000, 24, semilla)
        self.gen.catalogos()
        self.gen.proveedores()  # misma semilla = misma flota, conductores y tarifas que la BD
        self.prov = {p["id"]: p for p in PROVEEDORES}

    def simular(self, pid: int, s: dict, fecha, unidades: int, semilla: int) -> dict:
        self.gen.rng = np.random.default_rng(semilla)
        serv, _ = self.gen.simular_servicio(self.prov[pid], s, fecha.to_pydatetime(), unidades)
        return serv


def _mcdm_estatico(d: Datos, factibles: list[int], tarifas: dict[int, float]) -> int:
    """Precio 40 %, OTD histórico declarado 35 %, puntaje COSCO 25 %, normalizados entre los factibles."""
    p = d.proveedores.loc[factibles]
    precio = np.array([tarifas[i] for i in factibles])
    f_precio = precio.min() / precio
    f_otd = p.otd_historico.values / p.otd_historico.max()
    f_cosco = p.puntaje_desempeno_cosco.values / p.puntaje_desempeno_cosco.max()
    return factibles[int(np.argmax(0.40 * f_precio + 0.35 * f_otd + 0.25 * f_cosco))]


def correr(meses_prueba: int = 3, escenarios: int = 1000, limite: int | None = None, repeticiones: int = 20) -> tuple[pd.DataFrame, dict]:
    base = cargar_datos(get_engine())
    verdad = Verdad()
    hoy = pd.Timestamp(politicas()["fechas"]["hoy"])
    inicio = hoy - pd.Timedelta(days=int(meses_prueba * 30.44))
    sols = base.solicitudes[(base.solicitudes.fase == "historico") & (base.solicitudes.fecha_solicitud >= inicio)]
    if limite:
        sols = sols.sample(limite, random_state=1).sort_values("fecha_solicitud")
    elegido_hist = base.viajes.sort_index().groupby("solicitud_id").proveedor_id.first()

    filas, corte_actual, d = [], None, None
    for sid, s in sols.iterrows():
        corte = pd.Timestamp(s.fecha_solicitud.date().replace(day=1))  # el motor se actualiza cada mes
        corte = max(corte, inicio.normalize())
        if corte != corte_actual:
            d, corte_actual = recortar(base, corte), corte
        sol = armar_solicitud(d, int(sid))
        nombres = dict(origen=d.nombre("ciudades", sol.origen_id), destino=d.nombre("ciudades", sol.destino_id),
                       carga=d.nombre("tipos_carga", sol.tipo_carga_id),
                       vehiculo=d.nombre("tipos_vehiculo", sol.tipo_vehiculo_id))
        factibles, tarifas = [], {}
        for pid in d.proveedores.index:
            if pd.Timestamp(d.proveedores.at[pid, "fecha_inicio_cosco"]) > s.fecha_solicitud:
                continue
            rev = filtros.revisar(d, pid, sol.origen_id, sol.destino_id, sol.tipo_carga_id, sol.tipo_vehiculo_id,
                                  sol.unidades, sol.fecha)
            if rev.pasa:
                factibles.append(int(pid))
                tarifas[int(pid)] = rev.tarifa[0] * base.viajes.loc[base.viajes.solicitud_id == sid, "distancia_km"].iloc[0] + rev.tarifa[1]
        if not factibles:
            continue
        r = calcular(d, sol, n=escenarios)
        eleccion = dict(
            historica=int(elegido_hist[sid]),
            mas_barata=min(factibles, key=tarifas.get),
            mcdm_estatico=_mcdm_estatico(d, factibles, tarifas),
            sistema=r.ordenados[0].proveedor_id if r.ordenados else min(factibles, key=tarifas.get),
        )
        dist = float(base.viajes.loc[base.viajes.solicitud_id == sid, "distancia_km"].iloc[0])
        s_sim = dict(**nombres, dist=dist, plazo_horas=sol.plazo_h)

        def exito_real(pid: int) -> float:
            n = 0
            for rep in range(repeticiones):
                sv = verdad.simular(pid, s_sim, s.fecha_solicitud, sol.unidades, int(sid) * 7919 + rep)
                n += sv["a_tiempo"] and not sv["dano_carga"] and (
                    sol.presupuesto_cop is None or sv["costo_final_cop"] <= sol.presupuesto_cop)
            return n / repeticiones

        eleccion["oraculo"] = max(factibles, key=exito_real)  # techo: quien de verdad tenía más éxito
        for pol, pid in eleccion.items():
            for rep in range(repeticiones):  # mismos números aleatorios para todas las políticas
                serv = verdad.simular(pid, s_sim, s.fecha_solicitud, sol.unidades, int(sid) * 7919 + rep)
                dentro = sol.presupuesto_cop is None or serv["costo_final_cop"] <= sol.presupuesto_cop
                filas.append(dict(solicitud_id=int(sid), rep=rep, politica=pol, proveedor=d.nombre("proveedores", pid),
                                  perfil=sol.perfil, unidades=sol.unidades, a_tiempo=serv["a_tiempo"],
                                  costo_cop=serv["costo_final_cop"],
                                  costo_por_unidad=serv["costo_final_cop"] / sol.unidades,
                                  dano=serv["dano_carga"], dentro_presupuesto=dentro,
                                  exito=serv["a_tiempo"] and dentro and not serv["dano_carga"],
                                  retraso_h=max(0.0, serv["tiempo_real_h"] - sol.plazo_h)))
    df = pd.DataFrame(filas)
    return df, resumir(df)


def resumir(df: pd.DataFrame) -> dict:
    g = df.groupby("politica").agg(otd=("a_tiempo", "mean"), exito=("exito", "mean"), danos=("dano", "mean"),
                                   costo_por_unidad=("costo_por_unidad", "mean"), retraso_h=("retraso_h", "mean"),
                                   solicitudes=("solicitud_id", "nunique")).reindex(POLITICAS)
    h, s = g.loc["historica"], g.loc["sistema"]
    return dict(
        por_politica={p: {k: round(float(v), 4) for k, v in fila.items()} for p, fila in g.iterrows()},
        sistema_vs_historica=dict(
            otd_puntos=round(float(s.otd - h.otd) * 100, 1),
            exito_puntos=round(float(s.exito - h.exito) * 100, 1),
            costo_pct=round(float(s.costo_por_unidad / h.costo_por_unidad - 1) * 100, 1),
            danos_pct=round(float(s.danos / h.danos - 1) * 100, 1) if h.danos else None,
            retraso_promedio_h=round(float(s.retraso_h - h.retraso_h), 1),
            mejora_capturada_pct=round(float((s.exito - h.exito) / (g.loc["oraculo"].exito - h.exito)) * 100, 1),
        ),
        por_perfil={p: {pol: round(float(x), 3) for pol, x in sub.groupby("politica").exito.mean().reindex(POLITICAS).items()}
                    for p, sub in df.groupby("perfil")},
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meses", type=int, default=3)
    ap.add_argument("--escenarios", type=int, default=1000)
    ap.add_argument("--limite", type=int, help="probar con una muestra de solicitudes")
    ap.add_argument("--repeticiones", type=int, default=20, help="simulaciones de la verdad oculta por solicitud")
    a = ap.parse_args()
    df, res = correr(a.meses, a.escenarios, a.limite, a.repeticiones)
    (RAIZ / "data").mkdir(exist_ok=True)
    df.to_csv(RAIZ / "data" / "backtest.csv", index=False)
    with open(RAIZ / "data" / "backtest_resumen.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
