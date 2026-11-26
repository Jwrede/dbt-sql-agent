select
    employee_id as sales_rep_id,
    full_name,
    email,
    region,
    hire_date,
    annual_salary
from {{ ref('stg_employees') }}
