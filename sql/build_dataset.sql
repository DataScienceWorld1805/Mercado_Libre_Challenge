WITH base AS (
    SELECT
        order_id,
        checkout_ts,
        store_id,
        category,
        zone_id,
        distance_km,
        store_notify_ts,
        courier_notify_ts,
        courier_arrive_pos_ts,
        pickup_ts,
        deliver_ts,
        EXTRACT(HOUR FROM checkout_ts)              AS hour,
        EXTRACT(DOW FROM checkout_ts)               AS dow,  -- 0=Sunday in Postgres
        EXTRACT(EPOCH FROM (deliver_ts - checkout_ts)) / 60.0
            AS total_delivery_minutes,
        -- Observable prep proxy (NOT latent prep_ready)
        EXTRACT(EPOCH FROM (pickup_ts - store_notify_ts)) / 60.0
            AS prep_proxy_minutes,
        EXTRACT(EPOCH FROM (courier_arrive_pos_ts - courier_notify_ts)) / 60.0
            AS courier_to_store_minutes
    FROM orders
),


store_hist AS (
    SELECT
        b.order_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.prep_proxy_minutes)
            AS store_prep_p50_hist,
        PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY p.prep_proxy_minutes)
            AS store_prep_p90_hist
    FROM base b
    LEFT JOIN base p
      ON p.store_id = b.store_id
     AND p.checkout_ts < b.checkout_ts
    GROUP BY b.order_id
),


zone_hist AS (
    SELECT
        b.order_id,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.courier_to_store_minutes)
            AS zone_courier_p50_hist,
        COUNT(*) FILTER (
            WHERE p.checkout_ts >= b.checkout_ts - INTERVAL '3 hours'
              AND p.checkout_ts <  b.checkout_ts
        ) AS zone_load_raw
    FROM base b
    LEFT JOIN base p
      ON p.zone_id = b.zone_id
     AND p.checkout_ts < b.checkout_ts
    GROUP BY b.order_id, b.checkout_ts
),

zone_load_scaled AS (
    SELECT
        order_id,
        zone_courier_p50_hist,
        zone_load_raw / NULLIF(
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY zone_load_raw) OVER (),
            0
        ) AS zone_load_hist
    FROM zone_hist
)

SELECT
    b.order_id,
    b.checkout_ts,
    b.store_id,
    b.zone_id,
    b.category,
    b.hour,
    b.dow,
    CASE WHEN b.category = 'food'      THEN 1 ELSE 0 END AS category_food,
    CASE WHEN b.category = 'grocery'   THEN 1 ELSE 0 END AS category_grocery,
    CASE WHEN b.category = 'pharmacy'  THEN 1 ELSE 0 END AS category_pharmacy,
    b.distance_km,
    COALESCE(s.store_prep_p50_hist, 15.0)     AS store_prep_p50_hist,
    COALESCE(s.store_prep_p90_hist, 28.0)     AS store_prep_p90_hist,
    COALESCE(z.zone_courier_p50_hist, 12.0)   AS zone_courier_p50_hist,
    COALESCE(z.zone_load_hist, 1.0)           AS zone_load_hist,
    b.total_delivery_minutes                  AS target_total_delivery_minutes
FROM base b
LEFT JOIN store_hist s       ON s.order_id = b.order_id
LEFT JOIN zone_load_scaled z ON z.order_id = b.order_id
ORDER BY b.checkout_ts;
