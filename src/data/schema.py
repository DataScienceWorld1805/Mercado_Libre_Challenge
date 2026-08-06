from typing import Final

# Observable event timestamps (prep_ready_ts is latent and never used as a feature).
ORDER_COLUMNS: Final[list[str]] = [
    "order_id",
    "checkout_ts",
    "store_id",
    "category",
    "zone_id",
    "origin_lat",
    "origin_lon",
    "dest_lat",
    "dest_lon",
    "distance_km",
    "store_notify_ts",
    "courier_notify_ts",
    "courier_arrive_pos_ts",
    "pickup_ts",
    "deliver_ts",
]

# Latent column kept only in full synthetic dumps for analysis / debugging.
LATENT_COLUMNS: Final[list[str]] = [
    "prep_ready_ts",
]

FEATURE_COLUMNS: Final[list[str]] = [
    "hour",
    "dow",
    "category_food",
    "category_grocery",
    "category_pharmacy",
    "distance_km",
    "store_prep_p50_hist",
    "store_prep_p90_hist",
    "zone_courier_p50_hist",
    "zone_load_hist",
]

TARGET_COLUMN: Final[str] = "total_delivery_minutes"

CATEGORIES: Final[tuple[str, ...]] = ("food", "grocery", "pharmacy")
