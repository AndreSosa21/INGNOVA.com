"""Conexión a la base de datos. Usa DATABASE_URL (Supabase/Postgres) o SQLite local por defecto."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

RAIZ = Path(__file__).resolve().parents[2]

try:  # lee DATABASE_URL desde un archivo .env si existe
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
except ImportError:
    pass
SQLITE_LOCAL = f"sqlite:///{RAIZ / 'data' / 'cosco.db'}"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", SQLITE_LOCAL)
    # Supabase entrega "postgresql://..."; SQLAlchemy necesita el driver psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_ENGINES: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    """Un engine (y su pool de conexiones) por URL y por proceso.

    Crear uno nuevo en cada llamada abría conexiones nuevas al pooler de Supabase cada vez que el dashboard
    sondeaba la bandeja, hasta llenar su límite de clientes.
    """
    url = url or database_url()
    if url not in _ENGINES:
        _ENGINES[url] = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _ENGINES[url]
