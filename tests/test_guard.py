import pytest

from dbt_sql_agent import guard
from dbt_sql_agent.guard import GuardError


def code(sql, cat):
    with pytest.raises(GuardError) as e:
        guard.check(sql, cat)
    return e.value.code


def test_plain_select_passes_and_gets_limit(small_catalog):
    c = guard.check("select country, count(*) from marts.dim_customers group by country", small_catalog, max_rows=50)
    assert c.sql.endswith("LIMIT 50")
    assert c.tables == ["marts.dim_customers"]


def test_join_cte_and_unqualified_table(small_catalog):
    sql = ("with r as (select customer_id, sum(net_revenue) as rev from fct_orders where is_revenue group by 1) "
           "select c.company_name, r.rev from r join marts.dim_customers c using (customer_id) order by r.rev desc limit 5")
    c = guard.check(sql, small_catalog)
    assert c.tables == ["marts.dim_customers", "marts.fct_orders"]
    assert "LIMIT 5" in c.sql


def test_large_limit_is_capped(small_catalog):
    assert guard.check("select order_id from marts.fct_orders limit 999999", small_catalog, 100).sql.endswith("LIMIT 100")


@pytest.mark.parametrize("sql,expected", [
    ("select contact_email from marts.dim_customers", "blocked_column"),
    ("select c.CONTACT_EMAIL from marts.dim_customers c", "blocked_column"),
    ('select "contact_email" from marts.dim_customers', "blocked_column"),
    ("select company_name from marts.dim_customers where contact_email like '%x%'", "blocked_column"),
    ("select region, avg(annual_salary) from marts.dim_sales_reps group by 1", "blocked_column"),
    ("select * from marts.dim_customers", "star"),
    ("select c.* from marts.dim_customers c", "star"),
    ("select c from marts.dim_customers c", "whole_row"),
    ("select row_to_json(c) from marts.dim_customers c", "function"),
    ("select pg_read_file('/etc/passwd')", "table"),
    ("select pg_read_file('/etc/passwd'), country from marts.dim_customers", "function"),
    ("select pg_sleep(10), country from marts.dim_customers", "function"),
    ("select usename from pg_catalog.pg_user", "table"),
    ("select table_name from information_schema.tables", "table"),
    ("select x from staging.stg_customers", "table"),
    ("select country from other_db.marts.dim_customers", "table"),
    ("delete from marts.fct_orders", "not_select"),
    ("update marts.dim_customers set country = 'DE'", "not_select"),
    ("drop table marts.fct_orders", "not_select"),
    ("select 1 from marts.fct_orders; delete from marts.fct_orders", "multiple_statements"),
    ("select order_id into tmp_x from marts.fct_orders", "not_select"),
    ("select order_id from marts.fct_orders for update", "not_select"),
    ("with d as (delete from marts.fct_orders returning order_id) select order_id from d", "not_select"),
    ("select from where", "parse"),
])
def test_rejections(small_catalog, sql, expected):
    assert code(sql, small_catalog) == expected


def test_fetch_first_with_ties_is_a_limit(small_catalog):
    sql = "select country, count(*) as n from marts.dim_customers group by 1 order by n desc fetch first 1 rows with ties"
    c = guard.check(sql, small_catalog, 100)
    assert "WITH TIES" in c.sql and "LIMIT" not in c.sql
    capped = guard.check("select order_id from marts.fct_orders fetch first 5000 rows only", small_catalog, 100)
    assert capped.sql.endswith("LIMIT 100")


def test_count_star_is_allowed(small_catalog):
    guard.check("select count(*) from marts.dim_customers", small_catalog)


def test_union_gets_limit(small_catalog):
    c = guard.check("select country from marts.dim_customers union select region from marts.dim_sales_reps", small_catalog, 10)
    assert c.sql.endswith("LIMIT 10")


def test_context_hides_blocked_columns(small_catalog):
    with_docs = small_catalog.context(with_docs=True)
    assert "contact_email: NOT AVAILABLE (pii)" in with_docs
    bare = small_catalog.context(with_docs=False)
    assert "contact_email" not in bare and "annual_salary" not in bare
    assert "net_revenue numeric" in bare


def test_grants_list_only_allowed_columns(small_catalog):
    g = "\n".join(small_catalog.grants_sql("agent"))
    assert 'GRANT SELECT ("customer_id", "company_name", "country") ON "marts"."dim_customers" TO "agent"' in g
    assert "contact_email" not in g and "annual_salary" not in g
