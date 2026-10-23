"""Pruebas del motor sobre la BD local (data/cosco.db). Se generan los datos si no existen."""
import json
import shutil

import pytest

from cosco.db import RAIZ, get_engine
from cosco.db.migrar import crear_faltantes
from cosco.motor import api
from cosco.motor.datos import cargar_datos
from cosco.motor.ranking import armar_solicitud, calcular, pesos_finales, armar_requisitos

BD = RAIZ / "data" / "cosco.db"


@pytest.fixture(scope="module")
def d():
    if not BD.exists():
        pytest.skip("falta data/cosco.db: correr python -m cosco.db.seed")
    return cargar_datos(get_engine(f"sqlite:///{BD}"))


URGENTE = dict(origen="Buenaventura", destino="Bogotá", tipo_carga="Contenedor seco", unidades=1,
               prioridad="Tiempo", fecha="2026-10-27")


def test_ranking_basico_es_json_y_reproducible(d):
    a = calcular(d, URGENTE).a_dict()
    b = calcular(d, URGENTE).a_dict()
    json.dumps(a)
    assert a == b
    assert len(a["top3"]) == 3
    assert a["top3"][0]["puntaje"] > 0 and 0 <= a["top3"][0]["p_exito"] <= 1
    assert a["por_que_no_el_2"]["texto"]
    assert abs(sum(a["pesos"].values()) - 1) < 1e-6


def test_restriccion_quita_el_peso_y_lo_reparte(d):
    sol = armar_solicitud(d, dict(URGENTE, prioridad="Costo"))
    w, sin_peso = pesos_finales(sol, armar_requisitos(d, sol, [dict(factor="tiempo", tipo="restriccion", valor=40)]))
    assert sin_peso == ["tiempo"] and w["tiempo"] == 0
    assert w["precio"] == pytest.approx(0.40 / 0.90)


def test_restriccion_de_plazo_descarta_por_probabilidad(d):
    r = calcular(d, URGENTE, [dict(factor="tiempo", tipo="restriccion", valor=28)]).a_dict()
    motivos = [x["motivo"] for x in r["descartados"] if x["etapa"] == "restriccion"]
    assert motivos and all("probabilidad" in m for m in motivos)
    for x in r["ranking"]:
        assert x["p_a_tiempo"] >= 0.70


def test_cupo_insuficiente_propone_carga_dividida(d):
    # FríoExpress solo tiene 1 reefer libre del 24 al 27/10
    r = calcular(d, dict(origen="Buenaventura", destino="Bogotá", tipo_carga="Contenedor refrigerado", unidades=2,
                         fecha="2026-10-26")).a_dict()
    div = r["carga_dividida"]
    assert div and sum(x["unidades"] for x in div["reparto"]) == 2
    assert div["p_exito_conjunta"] <= min(x["p_exito"] for x in div["reparto"])


def test_sin_opcion_da_alternativas(d):
    # Carga Pesada Nacional sin cama baja del 24 al 28/10
    r = calcular(d, dict(origen="Cartagena", destino="Bogotá", tipo_carga="Carga extradimensionada", unidades=2,
                         prioridad="Carga crítica", fecha="2026-10-25")).a_dict()
    assert r["sin_opcion"] and r["alternativas"]
    assert all(a["descripcion"] for a in r["alternativas"])


def test_proveedor_nuevo_tiene_confianza_baja(d):
    r = calcular(d, URGENTE).a_dict()
    nova = next(x for x in r["ranking"] if x["proveedor"] == "NovaTrans 4.0")
    assert nova["confianza"] == "baja"


def test_proveedor_que_empeoro_aparece_en_caida(d):
    p = api.perfil_proveedor("Antioquia Freight", engine=get_engine(f"sqlite:///{BD}"))
    assert p["otd_ultimos_90d"] < p["otd_historico"] - 0.05
    assert any("límite de control" in r for r in p["riesgos"])


def test_las_30_solicitudes_de_prueba_responden(d):
    for sid in d.solicitudes[d.solicitudes.fase == "prueba"].index:
        r = calcular(d, int(sid), n=500).a_dict()
        assert r["top3"] or r["alternativas"], sid


def test_decision_y_cierre_actualizan_el_bandido(tmp_path):
    if not BD.exists():
        pytest.skip("falta data/cosco.db")
    copia = tmp_path / "copia.db"
    shutil.copy(BD, copia)
    e = get_engine(f"sqlite:///{copia}")
    crear_faltantes(e)
    sid = api.crear_solicitud(URGENTE, engine=e)
    dec = api.registrar_decision(sid, "MultiModal Colombia", "RutaSegura Logística", 0.9, motivo="pedido del cliente",
                                 usuario="prueba", requisitos=[dict(factor="tiempo", tipo="restriccion", valor=34)],
                                 engine=e)
    assert dec["cambio_manual"]
    with pytest.raises(ValueError):
        api.registrar_decision(sid, "MultiModal Colombia", "RutaSegura Logística", engine=e)
    cierre = api.cerrar_servicio(dec["decision_id"], True, 30.0, 6.5e6, engine=e)
    assert 0 < cierre["confiabilidad_nueva"] < 1
