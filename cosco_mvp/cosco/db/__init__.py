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


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)
