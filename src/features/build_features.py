"""Feature engineering aligned with sql/build_dataset.sql (no future leakage)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.data.schema import CATEGORIES, FEATURE_COLUMNS, TARGET_COLUMN

GLOBAL_DEFAULTS = {
    "store_prep_p50_hist": 15.0,
    "store_prep_p90_hist": 28.0,
    "zone_courier_p50_hist": 12.0,
    "zone_load_hist": 1.0,
}


def _ensure_ts(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in (
        "checkout_ts",
        "store_notify_ts",
        "courier_notify_ts",
        "courier_arrive_pos_ts",
        "pickup_ts",
        "deliver_ts",
    ):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True).dt.tz_convert("America/Argentina/Buenos_Aires")
    return out


def add_stage_times(df: pd.DataFrame) -> pd.DataFrame:
    """Compute stage durations and observable prep proxy.

    Prep ready is not observable. Proxy = minutes from store notify to pickup.
    This mixes true prep with courier wait, matching a realistic data limitation.
    """
    out = _ensure_ts(df)
    out["total_delivery_minutes"] = (out["deliver_ts"] - out["checkout_ts"]).dt.total_seconds() / 60.0
    out["prep_proxy_minutes"] = (out["pickup_ts"] - out["store_notify_ts"]).dt.total_seconds() / 60.0
    out["courier_to_store_minutes"] = (
        out["courier_arrive_pos_ts"] - out["courier_notify_ts"]
    ).dt.total_seconds() / 60.0
    out["delivery_leg_minutes"] = (out["deliver_ts"] - out["pickup_ts"]).dt.total_seconds() / 60.0
    out["hour"] = out["checkout_ts"].dt.hour
    out["dow"] = out["checkout_ts"].dt.dayofweek
    return out


def compute_historical_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Aggregate stats used for online lookup (cold-start aware defaults)."""
    staged = add_stage_times(df)
    store_stats = (
        staged.groupby("store_id")
        .agg(
            store_prep_p50_hist=("prep_proxy_minutes", lambda s: float(s.quantile(0.5))),
            store_prep_p90_hist=("prep_proxy_minutes", lambda s: float(s.quantile(0.9))),
            n_orders=("order_id", "count"),
        )
        .reset_index()
    )
    zone_stats = (
        staged.groupby("zone_id")
        .agg(
            zone_courier_p50_hist=("courier_to_store_minutes", lambda s: float(s.quantile(0.5))),
            zone_load_hist=("order_id", "count"),
        )
        .reset_index()
    )
    # Normalize zone load to relative intensity (per day approx over 21 days)
    zone_stats["zone_load_hist"] = zone_stats["zone_load_hist"] / zone_stats["zone_load_hist"].median()

    return {
        "store_stats": store_stats,
        "zone_stats": zone_stats,
        "defaults": GLOBAL_DEFAULTS,
    }


def _expanding_store_quantiles(staged: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time store prep quantiles using only prior orders (anti-leakage)."""
    staged = staged.sort_values("checkout_ts").reset_index(drop=True)
    p50_vals = np.full(len(staged), np.nan)
    p90_vals = np.full(len(staged), np.nan)

    for _, group in staged.groupby("store_id", sort=False):
        idxs = group.index.to_numpy()
        prep = staged.loc[idxs, "prep_proxy_minutes"].to_numpy()
        for pos, row_i in enumerate(idxs):
            if pos == 0:
                continue
            hist = prep[:pos]
            p50_vals[row_i] = float(np.quantile(hist, 0.5))
            p90_vals[row_i] = float(np.quantile(hist, 0.9))

    staged["store_prep_p50_hist"] = p50_vals
    staged["store_prep_p90_hist"] = p90_vals
    return staged


def _expanding_zone_stats(staged: pd.DataFrame) -> pd.DataFrame:
    staged = staged.sort_values("checkout_ts").reset_index(drop=True)
    courier_p50 = np.full(len(staged), np.nan)
    load = np.full(len(staged), np.nan)

    for _, group in staged.groupby("zone_id", sort=False):
        idxs = group.index.to_numpy()
        courier = staged.loc[idxs, "courier_to_store_minutes"].to_numpy()
        checkouts = staged.loc[idxs, "checkout_ts"]
        for pos, row_i in enumerate(idxs):
            if pos == 0:
                continue
            courier_p50[row_i] = float(np.quantile(courier[:pos], 0.5))
            t = checkouts.iloc[pos]
            window_start = t - pd.Timedelta(hours=3)
            prior_times = checkouts.iloc[:pos]
            load[row_i] = float(((prior_times >= window_start) & (prior_times < t)).sum())

    staged["zone_courier_p50_hist"] = courier_p50
    median_load = np.nanmedian(load[load > 0]) if np.any(load > 0) else 1.0
    staged["zone_load_hist"] = np.where(np.isnan(load), np.nan, load / max(median_load, 1.0))
    return staged


def build_modeling_frame(orders: pd.DataFrame) -> pd.DataFrame:
    """Build supervised learning frame matching the SQL contract."""
    staged = add_stage_times(orders)
    staged = _expanding_store_quantiles(staged)
    staged = _expanding_zone_stats(staged)

    for col, default in GLOBAL_DEFAULTS.items():
        staged[col] = staged[col].fillna(default)

    for cat in CATEGORIES:
        staged[f"category_{cat}"] = (staged["category"] == cat).astype(int)

    frame = staged[
        [
            "order_id",
            "checkout_ts",
            "store_id",
            "zone_id",
            "category",
            *FEATURE_COLUMNS,
            TARGET_COLUMN,
            "prep_proxy_minutes",
            "courier_to_store_minutes",
        ]
    ].copy()
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=[TARGET_COLUMN])
    return frame.reset_index(drop=True)


def build_online_features(
    *,
    checkout_ts: pd.Timestamp,
    category: str,
    distance_km: float,
    store_id: str,
    zone_id: str,
    hist_stats: dict[str, Any],
) -> dict[str, float]:
    """Build the online feature vector available at checkout time."""
    store_stats: pd.DataFrame = hist_stats["store_stats"]
    zone_stats: pd.DataFrame = hist_stats["zone_stats"]
    defaults = hist_stats["defaults"]

    store_row = store_stats.loc[store_stats["store_id"] == store_id]
    zone_row = zone_stats.loc[zone_stats["zone_id"] == zone_id]

    if len(store_row):
        prep_p50 = float(store_row.iloc[0]["store_prep_p50_hist"])
        prep_p90 = float(store_row.iloc[0]["store_prep_p90_hist"])
    else:
        prep_p50 = defaults["store_prep_p50_hist"]
        prep_p90 = defaults["store_prep_p90_hist"]

    if len(zone_row):
        courier_p50 = float(zone_row.iloc[0]["zone_courier_p50_hist"])
        zone_load = float(zone_row.iloc[0]["zone_load_hist"])
    else:
        courier_p50 = defaults["zone_courier_p50_hist"]
        zone_load = defaults["zone_load_hist"]

    ts = pd.Timestamp(checkout_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("America/Argentina/Buenos_Aires")

    feats = {
        "hour": float(ts.hour),
        "dow": float(ts.dayofweek),
        "category_food": 1.0 if category == "food" else 0.0,
        "category_grocery": 1.0 if category == "grocery" else 0.0,
        "category_pharmacy": 1.0 if category == "pharmacy" else 0.0,
        "distance_km": float(distance_km),
        "store_prep_p50_hist": prep_p50,
        "store_prep_p90_hist": prep_p90,
        "zone_courier_p50_hist": courier_p50,
        "zone_load_hist": zone_load,
    }
    # Preserve column order
    return {c: feats[c] for c in FEATURE_COLUMNS}
