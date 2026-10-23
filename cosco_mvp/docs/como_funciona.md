# Cómo funciona (versión sencilla)

Esta parte del proyecto responde una pregunta: **para este envío, ¿qué proveedor de transporte conviene y por qué?**
Tiene dos piezas: una base de datos con la historia de los envíos y un motor que recomienda.

---

## 1. La base de datos

Está en Supabase (Postgres) y tiene 23 tablas. Los datos son simulados, pero realistas:

- **15 proveedores** que cubren toda Colombia (7 regiones, 28 ciudades), con su flota, conductores, tarifas,
  certificaciones y cupo disponible para los próximos 30 días.
- **2 años de historia**: unas 10.000 solicitudes y 10.900 viajes. Por cada viaje se sabe si llegó a tiempo,
  cuánto costó al final, si hubo imprevistos (derrumbes, paros, averías…) y si se dañó la carga.
- **30 solicitudes nuevas** para la fase de prueba.
- Tablas para la **memoria del asistente**: decisiones tomadas, lecciones aprendidas y conversaciones.

**El truco:** cada proveedor tiene un comportamiento real que el motor no puede ver (la "verdad oculta"). Por
ejemplo, Antioquia Freight empezó a fallar desde junio, NovaTrans es nuevo y casi no tiene historia, y
Costa Norte es muy bueno en la Costa pero malo hacia Antioquia. El motor tiene que descubrir eso con los
datos, igual que en la vida real. Y como nosotros sí conocemos la verdad, podemos medir si el motor acierta.

---

## 2. El motor: un embudo de 5 preguntas

Cuando llega una solicitud (por ejemplo: *2 contenedores refrigerados de Buenaventura a Bogotá, para el
lunes, priorizando tiempo*), el motor la pasa por este embudo:

```
 15 proveedores
     │
 ① ¿Puede hacerlo?          → quita a quien no cubre la ruta, no tiene el camión o la certificación,
     │                         o no tiene cupo ese día
 ② ¿Qué tan probable es     → simula 5.000 veces el viaje con cada uno (Monte Carlo)
     │   que cumpla?
 ③ ¿Hay alguien mejor       → saca a quien otro supera en precio, tiempo y cumplimiento a la vez (Pareto)
     │   en todo?
 ④ ¿Cumple de verdad        → mira cómo le ha ido últimamente en esta ruta y tipo de carga (bandido)
     │   últimamente?
 ⑤ ¿Cuál encaja mejor       → da un puntaje según la prioridad: urgente, costo, carga crítica o equilibrado
     │   con lo que se pide?
     ▼
 Top 3 explicado + semáforo de riesgo
```

### ① Filtros: "¿puede hacerlo?"
Reglas de sí o no. Si el proveedor no opera en la región, no tiene el vehículo o la certificación (por
ejemplo, cadena de frío para refrigerados), o no tiene camiones libres ese día, sale. Siempre se dice por qué.

### ② Monte Carlo: "¿qué tan probable es que cumpla?"
En vez de usar un promedio, el motor **simula el viaje 5.000 veces** con cada proveedor. Cada simulación
toma un viaje parecido de su historia (misma región, carga y distancia, y con más peso los recientes) y lo
ajusta a esta ruta, a la temporada de lluvias y al riesgo de la vía. Así salen números como:

> *"RutaSegura llega a tiempo en el 91 % de los casos, cuesta en promedio COP 7,6 M y en el peor caso
> razonable (P90) tarda 32 h."*

Si el proveedor tiene poca historia, se completa con la del mercado. Así no se cree que "3 de 3" es perfecto.

### ③ Pareto: "¿hay alguien mejor en todo?"
Si B es más barato, más rápido y más cumplido que A, no tiene sentido recomendar a A. A baja al final de la
lista con la frase *"B es igual o mejor en costo, tiempo y % de éxito"*.

### ④ Bandido: "¿cumple de verdad últimamente?"
Es la parte que **aprende**. Por cada proveedor y cada segmento (región de destino × tipo de carga) lleva la
cuenta de entregas a tiempo y tarde. Lo reciente pesa más: un viaje de hace 4 meses vale la mitad que uno de
hoy. Por eso detecta rápido a quien empeora. Cada vez que se cierra un servicio, la cuenta se actualiza.

Cuando dos proveedores quedan casi empatados, el bandido a veces le da la oportunidad al que tiene menos
datos, para conocerlo mejor. Nunca lo hace con carga crítica.

### ⑤ Puntaje por perfil: "¿cuál encaja mejor?"
Seis factores (precio, tiempo, confiabilidad, historial de incidentes, holgura de capacidad y desempeño en el
segmento), cada uno de 0 a 1, multiplicados por los pesos del perfil:

| Factor | Urgente | Costo | Crítico | Equilibrado |
|---|---|---|---|---|
| Precio | 15 % | **40 %** | 10 % | 25 % |
| Tiempo | **30 %** | 10 % | 15 % | 20 % |
| Confiabilidad | **30 %** | 20 % | **35 %** | 25 % |
| Historial | 10 % | 10 % | 15 % | 10 % |
| Holgura | 5 % | 5 % | 5 % | 5 % |
| Segmento | 10 % | 15 % | 20 % | 15 % |

**Restricción vs. preferencia:** si el cliente dice *"tiene que llegar antes del jueves"*, el tiempo deja de
ser un factor con peso y pasa a ser una regla: solo quedan los que tienen al menos 70 % de probabilidad de
llegar a tiempo. Su peso se reparte entre los otros factores.

---

## 3. Lo que ve la persona

Para cada uno del top 3:

- **Puntaje** y **% de éxito** (llegar a tiempo, dentro del presupuesto y sin daño), con su nivel de
  confianza (alta, media o baja).
- **Costo esperado** y **tiempos** (normal y peor caso razonable).
- **Semáforo:** 🟢 sin alertas, 🟡 una, 🔴 dos o más o una grave. Las alertas son, por ejemplo: "OTD en
  caída", "pocos datos", "supera el presupuesto", "débil en este segmento" o "capacidad al límite".
- **Razones:** *"llega en 32 h en el 90 % de los casos; cumple 93 % últimamente en este segmento"*.
- **Por qué no el #2:** los puntos por factor y un *"si B bajara su precio 9 %, quedaría primero"*.

Y además:

- **Descartados**, con el motivo de cada uno.
- **Carga dividida:** si nadie tiene cupo para todo, reparte entre 2 o 3 proveedores. Advierte que el envío
  solo cumple si cumplen todos.
- **Alternativas:** si nadie cumple, dice qué relajar. Por ejemplo: *"si el cargue se mueve al 29/10,
  aparecen 2 proveedores"* o *"si se usa plataforma en vez de cama baja…"*. El motor nunca rompe una regla
  por su cuenta.

**La decisión siempre la toma la persona.** Si elige a otro distinto del recomendado, debe dar el motivo.
Eso queda guardado y, cuando se cierra el servicio, el bandido aprende del resultado.

---

## 4. ¿Funciona? Las pruebas

Como conocemos la verdad oculta, podemos comparar contra lo que se hacía antes:

**Backtest** (1.321 envíos de los últimos 3 meses; el motor solo vio lo anterior a cada uno):

| | % éxito | Costo por envío |
|---|---|---|
| Lo que eligió el equipo | 65,9 % | COP 9,04 M |
| Siempre el más barato | 69,8 % | COP 8,61 M |
| **Nuestro sistema** | **71,7 %** | COP 9,08 M |
| Lo mejor posible (techo) | 78,6 % | COP 9,33 M |

→ **+5,7 puntos de éxito y 12 % menos daños, con el mismo costo.**

**Simulación del aprendizaje** (448 envíos seguidos):

| | Arrepentimiento | Envíos a Antioquia Freight (que empeoró) |
|---|---|---|
| **Nuestro bandido** | **25,7** | **17 %** |
| Mejor promedio histórico | 37,7 | 48 % |

→ **32 % menos errores, y deja de mandarle carga al proveedor que empeoró.**

**Robustez:** probamos 48 combinaciones de pesos en un mes aparte y el resultado casi no cambia (entre 73,6 %
y 75,5 %). La recomendación no depende de pesos "afinados a mano".

---

## 5. Cómo lo usan el dashboard y el asistente

Todo sale de 6 funciones (en `cosco/motor/api.py`), que devuelven JSON:

| Función | Para qué |
|---|---|
| `consultar_ranking(solicitud, requisitos)` | el embudo completo |
| `explicar_diferencia(a, b, …)` | por qué A y no B |
| `simular_cambio(…, cambio)` | "¿y si amplío el plazo / subo el presupuesto / muevo un peso?" |
| `perfil_proveedor(nombre)` | fortalezas, debilidades y tendencia de un proveedor |
| `registrar_decision(…)` | guardar lo que se eligió y por qué |
| `cerrar_servicio(…)` | guardar el resultado real (y el bandido aprende) |

El asistente LLM usa estas mismas funciones como herramientas. **Ningún número lo inventa el LLM**, y no hay
función para asignar: eso lo decide la persona.

Más detalle técnico: [motor.md](motor.md) y [modelo_datos.md](modelo_datos.md).
