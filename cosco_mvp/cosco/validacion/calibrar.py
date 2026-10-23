"""Calibración de pesos con un mes de validación que NO entra en el backtest.

Se prueban variantes de los pesos de los perfiles sobre las solicitudes del mes anterior al periodo de prueba
(el motor solo ve lo anterior a cada solicitud) y se elige la que da más éxito real según la verdad oculta.
El backtest de los 3 meses de prueba se corre después, con los pesos ya fijos.

Variantes (iguales para los 4 perfiles, para no sobreajustar):
  alfa   peso que se da al % de éxito del Monte Carlo como factor (el resto se reescala)
  beta   multiplicador del peso de precio
  gamma  multiplicador del peso de confiabilidad

    python -m cosco.validacion.calibrar          # ~3 min; imprime la tabla y los pesos sugeridos
"""
from __future__ import annotations

import argparse
import itertools
import json

import numpy as np
import pandas as pd

from cosco.db import RAIZ, get_engine
from cosco.motor.datos import cargar_datos, politicas
from cosco.motor.ranking import FACTORES, armar_solicitud, calcular, ordenar, pareto, puntuar
from cosco.validacion.backtest import Verdad, recortar


def preparar(meses_prueba: int = 3, dias_validacion: int = 30, escenarios: int = 1000, repeticiones: int = 20) -> list:
    base = cargar_datos(get_engine())
    verdad = Verdad()
    hoy = pd.Timestamp(politicas()["fechas"]["hoy"])
    fin = (hoy - pd.Timedelta(days=int(meses_prueba * 30.44))).normalize()
    inicio = fin - pd.Timedelta(days=dias_validacion)
    sols = base.solicitudes[(base.solicitudes.fase == "historico") & (base.solicitudes.fecha_solicitud >= inicio)
                            & (base.solicitudes.fecha_solicitud < fin)]
    elegido_hist = base.viajes.sort_index().groupby("solicitud_id").proveedor_id.first()
    d = recortar(base, inicio)  # el motor se congela al inicio de la validación
    casos = []
    for sid, s in sols.iterrows():
        sol = armar_solicitud(d, int(sid))
        r = calcular(d, sol, n=escenarios)
        if not r.ordenados:
            continue
        dist = float(base.viajes.loc[base.viajes.solicitud_id == sid, "distancia_km"].iloc[0])
        s_sim = dict(origen=d.nombre("ciudades", sol.origen_id), destino=d.nombre("ciudades", sol.destino_id),
                     carga=d.nombre("tipos_carga", sol.tipo_carga_id),
                     vehiculo=d.nombre("tipos_vehiculo", sol.tipo_vehiculo_id), dist=dist, plazo_horas=sol.plazo_h)
        real = {}
        for pid in [e.proveedor_id for e in r.ordenados] + [int(elegido_hist[sid])]:
            ex, costo = [], []
            for rep in range(repeticiones):
                sv = verdad.simular(pid, s_sim, s.fecha_solicitud, sol.unidades, int(sid) * 7919 + rep)
                ex.append(sv["a_tiempo"] and not sv["dano_carga"]
                          and (sol.presupuesto_cop is None or sv["costo_final_cop"] <= sol.presupuesto_cop))
                costo.append(sv["costo_final_cop"] / sol.unidades)
            real[pid] = (float(np.mean(ex)), float(np.mean(costo)))
        casos.append(dict(sid=int(sid), sol=sol, evs=r.ordenados, real=real, historica=int(elegido_hist[sid])))
    return casos


def pesos_variante(perfil: str, alfa: float, beta: float, gamma: float) -> dict[str, float]:
    w = {f: politicas()["perfiles"][perfil].get(f, 0.0) for f in FACTORES}
    w["exito"] = 0.0
    w["precio"] *= beta
    w["confiabilidad"] *= gamma
    total = sum(w.values())
    w = {f: x / total * (1 - alfa) for f, x in w.items()}
    w["exito"] = alfa
    return w


def evaluar(casos: list, alfa: float, beta: float, gamma: float) -> dict:
    ex, costo = [], []
    for c in casos:
        evs = c["evs"]
        for e in evs:
            e.dominado_por, e.explorado = None, False
        puntuar(evs, pesos_variante(c["sol"].perfil, alfa, beta, gamma))
        pareto(evs)
        primero = ordenar(evs, c["sol"], np.random.default_rng(c["sid"]))[0]
        x, k = c["real"][primero.proveedor_id]
        ex.append(x)
        costo.append(k)
    return dict(alfa=alfa, beta=beta, gamma=gamma, exito=float(np.mean(ex)), costo_por_unidad=float(np.mean(costo)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=30)
    a = ap.parse_args()
    casos = preparar(dias_validacion=a.dias)
    hist = dict(exito=float(np.mean([c["real"][c["historica"]][0] for c in casos])),
                costo_por_unidad=float(np.mean([c["real"][c["historica"]][1] for c in casos])))
    tabla = pd.DataFrame([evaluar(casos, *v) for v in itertools.product(
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5], [0.5, 0.75, 1.0, 1.25], [1.0, 1.5])])
    tabla = tabla.sort_values("exito", ascending=False)
    print(f"Validación: {len(casos)} solicitudes. Decisión histórica: éxito {hist['exito']:.3f}, "
          f"costo/unidad {hist['costo_por_unidad']:,.0f}")
    print(tabla.head(12).to_string(index=False))
    mejor = tabla.iloc[0]
    sugeridos = {p: {f: round(x, 3) for f, x in pesos_variante(p, mejor.alfa, mejor.beta, mejor.gamma).items()}
                 for p in politicas()["perfiles"]}
    actual = tabla[(tabla.alfa == 0) & (tabla.beta == 1) & (tabla.gamma == 1)].iloc[0]
    res = dict(solicitudes=len(casos), historica=hist, actual=actual.to_dict(), mejor=mejor.to_dict(), pesos=sugeridos)
    with open(RAIZ / "data" / "calibracion.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
