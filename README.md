# Delivery Promise Optimization Challenge

Solución técnica para estimar la **promesa de entrega** en el checkout de Proximity (Mercado Libre) y decidir **cuándo activar al comercio**.

La promesa se expresa como un intervalo del mismo día (ej. 21:15–21:45). Debe equilibrar competitividad (intervalos atractivos) y realismo (bajo *Delay*).

## Cómo formalicé el problema

Estimamos el tiempo total `checkout → entrega` como una distribución condicional, no un punto único. En checkout devolvemos:

1. Un **intervalo de promesa** `[q20, q80]` redondeado a bloques de 15 minutos.
2. Un timestamp de **activación del comercio** para alinear prep con la llegada estimada del repartidor al PoS.

El fin exacto del empaquetado **no es observable**. Por eso el histórico de preparación usa un proxy: `pickup_ts - store_notify_ts`.

## Estructura

```text
Mercado_Libre_Challenge/
├── README.md
├── requirements.txt
├── sql/build_dataset.sql          # Contrato SQL de dataset/features
├── scripts/run_pipeline.py        # Reproduce datos + entrenamiento
├── notebooks/01_evaluation.ipynb
├── src/
│   ├── data/                      # Generación sintética
│   ├── features/                  # Features online/offline (anti-leakage)
│   ├── models/                    # Cuantiles LightGBM + evaluación
│   ├── activation/                # Estrategia de notify al comercio
│   └── api/                       # FastAPI /delivery-promise
├── data/sample/                   # Sample versionado
├── data/synthetic/                # Full dump local (gitignore)
└── artifacts/                     # Modelos locales (gitignore)
```

## Setup

Python 3.12+:

```powershell
cd Mercado_Libre_Challenge
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/run_pipeline.py
```

El pipeline genera ~12k órdenes sintéticas, entrena los modelos y escribe métricas en `artifacts/metrics.json`.

## Datos sintéticos y SQL

No hay dataset de ejemplo del challenge: generamos eventos operativos coherentes:

`checkout → store_notify → courier_notify → courier_arrive_pos → pickup → deliver`

más un `prep_ready_ts` **latente** (solo para simular la física; nunca es feature).

La consulta documental está en [`sql/build_dataset.sql`](sql/build_dataset.sql). El equivalente ejecutable es [`src/features/build_features.py`](src/features/build_features.py).

### Decisiones de construcción de datos

| Decisión | Motivo |
|----------|--------|
| Target = minutos totales a entrega | Es lo que el cliente experimenta / lo que define Delay |
| Proxy de prep = pickup − store_notify | El ready exacto no se observa |
| Agregados expanding / solo órdenes previas | Evita leakage temporal |
| Features de hora, categoría, distancia, hist store/zona | Disponibles (o precomputables) en checkout |
| Split temporal train/test | Evalúa generalización a futuro, no shuffle aleatorio |

### Variables predictoras principales

| Feature | Por qué |
|---------|---------|
| `hour`, `dow` | Estacionalidad de demanda/tráfico |
| `category_*` | Prep distinto (food > grocery > pharmacy) |
| `distance_km` | Impacta courier-to-store y delivery leg |
| `store_prep_p50_hist` / `p90_hist` | Capacidad crónica del comercio |
| `zone_courier_p50_hist` | Velocidad típica de retiro en la zona |
| `zone_load_hist` | Proxy de congestión reciente |

## Estimación de la promesa

Se entrenan **3 LightGBM quantile regressors** (`α = 0.2 / 0.5 / 0.8`) sobre `total_delivery_minutes`.

- El intervalo de promesa usa `p20`–`p80`.
- Se convierte a timestamps absolutos, se redondea a **15 minutos** y se clampea al mismo día.
- `confidence` es una transformación monótona del ancho relativo del intervalo (más angosto ⇒ más confianza).

## Activación del comercio

```text
activation_offset = max(0, courier_to_store_p50 - prep_p50 - buffer)
store_activation_ts = checkout_ts + activation_offset
```

Objetivo: que el pedido esté listo cerca de la llegada del courier, evitando comida esperando en mostrador y couriers esperando prep.

## Evaluación

Tras `python scripts/run_pipeline.py`, ver `artifacts/metrics.json` y el notebook [`notebooks/01_evaluation.ipynb`](notebooks/01_evaluation.ipynb).

Métricas principales (holdout temporal, seed=42):

| Métrica | Valor aprox. |
|---------|--------------|
| coverage | ~0.58 |
| delay_rate | ~0.20 |
| mean_width_minutes | ~10 |
| mae_p50 | ~5 min |

Tradeoff explícito: subir el cuantil alto mejora coverage y baja delay, pero ensancha la ventana y puede perjudicar conversión. El notebook explora esa curva.

## API

```powershell
uvicorn src.api.main:app --reload --port 8000
```

Docs interactivas: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### `GET /health`

### `POST /delivery-promise`

Request:

```json
{
  "order_id": "ord_demo_001",
  "checkout_ts": "2026-08-03T20:45:00-03:00",
  "store_id": "store_010",
  "category": "food",
  "origin": { "lat": -34.6037, "lon": -58.3816 },
  "destination": { "lat": -34.6150, "lon": -58.4200 }
}
```

Response:

```json
{
  "order_id": "ord_demo_001",
  "promise_window": {
    "start": "2026-08-03T21:15:00-03:00",
    "end": "2026-08-03T21:45:00-03:00"
  },
  "store_activation_ts": "2026-08-03T20:48:00-03:00",
  "confidence": 0.81
}
```

Ejemplo `curl`:

```powershell
curl -X POST http://127.0.0.1:8000/delivery-promise `
  -H "Content-Type: application/json" `
  -d "{\"order_id\":\"ord_demo_001\",\"checkout_ts\":\"2026-08-03T20:45:00-03:00\",\"store_id\":\"store_010\",\"category\":\"food\",\"origin\":{\"lat\":-34.6037,\"lon\":-58.3816},\"destination\":{\"lat\":-34.615,\"lon\":-58.42}}"
```

## Supuestos, riesgos y limitaciones

- Los datos son sintéticos: capturan mecanismos, no la distribución real de Proximity.
- El proxy de prep mezcla preparación verdadera con espera del courier.
- Los agregados online del demo usan estadísticas globales del dataset; en producción serían tablas batch point-in-time / near-real-time.
- No modelamos cancelaciones, reasignación de couriers ni clima.
- La promesa es single-shot: no hay recalibración post-checkout.

## Evolución en producción

1. Features online con stores de agregados frescos (minutos/horas).
2. Calibración de cuantiles por ciudad/categoría y monitoreo de delay.
3. Optimización multi-objetivo (conversión vs delay) con A/B.
4. Modelos de componentes (prep / courier / delivery) + suma con incertidumbre.
5. Feedback loop con outcomes reales y detección de drift.

## Declaración de uso de IA

| Herramienta | Uso | Validado / modificado / descartado |
|-------------|-----|------------------------------------|
| Cursor (asistente de código) | Scaffold del repo, generador sintético, SQL documental, pipeline LightGBM, FastAPI y README | Se validó el contrato del endpoint, el anti-leakage temporal y la métrica de cobertura/delay. Se descartó deep learning (innecesario para este problema). La estrategia de activación y los cuantiles 20/80 se eligieron y revisaron manualmente por interpretabilidad en la defensa. |

Durante la defensa se pueden explicar y defender todas las decisiones de diseño anteriores.
