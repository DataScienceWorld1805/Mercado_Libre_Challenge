"""FastAPI service exposing POST /delivery-promise."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException

from src.api.schemas import (
    DeliveryPromiseRequest,
    DeliveryPromiseResponse,
    HealthResponse,
    PromiseWindow,
)
from src.models.predict import PromisePredictor

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT / "artifacts"

_predictor: PromisePredictor | None = None
_load_error: str | None = None


def get_predictor() -> PromisePredictor:
    if _predictor is None:
        raise HTTPException(
            status_code=503,
            detail=_load_error or "Models not loaded. Run: python scripts/run_pipeline.py",
        )
    return _predictor


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _predictor, _load_error
    try:
        _predictor = PromisePredictor.load(ARTIFACTS_DIR)
        _load_error = None
    except Exception as exc:  # noqa: BLE001 — surface clear startup diagnostics
        _predictor = None
        _load_error = str(exc)
    yield


app = FastAPI(
    title="Delivery Promise API",
    description="Estimates checkout delivery promise windows and store activation time.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok" if _predictor else "degraded", models_loaded=_predictor is not None)


@app.post("/delivery-promise", response_model=DeliveryPromiseResponse)
def delivery_promise(payload: DeliveryPromiseRequest) -> DeliveryPromiseResponse:
    predictor = get_predictor()
    checkout_ts = pd.Timestamp(payload.checkout_ts)
    if checkout_ts.tzinfo is None:
        checkout_ts = checkout_ts.tz_localize("America/Argentina/Buenos_Aires")

    try:
        result = predictor.predict(
            order_id=payload.order_id,
            checkout_ts=checkout_ts,
            store_id=payload.store_id,
            category=payload.category,
            origin_lat=payload.origin.lat,
            origin_lon=payload.origin.lon,
            dest_lat=payload.destination.lat,
            dest_lon=payload.destination.lon,
            zone_id=payload.zone_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DeliveryPromiseResponse(
        order_id=result["order_id"],
        promise_window=PromiseWindow(
            start=datetime.fromisoformat(result["promise_window"]["start"]),
            end=datetime.fromisoformat(result["promise_window"]["end"]),
        ),
        store_activation_ts=datetime.fromisoformat(result["store_activation_ts"]),
        confidence=result["confidence"],
    )
