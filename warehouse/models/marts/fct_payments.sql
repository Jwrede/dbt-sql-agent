select
    payment_id,
    order_id,
    paid_at,
    amount,
    method
from {{ ref('stg_payments') }}
