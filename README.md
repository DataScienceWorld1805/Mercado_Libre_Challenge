# Delivery Promise Optimization Challenge

Solución técnica para estimar la **promesa de entrega** en el checkout de Proximity (Mercado Libre) y decidir **cuándo activar al comercio**.

La promesa se comunica una sola vez, como intervalo del mismo día (ej. 21:15–21:45), equilibrando:

- **Competitividad**: ventanas atractivas que favorezcan la compra.
- **Realismo**: minimizar entregas fuera de promesa (*Delay*).

---

## Cómo leer esta propuesta

**Orden de lectura recomendado (para comprender la solución de punta a punta):**

1. [Formalización del problema](#formalización-del-problema) — qué se resuelve y qué se devuelve  
2. [Flujo de la solución](#flujo-de-la-solución) — offline vs online  
3. [Datos, SQL y variables predictoras](#datos-sql-y-variables-predictoras) — qué información se usa y por qué  
4. [Estimación de la promesa](#estimación-de-la-promesa) — modelo, intervalo y activación  
5. [Evaluación](#evaluación) — cómo se mide el tradeoff  
6. [Setup y reproducción](#setup-y-reproducción) + [API HTTP](#api-http) — cómo correrlo y probarlo  
7. [Supuestos, riesgos y limitaciones](#supuestos-riesgos-y-limitaciones) + [Evolución en un contexto productivo](#evolución-en-un-contexto-productivo)

| Si querés… | Empezá por… |
|------------|-------------|
| Entender el problema y la formalización | [Formalización del problema](#formalización-del-problema) |
| Ver el flujo offline → online | [Flujo de la solución](#flujo-de-la-solución) |
| Reproducir datos, entrenamiento y métricas | [Setup y reproducción](#setup-y-reproducción) |
| Entender dataset, SQL y features | [Datos, SQL y variables predictoras](#datos-sql-y-variables-predictoras) |
| Ver cómo se estima la promesa | [Estimación de la promesa](#estimación-de-la-promesa) |
| Probar el endpoint | [API HTTP](#api-http) |
| Ver supuestos, riesgos y evolución | [Supuestos, riesgos y limitaciones](#supuestos-riesgos-y-limitaciones) |

**Entregables del challenge cubiertos por este repo**

1. Código fuente clave en `src/`
2. Este README
3. Consulta SQL + decisiones de datos en `sql/build_dataset.sql` (y esta sección)
4. Servicio HTTP con `POST /delivery-promise`
5. Declaración de uso de IA al final

---

## Formalización del problema

No estimamos un ETA puntual. Estimamos la **distribución condicional** del tiempo total:

`Y = minutos desde checkout hasta entrega al cliente`

En checkout el sistema devuelve dos decisiones:

1. **`promise_window`**: intervalo de promesa al cliente, derivado de los cuantiles `p20`–`p80`, convertido a reloj, redondeado a bloques de 15 minutos y limitado al mismo día.
2. **`store_activation_ts`**: cuándo notificar al comercio para iniciar la preparación.

El fin exacto del empaquetado **no es observable** (limitación del enunciado). El histórico de preparación usa el proxy observable:

```text
prep_proxy = pickup_ts - store_notify_ts
```

Ese proxy mezcla prep real con eventual espera del courier; es una limitación explícita del diseño.

---

## Flujo de la solución

### Offline (entrenamiento)

```text
scripts/run_pipeline.py
  → genera ~12k órdenes sintéticas
  → construye features point-in-time (anti-leakage)
  → entrena LightGBM cuantiles p20 / p50 / p80
  → evalúa en holdout temporal
  → persiste artifacts/ (modelos + lookups store/zona)
```

### Online (checkout)

```text
POST /delivery-promise
  → valida request
  → calcula distancia + arma features de checkout
  → predice minutos p20 / p50 / p80
  → traduce minutos → promise_window (reloj, 15 min)
  → calcula store_activation_ts (regla operativa)
  → responde JSON
```

**Importante:** el modelo predice minutos; la API **no** expone `p20/p50/p80` crudos. Expone el intervalo ya traducido a producto (`start` / `end`), como se comunica en checkout.

---

## Estructura del repositorio

```text
Mercado_Libre_Challenge/
├── README.md
├── requirements.txt
├── sql/build_dataset.sql              # SQL documental de dataset/features
├── scripts/run_pipeline.py            # Reproduce datos + train + métricas
├── notebooks/01_evaluation.ipynb      # Tradeoff coverage vs ancho
├── src/
│   ├── data/
│   │   ├── schema.py                  # Contratos de columnas
│   │   └── generate_synthetic.py      # Generador de órdenes/eventos
│   ├── features/
│   │   └── build_features.py          # Features offline/online (anti-leakage)
│   ├── models/
│   │   ├── train.py                   # Entrenamiento + persistencia
│   │   ├── predict.py                 # Serving: minutos → promesa
│   │   └── evaluate.py                # Coverage, delay, ancho, MAE
│   ├── activation/
│   │   └── strategy.py                # Política de activación del comercio
│   └── api/
│       ├── schemas.py                 # Contrato request/response
│       └── main.py                    # FastAPI: /delivery-promise, /health
├── data/sample/orders_sample.csv      # Sample versionado (observable)
├── data/synthetic/                    # Dump completo local (gitignore)
└── artifacts/                         # Modelos y lookups (gitignore; se regeneran)
```

---

## Setup y reproducción

Requiere **Python 3.12+**. Ejecutar siempre desde la raíz del repo.

```powershell
cd Mercado_Libre_Challenge
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/run_pipeline.py
```

El pipeline:

1. Genera ~12 000 órdenes sintéticas (`data/synthetic/orders.csv`)
2. Guarda un sample observable (`data/sample/orders_sample.csv`)
3. Entrena y evalúa los modelos
4. Escribe artefactos en `artifacts/` y métricas en `artifacts/metrics.json`

Sin correr el pipeline, la API arranca en modo degradado (modelos no cargados).

---

## Datos, SQL y variables predictoras

No se provee dataset del challenge: se generan **datos sintéticos** con la cadena operativa:

```text
checkout → store_notify → courier_notify → courier_arrive_pos → pickup → deliver
```

más `prep_ready_ts` **latente** (solo simulación; nunca feature).

- SQL documental: [`sql/build_dataset.sql`](sql/build_dataset.sql)
- Equivalente ejecutable: [`src/features/build_features.py`](src/features/build_features.py)

### Decisiones de construcción de datos

| Decisión | Motivo |
|----------|--------|
| Target = minutos totales a entrega | Outcome que experimenta el cliente y define Delay |
| Proxy de prep = pickup − store_notify | El ready exacto no se observa |
| Agregados expanding / solo órdenes previas | Evita leakage temporal |
| Features de hora, categoría, distancia, hist store/zona | Disponibles o precomputables en checkout |
| Split temporal train/test (80/20) | Evalúa generalización a futuro, no shuffle aleatorio |

### Variables predictoras principales

| Feature | Por qué |
|---------|---------|
| `hour`, `dow` | Estacionalidad de demanda y tráfico |
| `category_food` / `grocery` / `pharmacy` | Prep distinto por tipo de orden |
| `distance_km` | Impacta retiro y última milla |
| `store_prep_p50_hist` / `store_prep_p90_hist` | Capacidad crónica del comercio |
| `zone_courier_p50_hist` | Velocidad típica de llegada al PoS |
| `zone_load_hist` | Proxy de congestión reciente en la zona |

---

## Estimación de la promesa

Se entrenan **3 LightGBM quantile regressors** (`α = 0.2 / 0.5 / 0.8`) sobre `total_delivery_minutes`.

| Cuantil | Rol |
|---------|-----|
| `p20` | Cota inferior del intervalo de promesa |
| `p80` | Cota superior del intervalo de promesa |
| `p50` | Tiempo típico (centro). **No** arma la ventana al cliente; se usa para `confidence` y para medir `mae_p50` en evaluación |

Traducción a producto:

1. El modelo predice minutos (`p20`, `p50`, `p80`).
2. El intervalo de promesa al cliente usa solo `p20`–`p80`.
3. Se convierten a timestamps: `checkout_ts + minutos`.
4. Se redondean a bloques de **15 minutos** y se limitan al mismo día.
5. Eso es lo que ve el checkout en `promise_window.start` / `end`.

`confidence` se calcula con el ancho del intervalo relativo al `p50` (`(p80 - p20) / p50`): más angosto respecto del tiempo típico ⇒ mayor confianza. No es la probabilidad exacta de “llega sí o sí”.

### Activación del comercio

Política operativa (no es el modelo de cuantiles):

```text
activation_offset = max(0, courier_to_store_p50 - prep_p50 - 2)
store_activation_ts = checkout_ts + activation_offset
```

Objetivo: que el pedido esté listo cerca de la llegada del courier, evitando comida esperando en mostrador y couriers esperando preparación.

---

## Evaluación

Tras `python scripts/run_pipeline.py`:

- Métricas: `artifacts/metrics.json`
- Exploración del tradeoff: [`notebooks/01_evaluation.ipynb`](notebooks/01_evaluation.ipynb)

Resultados de referencia (holdout temporal, seed=42, n=2400):

| Métrica | Valor |
|---------|-------|
| coverage | ~0.58 |
| delay_rate | ~0.20 |
| mean_width_minutes | ~9.8 |
| mae_p50 | ~5.0 min |
| mean_delay_when_late | ~4.3 min |

Tradeoff: subir el cuantil alto mejora coverage y baja delay, pero ensancha la ventana y puede perjudicar conversión.

---

## API HTTP

Desde la raíz del repo, con el pipeline ya ejecutado:

```powershell
uvicorn src.api.main:app --reload --port 8000
```

- Swagger: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: `GET /health`
- Promesa: `POST /delivery-promise`

### Request

```json
{
  "order_id": "ord_demo_001",
  "checkout_ts": "2026-08-03T20:45:00-03:00",
  "store_id": "store_010",
  "category": "food",
  "origin": { "lat": -34.6037, "lon": -58.3816 },
  "destination": { "lat": -34.615, "lon": -58.42 }
}
```

`zone_id` es opcional; si no se envía, se infiere desde el `store_id`.

### Response

```json
{
  "order_id": "ord_demo_001",
  "promise_window": {
    "start": "2026-08-03T21:45:00-03:00",
    "end": "2026-08-03T22:00:00-03:00"
  },
  "store_activation_ts": "2026-08-03T20:45:00-03:00",
  "confidence": 0.83
}
```

| Campo | Significado |
|-------|-------------|
| `promise_window.start` / `end` | Intervalo de promesa al cliente (ya traducido a reloj) |
| `store_activation_ts` | Momento sugerido para notificar al comercio |
| `confidence` | Señal de confianza asociada al ancho del intervalo |

Los valores exactos dependen de los artefactos entrenados; el ejemplo de arriba corresponde a una corrida real del endpoint con este request.

### curl (PowerShell)

```powershell
curl -X POST http://127.0.0.1:8000/delivery-promise `
  -H "Content-Type: application/json" `
  -d "{\"order_id\":\"ord_demo_001\",\"checkout_ts\":\"2026-08-03T20:45:00-03:00\",\"store_id\":\"store_010\",\"category\":\"food\",\"origin\":{\"lat\":-34.6037,\"lon\":-58.3816},\"destination\":{\"lat\":-34.615,\"lon\":-58.42}}"
```

---

## Supuestos, riesgos y limitaciones

- Los datos son sintéticos: capturan mecanismos operativos, no la distribución real de Proximity.
- El proxy de prep mezcla preparación verdadera con espera del courier.
- Los lookups online del demo usan estadísticas agregadas del dataset; en producción serían tablas batch / near-real-time point-in-time.
- No se modelan cancelaciones, reasignación de couriers ni clima.
- La promesa es single-shot: no hay recalibración post-checkout.

---

## Evolución en un contexto productivo

1. Feature store con agregados frescos (store / zona / hora).
2. Calibración de cuantiles por ciudad/categoría y monitoreo de delay.
3. Optimización multi-objetivo (conversión vs delay vs ancho) con A/B.
4. Modelos por componente (prep / courier / delivery) + combinación de incertidumbre.
5. Feedback loop con outcomes reales y detección de drift.

---

## Declaración de uso de IA

| Herramienta | Uso | Validado / modificado / descartado |
|-------------|-----|------------------------------------|
| Cursor (asistente de código) | Scaffold del repo, generador sintético, SQL documental, pipeline LightGBM, FastAPI y README | Se validó el contrato del endpoint, el anti-leakage temporal y las métricas de cobertura/delay. Se descartó deep learning (innecesario para este problema tabular de baja latencia). La estrategia de activación y los cuantiles 20/80 se eligieron y revisaron manualmente por interpretabilidad y alineación al tradeoff de negocio. |
| Gemini-PRO | Apoyo en formalización del problema, brainstorming de features y revisión de la narrativa de la propuesta | Se descartaron enfoques sobredimensionados (p. ej. deep learning o arquitectura multi-servicio innecesaria para el challenge). |
| Claude.ai | Apoyo en redacción/claridad del README, revisión de supuestos/limitaciones y preparación de la explicación para la defensa | Se incorporaron mejoras de claridad y orden de lectura. Las decisiones de modelado, cuantiles, activación del comercio y métricas se validaron y ajustaron manualmente contra el enunciado y el código. |

Durante la defensa se pueden explicar y defender todas las decisiones de diseño anteriores.
