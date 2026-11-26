select
    product_id,
    sku,
    name as product_name,
    category,
    unit_price as list_price,
    unit_cost,
    is_active
from {{ ref('stg_products') }}
