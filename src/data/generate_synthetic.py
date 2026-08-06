from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .schema import CATEGORIES, ORDER_COLUMNS

# Approximate CABA bounding box
LAT_MIN, LAT_MAX = -34.65, -34.55
LON_MIN, LON_MAX = -58.48, -58.35

PREP_MEAN = {"food": 22.0, "grocery": 12.0, "pharmacy": 8.0}
PREP_STD = {"food": 8.0, "grocery": 4.0, "pharmacy": 3.0}


def _haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def generate_orders(n_orders: int = 12000, seed: int = 42, n_stores: int = 80) -> pd.DataFrame:
    """Genera órdenes sintéticas con timestamps operativos.

    ``prep_ready_ts`` es latente (no observable en producción). Nunca debe
    usarse como feature del modelo; el prep histórico usa un proxy observable.
    """
    rng = np.random.default_rng(seed)

    store_ids = np.array([f"store_{i:03d}" for i in range(n_stores)])
    store_lat = rng.uniform(LAT_MIN, LAT_MAX, n_stores)
    store_lon = rng.uniform(LON_MIN, LON_MAX, n_stores)
    store_zone = (
        ((store_lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * 3).astype(int).clip(0, 2) * 3
        + ((store_lon - LON_MIN) / (LON_MAX - LON_MIN) * 3).astype(int).clip(0, 2)
    )
    store_zone_id = np.array([f"zone_{z}" for z in store_zone])
    store_prep_factor = rng.lognormal(mean=0.0, sigma=0.25, size=n_stores)

    store_idx = rng.integers(0, n_stores, n_orders)
    categories = rng.choice(list(CATEGORIES), size=n_orders, p=[0.55, 0.30, 0.15])

    start = pd.Timestamp("2026-07-13 10:00:00", tz="America/Argentina/Buenos_Aires")
    offsets_min = rng.integers(0, 21 * 24 * 60, n_orders)
    hour_boost = rng.choice([0, 60, 120], size=n_orders, p=[0.7, 0.15, 0.15])
    checkout_ts = pd.to_datetime(start + pd.to_timedelta(offsets_min + hour_boost, unit="m")).floor("min")

    origin_lat = store_lat[store_idx]
    origin_lon = store_lon[store_idx]
    dest_lat = rng.uniform(LAT_MIN, LAT_MAX, n_orders)
    dest_lon = rng.uniform(LON_MIN, LON_MAX, n_orders)
    distance_km = np.clip(_haversine_km(origin_lat, origin_lon, dest_lat, dest_lon), 0.3, 12.0)

    hour = checkout_ts.hour.to_numpy()
    congestion = np.where(
        (hour >= 12) & (hour <= 14),
        1.25,
        np.where((hour >= 19) & (hour <= 21), 1.35, 1.0),
    )
    zone_load_noise = rng.uniform(0.9, 1.2, n_orders)

    prep_base = np.array([PREP_MEAN[c] for c in categories])
    prep_std = np.array([PREP_STD[c] for c in categories])
    prep_minutes = np.clip(
        rng.normal(prep_base, prep_std) * store_prep_factor[store_idx] * zone_load_noise,
        3.0,
        70.0,
    )

    activate_delay = np.clip(rng.normal(3.0, 1.5, n_orders), 0.5, 10.0)
    store_notify_ts = checkout_ts + pd.to_timedelta(activate_delay, unit="m")

    courier_dispatch_lag = np.clip(rng.normal(2.0, 1.0, n_orders), 0.2, 8.0)
    courier_notify_ts = store_notify_ts + pd.to_timedelta(courier_dispatch_lag, unit="m")

    courier_to_store = np.clip(
        rng.normal(8.0 + distance_km * 1.8, 3.0) * congestion,
        3.0,
        45.0,
    )
    courier_arrive_pos_ts = courier_notify_ts + pd.to_timedelta(courier_to_store, unit="m")

    prep_ready_ts = store_notify_ts + pd.to_timedelta(prep_minutes, unit="m")
    handoff = np.clip(rng.normal(1.5, 0.7, n_orders), 0.3, 5.0)
    pickup_start = np.maximum(prep_ready_ts.to_numpy(), courier_arrive_pos_ts.to_numpy())
    pickup_ts = pd.to_datetime(pickup_start) + pd.to_timedelta(handoff, unit="m")

    delivery_minutes = np.clip(
        rng.normal(6.0 + distance_km * 3.2, 2.5) * congestion,
        4.0,
        60.0,
    )
    deliver_ts = pickup_ts + pd.to_timedelta(delivery_minutes, unit="m")

    df = pd.DataFrame(
        {
            "order_id": [f"ord_{i:06d}" for i in range(n_orders)],
            "checkout_ts": checkout_ts,
            "store_id": store_ids[store_idx],
            "category": categories,
            "zone_id": store_zone_id[store_idx],
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
            "distance_km": np.round(distance_km, 3),
            "store_notify_ts": store_notify_ts,
            "courier_notify_ts": courier_notify_ts,
            "courier_arrive_pos_ts": courier_arrive_pos_ts,
            "pickup_ts": pickup_ts,
            "deliver_ts": deliver_ts,
            "prep_ready_ts": prep_ready_ts,
        }
    )
    return df.sort_values("checkout_ts").reset_index(drop=True)


def save_orders(
    df: pd.DataFrame,
    synthetic_dir: Path,
    sample_dir: Path,
    sample_n: int = 500,
) -> tuple[Path, Path]:
    """Persist full synthetic dump (with latent) and observable sample for the repo."""
    synthetic_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    full_path = synthetic_dir / "orders.csv"
    sample_path = sample_dir / "orders_sample.csv"

    df.to_csv(full_path, index=False)

    sample = df.sample(n=min(sample_n, len(df)), random_state=42).sort_values("checkout_ts")
    sample[ORDER_COLUMNS].to_csv(sample_path, index=False)
    return full_path, sample_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    orders = generate_orders()
    full, sample = save_orders(orders, root / "data" / "synthetic", root / "data" / "sample")
    print(f"Wrote {len(orders)} orders -> {full}")
    print(f"Sample -> {sample}")
