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

## Portal del cliente y dashboard del equipo (dos aplicaciones, misma BD)

```bash
python -m uvicorn cosco.server:app --port 8001          # dashboard del equipo logístico  http://localhost:8001
python -m uvicorn cosco.portal_server:app --port 8002   # portal del cliente             http://localhost:8002
```

Flujo: el cliente pide en el portal (3 pasos) -> la solicitud llega sola a la bandeja del dashboard (sondeo cada 3 s) ->
al abrirla pasa a "En análisis" -> el equipo compara tres opciones (Equilibrada, Más económica, Más confiable) y elige ->
el portal del cliente muestra "Asignada". Las solicitudes viven en `solicitudes` (fase `operacion`) y los datos de contacto en
`solicitudes_portal` (se crea sola, o con `python -m cosco.db.migrar`). `cosco/solicitudes.py` tiene la lógica compartida.

`cosco/server.py` expone `cosco.motor.api` por HTTP y calcula las tres estrategias (mismo motor, perfiles Urgente/Costo/Crítico).
`web/` y `portal/` son front sin paso de build; la UI no calcula nada, solo consume el contrato del motor. Elegir un proveedor
escribe en `decisiones` de la BD configurada. El portal usa una foto con licencia CC BY 3.0 (crédito en su pie).

**Seguimiento y cierre.** En "En curso", una solicitud asignada se marca "En tránsito" cuando sale el vehículo y luego se
registra cómo llegó (tiempo real, costo final, daño, calificación). Eso llama a `cerrar_servicio`: el servicio entra al
historial, la solicitud pasa a "Cerrada" (el cliente lo ve en el portal) y el bandido actualiza la confiabilidad del
proveedor en ese segmento (la pantalla muestra el antes y el después). Un servicio se cierra una sola vez.

**Gerencia** (`http://localhost:8001/#gerencia`, `GET /api/gerencia?meses=6&region=&tipo_vehiculo=`, lógica en
`cosco/gerencia.py`): los tableros que pide COSCO. Resumen del periodo contra el anterior (servicios, puntualidad, costo
real por km, sobrecosto, daños, decisiones), puntualidad mes a mes del mercado y de un proveedor, quién cambió, tiempos de
tránsito por corredor (P50 a P90 contra el estándar), tarifas vigentes y costo real por km, capacidad de los próximos 14
días por proveedor y disponibilidad de la flota hoy por tipo de vehículo.

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
