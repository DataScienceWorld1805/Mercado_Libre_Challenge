"""Pydantic contracts for the delivery-promise API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class DeliveryPromiseRequest(BaseModel):
    order_id: str
    checkout_ts: datetime
    store_id: str
    category: Literal["food", "grocery", "pharmacy"]
    origin: Coordinates
    destination: Coordinates
    zone_id: str | None = None


class PromiseWindow(BaseModel):
    start: datetime
    end: datetime


class DeliveryPromiseResponse(BaseModel):
    order_id: str
    promise_window: PromiseWindow
    store_activation_ts: datetime
    confidence: float = Field(..., ge=0, le=1)


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
