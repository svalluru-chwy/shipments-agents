WITH base AS (
  SELECT DISTINCT
      order_id,
      customer_id,
      order_status,
      order_auto_reorder_flag,
      order_placed_dttm
  FROM edldb.chewybi.orders
  WHERE customer_id = :customer_id
),
non_cancelled AS (
  -- Use only non-cancelled orders to compute the cycle
  SELECT
      customer_id,
      order_placed_dttm,
      LAG(order_placed_dttm) OVER (
        PARTITION BY customer_id
        ORDER BY order_placed_dttm
      ) AS prev_placed_dttm
  FROM base
  WHERE order_status <> 'X'
),
diffs AS (
  SELECT
      customer_id,
      DATEDIFF('day', prev_placed_dttm, order_placed_dttm) AS days_between
  FROM non_cancelled
  WHERE prev_placed_dttm IS NOT NULL
),
cycle_agg AS (
  -- Collapse to one row per customer to avoid fan-out
  SELECT
      customer_id,
      AVG(days_between) AS avg_order_cycle_days
  FROM diffs
  GROUP BY customer_id
)
, avg_ctd_days as (
select avg(datediff('day',order_placed_dttm,bulk_track_delivery_dttm)) as avg_ctd,
avg(datediff('day',order_placed_dttm,release_dttm)) as avg_ctr,
avg(datediff('day',release_dttm,actual_ship_dttm)) as avg_rts,
avg(datediff('day',actual_ship_dttm,bulk_track_delivery_dttm)) as avg_std,
sum(case when datediff('day',order_placed_dttm,bulk_track_delivery_dttm)>3 then 1 else 0 end) as ctd_greater_than_3days
from edldb.chewybi.shipment_transactions
where order_id in (select ORDER_ID from edldb.chewybi.orders
where customer_id = :customer_id
and order_placed_dttm >= current_date - 60
group by all)
)
, last_shipped as (
select postcode as last_shipped_zip
from edldb.chewybi.shipment_transactions
where order_id in (
    select ORDER_ID from edldb.chewybi.orders
    where customer_id = :customer_id
    group by all
)
and bulk_track_delivery_dttm = (
select max(bulk_track_delivery_dttm) 
from edldb.chewybi.shipment_transactions
where order_id in (
    select ORDER_ID from edldb.chewybi.orders
    where customer_id = :customer_id
    group by all
    )
  )
)
, most_shipped as (
select postcode as most_shipped_zip
from edldb.chewybi.shipment_transactions
where order_id in (
    select ORDER_ID from edldb.chewybi.orders
    where customer_id = :customer_id
    and order_placed_dttm >= current_date - 60
    group by all
    )
group by all
order by count(*) desc
limit 1
)
, cust_primary_zip as (
select customer_address_zip as customer_primary_zip
from edldb.chewybi.customer_addresses
where customer_id = :customer_id
and customer_address_primary_address_flag = TRUE
)
SELECT * from (
SELECT
    b.customer_id,
    COUNT(DISTINCT b.order_id)                                                    AS orders,
    COUNT(DISTINCT CASE WHEN b.order_auto_reorder_flag = TRUE THEN b.order_id END) AS as_orders,
    MAX(b.order_placed_dttm::DATE)                                                AS last_ordered,
    -- ca.avg_order_cycle_days                                                       AS avg_order_cycle_days,
    CASE
      WHEN ca.avg_order_cycle_days IS NULL OR ca.avg_order_cycle_days = 0 THEN NULL
      ELSE 30 / ca.avg_order_cycle_days
    END                                                                           AS order_freq_per_month,
    COUNT(DISTINCT CASE WHEN b.order_status = 'X' THEN b.order_id END)            AS total_cancelled_orders
FROM base b
LEFT JOIN cycle_agg ca
  ON ca.customer_id = b.customer_id
GROUP BY b.customer_id, ca.avg_order_cycle_days
)
LEFT JOIN avg_ctd_days ON 1=1
LEFT JOIN last_shipped ON 1=1
LEFT JOIN most_shipped ON 1=1
LEFT JOIN cust_primary_zip ON 1=1;;
