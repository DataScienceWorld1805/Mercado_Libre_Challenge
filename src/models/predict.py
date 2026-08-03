"""Online / offline prediction helpers for promise windows."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.activation.strategy import compute_store_activation
from src.data.schema import FEATURE_COLUMNS
from src.features.build_features import GLOBAL_DEFAULTS, build_online_features


def round_to_quarter_hour(ts: pd.Timestamp) -> pd.Timestamp:
    """Round timestamp up to the next 15-minute boundary."""
    discard = timedelta(
        minutes=ts.minute % 15,
        seconds=ts.second,
        microseconds=ts.microsecond,
    )
    if discard == timedelta(0):
        return ts
    return ts + (timedelta(minutes=15) - discard)


def minutes_to_promise_window(
    checkout_ts: pd.Timestamp,
    low_minutes: float,
    high_minutes: float,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Convert predicted minutes into a same-day 15-min promise window."""
    ts = pd.Timestamp(checkout_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("America/Argentina/Buenos_Aires")

    low_m = max(5.0, float(low_minutes))
    high_m = max(low_m + 15.0, float(high_minutes))

    start = round_to_quarter_hour(ts + pd.Timedelta(minutes=low_m))
    end = round_to_quarter_hour(ts + pd.Timedelta(minutes=high_m))
    if end <= start:
        end = start + pd.Timedelta(minutes=15)

    # Clamp to same calendar day end (23:45 local)
    day_end = ts.normalize() + pd.Timedelta(hours=23, minutes=45)
    if start > day_end:
        start = day_end - pd.Timedelta(minutes=30)
    if end > day_end:
        end = day_end
    if end <= start:
        end = min(start + pd.Timedelta(minutes=15), day_end + pd.Timedelta(minutes=15))

    return start, end


def confidence_from_width(low_m: float, high_m: float, p50: float) -> float:
    """Map relative interval width to a simple confidence score in (0, 1]."""
    width = max(high_m - low_m, 1.0)
    rel = width / max(p50, 1.0)
    # Narrower relative width → higher confidence; clamp to [0.55, 0.95]
    score = 1.0 / (1.0 + rel)
    return float(min(0.95, max(0.55, score)))


@dataclass
class PromisePredictor:
    models: dict[str, Any]
    feature_columns: list[str]
    hist_stats: dict[str, Any]
    store_zone: pd.DataFrame
    meta: dict[str, Any]

    @classmethod
    def load(cls, artifacts_dir: Path) -> "PromisePredictor":
        artifacts_dir = Path(artifacts_dir)
        required = ["q20.joblib", "q50.joblib", "q80.joblib", "model_meta.json", "store_stats.json"]
        missing = [p for p in required if not (artifacts_dir / p).exists()]
        if missing:
            raise FileNotFoundError(
                f"Missing artifacts: {missing}. Run: python scripts/run_pipeline.py"
            )

        models = {
            "q20": joblib.load(artifacts_dir / "q20.joblib"),
            "q50": joblib.load(artifacts_dir / "q50.joblib"),
            "q80": joblib.load(artifacts_dir / "q80.joblib"),
        }
        meta = json.loads((artifacts_dir / "model_meta.json").read_text(encoding="utf-8"))
        feature_columns = meta.get("feature_columns", FEATURE_COLUMNS)
        store_stats = pd.read_json(artifacts_dir / "store_stats.json")
        zone_stats = pd.read_json(artifacts_dir / "zone_stats.json")
        store_zone = pd.read_json(artifacts_dir / "store_zone.json")
        hist_stats = {
            "store_stats": store_stats,
            "zone_stats": zone_stats,
            "defaults": meta.get("defaults", GLOBAL_DEFAULTS),
        }
        return cls(
            models=models,
            feature_columns=feature_columns,
            hist_stats=hist_stats,
            store_zone=store_zone,
            meta=meta,
        )

    def resolve_zone(self, store_id: str, zone_id: str | None) -> str:
        if zone_id:
            return zone_id
        row = self.store_zone.loc[self.store_zone["store_id"] == store_id]
        if len(row):
            return str(row.iloc[0]["zone_id"])
        return "zone_0"

    def haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def predict(
        self,
        *,
        order_id: str,
        checkout_ts: pd.Timestamp,
        store_id: str,
        category: str,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        zone_id: str | None = None,
    ) -> dict[str, Any]:
        zone = self.resolve_zone(store_id, zone_id)
        distance_km = self.haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
        distance_km = float(np.clip(distance_km, 0.3, 12.0))

        feats = build_online_features(
            checkout_ts=checkout_ts,
            category=category,
            distance_km=distance_km,
            store_id=store_id,
            zone_id=zone,
            hist_stats=self.hist_stats,
        )
        X = pd.DataFrame([feats])[self.feature_columns]

        p20 = float(self.models["q20"].predict(X)[0])
        p50 = float(self.models["q50"].predict(X)[0])
        p80 = float(self.models["q80"].predict(X)[0])
        low, high = min(p20, p80), max(p20, p80)

        start, end = minutes_to_promise_window(checkout_ts, low, high)
        activation = compute_store_activation(
            checkout_ts=checkout_ts,
            prep_p50=feats["store_prep_p50_hist"],
            courier_to_store_p50=feats["zone_courier_p50_hist"],
        )

        return {
            "order_id": order_id,
            "promise_window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "store_activation_ts": activation["store_activation_ts"].isoformat(),
            "confidence": confidence_from_width(low, high, p50),
            "debug": {
                "predicted_minutes": {"p20": p20, "p50": p50, "p80": p80},
                "distance_km": distance_km,
                "zone_id": zone,
                "features": feats,
                "activation_reason": activation["reason"],
            },
        }
