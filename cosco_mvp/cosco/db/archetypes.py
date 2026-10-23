"""Perfiles de los proveedores simulados.

Cada proveedor tiene parámetros DECLARADOS (lo que ve el sistema) y una VERDAD OCULTA
(cómo se comporta en realidad). El seeder genera el historial con la verdad oculta; el
motor de recomendación solo ve el historial, así que tiene que "descubrir" fortalezas,
debilidades y tendencias. La verdad oculta se exporta aparte, solo para validar.

Claves:
  precio      multiplicador sobre la tarifa de mercado
  vel         multiplicador de velocidad crucero
  q_tarde     prob. base de retraso operativo (cargue tardío, conductor, ruta) sin imprevisto
  imprevisto  prob. base de imprevisto propio del proveedor (se suma al riesgo del corredor)
  reaccion_h  tiempo real de reacción a imprevistos (el declarado es más optimista)
  sigma       variabilidad del tiempo de tránsito (lognormal)
  sobrecosto  sobrecosto medio sobre lo cotizado
  estado_flota, conductores  medias 0-100
  doc, com    calidad de documentación y de comunicación/trazabilidad 0-100
  segmentos   {("region"|"carga", nombre): delta sobre q_tarde}  (+ = peor)
  tendencia   ("estable",) | ("mejora", fecha_inicio, delta_final) | ("deterioro", fecha_inicio, delta)
  popularidad sesgo histórico del equipo de operaciones al elegirlo
  utilizacion fracción típica de la flota ocupada
"""
from datetime import date

CAR, AND, ANT, PAC, SAN, ORI, SUR = (
    "Caribe",
    "Andina Centro",
    "Antioquia y Eje Cafetero",
    "Pacífico y Valle",
    "Santanderes",
    "Orinoquía",
    "Sur y Amazonía",
)
TODAS = [CAR, AND, ANT, PAC, SAN, ORI, SUR]

T40, T20, REEF, PLAT, CAMA, CIST, DT, SENC, TURBO = (
    "Tractomula 40' (FEU)",
    "Tractomula 20' (TEU)",
    "Tractomula Reefer 40'",
    "Plataforma (cama alta)",
    "Cama baja",
    "Cisterna / ISO tank",
    "Doble troque",
    "Camión sencillo",
    "Turbo",
)

INICIO_HISTORIAL = date(2024, 10, 24)

PROVEEDORES = [
    dict(
        nombre="Transportes Andinos del Pacífico", base="Cali", fundacion=1998,
        regiones=[PAC, AND, ANT], flota={T40: 40, T20: 25, PLAT: 6},
        certs=["Mercancía peligrosa", "BASC", "Permiso INVÍAS extradimensionada"],
        precio=1.02, vel=1.00, q_tarde=0.06, imprevisto=0.04, reaccion_h=2.5, sigma=0.08, sobrecosto=0.02,
        estado_flota=82, conductores=84, doc=88, com=85,
        segmentos={("region", PAC): -0.03, ("region", ANT): 0.07},
        tendencia=("estable",), popularidad=1.6, utilizacion=0.70,
        perfil="Especialista del corredor Buenaventura–Cali–Bogotá.",
    ),
    dict(
        nombre="LogiCaribe S.A.S.", base="Barranquilla", fundacion=2009,
        regiones=[CAR, SAN, ANT, AND], flota={T40: 30, T20: 30, DT: 10, SENC: 8},
        certs=[],
        precio=0.90, vel=1.00, q_tarde=0.09, imprevisto=0.05, reaccion_h=4.0, sigma=0.10, sobrecosto=0.04,
        estado_flota=74, conductores=76, doc=75, com=70,
        segmentos={("region", AND): 0.09, ("region", CAR): -0.03},
        tendencia=("estable",), popularidad=1.3, utilizacion=0.65,
        perfil="Barato y fuerte en la Costa; se complica subiendo a la montaña.",
    ),
    dict(
        nombre="FríoExpress Colombia", base="Bogotá", fundacion=2005,
        regiones=TODAS, flota={REEF: 35, SENC: 5},
        certs=["Cadena de frío", "BASC"],
        precio=1.12, vel=1.02, q_tarde=0.05, imprevisto=0.03, reaccion_h=1.5, sigma=0.07, sobrecosto=0.02,
        estado_flota=88, conductores=86, doc=90, com=92,
        segmentos={("region", SUR): 0.07},
        tendencia=("estable",), popularidad=1.0, utilizacion=0.85,
        perfil="Líder en refrigerados a nivel nacional, caro y casi siempre lleno.",
    ),
    dict(
        nombre="Carga Pesada Nacional", base="Medellín", fundacion=1992,
        regiones=TODAS, flota={CAMA: 12, PLAT: 15, T40: 8},
        certs=["Permiso INVÍAS extradimensionada"],
        precio=1.05, vel=0.92, q_tarde=0.09, imprevisto=0.06, reaccion_h=4.0, sigma=0.12, sobrecosto=0.05,
        estado_flota=76, conductores=80, doc=82, com=72,
        segmentos={},
        tendencia=("estable",), popularidad=0.9, utilizacion=0.75,
        perfil="Casi el único con cama baja y permisos de extradimensionada.",
    ),
    dict(
        nombre="Tanqueros Unidos", base="Bucaramanga", fundacion=2001,
        regiones=TODAS, flota={CIST: 25, T20: 10, T40: 6},
        certs=["Mercancía peligrosa"],
        precio=1.08, vel=0.97, q_tarde=0.07, imprevisto=0.04, reaccion_h=2.0, sigma=0.09, sobrecosto=0.03,
        estado_flota=84, conductores=85, doc=91, com=80,
        segmentos={("carga", "Contenedor seco"): 0.04},
        tendencia=("estable",), popularidad=0.9, utilizacion=0.70,
        perfil="Especialista en granel líquido y mercancía peligrosa.",
    ),
    dict(
        nombre="RutaSegura Logística", base="Bogotá", fundacion=2011,
        regiones=TODAS, flota={T40: 20, T20: 15, SENC: 12},
        certs=["Escolta y GPS", "BASC", "Mercancía peligrosa"],
        precio=1.25, vel=1.00, q_tarde=0.04, imprevisto=0.025, reaccion_h=1.0, sigma=0.06, sobrecosto=0.01,
        estado_flota=92, conductores=91, doc=95, com=95,
        segmentos={},
        tendencia=("estable",), popularidad=0.8, utilizacion=0.70,
        perfil="Premium: el más confiable y el más caro; ideal para alto valor.",
    ),
    dict(
        nombre="TransOriente Llanero", base="Villavicencio", fundacion=2012,
        regiones=[ORI, AND, SAN], flota={T40: 8, T20: 6, DT: 8, SENC: 6, CIST: 4},
        certs=["Mercancía peligrosa"],
        precio=0.95, vel=0.97, q_tarde=0.08, imprevisto=0.05, reaccion_h=3.0, sigma=0.10, sobrecosto=0.03,
        estado_flota=75, conductores=79, doc=78, com=74,
        segmentos={("region", ORI): -0.04},
        tendencia=("estable",), popularidad=1.6, utilizacion=0.60,
        perfil="Conoce los Llanos como nadie; flota pequeña.",
    ),
    dict(
        nombre="Sur Cargo Express", base="Neiva", fundacion=2008,
        regiones=[SUR, PAC, AND], flota={T40: 10, T20: 10, DT: 8, SENC: 8, TURBO: 6, REEF: 3},
        certs=["Cadena de frío"],
        precio=1.00, vel=0.95, q_tarde=0.08, imprevisto=0.06, reaccion_h=1.8, sigma=0.11, sobrecosto=0.03,
        estado_flota=78, conductores=82, doc=80, com=84,
        segmentos={("region", SUR): -0.05},
        tendencia=("estable",), popularidad=1.5, utilizacion=0.60,
        perfil="El mejor en el sur del país (Pasto, Mocoa, Florencia); reacciona rápido.",
    ),
    dict(
        nombre="Antioquia Freight", base="Medellín", fundacion=2003,
        regiones=[ANT, CAR, AND, PAC], flota={T40: 30, T20: 20, PLAT: 8, DT: 6, CAMA: 3, REEF: 4},
        certs=["BASC", "Permiso INVÍAS extradimensionada", "Cadena de frío", "Escolta y GPS"],
        precio=0.97, vel=1.03, q_tarde=0.05, imprevisto=0.04, reaccion_h=2.5, sigma=0.08, sobrecosto=0.02,
        estado_flota=83, conductores=83, doc=86, com=84,
        segmentos={("region", ANT): -0.02},
        tendencia=("deterioro", date(2026, 6, 1), 0.22), popularidad=1.4, utilizacion=0.70,
        perfil="Fue de los mejores; desde junio de 2026 viene empeorando (problemas de flota).",
    ),
    dict(
        nombre="Santander Trucking", base="Bucaramanga", fundacion=2014,
        regiones=[SAN, CAR, AND, ORI], flota={T40: 15, T20: 15, DT: 10, SENC: 6},
        certs=[],
        precio=0.93, vel=1.00, q_tarde=0.17, imprevisto=0.06, reaccion_h=3.5, sigma=0.12, sobrecosto=0.04,
        estado_flota=72, conductores=74, doc=76, com=72,
        segmentos={("region", SAN): -0.03},
        tendencia=("mejora", date(2025, 9, 1), -0.12), popularidad=1.4, utilizacion=0.60,
        perfil="Arrancó flojo pero renovó flota y viene mejorando mes a mes.",
    ),
    dict(
        nombre="Económicos del Valle", base="Cali", fundacion=2016,
        regiones=[PAC, ANT, AND, SUR], flota={T40: 20, T20: 25, DT: 10, SENC: 10, TURBO: 8},
        certs=[],
        precio=0.80, vel=0.96, q_tarde=0.17, imprevisto=0.08, reaccion_h=5.5, sigma=0.16, sobrecosto=0.07,
        estado_flota=60, conductores=66, doc=64, com=60,
        segmentos={("carga", "Contenedor refrigerado"): 0.10},
        tendencia=("estable",), popularidad=1.5, utilizacion=0.55,
        perfil="El más barato, pero con retrasos frecuentes y alta variabilidad.",
    ),
    dict(
        nombre="MultiModal Colombia", base="Bogotá", fundacion=1995,
        regiones=TODAS, flota={T40: 45, T20: 35, PLAT: 8, DT: 15, SENC: 15, TURBO: 10},
        certs=["BASC", "Mercancía peligrosa", "Escolta y GPS"],
        precio=1.00, vel=1.00, q_tarde=0.08, imprevisto=0.05, reaccion_h=3.0, sigma=0.10, sobrecosto=0.03,
        estado_flota=80, conductores=79, doc=84, com=80,
        segmentos={("carga", "Mercancía peligrosa (IMO)"): 0.06, ("region", ORI): 0.05},
        tendencia=("estable",), popularidad=1.3, utilizacion=0.72,
        perfil="Generalista nacional con la flota más grande; desempeño promedio.",
    ),
    dict(
        nombre="NovaTrans 4.0", base="Bogotá", fundacion=2024,
        regiones=[AND, PAC, ANT, CAR], flota={T40: 8, T20: 6, REEF: 2},
        certs=["Cadena de frío", "BASC"],
        precio=0.92, vel=1.04, q_tarde=0.04, imprevisto=0.03, reaccion_h=1.2, sigma=0.07, sobrecosto=0.01,
        estado_flota=95, conductores=88, doc=90, com=93,
        segmentos={},
        tendencia=("estable",), popularidad=-0.4, utilizacion=0.45, inicio_cosco=date(2026, 9, 5),
        perfil="Proveedor nuevo con flota 2025 y telemetría; muy pocos servicios con COSCO.",
    ),
    dict(
        nombre="Costa Norte Carga", base="Cartagena", fundacion=2006,
        regiones=[CAR, SAN, ANT], flota={T40: 25, T20: 20, PLAT: 6, CIST: 6},
        certs=["Mercancía peligrosa"],
        precio=0.92, vel=1.00, q_tarde=0.06, imprevisto=0.04, reaccion_h=2.5, sigma=0.09, sobrecosto=0.03,
        estado_flota=80, conductores=81, doc=83, com=79,
        segmentos={("region", ANT): 0.10, ("region", CAR): -0.03},
        tendencia=("estable",), popularidad=1.2, utilizacion=0.68,
        perfil="Excelente desde Cartagena hacia la Costa y Santanderes; débil hacia Antioquia.",
    ),
    dict(
        nombre="Express Cafetero", base="Pereira", fundacion=2010,
        regiones=[ANT, PAC, AND], flota={DT: 15, SENC: 15, TURBO: 12, T20: 6},
        certs=[],
        precio=0.88, vel=1.02, q_tarde=0.07, imprevisto=0.04, reaccion_h=2.0, sigma=0.09, sobrecosto=0.02,
        estado_flota=79, conductores=83, doc=80, com=82,
        segmentos={("carga", "Carga suelta / paletizada"): -0.03},
        tendencia=("estable",), popularidad=1.7, utilizacion=0.62,
        perfil="Camiones medianos y pequeños para carga suelta en el Eje Cafetero.",
    ),
]

# Ajustes de disponibilidad para casos de demostración: (proveedor, vehículo, desde, hasta, disponibles)
RESTRICCIONES_DISPONIBILIDAD = [
    ("Carga Pesada Nacional", CAMA, date(2026, 10, 24), date(2026, 10, 28), 0),
    ("FríoExpress Colombia", REEF, date(2026, 10, 24), date(2026, 10, 27), 1),
    ("RutaSegura Logística", T40, date(2026, 10, 25), date(2026, 10, 26), 2),
]
