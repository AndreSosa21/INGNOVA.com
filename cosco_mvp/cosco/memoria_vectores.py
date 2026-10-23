"""Búsqueda semántica (RAG híbrido) sobre la memoria del asistente, con pgvector en Supabase.

Solo toca la tabla `casos_memoria`: agrega la columna `embedding vector(768)` y la llena.
No borra ni vuelve a generar ningún dato.

Requisitos en .env:
    DATABASE_URL=...      (Supabase, Session pooler)
    GEMINI_API_KEY=...    (gratis en https://aistudio.google.com/apikey)

Uso:
    python -m cosco.memoria_vectores                      # habilita pgvector, crea la columna y vectoriza lo pendiente
    python -m cosco.memoria_vectores buscar "derrumbe hacia Bogotá con refrigerado"
    python -m cosco.memoria_vectores buscar "landslide delays" --destino Bogotá --carga "Contenedor refrigerado"

Vuelvan a correr el primer comando cada vez que se agreguen casos nuevos: solo vectoriza los que no tienen embedding.
Si algún día se vuelve a correr el seeder, la tabla se recrea sin la columna y basta con correrlo otra vez.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

from cosco.db import get_engine

MODELO_EMBEDDING = "gemini-embedding-001"
DIMENSIONES = 768
BONO_FILTRO = 0.05  # cuánto sube el puntaje por cada coincidencia exacta (ruta, carga, proveedor)

_CAMPOS_CASO = """
    c.id, c.titulo, c.que_paso, c.consecuencia, c.leccion, c.importancia, c.etiquetas, c.fecha,
    co.nombre AS origen, cd.nombre AS destino, tc.nombre AS tipo_carga, p.nombre AS proveedor
"""
_JOINS_CASO = """
    FROM casos_memoria c
    LEFT JOIN ciudades co ON co.id = c.origen_id
    LEFT JOIN ciudades cd ON cd.id = c.destino_id
    LEFT JOIN tipos_carga tc ON tc.id = c.tipo_carga_id
    LEFT JOIN proveedores p ON p.id = c.proveedor_id
"""


def _cliente_gemini():
    from google import genai

    clave = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not clave:
        raise SystemExit("Falta GEMINI_API_KEY en el .env (se saca gratis en https://aistudio.google.com/apikey).")
    return genai.Client(api_key=clave)


def embeber(textos: list[str], tarea: str, cliente=None) -> list[list[float]]:
    """Vectoriza textos con Gemini. tarea: RETRIEVAL_DOCUMENT (casos) o RETRIEVAL_QUERY (preguntas)."""
    from google.genai import types

    cliente = cliente or _cliente_gemini()
    resp = cliente.models.embed_content(
        model=MODELO_EMBEDDING,
        contents=textos,
        config=types.EmbedContentConfig(task_type=tarea, output_dimensionality=DIMENSIONES),
    )
    vectores = np.array([e.values for e in resp.embeddings], dtype=float)
    # con menos de 3072 dimensiones Gemini no entrega vectores normalizados
    vectores /= np.linalg.norm(vectores, axis=1, keepdims=True)
    return vectores.tolist()


def _literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _exigir_postgres(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        raise SystemExit("La búsqueda vectorial necesita Supabase/Postgres: revisa DATABASE_URL en el .env.")


def migrar(engine: Engine) -> None:
    """Habilita pgvector y agrega la columna e índice. Es idempotente y no modifica datos existentes."""
    _exigir_postgres(engine)
    with engine.begin() as cx:
        cx.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        cx.execute(text(f"ALTER TABLE casos_memoria ADD COLUMN IF NOT EXISTS embedding vector({DIMENSIONES})"))
        cx.execute(text(
            "CREATE INDEX IF NOT EXISTS casos_memoria_embedding_idx "
            "ON casos_memoria USING hnsw (embedding vector_cosine_ops)"))


def texto_caso(fila) -> str:
    partes = [
        fila.titulo,
        f"Ruta: {fila.origen or '?'} → {fila.destino or '?'}. Carga: {fila.tipo_carga or '?'}. "
        f"Proveedor: {fila.proveedor or '?'}.",
        f"Qué pasó: {fila.que_paso}",
        f"Consecuencia: {fila.consecuencia}",
        f"Lección: {fila.leccion}",
        f"Etiquetas: {fila.etiquetas}",
    ]
    return "\n".join(partes)


def vectorizar_pendientes(engine: Engine, lote: int = 50) -> int:
    """Calcula el embedding de los casos que aún no lo tienen. Devuelve cuántos vectorizó."""
    _exigir_postgres(engine)
    with engine.connect() as cx:
        filas = cx.execute(text(f"SELECT {_CAMPOS_CASO} {_JOINS_CASO} WHERE c.embedding IS NULL ORDER BY c.id")).all()
    if not filas:
        return 0
    cliente = _cliente_gemini()
    for i in range(0, len(filas), lote):
        grupo = filas[i:i + lote]
        vectores = embeber([texto_caso(f) for f in grupo], "RETRIEVAL_DOCUMENT", cliente)
        with engine.begin() as cx:
            cx.execute(
                text("UPDATE casos_memoria SET embedding = CAST(:v AS vector) WHERE id = :id"),
                [{"v": _literal(v), "id": f.id} for f, v in zip(grupo, vectores)],
            )
    return len(filas)


def buscar_casos(
    consulta: str,
    k: int = 5,
    origen: str | None = None,
    destino: str | None = None,
    tipo_carga: str | None = None,
    proveedor: str | None = None,
    engine: Engine | None = None,
) -> list[dict]:
    """RAG híbrido: similitud semántica + bono por coincidir en ruta, carga o proveedor.

    La consulta puede venir en cualquier idioma (los embeddings de Gemini son multilingües).
    Devuelve los k casos más relevantes con su `similitud` (0-1) y `puntaje` final.
    """
    engine = engine or get_engine()
    _exigir_postgres(engine)
    q = embeber([consulta], "RETRIEVAL_QUERY")[0]
    sql = text(f"""
        SELECT * FROM (
            SELECT {_CAMPOS_CASO},
                   1 - (c.embedding <=> CAST(:q AS vector)) AS similitud
            {_JOINS_CASO}
            WHERE c.embedding IS NOT NULL
        ) t
        ORDER BY similitud
                 + :bono * (COALESCE((origen = CAST(:origen AS text))::int, 0)
                            + COALESCE((destino = CAST(:destino AS text))::int, 0)
                            + COALESCE((tipo_carga = CAST(:carga AS text))::int, 0)
                            + COALESCE((proveedor = CAST(:proveedor AS text))::int, 0))
                 + 0.01 * importancia DESC
        LIMIT :k
    """)
    params = dict(q=_literal(q), bono=BONO_FILTRO, origen=origen, destino=destino, carga=tipo_carga,
                  proveedor=proveedor, k=k)
    with engine.connect() as cx:
        filas = cx.execute(sql, params).mappings().all()
    resultado = []
    for f in filas:
        d = dict(f)
        coincidencias = sum(d[c] == v for c, v in (("origen", origen), ("destino", destino),
                                                     ("tipo_carga", tipo_carga), ("proveedor", proveedor)) if v)
        d["similitud"] = round(float(d["similitud"]), 3)
        d["puntaje"] = round(d["similitud"] + BONO_FILTRO * coincidencias + 0.01 * d["importancia"], 3)
        resultado.append(d)
    return resultado


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("buscar", help="buscar casos parecidos")
    b.add_argument("consulta")
    b.add_argument("-k", type=int, default=5)
    b.add_argument("--origen")
    b.add_argument("--destino")
    b.add_argument("--carga")
    b.add_argument("--proveedor")
    a = ap.parse_args()

    engine = get_engine()
    if a.cmd == "buscar":
        for c in buscar_casos(a.consulta, a.k, a.origen, a.destino, a.carga, a.proveedor, engine):
            print(f"[{c['puntaje']:.3f} | sim {c['similitud']:.3f}] {c['titulo']}\n    Lección: {c['leccion']}")
        return
    migrar(engine)
    n = vectorizar_pendientes(engine)
    print(f"pgvector listo. Casos vectorizados ahora: {n}")


if __name__ == "__main__":
    main()
