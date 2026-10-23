# COSCO SHIPPING · Selección de proveedores de transporte terrestre (Sabana Hack 2026)

MVP para recomendar, en cada solicitud de transporte terrestre en Colombia, el proveedor más adecuado
(o una lista corta ordenada) de forma rápida, consistente, explicable y basada en datos.

**Estado actual:** la base de datos simulada (23 tablas, cargada en Supabase) y el núcleo del motor de
recomendación (filtros, Monte Carlo, bandido, Pareto, puntaje por perfil, semáforo, carga dividida y cascada de
alternativas). El dashboard y el asistente LLM usan las funciones de `cosco.motor.api`: ver [docs/motor.md](docs/motor.md).

## Arranque rápido

```bash
pip install -r requirements.txt
python -m cosco.db.seed          # crea data/cosco.db (SQLite) + data/csv/*.csv en ~12 s
python -m pytest -q              # 14 pruebas: datos (cobertura, llaves, rangos) y motor (casos demo)
python -c "from cosco.motor import api; print(api.consultar_ranking(10001)['top3'][0])"
```

**No volver a correr el seeder contra Supabase:** borra todo. Se detiene solo si la BD ya tiene datos.
Para crear tablas nuevas sin tocar datos: `python -m cosco.db.migrar`.

### Cargar en Supabase (BD compartida del equipo)

1. Crear el proyecto en [supabase.com](https://supabase.com) (se puede entrar con GitHub).
2. En **Project Settings → Database → Connection string**, copiar la URI de **Session pooler** (funciona en
   redes IPv4; la conexión directa de Supabase es solo IPv6).
3. Copiar `.env.example` como `.env` y pegar la URI con la contraseña. `.env` está en `.gitignore`:
   **nunca se sube al repo ni se pega en el chat.**
4. (Ya hecho el 23/10.) `python -m cosco.db.seed` lee `DATABASE_URL` del `.env` y crea y llena las tablas en Supabase.

Sin `.env`, todo sigue funcionando con SQLite local, que sirve de respaldo para la demo si no hay internet.

### Parámetros del seeder

| Parámetro | Por defecto | Para qué |
|---|---|---|
| `--servicios` | 10000 | solicitudes históricas (genera ~10.900 servicios porque algunas se dividen) |
| `--meses` | 24 | meses de historial hasta el 24/10/2026 |
| `--semilla` | 2026 | misma semilla = mismos datos para todo el equipo |
| `--sin-csv` | — | no exportar `data/csv/` |

Más detalle en [docs/modelo_datos.md](docs/modelo_datos.md).

## Memoria del asistente con búsqueda semántica (pgvector)

Solo para Supabase. Agrega la columna `embedding` a `casos_memoria` y la llena, **sin tocar los demás datos**:

```bash
pip install -r requirements.txt          # agrega google-genai
# en .env: GEMINI_API_KEY=...  (gratis en https://aistudio.google.com/apikey)
python -m cosco.memoria_vectores         # habilita pgvector, crea la columna e índice y vectoriza los casos
python -m cosco.memoria_vectores buscar "landslide delays to Bogotá" --destino Bogotá
```

Desde el código del asistente: `from cosco.memoria_vectores import buscar_casos, vectorizar_pendientes`.
Es un RAG híbrido: similitud semántica (multilingüe) + bono si coincide la ruta, la carga o el proveedor.
Los números (OTD, costos, tiempos) **no** se vectorizan: el LLM los pide a la BD o al motor con herramientas.
Después de guardar casos nuevos, llamar `vectorizar_pendientes(engine)` (solo procesa los que no tienen vector).
