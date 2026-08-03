# Delivery Promise Optimization Challenge

Solución técnica para estimar la **promesa de entrega** en el checkout de Proximity (Mercado Libre), expresada como un intervalo de tiempo del mismo día (ej. 21:15–21:45), y una estrategia razonable de **activación del comercio**.

## Problema

La promesa se comunica una sola vez en el checkout. Debe equilibrar:

- **Competitividad**: intervalos atractivos que favorezcan la compra.
- **Realismo**: minimizar entregas fuera de promesa (*Delay*) y mala experiencia.

El tiempo total de entrega se descompone en:

1. Preparación en el comercio (parcialmente no observable: el fin exacto del empaquetado no se ve).
2. Retiro por el repartidor.
3. Entrega al cliente.

Además de estimar el intervalo, hay que decidir **cuándo notificar al comercio** para iniciar la preparación.

> Las secciones siguientes se completan / ajustan a medida que se implementa la solución.

## Estructura del repositorio

```text
Mercado_Libre_Challenge/
├── README.md
├── requirements.txt
├── sql/
│   └── build_dataset.sql          # Consulta SQL para dataset y features
├── src/
│   ├── data/                      # Generación de datos sintéticos / carga
│   ├── features/                  # Construcción de variables predictoras
│   ├── models/                    # Entrenamiento y estimación de promesa
│   ├── activation/                # Estrategia de notificación al comercio
│   └── api/                       # Servicio HTTP
├── notebooks/                     # Exploración y evaluación (opcional)
├── artifacts/                     # Modelos persistidos (ignorado por git)
└── data/                          # Datos locales (ignorado por git)
```

## Setup

Requiere Python 3.12+.

```powershell
cd Mercado_Libre_Challenge
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Datos y SQL

No se provee un dataset de ejemplo: se generan **datos sintéticos** coherentes con los eventos operativos (notificación al comercio, notificación al repartidor, llegada al PoS, retiro, entrega).

La consulta SQL y la explicación de decisiones de feature engineering viven en:

- `sql/build_dataset.sql`

### Variables predictoras principales (borrador)

| Feature | Motivación |
|---------|------------|
| Hora / día de la semana del checkout | Estacionalidad de demanda y tráfico |
| Categoría / tipo de orden | Impacta tiempo de preparación |
| Distancia / zona origen–destino | Impacta retiro y entrega |
| Históricos del comercio (prep time p50/p90) | Señal de capacidad del PoS |
| Históricos de courier en zona | Señal de disponibilidad / velocidad |
| Carga operativa estimada | Contexto de congestión |

## Enfoque de estimación

*(Completar al implementar)*

- Target: tiempo total checkout → entrega (y/o componentes).
- Forma de la promesa: intervalo `[ETA_low, ETA_high]` calibrado a un nivel de cobertura (ej. cuantiles).
- Consumo en línea: features disponibles **solo al momento del checkout**.

## Estrategia de activación del comercio

*(Completar al implementar)*

Objetivo: notificar lo suficientemente temprano para que el pedido esté listo cuando llegue el repartidor, sin generar espera excesiva en el PoS.

## API

Servicio HTTP con endpoint:

```http
POST /delivery-promise
```

### Ejemplo de request (borrador de contrato)

```json
{
  "order_id": "ord_123",
  "checkout_ts": "2026-08-03T20:45:00-03:00",
  "store_id": "store_42",
  "category": "food",
  "destination": { "lat": -34.60, "lon": -58.38 },
  "origin": { "lat": -34.59, "lon": -58.41 }
}
```

### Ejemplo de response (borrador de contrato)

```json
{
  "order_id": "ord_123",
  "promise_window": {
    "start": "2026-08-03T21:15:00-03:00",
    "end": "2026-08-03T21:45:00-03:00"
  },
  "store_activation_ts": "2026-08-03T21:00:00-03:00",
  "confidence": 0.85
}
```

### Cómo levantar el servicio

```powershell
uvicorn src.api.main:app --reload --port 8000
```

## Evaluación

Métricas y criterios propuestos:

- Cobertura del intervalo (hit rate de entrega dentro de promesa).
- Ancho promedio del intervalo (competitividad / utilidad).
- Delay rate y magnitud de delay.
- Calidad de la activación (tiempo de espera del pedido listo vs. courier tardío).

## Supuestos, riesgos y limitaciones

*(Completar con los supuestos finales de la solución)*

- El fin exacto del empaquetado no es observable.
- Los datos sintéticos aproximan la dinámica operativa; no reemplazan datos reales.
- Features en línea están limitadas a información disponible en checkout.

## Evolución en producción

Ideas de siguiente paso: calibración online, feedback de delay, modelos por segmento (ciudad/categoría), monitoreo de drift y A/B de agresividad de promesa.

## Declaración de uso de IA

Se permite el uso de herramientas de IA. Declaración a completar:

| Herramienta | Uso | Qué se validó / modificó / descartó |
|-------------|-----|-------------------------------------|
| Cursor / asistente de código | Setup del entorno, estructura del repo, borrador de README | Pendiente de validación humana sobre diseño del modelo y métricas |

Durante la defensa se podrá explicar y defender cada decisión de la solución.
