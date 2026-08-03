"""Offline evaluation metrics for delivery promise intervals."""

from __future__ import annotations

import numpy as np
import pandas as pd


def evaluate_promise(
    y_true: np.ndarray,
    y_p20: np.ndarray,
    y_p50: np.ndarray,
    y_p80: np.ndarray,
) -> dict[str, float]:
    """Compute coverage, width, delay rate and point-forecast MAE."""
    y_true = np.asarray(y_true, dtype=float)
    y_p20 = np.asarray(y_p20, dtype=float)
    y_p50 = np.asarray(y_p50, dtype=float)
    y_p80 = np.asarray(y_p80, dtype=float)

    # Ensure ordered bounds
    low = np.minimum(y_p20, y_p80)
    high = np.maximum(y_p20, y_p80)

    inside = (y_true >= low) & (y_true <= high)
    delayed = y_true > high
    width = high - low

    return {
        "n": float(len(y_true)),
        "coverage": float(inside.mean()),
        "delay_rate": float(delayed.mean()),
        "mean_width_minutes": float(width.mean()),
        "median_width_minutes": float(np.median(width)),
        "mae_p50": float(np.mean(np.abs(y_true - y_p50))),
        "mean_delay_when_late": float(np.mean(y_true[delayed] - high[delayed])) if delayed.any() else 0.0,
    }


def metrics_to_frame(metrics: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([metrics])
