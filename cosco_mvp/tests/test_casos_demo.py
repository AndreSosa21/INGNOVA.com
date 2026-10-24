"""Casos de uso de la demo: el sistema no se rompe ante capacidad insuficiente, plazos o presupuestos imposibles,
cargas con certificación, rutas sin cobertura y entradas inválidas del portal.

Las afirmaciones son estructurales (qué etapa descarta, si hay alternativa), no cifras exactas, salvo el texto de
capacidad que sale de la tabla `disponibilidad` del 27/10/2026 (fecha de cargue usada en todos los casos).
Correr:  python -m pytest tests/test_casos_demo.py -v
"""
import json

import pytest

from cosco import solicitudes
from cosco.db import RAIZ
from cosco.motor import api

if not (RAIZ / "data" / "cosco.db").exists():
    pytest.skip("falta data/cosco.db: correr python -m cosco.db.seed", allow_module_level=True)

BASE = dict(prioridad="Equilibrado", presupuesto_cop=None, peso_t=20, fecha="2026-10-27")


def rank(extra, req=None):
    r = api.consultar_ranking({**BASE, **extra}, req or [])
    json.dumps(r)                                   # siempre serializable: nada de NaN ni objetos raros
    return r


def motivos(r, etapa=None):
    return {d["proveedor"]: d["motivo"] for d in r["descartados"] if etapa in (None, d["etapa"])}


def test_c1_caso_normal_sin_alertas():
    r = rank(dict(origen="Bogotá", destino="Medellín", tipo_carga="Contenedor seco", unidades=1, plazo_horas=48))
    assert not r["sin_opcion"] and len(r["top3"]) == 3
    assert r["ranking"][0]["semaforo"] == "verde" and r["ranking"][0]["p_exito"] > 0.9


def test_c2_capacidad_insuficiente_descarta_y_deja_un_unico_proveedor_con_cupo():
    r = rank(dict(origen="Bogotá", destino="Barranquilla", tipo_carga="Contenedor seco", unidades=6, plazo_horas=96))
    cap = motivos(r, "capacidad")
    assert cap["Antioquia Freight"] == "solo tiene 4 de 6 Tractomula 40' (FEU) libres el 27/10"
    assert "Antioquia Freight" not in [o["proveedor"] for o in r["ranking"]]
    assert r["ranking"] and not r["sin_opcion"]


def test_c2b_ningun_proveedor_alcanza_solo_pero_dos_o_tres_juntos_si():
    r = rank(dict(origen="Bogotá", destino="Barranquilla", tipo_carga="Contenedor seco", unidades=8, plazo_horas=96))
    assert r["sin_opcion"]
    div = r["carga_dividida"]
    assert div and sum(x["unidades"] for x in div["reparto"]) == 8 and len(div["reparto"]) >= 2
    assert div["p_exito_conjunta"] <= min(x["p_exito"] for x in div["reparto"])   # el conjunto nunca supera a la parte


def test_c3_equipo_obliga_a_un_proveedor_sin_cupo():
    req = [dict(factor="proveedor", tipo="restriccion", valor="solo:Antioquia Freight")]
    r = rank(dict(origen="Bogotá", destino="Barranquilla", tipo_carga="Contenedor seco", unidades=6, plazo_horas=96), req)
    assert r["sin_opcion"] and not r["ranking"]
    assert "solo tiene 4 de 6" in motivos(r)["Antioquia Freight"]
    assert any(a["cambio"].get("fecha") and a["mejor"] == "Antioquia Freight" for a in r["alternativas"])


def test_c4_excluir_por_falta_de_capacidad_reordena():
    s = dict(origen="Bogotá", destino="Medellín", tipo_carga="Contenedor seco", unidades=1, plazo_horas=48)
    antes = rank(s)["ranking"][0]["proveedor"]
    despues = rank(s, [dict(factor="proveedor", tipo="restriccion", valor=f"excluir:{antes}")])
    assert antes not in [o["proveedor"] for o in despues["ranking"]]
    assert despues["ranking"] and despues["ranking"][0]["proveedor"] != antes


def test_c5_demanda_mayor_que_toda_la_red_propone_salidas():
    r = rank(dict(origen="Bogotá", destino="Barranquilla", tipo_carga="Contenedor seco", unidades=10, plazo_horas=96))
    assert r["sin_opcion"]
    cambios = [list(a["cambio"]) for a in r["alternativas"]]
    assert ["tipo_vehiculo"] in cambios and ["fecha"] in cambios


def test_c6_plazo_imposible_no_se_vende_como_bueno():
    r = rank(dict(origen="Buenaventura", destino="Cúcuta", tipo_carga="Contenedor seco", unidades=1, plazo_horas=20))
    assert all(o["p_exito"] < 0.05 and o["semaforo"] == "rojo" for o in r["ranking"][:3])
    amp = [a for a in r["alternativas"] if "plazo_horas" in a["cambio"]]
    assert amp and amp[0]["p_exito_mejor"] > 0.8


def test_c7_presupuesto_imposible_ofrece_cambiar_vehiculo_o_presupuesto():
    r = rank(dict(origen="Bogotá", destino="Cartagena", tipo_carga="Contenedor seco", unidades=2, plazo_horas=72,
                  presupuesto_cop=18_000_000))
    assert all(o["semaforo"] == "rojo" for o in r["ranking"][:3])
    tipos = {k for a in r["alternativas"] for k in a["cambio"]}
    assert tipos & {"presupuesto_cop", "tipo_vehiculo"}


def test_c8_carga_critica_exige_certificacion():
    r = rank(dict(origen="Bogotá", destino="Barranquilla", tipo_carga="Alto valor", unidades=1, plazo_horas=72,
                  prioridad="Carga crítica"))
    cert = [m for m in motivos(r, "filtro").values() if "Escolta y GPS" in m]
    assert len(cert) >= 5
    assert all(o["proveedor"] not in motivos(r) for o in r["ranking"])


def test_c9_refrigerado_pocos_proveedores_con_certificacion():
    r = rank(dict(origen="Bogotá", destino="Cali", tipo_carga="Contenedor refrigerado", unidades=2, plazo_horas=48,
                  fecha="2026-10-28"))
    assert len(r["ranking"]) <= 3
    assert sum("Cadena de frío" in m for m in motivos(r).values()) >= 5


def test_c10_extradimensionada_sin_vehiculo_libre_propone_otra_fecha_o_vehiculo():
    r = rank(dict(origen="Buenaventura", destino="Bogotá", tipo_carga="Carga extradimensionada", unidades=1,
                  plazo_horas=96, fecha="2026-10-28"))
    assert r["sin_opcion"] and r["alternativas"]


def test_c11_ruta_con_un_solo_proveedor():
    r = rank(dict(origen="Quibdó", destino="Arauca", tipo_carga="Contenedor refrigerado", unidades=1, plazo_horas=80))
    assert len(r["ranking"]) == 1 and r["ranking"][0]["proveedor"] == "FríoExpress Colombia"


@pytest.mark.parametrize("datos,mensaje", [
    (dict(origen="Bogotá", destino="Bogotá", fecha="2026-10-27", unidades=1, plazo_horas=48), "no pueden ser el mismo"),
    (dict(origen="Bogotá", destino="Cali", fecha="2026-10-20", unidades=1, plazo_horas=48), "anterior a hoy"),
    (dict(origen="Bogotá", destino="Cali", fecha="2026-10-27", unidades=0, plazo_horas=48), "al menos una unidad"),
    (dict(origen="Bogotá", destino="Cali", fecha="2026-10-27", unidades=1, plazo_horas=0), "mayor a cero"),
])
def test_c12_el_portal_rechaza_entradas_invalidas_con_mensaje(datos, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        solicitudes.crear({**datos, "tipo_carga": "Contenedor seco"})


def test_c13_las_30_solicitudes_de_prueba_nunca_rompen_el_motor():
    sin_opcion = 0
    for sid in range(10001, 10031):
        r = api.consultar_ranking(sid, [])
        json.dumps(r)
        sin_opcion += r["sin_opcion"]
        assert r["ranking"] or r["sin_opcion"]
        if r["sin_opcion"]:
            assert r["alternativas"] is not None
    assert sin_opcion <= 6        # hoy son 4; si sube mucho, algo cambió en datos o motor
