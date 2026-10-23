"""Seeder de la base de datos simulada de COSCO SHIPPING - transporte terrestre Colombia.

Uso:
    python -m cosco.db.seed                       # SQLite local en data/cosco.db
    DATABASE_URL=postgresql://... python -m cosco.db.seed   # Supabase / Postgres
    python -m cosco.db.seed --servicios 20000 --meses 24 --semilla 7

Todo es reproducible con la semilla: los 5 integrantes obtienen exactamente los mismos datos.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker
from sqlalchemy import inspect

from cosco import catalog, geo
from cosco.db import RAIZ, database_url, get_engine
from cosco.db.archetypes import PROVEEDORES, RESTRICCIONES_DISPONIBILIDAD
from cosco.db.models import Base

FECHA_CORTE = date(2026, 10, 24)  # "hoy" para la demo: fin del historial
TARIFA_MERCADO_KM = 11_500  # COP/km para una tractomula 40' en un corredor típico
CARGO_FIJO = 650_000  # COP por viaje (cargue, descargue, peajes base)
STANDBY_COP_H = 45_000  # costo de hora de vehículo detenido
MESES_LLUVIA = {4, 5, 10, 11}

RESOLUCION_H = {  # horas medianas para resolver cada imprevisto
    "Avería mecánica": 6,
    "Derrumbe / cierre vial": 14,
    "Bloqueo / paro": 20,
    "Retención documental": 7,
    "Accidente menor": 9,
    "Falla equipo de frío": 5,
    "Intento de hurto": 10,
}

SECTORES = ["Alimentos", "Retail", "Automotriz", "Químicos", "Farmacéutico", "Construcción",
            "Agroindustria", "Tecnología", "Minería", "Textil", "Bebidas", "Flores"]

# Pesos de destino (actividad económica) y de puerto de origen
PESO_PUERTO = {"Buenaventura": 0.38, "Cartagena": 0.32, "Barranquilla": 0.18, "Santa Marta": 0.12}
PESO_CIUDAD = {
    "Bogotá": 26, "Medellín": 14, "Cali": 11, "Barranquilla": 6, "Cartagena": 5, "Bucaramanga": 5,
    "Pereira": 3, "Manizales": 2.5, "Armenia": 2, "Ibagué": 2.5, "Cúcuta": 3, "Villavicencio": 2.5,
    "Neiva": 2, "Tunja": 1.5, "Pasto": 2, "Popayán": 1.5, "Montería": 2, "Sincelejo": 1.2,
    "Valledupar": 1.8, "Santa Marta": 2, "Riohacha": 0.8, "Yopal": 1.5, "Arauca": 0.6, "Mocoa": 0.5,
    "Florencia": 0.7, "Quibdó": 0.5, "San José del Guaviare": 0.4, "Buenaventura": 1,
}
MEZCLA_CARGA = {
    "Contenedor seco": 0.50, "Contenedor refrigerado": 0.12, "Carga suelta / paletizada": 0.14,
    "Carga extradimensionada": 0.04, "Mercancía peligrosa (IMO)": 0.08, "Granel líquido": 0.04,
    "Alto valor": 0.08,
}
PRIORIDADES = ["Equilibrado", "Tiempo", "Costo", "Carga crítica"]


# ====================================================================== utilidades
def _horas_planeadas(dist_km: float, terreno: float, vel_kmh: float) -> float:
    conduccion = dist_km * terreno / vel_kmh
    descanso = math.floor(conduccion / 10) * 8  # 8 h de descanso por cada 10 h de manejo
    return conduccion + descanso + 6  # + cargue/descargue y trámites


def _estado_texto(p: float) -> str:
    return "Excelente" if p >= 88 else "Bueno" if p >= 74 else "Regular" if p >= 60 else "Malo"


def _ajuste_tendencia(prov: dict, fecha: date) -> float:
    t = prov["tendencia"]
    if t[0] == "estable" or fecha < t[1]:
        return 0.0
    if t[0] == "deterioro":  # rampa de 3 meses hasta el delta completo
        return t[2] * min(1.0, (fecha - t[1]).days / 90)
    meses_total = max(1, (FECHA_CORTE - t[1]).days)
    return t[2] * min(1.0, (fecha - t[1]).days / meses_total)


def _ajuste_segmento(prov: dict, reg_o: str, reg_d: str, carga: str) -> float:
    seg = prov["segmentos"]
    deltas_region = [seg[("region", r)] for r in {reg_o, reg_d} if ("region", r) in seg]
    delta = max(deltas_region, key=abs) if deltas_region else 0.0
    return delta + seg.get(("carga", carga), 0.0)


def _factible(prov: dict, origen: str, destino: str, carga: str, vehiculo: str) -> bool:
    if vehiculo not in prov["flota"]:
        return False
    if geo.region(origen) not in prov["regiones"] or geo.region(destino) not in prov["regiones"]:
        return False
    cert = catalog.CERT_REQUERIDA.get(carga)
    return cert is None or cert in prov["certs"]


# ====================================================================== cobertura
def verificar_cobertura(proveedores: list[dict]) -> pd.DataFrame:
    """Para cada par de ciudades × tipo de carga, cuenta los proveedores que lo pueden atender."""
    filas = []
    ciudades = list(geo.CIUDADES)
    for o in ciudades:
        for d in ciudades:
            if o == d:
                continue
            for carga, vehiculos in catalog.CARGAS.items():
                n = sum(any(_factible(p, o, d, carga, v) for v in vehiculos) for p in proveedores)
                filas.append((o, d, carga, n))
    return pd.DataFrame(filas, columns=["origen", "destino", "tipo_carga", "proveedores_factibles"])


# ====================================================================== generación
class Generador:
    def __init__(self, n_servicios: int, meses: int, semilla: int):
        self.rng = np.random.default_rng(semilla)
        self.fake = Faker("es_CO")
        Faker.seed(semilla)
        self.n_servicios = n_servicios
        self.inicio = FECHA_CORTE - timedelta(days=int(meses * 30.44))
        self.tablas: dict[str, pd.DataFrame] = {}
        self.verdad: dict = {}

    # ------------------------------------------------------------ catálogos
    def catalogos(self):
        reg = pd.DataFrame({"id": range(1, len(geo.REGIONES) + 1), "nombre": geo.REGIONES})
        self.reg_id = dict(zip(reg.nombre, reg.id))
        ciu = pd.DataFrame(
            [
                dict(id=i + 1, nombre=c, region_id=self.reg_id[v[2]], lat=v[0], lon=v[1], es_puerto=v[3],
                     factor_terreno=v[4], riesgo_vial=v[5])
                for i, (c, v) in enumerate(geo.CIUDADES.items())
            ]
        )
        self.ciu_id = dict(zip(ciu.nombre, ciu.id))
        tv = pd.DataFrame(
            [
                dict(id=i + 1, nombre=k, capacidad_t=v["cap_t"], teu=v["teu"], mult_tarifa=v["mult_tarifa"],
                     velocidad_kmh=v["vel"])
                for i, (k, v) in enumerate(catalog.VEHICULOS.items())
            ]
        )
        self.tv_id = dict(zip(tv.nombre, tv.id))
        tc = pd.DataFrame(
            [
                dict(id=i + 1, nombre=k, certificacion_requerida=catalog.CERT_REQUERIDA.get(k),
                     sensibilidad=catalog.SENSIBILIDAD[k])
                for i, k in enumerate(catalog.CARGAS)
            ]
        )
        self.tc_id = dict(zip(tc.nombre, tc.id))
        comp = pd.DataFrame(
            [
                dict(tipo_carga_id=self.tc_id[c], tipo_vehiculo_id=self.tv_id[v], preferencia=j + 1)
                for c, vs in catalog.CARGAS.items()
                for j, v in enumerate(vs)
            ]
        )
        certs = sorted({c for p in PROVEEDORES for c in p["certs"]} | set(catalog.CERT_REQUERIDA.values()))
        cert = pd.DataFrame({"id": range(1, len(certs) + 1), "nombre": certs})
        self.cert_id = dict(zip(cert.nombre, cert.id))

        ciudades_cliente = list(PESO_CIUDAD)
        pesos = np.array([PESO_CIUDAD[c] for c in ciudades_cliente])
        cli = pd.DataFrame(
            [
                dict(id=i + 1, nombre=self.fake.unique.company(), sector=self.rng.choice(SECTORES),
                     ciudad_id=self.ciu_id[self.rng.choice(ciudades_cliente, p=pesos / pesos.sum())])
                for i in range(45)
            ]
        )
        self.tablas.update(regiones=reg, ciudades=ciu, tipos_vehiculo=tv, tipos_carga=tc,
                           compatibilidad_carga=comp, certificaciones=cert, clientes=cli)

    # ------------------------------------------------------------ proveedores, flota, conductores
    def proveedores(self):
        rng = self.rng
        provs, cob, pcert, veh, cond, tar = [], [], [], [], [], []
        placas = set()
        vid = cid = 1
        self.flota_por_prov: dict[tuple[int, str], list[int]] = {}
        self.cond_por_prov: dict[int, list[int]] = {}
        self.veh_estado: dict[int, float] = {}
        self.cond_puntaje: dict[int, float] = {}
        for i, p in enumerate(PROVEEDORES, start=1):
            p["id"] = i
            inicio = p.get("inicio_cosco", self.inicio - timedelta(days=int(rng.integers(100, 2000))))
            p["inicio_cosco_real"] = inicio
            provs.append(dict(
                id=i, nombre=p["nombre"], nit=f"{rng.integers(800_000_000, 901_999_999)}-{rng.integers(0, 9)}",
                ciudad_base_id=self.ciu_id[p["base"]], anio_fundacion=p["fundacion"], fecha_inicio_cosco=inicio,
                tiempo_reaccion_prom_h=round(p["reaccion_h"] * rng.uniform(0.65, 0.85), 1),  # declarado: optimista
                puntaje_desempeno_cosco=0.0, otd_historico=0.0, tiempo_entrega_prom_h=0.0, servicios_historicos=0,
                contacto=self.fake.email(), activo=True,
            ))
            cob += [dict(proveedor_id=i, region_id=self.reg_id[r]) for r in p["regiones"]]
            pcert += [dict(proveedor_id=i, certificacion_id=self.cert_id[c],
                           vence=FECHA_CORTE + timedelta(days=int(rng.integers(60, 700)))) for c in p["certs"]]
            for tipo, n in p["flota"].items():
                ids = []
                for _ in range(n):
                    while True:
                        placa = f"{''.join(rng.choice(list('ABCDEFGHIJKLMNOPRSTUVWXYZ'), 3))}{rng.integers(100, 999)}"
                        if placa not in placas:
                            placas.add(placa)
                            break
                    anio = int(np.clip(rng.normal(2026 - (100 - p["estado_flota"]) / 3.5, 3), 2004, 2026))
                    puntaje = float(np.clip(rng.normal(p["estado_flota"], 7), 30, 100))
                    veh.append(dict(
                        id=vid, proveedor_id=i, tipo_vehiculo_id=self.tv_id[tipo], placa=placa, modelo_anio=anio,
                        estado=_estado_texto(puntaje), puntaje_estado=round(puntaje, 1),
                        kilometraje=int((2026 - anio + 0.5) * rng.uniform(70_000, 120_000)),
                        gps=bool(rng.random() < (0.98 if "Escolta y GPS" in p["certs"] else 0.8)),
                        ultima_revision=FECHA_CORTE - timedelta(days=int(rng.integers(5, 200))),
                    ))
                    self.veh_estado[vid] = puntaje
                    ids.append(vid)
                    vid += 1
                self.flota_por_prov[(i, tipo)] = ids
                base_km = TARIFA_MERCADO_KM * catalog.VEHICULOS[tipo]["mult_tarifa"] * p["precio"]
                tar.append(dict(proveedor_id=i, tipo_vehiculo_id=self.tv_id[tipo],
                                tarifa_km_cop=round(base_km * rng.uniform(0.97, 1.03), -1),
                                cargo_fijo_cop=round(CARGO_FIJO * p["precio"] * rng.uniform(0.9, 1.1), -3),
                                vigente_desde=date(2026, 1, 1)))
            n_cond = int(sum(p["flota"].values()) * 1.15)
            self.cond_por_prov[i] = []
            for _ in range(n_cond):
                m = {k: float(np.clip(rng.normal(p["conductores"], 8), 35, 100)) for k in catalog.METRICAS_CONDUCTOR}
                total = sum(m[k] * w for k, w in catalog.METRICAS_CONDUCTOR.items())
                cond.append(dict(id=cid, proveedor_id=i, nombre=self.fake.name_male() if rng.random() < 0.93
                                 else self.fake.name_female(), cedula=str(rng.integers(10_000_000, 1_199_999_999)),
                                 anios_experiencia=int(rng.integers(1, 30)), **{k: round(v, 1) for k, v in m.items()},
                                 puntaje_total=round(total, 1)))
                self.cond_puntaje[cid] = total
                self.cond_por_prov[i].append(cid)
                cid += 1
            self.verdad[p["nombre"]] = {
                k: (v if not isinstance(v, (date, tuple, dict)) else str(v))
                for k, v in p.items() if k not in ("flota", "regiones", "certs", "id", "inicio_cosco_real")
            }
        self.tablas.update(
            proveedores=pd.DataFrame(provs), cobertura=pd.DataFrame(cob), proveedor_certificaciones=pd.DataFrame(pcert),
            vehiculos=pd.DataFrame(veh), conductores=pd.DataFrame(cond), tarifas=pd.DataFrame(tar),
        )
        self.tarifa = {(r.proveedor_id, r.tipo_vehiculo_id): (r.tarifa_km_cop, r.cargo_fijo_cop)
                       for r in self.tablas["tarifas"].itertuples()}

    # ------------------------------------------------------------ solicitud aleatoria
    def _solicitud_aleatoria(self, fecha: datetime) -> dict:
        rng = self.rng
        ciudades = list(PESO_CIUDAD)
        pesos = np.array([PESO_CIUDAD[c] for c in ciudades], float)
        if rng.random() < 0.72:  # importación/exportación por puerto
            puerto = rng.choice(list(PESO_PUERTO), p=list(PESO_PUERTO.values()))
            pi = pesos.copy()
            pi[ciudades.index(puerto)] = 0
            interior = rng.choice(ciudades, p=pi / pi.sum())
            origen, destino = (puerto, interior) if rng.random() < 0.68 else (interior, puerto)
        else:
            origen = rng.choice(ciudades, p=pesos / pesos.sum())
            pd_ = pesos.copy()
            pd_[ciudades.index(origen)] = 0
            destino = rng.choice(ciudades, p=pd_ / pd_.sum())
        carga = rng.choice(list(MEZCLA_CARGA), p=list(MEZCLA_CARGA.values()))
        opciones = catalog.CARGAS[carga]
        vehiculo = opciones[0] if rng.random() < 0.7 else rng.choice(opciones)
        unidades = int(rng.choice([1, 1, 1, 1, 1, 2, 2, 3, 4, 6]))
        cap = catalog.VEHICULOS[vehiculo]["cap_t"]
        peso = round(unidades * cap * rng.uniform(0.45, 0.95), 1)
        dist = geo.distancia_km(origen, destino)
        estandar = _horas_planeadas(dist, geo.factor_terreno(origen, destino), catalog.VEHICULOS[vehiculo]["vel"] * 0.94)
        prioridad = rng.choice(PRIORIDADES, p=[0.45, 0.25, 0.2, 0.1])
        holgura = {"Tiempo": (1.02, 1.18), "Costo": (1.2, 1.6)}.get(prioridad, (1.1, 1.4))
        plazo = round(estandar * rng.uniform(*holgura), 0)
        presupuesto = None
        if rng.random() < 0.6:
            mercado = (TARIFA_MERCADO_KM * catalog.VEHICULOS[vehiculo]["mult_tarifa"] * dist + CARGO_FIJO) * unidades
            presupuesto = round(mercado * rng.uniform(0.95, 1.25), -4)
        return dict(fecha_solicitud=fecha, cliente_id=int(rng.integers(1, 46)), origen=origen, destino=destino,
                    carga=carga, vehiculo=vehiculo, unidades=unidades, peso_t=peso, plazo_horas=plazo,
                    presupuesto_cop=presupuesto, prioridad=prioridad, dist=dist)

    # ------------------------------------------------------------ resultado "real" de un servicio
    def simular_servicio(self, prov: dict, s: dict, fecha: datetime, unidades: int) -> tuple[dict, dict | None]:
        rng = self.rng
        o, d, carga, veh_tipo = s["origen"], s["destino"], s["carga"], s["vehiculo"]
        vehiculo_id = int(rng.choice(self.flota_por_prov[(prov["id"], veh_tipo)]))
        conductor_id = int(rng.choice(self.cond_por_prov[prov["id"]]))
        estado = self.veh_estado[vehiculo_id]
        conductor = self.cond_puntaje[conductor_id]
        terreno = geo.factor_terreno(o, d)
        vel = catalog.VEHICULOS[veh_tipo]["vel"] * prov["vel"]
        planeado = _horas_planeadas(s["dist"], terreno, vel)

        lluvia = 1.6 if fecha.month in MESES_LLUVIA else 1.0
        p_imp = (prov["imprevisto"] + geo.riesgo_corredor(o, d) * 0.8 * lluvia
                 + (100 - estado) / 100 * 0.06 + (100 - conductor) / 100 * 0.03)
        q_tarde = max(0.005, prov["q_tarde"] + _ajuste_segmento(prov, geo.region(o), geo.region(d), carga)
                      + _ajuste_tendencia(prov, fecha.date()) + (100 - conductor) / 100 * 0.04)

        real = planeado * rng.lognormal(0.0, prov["sigma"])
        if rng.random() < q_tarde:  # retraso operativo
            real += planeado * rng.exponential(0.45) + rng.uniform(4, 12)

        imprevisto = None
        if rng.random() < min(p_imp, 0.6):
            tipos = list(RESOLUCION_H)
            w = np.array([3, 2 * lluvia * terreno, 1.5, 1.2, 1.0, 2.5 if "Reefer" in veh_tipo else 0,
                          1.5 if carga == "Alto valor" or geo.riesgo_corredor(o, d) > 0.1 else 0.3])
            tipo = rng.choice(tipos, p=w / w.sum())
            reaccion = rng.gamma(2.0, prov["reaccion_h"] / 2)
            retraso = reaccion + rng.lognormal(math.log(RESOLUCION_H[tipo]), 0.5)
            extra = retraso * STANDBY_COP_H * catalog.VEHICULOS[veh_tipo]["mult_tarifa"] + (
                rng.uniform(400_000, 2_500_000) if tipo in ("Avería mecánica", "Accidente menor") else 0)
            real += retraso
            imprevisto = dict(tipo=tipo, tiempo_reaccion_h=round(reaccion, 1), retraso_h=round(retraso, 1),
                              costo_extra_cop=round(extra, -3))
        if imprevisto:
            mult = 1.3 if imprevisto["tipo"] in ("Accidente menor", "Falla equipo de frío", "Intento de hurto") else 0.6
            p_dano = catalog.SENSIBILIDAD[carga] * (1.6 - estado / 100) * mult * (1 + imprevisto["tiempo_reaccion_h"] / 10)
        else:
            p_dano = 0.002
        dano = bool(rng.random() < p_dano)

        tarifa_km, fijo = self.tarifa[(prov["id"], self.tv_id[veh_tipo])]
        cotizado = (tarifa_km * s["dist"] + fijo) * unidades
        final = cotizado * (1 + max(0.0, rng.normal(prov["sobrecosto"], 0.025)))
        if imprevisto:
            final += imprevisto["costo_extra_cop"] * 0.5 * unidades
        a_tiempo = real <= s["plazo_horas"]
        nota = 5 - (not a_tiempo) - (real - s["plazo_horas"] > 12) - 2 * dano - (final / cotizado > 1.08)
        nota = int(np.clip(nota + rng.choice([-1, 0, 0, 0, 1]) * (nota < 5), 1, 5))
        servicio = dict(proveedor_id=prov["id"], vehiculo_id=vehiculo_id, conductor_id=conductor_id,
                        fecha_cargue=fecha + timedelta(hours=float(rng.uniform(2, 30))), distancia_km=s["dist"],
                        unidades=unidades, tiempo_planeado_h=round(planeado, 1), tiempo_real_h=round(real, 1),
                        a_tiempo=bool(a_tiempo), costo_cotizado_cop=round(cotizado, -3), costo_final_cop=round(final, -3),
                        tuvo_imprevisto=imprevisto is not None, dano_carga=dano, calificacion_cliente=nota)
        if imprevisto:
            imprevisto["descripcion"] = self._describir_imprevisto(imprevisto, o, d, prov["nombre"])
        return servicio, imprevisto

    def _describir_imprevisto(self, imp: dict, o: str, d: str, prov: str) -> str:
        tramo = {
            "Derrumbe / cierre vial": "cierre por derrumbe en la vía",
            "Bloqueo / paro": "bloqueo por paro en la vía",
            "Avería mecánica": "avería mecánica del vehículo",
            "Retención documental": "retención en control por documentación incompleta",
            "Accidente menor": "accidente menor en ruta",
            "Falla equipo de frío": "falla del equipo de frío del contenedor",
            "Intento de hurto": "intento de hurto en ruta",
        }[imp["tipo"]]
        return (f"{tramo.capitalize()} en el trayecto {o}–{d}. {prov} reaccionó en "
                f"{imp['tiempo_reaccion_h']} h; retraso total {imp['retraso_h']} h.")

    # ------------------------------------------------------------ historial
    def historial(self):
        rng = self.rng
        dias = (FECHA_CORTE - self.inicio).days
        # crecimiento de volumen en el tiempo (+35 % en el periodo)
        t = rng.uniform(0, 1, self.n_servicios)
        t = np.sort((np.sqrt(1 + 0.35 * (2 + 0.35) * t) - 1) / 0.35 / 1.0)
        t = t / t.max()
        sols, servs, imps = [], [], []
        sid = 1
        for k in range(self.n_servicios):
            fecha = datetime.combine(self.inicio, datetime.min.time()) + timedelta(
                days=float(t[k] * (dias - 3)), hours=float(rng.uniform(6, 18)))
            s = self._solicitud_aleatoria(fecha)
            cands = [p for p in PROVEEDORES if p["inicio_cosco_real"] <= fecha.date()
                     and _factible(p, s["origen"], s["destino"], s["carga"], s["vehiculo"])]
            if not cands:
                continue
            # decisión humana histórica: precio + costumbre + ruido (no es óptima)
            util = np.array([-1.5 * p["precio"] + p["popularidad"] for p in cands]) + rng.gumbel(0, 0.55, len(cands))
            orden = [cands[j] for j in np.argsort(-util)]
            sol_id = len(sols) + 1
            sols.append(dict(id=sol_id, fecha_solicitud=fecha, cliente_id=s["cliente_id"],
                             origen_id=self.ciu_id[s["origen"]], destino_id=self.ciu_id[s["destino"]],
                             tipo_carga_id=self.tc_id[s["carga"]], tipo_vehiculo_id=self.tv_id[s["vehiculo"]],
                             unidades=s["unidades"], peso_t=s["peso_t"], plazo_horas=s["plazo_horas"],
                             presupuesto_cop=s["presupuesto_cop"], prioridad=s["prioridad"], fase="historico",
                             estado="atendida"))
            reparto = [(orden[0], s["unidades"])]
            if s["unidades"] >= 3 and len(orden) > 1 and rng.random() < 0.35:  # carga dividida
                a = int(math.ceil(s["unidades"] / 2))
                reparto = [(orden[0], a), (orden[1], s["unidades"] - a)]
            for prov, u in reparto:
                serv, imp = self.simular_servicio(prov, s, fecha, u)
                serv.update(id=sid, solicitud_id=sol_id)
                servs.append(serv)
                if imp:
                    imp.update(servicio_id=sid)
                    imps.append(imp)
                sid += 1
        imp_df = pd.DataFrame(imps)
        imp_df.insert(0, "id", range(1, len(imp_df) + 1))
        self.tablas.update(solicitudes=pd.DataFrame(sols), servicios=pd.DataFrame(servs), imprevistos=imp_df)
        self._sol_meta = {s["id"]: s for s in sols}

    # ------------------------------------------------------------ evaluación mensual y resumen
    def evaluaciones(self):
        rng = self.rng
        sv = self.tablas["servicios"].copy()
        sv["mes"] = pd.to_datetime(sv["fecha_cargue"]).dt.to_period("M").dt.to_timestamp().dt.date
        sv["sobrecosto"] = sv.costo_final_cop / sv.costo_cotizado_cop - 1
        filas = []
        for (pid, mes), g in sv.groupby(["proveedor_id", "mes"]):
            p = PROVEEDORES[pid - 1]
            otd = g.a_tiempo.mean() * 100
            sin = 100 - (g.tuvo_imprevisto.mean() * 60 + g.dano_carga.mean() * 400)
            doc = np.clip(rng.normal(p["doc"], 4), 0, 100)
            com = np.clip(rng.normal(p["com"], 4), 0, 100)
            tar = np.clip(100 - g.sobrecosto.mean() * 600, 0, 100)
            m = dict(otd=otd, siniestralidad=np.clip(sin, 0, 100), documentacion=doc, comunicacion_trazabilidad=com,
                     cumplimiento_tarifa=tar)
            total = sum(m[k] * w for k, w in catalog.ESTANDAR_COSCO.items())
            filas.append(dict(proveedor_id=pid, mes=mes, servicios=len(g), **{k: round(float(v), 1) for k, v in m.items()},
                              puntaje_total=round(float(total), 1)))
        ev = pd.DataFrame(filas)
        ev.insert(0, "id", range(1, len(ev) + 1))
        self.tablas["evaluaciones_mensuales"] = ev

        pr = self.tablas["proveedores"]
        corte6 = FECHA_CORTE - timedelta(days=183)
        for idx, row in pr.iterrows():
            g = sv[sv.proveedor_id == row.id]
            e = ev[(ev.proveedor_id == row.id) & (pd.to_datetime(ev.mes).dt.date >= corte6)]
            if e.empty:
                e = ev[ev.proveedor_id == row.id]
            pr.loc[idx, "otd_historico"] = round(float(g.a_tiempo.mean()), 3) if len(g) else 0.0
            pr.loc[idx, "tiempo_entrega_prom_h"] = round(float(g.tiempo_real_h.mean()), 1) if len(g) else 0.0
            pr.loc[idx, "servicios_historicos"] = len(g)
            pr.loc[idx, "puntaje_desempeno_cosco"] = (
                round(float(np.average(e.puntaje_total, weights=e.servicios)), 1) if len(e) else 0.0)

    # ------------------------------------------------------------ disponibilidad futura
    def disponibilidad(self, dias: int = 30):
        rng = self.rng
        filas = []
        for p in PROVEEDORES:
            for tipo, n in p["flota"].items():
                for k in range(dias):
                    f = FECHA_CORTE + timedelta(days=k)
                    util = np.clip(p["utilizacion"] + (0.08 if f.weekday() < 5 else -0.15) + rng.normal(0, 0.08), 0, 1)
                    libres = int(n - rng.binomial(n, util))
                    for nom, veh, desde, hasta, cupo in RESTRICCIONES_DISPONIBILIDAD:
                        if nom == p["nombre"] and veh == tipo and desde <= f <= hasta:
                            libres = min(libres, cupo)
                    filas.append(dict(proveedor_id=p["id"], tipo_vehiculo_id=self.tv_id[tipo], fecha=f,
                                      vehiculos_totales=n, vehiculos_disponibles=libres))
        df = pd.DataFrame(filas)
        df.insert(0, "id", range(1, len(df) + 1))
        self.tablas["disponibilidad"] = df

    # ------------------------------------------------------------ solicitudes de la fase de prueba
    def solicitudes_prueba(self, n: int = 30):
        rng = self.rng
        sols = self.tablas["solicitudes"]
        siguiente = int(sols.id.max()) + 1
        filas = []
        for k in range(n):
            fecha = datetime.combine(FECHA_CORTE, datetime.min.time()) + timedelta(
                days=int(rng.integers(1, 7)), hours=float(rng.uniform(6, 18)))
            s = self._solicitud_aleatoria(fecha)
            filas.append(dict(id=siguiente + k, fecha_solicitud=fecha, cliente_id=s["cliente_id"],
                              origen_id=self.ciu_id[s["origen"]], destino_id=self.ciu_id[s["destino"]],
                              tipo_carga_id=self.tc_id[s["carga"]], tipo_vehiculo_id=self.tv_id[s["vehiculo"]],
                              unidades=s["unidades"], peso_t=s["peso_t"], plazo_horas=s["plazo_horas"],
                              presupuesto_cop=s["presupuesto_cop"], prioridad=s["prioridad"], fase="prueba",
                              estado="pendiente"))
        self.tablas["solicitudes"] = pd.concat([sols, pd.DataFrame(filas)], ignore_index=True)

    # ------------------------------------------------------------ memoria inicial del asistente
    def memoria(self, n_lecciones: int = 30):
        sv = self.tablas["servicios"]
        imp = self.tablas["imprevistos"].merge(sv, left_on="servicio_id", right_on="id", suffixes=("", "_s"))
        sol = self.tablas["solicitudes"].set_index("id")
        ciu = self.tablas["ciudades"].set_index("id").nombre
        tc = self.tablas["tipos_carga"].set_index("id").nombre
        pr = self.tablas["proveedores"].set_index("id").nombre
        graves = imp.sort_values("retraso_h", ascending=False).head(n_lecciones // 2)
        danos = imp[imp.dano_carga].sort_values("costo_extra_cop", ascending=False).head(n_lecciones // 4)
        rapidos = imp[(imp.tiempo_reaccion_h < 1.0) & (imp.retraso_h < 10)].head(n_lecciones // 4)
        filas = []
        for grupo, tipo in ((graves, "retraso"), (danos, "daño"), (rapidos, "buena reacción")):
            for r in grupo.itertuples():
                s = sol.loc[r.solicitud_id]
                o, d, c, p = ciu[s.origen_id], ciu[s.destino_id], tc[s.tipo_carga_id], pr[r.proveedor_id]
                mes = pd.Timestamp(r.fecha_cargue).strftime("%m/%Y")
                if tipo == "retraso":
                    titulo = f"{r.tipo} dejó {r.retraso_h:.0f} h de retraso en {o}–{d}"
                    cons = (f"La carga ({c}) llegó {r.tiempo_real_h - s.plazo_horas:.0f} h después del plazo; "
                            f"sobrecosto de {r.costo_final_cop - r.costo_cotizado_cop:,.0f} COP.")
                    leccion = (f"En {o}–{d} prever holgura extra" + (" en temporada de lluvias" if
                               pd.Timestamp(r.fecha_cargue).month in MESES_LLUVIA else "") +
                               f"; {p} tardó {r.tiempo_reaccion_h} h en reaccionar.")
                    imp_n = 4
                elif tipo == "daño":
                    titulo = f"Daño de carga {c.lower()} con {p} ({o}–{d})"
                    cons = f"Hubo daño en la mercancía después de: {r.tipo.lower()}. Reclamación del cliente."
                    leccion = f"Para {c.lower()} exigir vehículos en estado Excelente/Bueno y reacción < 2 h."
                    imp_n = 5
                else:
                    titulo = f"{p} resolvió rápido un imprevisto en {o}–{d}"
                    cons = f"Reaccionó en {r.tiempo_reaccion_h} h y el retraso fue de solo {r.retraso_h:.0f} h."
                    leccion = f"{p} es buena opción de respaldo en {o}–{d} cuando hay riesgo de imprevistos."
                    imp_n = 3
                filas.append(dict(fecha=pd.Timestamp(r.fecha_cargue).to_pydatetime(), origen_id=s.origen_id,
                                  destino_id=s.destino_id, tipo_carga_id=s.tipo_carga_id, proveedor_id=r.proveedor_id,
                                  servicio_id=r.servicio_id, titulo=titulo, que_paso=f"{mes}: {r.descripcion}",
                                  consecuencia=cons, leccion=leccion, importancia=imp_n,
                                  etiquetas=",".join([tipo, r.tipo, geo.region(o), geo.region(d), c]), fuente="historico"))
        mem = pd.DataFrame(filas)
        mem.insert(0, "id", range(1, len(mem) + 1))
        self.tablas["casos_memoria"] = mem

    def generar(self):
        self.catalogos()
        self.proveedores()
        self.historial()
        self.evaluaciones()
        self.disponibilidad()
        self.solicitudes_prueba()
        self.memoria()
        return self.tablas


ORDEN_CARGA = [
    "regiones", "ciudades", "tipos_vehiculo", "tipos_carga", "compatibilidad_carga", "clientes", "certificaciones",
    "proveedores", "proveedor_certificaciones", "cobertura", "vehiculos", "conductores", "tarifas", "disponibilidad",
    "solicitudes", "servicios", "imprevistos", "evaluaciones_mensuales", "casos_memoria",
]


def cargar(tablas: dict[str, pd.DataFrame], url: str | None = None, csv: bool = True) -> None:
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for nombre in ORDEN_CARGA:
        tablas[nombre].to_sql(nombre, engine, if_exists="append", index=False, chunksize=2000, method="multi")
    if engine.dialect.name == "postgresql":  # alinear secuencias de id tras insertar ids explícitos
        with engine.begin() as cx:
            for t in inspect(engine).get_table_names():
                if "id" in [c["name"] for c in inspect(engine).get_columns(t)]:
                    cx.exec_driver_sql(
                        f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
    if csv:
        carpeta = RAIZ / "data" / "csv"
        carpeta.mkdir(parents=True, exist_ok=True)
        for nombre, df in tablas.items():
            df.to_csv(carpeta / f"{nombre}.csv", index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--servicios", type=int, default=10_000, help="solicitudes históricas a generar")
    ap.add_argument("--meses", type=int, default=24)
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--sin-csv", action="store_true")
    ap.add_argument("--forzar", action="store_true", help="borrar y volver a cargar una BD de Postgres que ya tiene datos")
    a = ap.parse_args()

    engine = get_engine()
    if engine.dialect.name == "postgresql" and not a.forzar and "solicitudes" in inspect(engine).get_table_names():
        raise SystemExit("La BD de Supabase ya tiene datos y el seeder la borraría entera (incluidas decisiones y "
                         "memoria). Para crear solo tablas nuevas: python -m cosco.db.migrar. "
                         "Para volver a cargar todo de verdad: --forzar.")

    faltantes = verificar_cobertura(PROVEEDORES).query("proveedores_factibles == 0")
    if not faltantes.empty:
        raise SystemExit(f"Hay casos sin proveedor factible:\n{faltantes}")

    gen = Generador(a.servicios, a.meses, a.semilla)
    tablas = gen.generar()
    cargar(tablas, csv=not a.sin_csv)
    (RAIZ / "data").mkdir(exist_ok=True)
    with open(RAIZ / "data" / "verdad_oculta.json", "w", encoding="utf-8") as f:
        json.dump(gen.verdad, f, ensure_ascii=False, indent=2)
    url = database_url()
    print(f"BD cargada en {url.split('@')[-1]}")
    for n in ORDEN_CARGA:
        print(f"  {n:<26} {len(tablas[n]):>7,} filas")


if __name__ == "__main__":
    main()
