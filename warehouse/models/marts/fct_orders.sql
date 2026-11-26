with lines as (
    select
        order_id,
        sum(quantity * unit_price) as gross_amount,
        sum(net_amount) as net_revenue,
        sum(cogs) as cogs,
        sum(quantity) as item_count
    from {{ ref('fct_order_lines') }}
    group by 1
)
select
    o.order_id,
    o.customer_id,
    o.sales_rep_id,
    o.order_date,
    date_trunc('month', o.order_date)::date as order_month,
    o.status,
    o.status = 'completed' as is_revenue,
    round(l.gross_amount, 2) as gross_amount,
    round(l.gross_amount - l.net_revenue, 2) as discount_amount,
    l.net_revenue,
    o.shipping_fee,
    l.cogs,
    l.net_revenue - l.cogs as gross_margin,
    l.item_count
from {{ ref('stg_orders') }} o
join lines l on l.order_id = o.order_id
