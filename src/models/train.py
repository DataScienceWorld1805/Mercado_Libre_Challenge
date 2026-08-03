"""Train LightGBM quantile models and persist artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from src.data.schema import FEATURE_COLUMNS, TARGET_COLUMN
from src.features.build_features import build_modeling_frame, compute_historical_stats
from src.models.evaluate import evaluate_promise

QUANTILES = (0.2, 0.5, 0.8)
MODEL_NAMES = {0.2: "q20", 0.5: "q50", 0.8: "q80"}


def temporal_split(frame: pd.DataFrame, test_ratio: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = frame.sort_values("checkout_ts")
    cut = int(len(frame) * (1 - test_ratio))
    return frame.iloc[:cut].copy(), frame.iloc[cut:].copy()


def _fit_quantile(X: pd.DataFrame, y: np.ndarray, alpha: float, seed: int = 42) -> lgb.LGBMRegressor:
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        verbosity=-1,
    )
    model.fit(X, y)
    return model


def train_and_persist(
    orders: pd.DataFrame,
    artifacts_dir: Path,
    seed: int = 42,
) -> dict[str, Any]:
    """Train quantile models, evaluate on a temporal holdout, save artifacts."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    frame = build_modeling_frame(orders)
    train_df, test_df = temporal_split(frame, test_ratio=0.2)

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN].to_numpy()
    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_COLUMN].to_numpy()

    models: dict[str, Any] = {}
    preds: dict[float, np.ndarray] = {}
    for alpha in QUANTILES:
        name = MODEL_NAMES[alpha]
        model = _fit_quantile(X_train, y_train, alpha=alpha, seed=seed)
        models[name] = model
        preds[alpha] = model.predict(X_test)
        joblib.dump(model, artifacts_dir / f"{name}.joblib")

    metrics = evaluate_promise(y_test, preds[0.2], preds[0.5], preds[0.8])

    # Historical lookups for online serving (computed on full history for demo;
    # in production these would be batch-refreshed tables).
    hist_stats = compute_historical_stats(orders)
    hist_stats["store_stats"].to_json(artifacts_dir / "store_stats.json", orient="records")
    hist_stats["zone_stats"].to_json(artifacts_dir / "zone_stats.json", orient="records")

    # Store → zone mapping for online requests that only send store_id
    store_zone = (
        orders.sort_values("checkout_ts")
        .drop_duplicates("store_id", keep="last")[["store_id", "zone_id", "origin_lat", "origin_lon"]]
        .reset_index(drop=True)
    )
    store_zone.to_json(artifacts_dir / "store_zone.json", orient="records")

    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "quantiles": list(QUANTILES),
        "target": TARGET_COLUMN,
        "train_size": int(len(train_df)),
        "test_size": int(len(test_df)),
        "metrics": metrics,
        "defaults": hist_stats["defaults"],
    }
    (artifacts_dir / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (artifacts_dir / "feature_columns.json").write_text(
        json.dumps(FEATURE_COLUMNS, indent=2), encoding="utf-8"
    )
    (artifacts_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return {"metrics": metrics, "meta": meta, "frame": frame, "test_df": test_df, "preds": preds}
