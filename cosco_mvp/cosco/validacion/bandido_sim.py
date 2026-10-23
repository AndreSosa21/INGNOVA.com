"""Simulación del bandido: ¿el sistema aprende y detecta a quien empeora?

500 solicitudes de los últimos 3 meses, una tras otra. En cada una, cada política elige un proveedor entre los
que pueden atenderla, ve si llegó a tiempo (simulado con la verdad oculta) y aprende de eso. Arrepentimiento
(regret) = P(a tiempo) real del mejor proveedor posible − P(a tiempo) real del elegido, acumulado.

Políticas:
  thompson_olvido   el bandido del motor: Beta por proveedor × segmento con vida media de 4 meses
  mejor_promedio    siempre el de mejor % a tiempo histórico, sin olvido ni exploración
  azar              uno al azar

    python -m cosco.validacion.bandido_sim       # ~2 min, guarda data/bandido_sim.csv y data/bandido_sim.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import replace

import numpy as np
import pandas as pd

from cosco.db import RAIZ, get_engine
from cosco.motor import filtros
from cosco.motor.datos import cargar_datos, politicas
from cosco.motor.ranking import armar_solicitud
from cosco.validacion.backtest import Verdad

POLITICAS = ["thompson_olvido", "mejor_promedio", "azar"]


class Memoria:
    """Historial de resultados (fecha, a tiempo) por proveedor × segmento que cada política va ampliando."""

    def __init__(self, viajes: pd.DataFrame):
        self.eventos: dict[tuple[int, str], list[tuple[pd.Timestamp, bool]]] = defaultdict(list)
        for pid, seg, f, ok in zip(viajes.proveedor_id, viajes.segmento, viajes.fecha_cargue, viajes.a_tiempo):
            self.eventos[(int(pid), seg)].append((f, bool(ok)))

    def agregar(self, pid: int, seg: str, fecha, ok: bool) -> None:
        self.eventos[(pid, seg)].append((fecha, ok))

    def conteos(self, pid: int, seg: str, hoy: pd.Timestamp, vida_media: float | None) -> tuple[float, float]:
        ev = self.eventos.get((pid, seg), [])
        if not ev:
            return 0.0, 0.0
        f = np.array([(hoy - x[0]).days for x in ev], float)
        ok = np.array([x[1] for x in ev], float)
        w = np.ones_like(f) if vida_media is None else np.power(0.5, np.maximum(f, 0) / 30.44 / vida_media)
        return float(np.sum(w * ok)), float(np.sum(w))


def correr(n: int = 500, repeticiones_verdad: int = 40, semilla: int = 7) -> tuple[pd.DataFrame, dict]:
    d = cargar_datos(get_engine())
    d_sin_cupo = replace(d, cupo_ilimitado=True)  # en fechas pasadas no hay dato de cupo: toda la flota
    pb = politicas()["bandido"]
    verdad = Verdad()
    hoy = pd.Timestamp(politicas()["fechas"]["hoy"])
    inicio = (hoy - pd.Timedelta(days=91)).normalize()
    previos = d.viajes[d.viajes.fecha_cargue < inicio]
    sols = d.solicitudes[(d.solicitudes.fase == "historico") & (d.solicitudes.fecha_solicitud >= inicio)]
    sols = sols.sample(min(n, len(sols)), random_state=semilla).sort_values("fecha_solicitud")
    memorias = {p: Memoria(previos) for p in POLITICAS}
    rng = np.random.default_rng(semilla)
    filas = []
    for k, (sid, s) in enumerate(sols.iterrows()):
        sol = armar_solicitud(d, int(sid))
        seg = f"{int(d.ciudades.at[sol.destino_id, 'region_id'])}|{sol.tipo_carga_id}"
        factibles = []
        for pid in d.proveedores.index:
            if pd.Timestamp(d.proveedores.at[pid, "fecha_inicio_cosco"]) > s.fecha_solicitud:
                continue
            if filtros.revisar(d_sin_cupo, int(pid), sol.origen_id, sol.destino_id, sol.tipo_carga_id,
                               sol.tipo_vehiculo_id, sol.unidades, sol.fecha).pasa:
                factibles.append(int(pid))
        if len(factibles) < 2:
            continue
        dist = float(d.viajes.loc[d.viajes.solicitud_id == sid, "distancia_km"].iloc[0])
        s_sim = dict(origen=d.nombre("ciudades", sol.origen_id), destino=d.nombre("ciudades", sol.destino_id),
                     carga=d.nombre("tipos_carga", sol.tipo_carga_id),
                     vehiculo=d.nombre("tipos_vehiculo", sol.tipo_vehiculo_id), dist=dist, plazo_horas=sol.plazo_h)
        p_real = {pid: np.mean([verdad.simular(pid, s_sim, s.fecha_solicitud, sol.unidades, int(sid) * 31 + r)["a_tiempo"]
                                for r in range(repeticiones_verdad)]) for pid in factibles}
        mejor = max(p_real.values())
        hoy_k = s.fecha_solicitud
        for pol, mem in memorias.items():
            if pol == "azar":
                pid = int(rng.choice(factibles))
            else:
                vida = pb["vida_media_meses"] if pol == "thompson_olvido" else None
                conteos = {p: mem.conteos(p, seg, hoy_k, vida) for p in factibles}
                tot_e, tot_n = sum(c[0] for c in conteos.values()), sum(c[1] for c in conteos.values())
                m = float(np.clip(tot_e / tot_n, 0.02, 0.98)) if tot_n else 0.8
                if pol == "thompson_olvido":
                    k0 = pb["peso_prior"]
                    muestra = {p: rng.beta(k0 * m + e, k0 * (1 - m) + n_ - e) for p, (e, n_) in conteos.items()}
                    pid = max(muestra, key=muestra.get)
                else:
                    pid = max(conteos, key=lambda p: (conteos[p][0] + m) / (conteos[p][1] + 1))
            ok = bool(verdad.simular(pid, s_sim, s.fecha_solicitud, sol.unidades, int(sid) * 17 + 3)["a_tiempo"])
            mem.agregar(pid, seg, hoy_k, ok)
            filas.append(dict(paso=k, solicitud_id=int(sid), fecha=hoy_k, politica=pol,
                              proveedor=d.nombre("proveedores", pid), a_tiempo=ok,
                              regret=float(mejor - p_real[pid]), p_real=float(p_real[pid])))
    df = pd.DataFrame(filas)
    df["regret_acumulado"] = df.groupby("politica").regret.cumsum()
    af = "Antioquia Freight"
    res = dict(
        solicitudes=int(df.solicitud_id.nunique()),
        regret_total={p: round(float(g.regret.sum()), 1) for p, g in df.groupby("politica")},
        otd_real_promedio={p: round(float(g.p_real.mean()), 3) for p, g in df.groupby("politica")},
        cuota_antioquia_freight={p: round(float((g.proveedor == af).mean()), 3) for p, g in df.groupby("politica")},
    )
    return df, res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=500)
    a = ap.parse_args()
    df, res = correr(a.n)
    df.to_csv(RAIZ / "data" / "bandido_sim.csv", index=False)
    with open(RAIZ / "data" / "bandido_sim.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
