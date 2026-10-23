# Motor de recomendación

Código en `cosco/motor/`, reglas y pesos en `cosco/politicas.toml`. Implementa el embudo del
"Plan integrado del motor COSCO".

## Uso rápido

```python
from cosco.motor import api

sol = {"origen": "Buenaventura", "destino": "Bogotá", "tipo_carga": "Contenedor refrigerado",
       "unidades": 2, "plazo_horas": 40, "prioridad": "Tiempo", "fecha": "2026-10-26"}
req = [{"factor": "tiempo", "tipo": "restriccion"}]          # el plazo es obligatorio

r = api.consultar_ranking(sol, req)          # también acepta el id de una solicitud: api.consultar_ranking(10001)
r["top3"], r["descartados"], r["carga_dividida"], r["alternativas"], r["por_que_no_el_2"]

api.explicar_diferencia("RutaSegura", "MultiModal", sol, req)
api.simular_cambio(sol, req, {"plazo_horas": 48})            # también: presupuesto_cop, fecha, unidades,
                                                             # tipo_vehiculo, perfil, pesos, excluir
api.perfil_proveedor("Antioquia Freight")
sid = api.crear_solicitud(sol)
dec = api.registrar_decision(sid, "FríoExpress Colombia", "NovaTrans 4.0", 0.81, motivo="...", usuario="Pablo",
                             requisitos=req)
api.cerrar_servicio(dec["decision_id"], a_tiempo=True, tiempo_real_h=37, costo_final_cop=16.2e6)
```

Todas devuelven JSON simple, así que sirven tal cual como herramientas del LLM. **No hay función para asignar:**
decide la persona. Lee la BD de `DATABASE_URL` (Supabase) y guarda los datos en memoria la primera vez
(~0,5 s). Cada ranking tarda 0,1-0,5 s; con cascada, hasta ~2 s.

## Requisitos (lo que va en `requisitos_solicitud`)

| factor | tipo restriccion: `valor` | Qué hace |
|---|---|---|
| `tiempo` | horas (vacío = el plazo de la solicitud) | pasa solo con P(a tiempo) ≥ 70 %; el peso de tiempo se reparte |
| `precio` | COP máximo (vacío = el presupuesto) | pasa solo si el costo P90 ≤ máximo; el peso de precio se reparte |
| `confiabilidad` | 0,9 o 90 | pasa si la media del bandido en el segmento llega |
| `incidentes` | días (vacío = 90) | nadie con imprevistos en esa ventana; el peso de historial se reparte |
| `proveedor` | `"excluir:Nombre"` o `"solo:Nombre"` | lo saca o lo deja solo a él |

Una preferencia es `{"factor": "precio", "tipo": "preferencia", "valor": "alta"}` (alta ×1,5, muy alta ×2,
baja ×0,5, ninguna 0) o un peso numérico. Después se renormalizan los pesos.

## El embudo, capa por capa

| Capa | Archivo | Qué hace |
|---|---|---|
| Filtros duros | `filtros.py` | cobertura del origen y del destino, vehículo compatible y en la flota, certificación vigente, tarifa y cupo ese día (`disponibilidad`). Con cupo menor al pedido queda como "cupo parcial" para la carga dividida |
| Bandido | `bandido.py` | Beta por proveedor × (región destino, carga). Peso 0,5^(edad/4 meses). Prior = mercado del segmento con peso 5 |
| Monte Carlo | `montecarlo.py` | 5.000 escenarios. θ de la Beta decide si el escenario es "a tiempo" o "tarde"; el historial (propio, encogido al mercado con n/(n+10)) decide cuánto. El tiempo se lleva a la ruta pedida con el tiempo estándar y el retraso de imprevistos se ajusta por riesgo vial y lluvias. El costo es la tarifa del proveedor × el sobrecosto real del viaje. Daño, presupuesto y plazo dan el % de éxito |
| Restricciones | `ranking._evaluar` | plazo, precio, confiabilidad, incidentes, exclusiones |
| Puntaje | `ranking.puntuar` | 6 factores normalizados 0-1 entre los candidatos (con tolerancia para que diferencias mínimas no exageren), × pesos del perfil × 100. El % de éxito es el titular, no un factor |
| Semáforo | `ranking.semaforo` | señales: pasarse del plazo, superar el presupuesto, debilidad en el segmento, OTD en caída, variabilidad alta, pocos datos, capacidad al límite, daño, concentración. Verde 0, amarillo 1, rojo 2+ o una crítica |
| Pareto | `ranking.pareto` | sale (al final del ranking, con su motivo) quien otro iguala o supera en costo esperado, tiempo P90 y % de éxito. Un proveedor con alerta crítica no deja fuera a nadie |
| Orden y bandido | `ranking.ordenar` | no dominados por puntaje; los de alerta crítica después. Thompson desempata a menos de 5 % del primero, nunca en carga crítica |
| Explicación | `ranking.razones`, `diferencia`, `contrafactual` | 2 razones por proveedor, "por qué no el #2" por factor y "si B bajara su precio X %…" |
| Carga dividida | `ranking.dividir` | si alguien tiene cupo parcial: reparte en orden de puntaje (máx. 3). El éxito conjunto exige que todos cumplan |
| Cascada | `ranking.cascada` | si nadie pasa: vehículo alterno, mover la fecha, ampliar plazo, subir precio, bajar confiabilidad, aceptar incidentes, cada uno solo, con o sin dividir. Nunca relaja por su cuenta |

## Perfiles

`prioridad` de la solicitud → perfil: Tiempo → Urgente, Costo → Costo, Carga crítica → Crítico,
Equilibrado → Equilibrado. Los pesos están en `politicas.toml` (los de la propuesta de Juan Felipe).

## Tablas que escribe

`solicitudes` (fase `operacion`), `decisiones`, `requisitos_solicitud`, `servicios` (al cerrar) y
`estado_bandit` (caché de α y β; `api.guardar_estado_bandit()` la llena entera). Nunca borra datos.
`python -m cosco.db.migrar` crea solo las tablas que falten.

## Backtest (`python -m cosco.validacion.backtest`, ~5 min)

1.321 solicitudes de los últimos 3 meses; el motor se actualiza cada mes solo con lo anterior. Cada política se
simula 20 veces con la verdad oculta y los mismos números aleatorios. Resultado (23/10):

| Política | % éxito | OTD | Costo/unidad | Daños |
|---|---|---|---|---|
| Histórica (equipo) | 65,9 % | 78,6 % | COP 9,04 M | 1,08 % |
| Más barata | 69,8 % | 76,9 % | COP 8,61 M | 1,12 % |
| MCDM estático* | 69,5 % | 82,2 % | COP 9,00 M | 0,95 % |
| **Sistema** | **71,7 %** | 80,1 % | COP 9,08 M | 0,95 % |
| Oráculo (techo) | 78,6 % | 85,7 % | COP 9,33 M | 0,87 % |

El sistema sube el éxito 5,7 puntos frente a la decisión histórica con el mismo costo (+0,5 %) y captura el
45 % de la mejora posible. *El MCDM estático usa `otd_historico`, que incluye el periodo de prueba: está
favorecido.

## Pendiente

- Simulación de regret del bandido.
- Sensibilidad de pesos ±20 %.
- Modo lote con PuLP y curva ε-restricción (plus).
