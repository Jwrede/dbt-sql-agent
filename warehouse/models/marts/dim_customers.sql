with orders as (
    select * from {{ ref('fct_orders') }}
)
select
    c.customer_id,
    c.company_name,
    c.contact_name,
    c.contact_email,
    c.contact_phone,
    c.country,
    c.segment,
    c.created_at,
    min(o.order_date) filter (where o.is_revenue) as first_order_date,
    max(o.order_date) filter (where o.is_revenue) as last_order_date,
    count(o.order_id) filter (where o.is_revenue) as lifetime_orders,
    coalesce(sum(o.net_revenue) filter (where o.is_revenue), 0) as lifetime_net_revenue
from {{ ref('stg_customers') }} c
left join orders o on o.customer_id = c.customer_id
group by 1, 2, 3, 4, 5, 6, 7, 8
