"""Catálogo de tipos de vehículo y de carga, y su compatibilidad."""

# tipo: capacidad (t), contenedores TEU que lleva, multiplicador de tarifa, velocidad crucero km/h
VEHICULOS = {
    "Tractomula 40' (FEU)": {"cap_t": 30, "teu": 2, "mult_tarifa": 1.00, "vel": 48},
    "Tractomula 20' (TEU)": {"cap_t": 26, "teu": 1, "mult_tarifa": 0.80, "vel": 50},
    "Tractomula Reefer 40'": {"cap_t": 28, "teu": 2, "mult_tarifa": 1.35, "vel": 47},
    "Plataforma (cama alta)": {"cap_t": 34, "teu": 0, "mult_tarifa": 1.05, "vel": 46},
    "Cama baja": {"cap_t": 45, "teu": 0, "mult_tarifa": 1.70, "vel": 35},
    "Cisterna / ISO tank": {"cap_t": 30, "teu": 0, "mult_tarifa": 1.30, "vel": 45},
    "Doble troque": {"cap_t": 17, "teu": 0, "mult_tarifa": 0.65, "vel": 52},
    "Camión sencillo": {"cap_t": 9, "teu": 0, "mult_tarifa": 0.45, "vel": 55},
    "Turbo": {"cap_t": 4.5, "teu": 0, "mult_tarifa": 0.32, "vel": 60},
}

# Tipo de carga -> vehículos admisibles (en orden de preferencia)
CARGAS = {
    "Contenedor seco": ["Tractomula 40' (FEU)", "Tractomula 20' (TEU)"],
    "Contenedor refrigerado": ["Tractomula Reefer 40'"],
    "Carga suelta / paletizada": ["Doble troque", "Camión sencillo", "Plataforma (cama alta)", "Turbo"],
    "Carga extradimensionada": ["Cama baja", "Plataforma (cama alta)"],
    "Mercancía peligrosa (IMO)": ["Tractomula 40' (FEU)", "Tractomula 20' (TEU)", "Cisterna / ISO tank"],
    "Granel líquido": ["Cisterna / ISO tank"],
    "Alto valor": ["Tractomula 40' (FEU)", "Tractomula 20' (TEU)", "Camión sencillo"],
}

# Certificación que exige cada tipo de carga (si aplica)
CERT_REQUERIDA = {
    "Mercancía peligrosa (IMO)": "Mercancía peligrosa",
    "Granel líquido": "Mercancía peligrosa",
    "Alto valor": "Escolta y GPS",
    "Contenedor refrigerado": "Cadena de frío",
    "Carga extradimensionada": "Permiso INVÍAS extradimensionada",
}

# Sensibilidad de la carga a daño cuando hay un imprevisto
SENSIBILIDAD = {
    "Contenedor seco": 0.04,
    "Contenedor refrigerado": 0.25,
    "Carga suelta / paletizada": 0.10,
    "Carga extradimensionada": 0.12,
    "Mercancía peligrosa (IMO)": 0.10,
    "Granel líquido": 0.08,
    "Alto valor": 0.15,
}

TIPOS_IMPREVISTO = [
    "Avería mecánica",
    "Derrumbe / cierre vial",
    "Bloqueo / paro",
    "Retención documental",
    "Accidente menor",
    "Falla equipo de frío",
    "Intento de hurto",
]

# Métricas del puntaje de conductor definidas por COSCO (pesos)
METRICAS_CONDUCTOR = {
    "puntualidad": 0.30,
    "seguridad_vial": 0.30,  # excesos de velocidad, frenadas bruscas (telemetría)
    "documentacion": 0.15,
    "cuidado_carga": 0.15,
    "comunicacion": 0.10,
}

# Estándar de desempeño de proveedor COSCO (pesos)
ESTANDAR_COSCO = {
    "otd": 0.35,
    "siniestralidad": 0.20,
    "documentacion": 0.15,
    "comunicacion_trazabilidad": 0.15,
    "cumplimiento_tarifa": 0.15,
}


def unidades_por_vehiculo(vehiculo: str, carga: str) -> str:
    return "contenedores" if VEHICULOS[vehiculo]["teu"] > 0 and "Contenedor" in carga else "viajes"
