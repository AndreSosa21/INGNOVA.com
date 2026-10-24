# Contexto completo del proyecto (para los Claude del equipo)

> Pásale este archivo a tu Claude al empezar. Resume el reto, lo que ya está hecho, lo que falta, las
> decisiones tomadas y las reglas del equipo. Actualizado: sábado 24/10/2026 madrugada.

---

## 1. El reto (Sabana Hack 2026 · COSCO SHIPPING)

COSCO SHIPPING contrata el transporte terrestre en Colombia (puerto ↔ bodega del cliente) con más de 10
proveedores locales. Hoy el equipo de operaciones compara proveedores a mano para cada solicitud: es lento,
inconsistente y difícil de explicar.

**Pregunta del reto:** ¿cómo ayudar a operaciones a identificar, para cada solicitud, el proveedor más adecuado,
de forma **rápida, consistente, explicable y basada en datos**? El sistema **ayuda a decidir; la persona
decide.**

**7 factores del problema:** precio, tiempo de tránsito, disponibilidad del tipo de vehículo, capacidad
disponible, desempeño histórico, confiabilidad / entregas a tiempo, y fortalezas y debilidades específicas.

**Entregables que pide COSCO:**
1. Prototipo funcional: a partir de una solicitud recomienda un proveedor o una lista corta ordenada.
2. Base de datos de proveedores y modelo de datos.
3. Metodología de puntuación y recomendación.
4. Ranking de proveedores y análisis de fortalezas, debilidades y riesgos.
5. **Tableros visuales:** precios, tiempos de tránsito, capacidad, disponibilidad de vehículos y tendencias de
   desempeño.
6. Demostración con datos históricos y de prueba.
7. Valor de negocio, escalabilidad y plan de implementación (breve).

**Lo que busca el jurado en la demo:** solicitudes con requisitos distintos y su recomendación; coherencia con
los requisitos; entender por qué uno y no otro; análisis de fortalezas y riesgos apoyado en datos;
visualizaciones para comparar proveedores y seguirlos en el tiempo; evidencia de validación.

**Rúbrica (100 pts):**

| Criterio | Pts |
|---|---|
| Comprensión del problema | 15 |
| Calidad de la recomendación (incluye casos sin opción ideal) | 20 |
| Metodología y transparencia | 20 |
| Funcionamiento y demostración | 20 |
| Análisis y visualización | 10 |
| Valor de negocio y viabilidad | 10 |
| Comunicación | 5 |

El texto completo del reto está en la carpeta del proyecto: `CONTEXTO COSCO.txt`.

---

## 2. Alcance que definimos (el MVP)

Cinco piezas:

1. **BD de proveedores simulada** (toda Colombia, al menos un proveedor por caso). ✅ Hecha.
2. **Motor de IA:** Monte Carlo + bandido (multi-armed bandit) + puntaje multicriterio. ✅ Hecho.
3. **Ranking de escenarios** con "el proveedor A tiene x % de éxito" y razones, según la prioridad (tiempo,
   costo, carga) y el caso (carga dividida, disponibilidad). ✅ Hecho (sale del motor).
4. **Dashboard. OBLIGATORIO.** ⏳ Medi y Andrea.
5. **Asistente LLM. OBLIGATORIO.** ⏳ Medi y Andrea.
   - Lo único opcional es que **el usuario final** decida si usa el asistente o no: un interruptor en la app.
   - Debe ser **multilingüe**: el equipo habla español y COSCO se comunica en inglés.
   - Debe tener **memoria persistente de casos**: "en un caso parecido pasó X y causó Y".

---

## 3. Equipo y responsabilidades

| Persona | Responsable de |
|---|---|
| **Pablo** + **Juan Felipe** | BD, simulación/entrenamiento y motor de decisión. Pablo revisa el código del motor |
| **Medi** + **Andrea** | Dashboard (Streamlit), asistente LLM y la BD de memoria del LLM |
| **Lau** | Pitch y caso de negocio |

---

## 4. Stack y decisiones técnicas

- **Python 3.11+**, SQLAlchemy 2, pandas y numpy.
- **Dashboard:** Streamlit.
- **LLM:** Gemini API (Google AI Studio, llave gratis), detrás de una capa que se pueda cambiar.
- **BD compartida:** Supabase (Postgres 17), proyecto `cosco-mvp`. Respaldo local: SQLite en
  `cosco_mvp/data/cosco.db`.
  - **RLS activado en todas las tablas y SIN políticas.** Python entra con el usuario `postgres` por el
    Session pooler y no le afecta. **Si el dashboard usa la llave pública (anon) de Supabase, no va a ver
    nada** hasta que alguien cree políticas. Recomendación: que el dashboard llame a las funciones de Python
    (`cosco.motor.api`) y no vaya directo a Supabase.
- **RAG:** no hace falta para el motor. Hay un script opcional sin probar, `cosco/memoria_vectores.py`
  (pgvector + embeddings de Gemini sobre `casos_memoria`), por si Medi y Andrea lo quieren para el asistente.
- **Reglas y pesos** en `cosco/politicas.toml`, no en el código.

---

## 5. Base de datos (23 tablas)

Detalle completo en `docs/modelo_datos.md`. Resumen:

| Grupo | Tablas |
|---|---|
| Catálogos | `regiones` (7), `ciudades` (28), `tipos_vehiculo` (9), `tipos_carga` (7), `compatibilidad_carga`, `clientes` (45), `certificaciones` (5) |
| Proveedores (15) | `proveedores`, `cobertura`, `proveedor_certificaciones`, `vehiculos` (~830), `conductores` (~945, 5 métricas COSCO), `tarifas`, `disponibilidad` (cupo diario del 24/10 al 22/11) |
| Historia (24 meses) | `solicitudes` (10.000 históricas + **30 de prueba** con `fase='prueba'`), `servicios` (10.953 viajes), `imprevistos` (1.360), `evaluaciones_mensuales` |
| Memoria del asistente | `decisiones` (qué se recomendó, qué se eligió y por qué, y el resultado), `casos_memoria` (29 lecciones iniciales), `conversaciones_agente` (texto del usuario y campos que extrajo el LLM, en JSON) |
| Motor | `requisitos_solicitud` (restricciones y preferencias confirmadas), `estado_bandit` (caché de α y β) |

**"Verdad oculta":** cada proveedor tiene un comportamiento real que el motor no ve (está en
`data/verdad_oculta.json`, **solo para validar**; el motor y el LLM no lo deben leer). Casos armados:

- **Antioquia Freight** empeora desde junio de 2026.
- **Santander Trucking** mejora.
- **NovaTrans 4.0** es nuevo: 9 servicios, todos a tiempo.
- **Costa Norte** es fuerte en la Costa y débil hacia Antioquia.
- **Económicos del Valle** falla en refrigerados.
- El tiempo de reacción declarado es más optimista que el real.

Casos de cupo para la demo:

- **FríoExpress:** 1 reefer libre del 24 al 27/10.
- **Carga Pesada Nacional:** sin cama baja del 24 al 28/10.
- **RutaSegura:** 2 tractomulas 40' libres el 25 y el 26/10.

⚠️ **Nunca volver a correr el seeder contra Supabase:** borra todo, incluidas las decisiones y la memoria.
El seeder se detiene solo si la BD tiene datos. Para crear tablas nuevas sin tocar datos:
`python -m cosco.db.migrar`. Todo cambio en Supabase debe ser **aditivo**.

---

## 6. El motor (cómo funciona)

Versión sencilla: `docs/como_funciona.md`. Versión técnica: `docs/motor.md`.

El embudo:

1. **Filtros:** región, vehículo, certificación y cupo.
2. **Monte Carlo:** 5.000 escenarios por proveedor, que dan % de éxito, costo esperado y P90, y tiempo P50 y P90.
3. **Restricciones:** fecha límite (≥ 70 % de probabilidad) y precio máximo (P90).
4. **Pareto.**
5. **Bandido:** Beta por proveedor × segmento, con vida media de 4 meses.
6. **Puntaje por perfil:** Urgente, Costo, Crítico o Equilibrado.
7. **Semáforo.**
8. **Top 3 explicado**, más carga dividida y cascada de alternativas si nadie cumple.

**Restricción vs. preferencia:** una restricción descarta a quien no la cumple y su peso se reparte entre los
demás factores. Una preferencia solo cambia los pesos.

---

## 7. API del motor: lo que deben llamar el dashboard y el asistente

Todo está en `cosco/motor/api.py` y todas las funciones devuelven JSON (dict y list).

```python
from cosco.motor import api

sol = {"origen": "Buenaventura", "destino": "Bogotá", "tipo_carga": "Contenedor refrigerado",
       "unidades": 2, "plazo_horas": 40, "presupuesto_cop": 18e6,
       "prioridad": "Tiempo",            # Tiempo | Costo | Carga crítica | Equilibrado
       "fecha": "2026-10-26"}
req = [{"factor": "tiempo", "tipo": "restriccion"}]   # opcional; ver tabla abajo

api.consultar_ranking(sol, req)            # o api.consultar_ranking(10001) con el id de una solicitud de prueba
api.explicar_diferencia("RutaSegura", "MultiModal", sol, req)
api.simular_cambio(sol, req, {"plazo_horas": 48})   # también: presupuesto_cop, fecha, unidades,
                                                    # tipo_vehiculo, perfil, pesos {factor: w}, excluir [nombres]
api.perfil_proveedor("Antioquia Freight")           # fortalezas, debilidades, carta de control OTD, riesgos
sid = api.crear_solicitud(sol)
dec = api.registrar_decision(sid, "FríoExpress Colombia", proveedor_recomendado="NovaTrans 4.0",
                             exito_predicho=0.81, motivo="...", usuario="Pablo", requisitos=req)
api.cerrar_servicio(dec["decision_id"], a_tiempo=True, tiempo_real_h=37, costo_final_cop=16.2e6)
```

**Requisitos** (el mismo formato que la tabla `requisitos_solicitud`):

| factor | Como restricción, `valor` = | Qué hace |
|---|---|---|
| `tiempo` | horas (vacío = el plazo de la solicitud) | solo quedan los que tienen P(a tiempo) ≥ 70 % |
| `precio` | COP máximo (vacío = el presupuesto) | solo quedan los que tienen costo P90 ≤ máximo |
| `confiabilidad` | 0,9 o 90 | mínimo de confiabilidad reciente |
| `incidentes` | días (vacío = 90) | nadie con imprevistos en esa ventana |
| `proveedor` | `"excluir:Nombre"` / `"solo:Nombre"` | lo saca, o deja solo a ese proveedor |

Una preferencia se escribe `{"factor": "precio", "tipo": "preferencia", "valor": "alta"}`. Los valores
posibles son `alta`, `muy alta`, `baja`, `ninguna`, o un peso numérico.

**Campos principales de `consultar_ranking`:**

- `solicitud`: con nombres, distancia y tiempo estándar.
- `pesos` y `restricciones`.
- `top3` y `ranking`. Cada proveedor trae:
  - `proveedor`, `puntaje`, `p_exito`, `p_a_tiempo`, `confianza` (alta, media o baja) e
    `intervalo_confiabilidad`;
  - `costo_esperado_cop`, `costo_p90_cop`, `tiempo_p50_h` y `tiempo_p90_h`;
  - `aportes` (puntos por factor), `semaforo` (verde, amarillo o rojo), `senales` y `razones`;
  - `dominado_por` y `explorado`.
- `por_que_no_el_2`: trae `texto`, `por_factor` y `contrafactual`.
- `descartados`: lista de `{proveedor, etapa (filtro | capacidad | restriccion | pareto), motivo}`.
- `carga_dividida`: `{reparto, p_exito_conjunta, costo_esperado_cop, tiempo_p90_h}` o `null`.
- `alternativas`: cuando nadie cumple, lista de `{cambio, descripcion, proveedores, mejor, p_exito_mejor}`.
- `sin_opcion` y `hhi_90d` (concentración).

**Reglas para el asistente LLM:**

- El LLM **no inventa números**: todo número sale de estas funciones.
- **No hay función para asignar.** La decisión la toma la persona con `registrar_decision`. Si elige otro
  distinto del recomendado, el `motivo` es obligatorio.
- Flujo sugerido:
  1. El usuario escribe en texto libre.
  2. El LLM extrae los campos (función `leer_solicitud`, del lado del LLM) y los guarda en
     `conversaciones_agente`.
  3. Pregunta lo que falte y separa restricciones de preferencias.
  4. La persona confirma.
  5. Se llama `consultar_ranking`.
  6. El LLM explica en el idioma del usuario.
- Memoria: leer y escribir `casos_memoria` (lecciones) y `decisiones`.

**Para el dashboard** (los tableros que pide COSCO), además de la API se pueden leer las tablas con pandas:

- **Precios:** `tarifas`.
- **Tiempos de tránsito y tendencias:** `servicios` (`tiempo_real_h`, `a_tiempo` y `fecha_cargue`) y
  `evaluaciones_mensuales`.
- **Capacidad y vehículos:** `disponibilidad` y `vehiculos`.
- **Carta de control OTD:** `perfil_proveedor(...)["carta_control_otd"]`.

Para leer los datos ya cargados en memoria: `from cosco.motor.datos import datos; d = datos()`, que expone
`d.viajes`, `d.proveedores` y las demás tablas.

---

## 8. Evidencia (para el pitch y para los tableros)

| Prueba | Resultado |
|---|---|
| **Backtest:** 1.321 envíos de los últimos 3 meses; el motor solo ve el pasado | Éxito: equipo 65,9 %, más barato 69,8 %, puntaje sin aprendizaje 69,5 %, **sistema 71,7 %**, techo 78,6 %. **+5,7 pts y 12 % menos daños con el mismo costo (+0,5 %)**. Captura el 45 % de la mejora posible |
| **Calibración:** julio, mes aparte; 48 variantes de pesos | Todas entre 73,6 % y 75,5 %: el resultado es robusto y se mantienen los pesos de los perfiles |
| **Simulación del bandido:** 448 envíos seguidos | Regret: **bandido 25,7** vs. mejor promedio 37,7 vs. azar 38,1 (**32 % menos**). Envíos a Antioquia Freight, que empeoró: 17 % vs. 48 % |

Los archivos con estos resultados se regeneran con:

- `python -m cosco.validacion.backtest` → `data/backtest_resumen.json`
- `python -m cosco.validacion.calibrar`
- `python -m cosco.validacion.bandido_sim` → `data/bandido_sim.csv`, con el regret paso a paso para
  graficarlo

---

## 9. Repo y reglas de ramas

- Repo: https://github.com/AndreSosa21/INGNOVA.com. Todo el código está en la carpeta **`cosco_mvp/`**.
- Ramas:

  | Rama | De quién es |
  |---|---|
  | `BD-D` | Pablo: BD y motor |
  | `Dash-LLM` | Medi y Andrea |
  | `pitch` | Lau |
  | `integration` | para juntar todo |
  | `main` | la versión final |

- El **PR #1 (BD-D → Dash-LLM) ya está fusionado**: Dash-LLM ya tiene la BD, el motor y los docs.
- Cada quien trabaja **solo en su rama** y pasa cambios por pull request. No empujar a ramas ajenas.
- El código del motor (`cosco/motor`, `cosco/db`) es de Pablo y Juan Felipe. Si el dashboard o el LLM
  necesitan un cambio ahí, se pide; no se edita desde Dash-LLM.
- **Nunca subir `.env`**, contraseñas ni llaves (ya está en `.gitignore`). Nunca pegarlas en el chat.

---

## 10. Cómo correrlo

```bash
cd cosco_mvp
pip install -r requirements.txt

# Opción A, local (SQLite). No necesita .env:
python -m cosco.db.seed            # crea data/cosco.db en ~12 s. Mismos datos que Supabase (semilla 2026)

# Opción B, Supabase (la BD compartida):
cp .env.example .env               # pegar la URI del "Session pooler" con la contraseña (pedírsela a Pablo en persona)
python -m cosco.db.migrar          # crea solo las tablas que falten; no toca datos

python -m pytest -q                # 14 pruebas
python -c "from cosco.motor import api; print(api.consultar_ranking(10001)['top3'][0])"
```

Rendimiento: la primera carga tarda ~0,5 s, cada ranking 0,1-0,5 s, y hasta ~2 s si entra la cascada.

---

## 11. Fechas

- **Entrega: sábado 24 de octubre de 2026 por la tarde.**
- Plan: **congelar el código ~13:00**, integrar en `integration` y después preparar el pitch.

## 12. Pendiente

- **Medi y Andrea:**
  - Dashboard: las 4 pantallas de la propuesta de Juan Felipe (solicitud → ranking; perfil de proveedor;
    tableros de precios, tiempos, capacidad y tendencias; registro de decisiones).
  - Asistente LLM: interruptor de activación, multilingüe, con memoria.
- **Lau:** pitch con las cifras del punto 8, el valor de negocio y el plan de implementación.
- **Plus, si alcanza el tiempo:**
  - modo lote con PuLP para repartir las 30 solicitudes de prueba sin pasar capacidades ni el 30 % de
    concentración;
  - curva costo vs. cumplimiento.
