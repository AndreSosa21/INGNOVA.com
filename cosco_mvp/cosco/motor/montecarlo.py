"""Monte Carlo: "¿qué tan probable es que este proveedor cumpla en ESTE envío?".

Cada escenario es un viaje posible del proveedor en la ruta pedida:
  1. Se saca θ de la Beta del bandido (qué tan seguido cumple últimamente en el segmento).
  2. Con probabilidad θ se toma un viaje histórico que llegó a tiempo y si no, uno que llegó tarde.
     Así el bandido decide CUÁNTAS veces se retrasa y el historial CUÁNTO se retrasa cuando pasa.
  3. El viaje sale del proveedor (más peso a los recientes y a los parecidos: misma región de destino,
     carga, ruta y distancia). Con pocos datos se mezcla con el mercado del segmento en proporción
     n / (n + k).
  4. El tiempo se lleva a la ruta pedida: (tiempo sin imprevisto / tiempo estándar del viaje histórico)
     × tiempo estándar de la ruta pedida, más el retraso del imprevisto ajustado por el riesgo vial
     del corredor y la temporada de lluvias.
  5. El costo es la tarifa del proveedor para la ruta × el sobrecosto real que tuvo ese viaje.
Salen: P(a tiempo), P(éxito = a tiempo + dentro del presupuesto + sin daño), costo esperado y P90,
tiempo P50 y P90.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from cosco.motor.bandido import Beta
from cosco.motor.datos import Datos, peso_recencia, politicas


@dataclass
class Ruta:
    """Lo que el Monte Carlo necesita saber del envío pedido."""

    origen_id: int
    destino_id: int
    region_destino_id: int
    tipo_carga_id: int
    tipo_vehiculo_id: int
    unidades: int
    plazo_h: float
    presupuesto_cop: float | None
    mes: int
    distancia_km: float
    estandar_h: float
    riesgo: float

    @property
    def segmento(self) -> str:
        return f"{self.region_destino_id}|{self.tipo_carga_id}"


@dataclass
class ResultadoMC:
    proveedor_id: int
    p_a_tiempo: float
    p_exito: float
    p_dano: float
    p_sobre_presupuesto: float
    costo_esperado: float
    costo_p90: float
    tiempo_p50: float
    tiempo_p90: float
    peso_propio: float  # n / (n + k): cuánto del resultado sale del historial propio
    tiempos: np.ndarray = field(repr=False)
    costos: np.ndarray = field(repr=False)
    exito: np.ndarray = field(repr=False)


def _similitud(v: pd.DataFrame, r: Ruta, vida_media: float) -> np.ndarray:
    w = peso_recencia(v.edad_dias, vida_media)
    w = w * (1 + 2 * (v.region_destino_id.values == r.region_destino_id)
             + 2 * (v.tipo_carga_id.values == r.tipo_carga_id)
             + 3 * ((v.origen_id.values == r.origen_id) & (v.destino_id.values == r.destino_id)))
    return w * np.exp(-np.abs(np.log(v.distancia_km.values / r.distancia_km)) / 0.5)


def _muestrear(rng: np.random.Generator, pesos: np.ndarray, n: int) -> np.ndarray:
    return rng.choice(len(pesos), size=n, p=pesos / pesos.sum())


def simular(d: Datos, proveedor_id: int, r: Ruta, beta: Beta, tarifa: tuple[float, float],
            rng: np.random.Generator, n: int | None = None, viajes: pd.DataFrame | None = None) -> ResultadoMC:
    pol = politicas()["montecarlo"]
    n = n or pol["escenarios"]
    viajes = d.viajes if viajes is None else viajes

    propios = viajes[viajes.proveedor_id == proveedor_id]
    mercado = viajes[viajes.segmento == r.segmento]
    if len(mercado) < 20:  # segmento casi vacío: el mercado es la misma carga en cualquier destino
        mercado = viajes[viajes.tipo_carga_id == r.tipo_carga_id]
    w_prop = _similitud(propios, r, pol["vida_media_meses"])
    w_merc = _similitud(mercado, r, pol["vida_media_meses"])

    lam = beta.n_efectivo / (beta.n_efectivo + pol["k_encogimiento"])
    theta = rng.beta(beta.alfa, beta.beta, n)
    tarde = rng.random(n) >= theta
    de_propio = rng.random(n) < lam

    # cada escenario toma un viaje de uno de 4 grupos: propio/mercado × a tiempo/tarde
    filas = []
    for fuente, w, usar in ((propios, w_prop, de_propio), (mercado, w_merc, ~de_propio)):
        for es_tarde in (False, True):
            sel = usar & (tarde == es_tarde)
            if not sel.any():
                continue
            # si el proveedor nunca llegó tarde (o nunca a tiempo) se usa el mercado, y si tampoco, todo el historial
            for src_df, src_w in ((fuente, w), (mercado, w_merc), (viajes, peso_recencia(viajes.edad_dias, 12))):
                mask = src_df.a_tiempo.values == (not es_tarde)
                src, ws = src_df[mask], src_w[mask]
                if len(src) and ws.sum() > 0:
                    break
            k = _muestrear(rng, ws, int(sel.sum()))
            filas.append((sel, src.iloc[k]))

    tiempos = np.empty(n)
    ratio_costo = np.empty(n)
    dano = np.empty(n, dtype=bool)
    lluvia_r = pol["factor_lluvia"] if r.mes in pol["meses_lluvia"] else 1.0
    tasa_dano_carga = _tasa_dano(viajes, r.tipo_carga_id)
    for sel, s in filas:
        retraso = s.retraso_imprevisto_h.values
        base = (s.tiempo_real_h.values - retraso) / s.estandar_h.values
        lluvia_h = np.where(np.isin(s.mes.values, pol["meses_lluvia"]), pol["factor_lluvia"], 1.0)
        k_riesgo = np.clip((r.riesgo * lluvia_r) / (s.riesgo.values * lluvia_h), 0.6, 1.8)
        tiempos[sel] = base * r.estandar_h + retraso * k_riesgo
        ratio_costo[sel] = s.ratio_costo.values
        misma_carga = s.tipo_carga_id.values == r.tipo_carga_id
        dano[sel] = np.where(misma_carga, s.dano_carga.values, rng.random(len(s)) < tasa_dano_carga)

    tarifa_km, fijo = tarifa
    costos = (tarifa_km * r.distancia_km + fijo) * r.unidades * ratio_costo
    a_tiempo = tiempos <= r.plazo_h
    dentro = np.ones(n, bool) if r.presupuesto_cop is None else costos <= r.presupuesto_cop
    exito = a_tiempo & dentro & ~dano
    return ResultadoMC(
        proveedor_id=proveedor_id, p_a_tiempo=float(a_tiempo.mean()), p_exito=float(exito.mean()),
        p_dano=float(dano.mean()), p_sobre_presupuesto=float(1 - dentro.mean()),
        costo_esperado=float(costos.mean()), costo_p90=float(np.quantile(costos, 0.9)),
        tiempo_p50=float(np.quantile(tiempos, 0.5)), tiempo_p90=float(np.quantile(tiempos, 0.9)),
        peso_propio=float(lam), tiempos=tiempos, costos=costos, exito=exito,
    )


def _tasa_dano(viajes: pd.DataFrame, tipo_carga_id: int) -> float:
    v = viajes[viajes.tipo_carga_id == tipo_carga_id]
    return float(v.dano_carga.mean()) if len(v) else 0.01
