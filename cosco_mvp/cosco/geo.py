"""Geografía de Colombia: ciudades, regiones operativas, distancias y riesgo de corredor."""
from __future__ import annotations

import math

# Regiones operativas en las que se agrupa la cobertura de los proveedores.
REGIONES = [
    "Caribe",
    "Andina Centro",
    "Antioquia y Eje Cafetero",
    "Pacífico y Valle",
    "Santanderes",
    "Orinoquía",
    "Sur y Amazonía",
]

# ciudad: (lat, lon, región, es_puerto, factor_terreno, riesgo_vial)
#   factor_terreno: >1 = vía más lenta (montaña, vía secundaria)
#   riesgo_vial: probabilidad base adicional de imprevisto (derrumbes, orden público, bloqueos)
CIUDADES = {
    "Buenaventura": (3.8801, -77.0312, "Pacífico y Valle", True, 1.35, 0.10),
    "Cartagena": (10.3910, -75.4794, "Caribe", True, 1.00, 0.03),
    "Barranquilla": (10.9685, -74.7813, "Caribe", True, 1.00, 0.03),
    "Santa Marta": (11.2408, -74.1990, "Caribe", True, 1.05, 0.04),
    "Bogotá": (4.7110, -74.0721, "Andina Centro", False, 1.25, 0.04),
    "Tunja": (5.5353, -73.3678, "Andina Centro", False, 1.20, 0.03),
    "Ibagué": (4.4389, -75.2322, "Andina Centro", False, 1.25, 0.05),
    "Medellín": (6.2442, -75.5812, "Antioquia y Eje Cafetero", False, 1.30, 0.04),
    "Pereira": (4.8133, -75.6961, "Antioquia y Eje Cafetero", False, 1.25, 0.04),
    "Manizales": (5.0703, -75.5138, "Antioquia y Eje Cafetero", False, 1.30, 0.05),
    "Armenia": (4.5339, -75.6811, "Antioquia y Eje Cafetero", False, 1.25, 0.04),
    "Cali": (3.4516, -76.5320, "Pacífico y Valle", False, 1.05, 0.04),
    "Popayán": (2.4448, -76.6147, "Pacífico y Valle", False, 1.25, 0.08),
    "Quibdó": (5.6947, -76.6611, "Pacífico y Valle", False, 1.60, 0.16),
    "Bucaramanga": (7.1193, -73.1227, "Santanderes", False, 1.30, 0.05),
    "Cúcuta": (7.8939, -72.5078, "Santanderes", False, 1.25, 0.07),
    "Villavicencio": (4.1420, -73.6266, "Orinoquía", False, 1.20, 0.08),
    "Yopal": (5.3378, -72.3959, "Orinoquía", False, 1.20, 0.06),
    "Arauca": (7.0847, -70.7591, "Orinoquía", False, 1.30, 0.13),
    "Neiva": (2.9273, -75.2819, "Sur y Amazonía", False, 1.10, 0.05),
    "Pasto": (1.2136, -77.2811, "Sur y Amazonía", False, 1.35, 0.09),
    "Mocoa": (1.1528, -76.6466, "Sur y Amazonía", False, 1.45, 0.14),
    "Florencia": (1.6144, -75.6062, "Sur y Amazonía", False, 1.35, 0.10),
    "San José del Guaviare": (2.5729, -72.6459, "Sur y Amazonía", False, 1.40, 0.12),
    "Montería": (8.7479, -75.8814, "Caribe", False, 1.05, 0.05),
    "Sincelejo": (9.3047, -75.3978, "Caribe", False, 1.05, 0.04),
    "Valledupar": (10.4631, -73.2532, "Caribe", False, 1.05, 0.05),
    "Riohacha": (11.5444, -72.9072, "Caribe", False, 1.10, 0.07),
}

PUERTOS = [c for c, v in CIUDADES.items() if v[3]]


def region(ciudad: str) -> str:
    return CIUDADES[ciudad][2]


def _haversine_km(a: str, b: str) -> float:
    la1, lo1 = map(math.radians, CIUDADES[a][:2])
    la2, lo2 = map(math.radians, CIUDADES[b][:2])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(d))


def distancia_km(a: str, b: str) -> float:
    """Distancia por carretera aproximada (línea recta × factor de sinuosidad)."""
    if a == b:
        return 25.0
    return round(_haversine_km(a, b) * 1.38, 1)


def factor_terreno(a: str, b: str) -> float:
    return (CIUDADES[a][4] + CIUDADES[b][4]) / 2


def riesgo_corredor(a: str, b: str) -> float:
    """Probabilidad base de imprevisto en el corredor (máximo de los extremos + media)."""
    ra, rb = CIUDADES[a][5], CIUDADES[b][5]
    return round(0.6 * max(ra, rb) + 0.4 * (ra + rb) / 2, 4)


def corredor(a: str, b: str) -> str:
    return f"{a} → {b}"
