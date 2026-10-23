"""Bandido Beta-Bernoulli con olvido: "¿cumple de verdad últimamente en este segmento?".

Segmento = región de destino × tipo de carga. Cada entrega a tiempo suma a α y cada retraso a β,
con peso 0,5^(edad en meses / vida media), así que lo reciente pesa más y un proveedor que empeoró
se nota en semanas. El punto de partida es el promedio del mercado en el segmento con el peso de
`peso_prior` servicios: un proveedor nuevo arranca "como el mercado" y con confianza baja.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from cosco.motor.datos import Datos, peso_recencia, politicas


@dataclass
class Beta:
    alfa: float
    beta: float
    n_efectivo: float  # servicios del proveedor en el segmento, ya con el peso de recencia

    @property
    def media(self) -> float:
        return self.alfa / (self.alfa + self.beta)

    def intervalo90(self, rng: np.random.Generator | None = None) -> tuple[float, float]:
        m = (rng or np.random.default_rng(0)).beta(self.alfa, self.beta, 4000)
        return float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95))

    def confianza(self) -> str:
        lo, hi = self.intervalo90()
        ancho = hi - lo
        return "alta" if ancho < 0.12 else "media" if ancho < 0.25 else "baja"


def segmento(region_destino_id: int, tipo_carga_id: int) -> str:
    return f"{region_destino_id}|{tipo_carga_id}"


def _pesos(viajes: pd.DataFrame) -> np.ndarray:
    return peso_recencia(viajes.edad_dias, politicas()["bandido"]["vida_media_meses"])


def tasa_mercado(viajes: pd.DataFrame, seg: str) -> float:
    """Tasa a tiempo de todos los proveedores en el segmento (o global si el segmento no tiene viajes)."""
    v = viajes[viajes.segmento == seg]
    v = viajes if v.empty else v
    w = _pesos(v)
    return float(np.clip(np.sum(w * v.a_tiempo) / np.sum(w), 0.02, 0.98))  # nunca 0 ni 100 %: la Beta lo exige


def posterior(d: Datos, proveedor_id: int, seg: str, viajes: pd.DataFrame | None = None) -> Beta:
    """Beta del proveedor en el segmento. `viajes` permite calcularla con otro historial (backtest)."""
    viajes = d.viajes if viajes is None else viajes
    k = politicas()["bandido"]["peso_prior"]
    m = tasa_mercado(viajes, seg)
    v = viajes[(viajes.proveedor_id == proveedor_id) & (viajes.segmento == seg)]
    w = _pesos(v)
    exitos = float(np.sum(w * v.a_tiempo))
    n = float(np.sum(w))
    return Beta(alfa=k * m + exitos, beta=k * (1 - m) + n - exitos, n_efectivo=n)


def tabla_estado(d: Datos) -> pd.DataFrame:
    """α y β de todos los proveedores × segmentos con historial (para guardar en estado_bandit)."""
    filas = []
    for (pid, seg), _ in d.viajes.groupby(["proveedor_id", "segmento"]):
        b = posterior(d, int(pid), seg)
        filas.append(dict(proveedor_id=int(pid), segmento=seg, alfa=round(b.alfa, 4), beta=round(b.beta, 4)))
    return pd.DataFrame(filas)
