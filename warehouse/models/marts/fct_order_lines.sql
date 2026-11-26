select
    l.order_id,
    l.line_number,
    l.product_id,
    l.quantity,
    l.unit_price,
    l.discount_pct,
    round(l.quantity * l.unit_price * (100 - l.discount_pct) / 100.0, 2) as net_amount,
    round(l.quantity * p.unit_cost, 2) as cogs
from {{ ref('stg_order_lines') }} l
join {{ ref('stg_products') }} p on p.product_id = l.product_id
