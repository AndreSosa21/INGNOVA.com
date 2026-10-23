"""Crea solo las tablas que falten (por ejemplo, las del motor en una BD sembrada antes). No toca ni borra datos.

    python -m cosco.db.migrar
"""
from sqlalchemy import inspect

from cosco.db import get_engine
from cosco.db.models import Base


def crear_faltantes(engine=None) -> list[str]:
    engine = engine or get_engine()
    existentes = set(inspect(engine).get_table_names())
    faltantes = [t for t in Base.metadata.sorted_tables if t.name not in existentes]
    Base.metadata.create_all(engine, tables=faltantes)
    return [t.name for t in faltantes]


if __name__ == "__main__":
    creadas = crear_faltantes()
    print("Tablas creadas: " + (", ".join(creadas) if creadas else "ninguna, ya estaban todas"))
