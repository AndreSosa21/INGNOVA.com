import pandas as pd
import pytest
from sqlalchemy import text

from cosco.db import get_engine
from cosco.db.archetypes import PROVEEDORES
from cosco.db.seed import Generador, cargar, verificar_cobertura


@pytest.fixture(scope="module")
def tablas():
    return Generador(n_servicios=800, meses=24, semilla=11).generar()


def test_cada_caso_tiene_al_menos_un_proveedor():
    cob = verificar_cobertura(PROVEEDORES)
    assert cob.proveedores_factibles.min() >= 1


def test_reproducible():
    a = Generador(300, 24, 5).generar()["servicios"]
    b = Generador(300, 24, 5).generar()["servicios"]
    pd.testing.assert_frame_equal(a, b)


def test_llaves_foraneas_consistentes(tablas):
    sv, sol = tablas["servicios"], tablas["solicitudes"]
    assert sv.solicitud_id.isin(sol.id).all()
    assert sv.vehiculo_id.isin(tablas["vehiculos"].id).all()
    assert tablas["imprevistos"].servicio_id.isin(sv.id).all()
    veh = tablas["vehiculos"].set_index("id")
    assert (veh.loc[sv.vehiculo_id, "proveedor_id"].values == sv.proveedor_id.values).all()


def test_rangos_plausibles(tablas):
    sv = tablas["servicios"]
    assert 0.55 < sv.a_tiempo.mean() < 0.95
    assert (sv.costo_final_cop >= sv.costo_cotizado_cop).all()
    assert (tablas["solicitudes"].fase == "prueba").sum() == 30


def test_carga_en_sqlite(tablas, tmp_path):
    url = f"sqlite:///{tmp_path / 't.db'}"
    cargar(tablas, url, csv=False)
    with get_engine(url).connect() as cx:
        n = cx.execute(text("select count(*) from servicios")).scalar()
    assert n == len(tablas["servicios"])
