"""Filtros duros: "¿puede hacerlo?". Región, vehículo, certificación y cupo ese día."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cosco.motor.datos import Datos


@dataclass
class Revision:
    proveedor_id: int
    pasa: bool
    motivo: str | None          # por qué no pasa (None si pasa)
    disponibles: int            # vehículos libres del tipo pedido ese día
    tarifa: tuple[float, float] | None  # (COP/km, cargo fijo)
    cupo_parcial: bool = False  # tiene cupo, pero menos del que pide la solicitud (sirve para carga dividida)


def tarifa_vigente(d: Datos, proveedor_id: int, tipo_vehiculo_id: int, fecha: date) -> tuple[float, float] | None:
    t = d.tarifas[(d.tarifas.proveedor_id == proveedor_id) & (d.tarifas.tipo_vehiculo_id == tipo_vehiculo_id)
                  & (d.tarifas.vigente_desde <= fecha)]
    if t.empty:
        return None
    fila = t.sort_values("vigente_desde").iloc[-1]
    return float(fila.tarifa_km_cop), float(fila.cargo_fijo_cop)


def cupo(d: Datos, proveedor_id: int, tipo_vehiculo_id: int, fecha: date) -> int:
    if d.cupo_ilimitado:
        return int(((d.vehiculos.proveedor_id == proveedor_id) & (d.vehiculos.tipo_vehiculo_id == tipo_vehiculo_id)).sum())
    disp = d.disponibilidad
    fila = disp[(disp.proveedor_id == proveedor_id) & (disp.tipo_vehiculo_id == tipo_vehiculo_id) & (disp.fecha == fecha)]
    if not fila.empty:
        return int(fila.vehiculos_disponibles.iloc[0])
    # fuera de los 30 días con dato de cupo: se supone libre un tercio de la flota de ese tipo
    flota = int(((d.vehiculos.proveedor_id == proveedor_id) & (d.vehiculos.tipo_vehiculo_id == tipo_vehiculo_id)).sum())
    return flota // 3


def revisar(d: Datos, proveedor_id: int, origen_id: int, destino_id: int, tipo_carga_id: int,
            tipo_vehiculo_id: int, unidades: int, fecha: date) -> Revision:
    nombre_v = d.nombre("tipos_vehiculo", tipo_vehiculo_id)
    compatibles = d.compatibilidad[d.compatibilidad.tipo_carga_id == tipo_carga_id].tipo_vehiculo_id
    if tipo_vehiculo_id not in set(compatibles):
        return Revision(proveedor_id, False, f"el vehículo {nombre_v} no sirve para esta carga", 0, None)

    regiones = set(d.cobertura[d.cobertura.proveedor_id == proveedor_id].region_id)
    faltan = [d.nombre("regiones", r) for r in {d.ciudades.at[origen_id, "region_id"],
                                                 d.ciudades.at[destino_id, "region_id"]} if r not in regiones]
    if faltan:
        return Revision(proveedor_id, False, f"no opera en {', '.join(sorted(faltan))}", 0, None)

    cert = d.tipos_carga.at[tipo_carga_id, "certificacion_requerida"]
    if isinstance(cert, str) and cert:
        cert_id = d.id_de("certificaciones", cert)
        pc = d.prov_cert[(d.prov_cert.proveedor_id == proveedor_id) & (d.prov_cert.certificacion_id == cert_id)]
        if pc.empty:
            return Revision(proveedor_id, False, f"no tiene la certificación {cert}", 0, None)
        if (pc.vence < fecha).all():
            return Revision(proveedor_id, False, f"la certificación {cert} vence antes del envío", 0, None)

    tarifa = tarifa_vigente(d, proveedor_id, tipo_vehiculo_id, fecha)
    flota = int(((d.vehiculos.proveedor_id == proveedor_id) & (d.vehiculos.tipo_vehiculo_id == tipo_vehiculo_id)).sum())
    if flota == 0 or tarifa is None:
        return Revision(proveedor_id, False, f"no tiene {nombre_v} en su flota", 0, None)

    libres = cupo(d, proveedor_id, tipo_vehiculo_id, fecha)
    if libres == 0:
        return Revision(proveedor_id, False, f"no tiene {nombre_v} libre el {fecha:%d/%m}", 0, tarifa)
    if libres < unidades:
        return Revision(proveedor_id, False, f"solo tiene {libres} de {unidades} {nombre_v} libres el {fecha:%d/%m}",
                        libres, tarifa, cupo_parcial=True)
    return Revision(proveedor_id, True, None, libres, tarifa)
