"""Store activation timing strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd


def compute_store_activation(
    *,
    checkout_ts: pd.Timestamp,
    prep_p50: float,
    courier_to_store_p50: float,
    buffer_minutes: float = 2.0,
) -> dict[str, Any]:
    """Choose when to notify the store after checkout.

    Goal: have the order ready close to courier arrival at the PoS, avoiding
    early prep (food waiting) and late prep (courier idle / delay).

    activation_offset = max(0, courier_to_store_p50 - prep_p50 - buffer)
    """
    ts = pd.Timestamp(checkout_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("America/Argentina/Buenos_Aires")

    prep = max(float(prep_p50), 1.0)
    courier = max(float(courier_to_store_p50), 1.0)
    offset = max(0.0, courier - prep - buffer_minutes)

    activation_ts = ts + pd.Timedelta(minutes=offset)
    reason = (
        f"Notify store {offset:.1f}m after checkout so estimated prep ({prep:.1f}m) "
        f"finishes near courier arrival to store ({courier:.1f}m), with {buffer_minutes:.1f}m buffer."
    )
    return {
        "store_activation_ts": activation_ts,
        "activation_offset_minutes": offset,
        "prep_p50": prep,
        "courier_to_store_p50": courier,
        "reason": reason,
    }
