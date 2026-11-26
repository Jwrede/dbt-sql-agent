import os
from pathlib import Path

import pytest

from dbt_sql_agent.catalog import Catalog, Column, Model

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "warehouse" / "target" / "manifest.json"


@pytest.fixture
def small_catalog() -> Catalog:
    cust = Model("dim_customers", "marts", "customers", {
        "customer_id": Column("customer_id", data_type="integer"),
        "company_name": Column("company_name", data_type="text"),
        "contact_email": Column("contact_email", data_type="text", blocked_reason="pii"),
        "country": Column("country", data_type="text"),
    })
    orders = Model("fct_orders", "marts", "orders", {
        "order_id": Column("order_id", data_type="integer"),
        "customer_id": Column("customer_id", data_type="integer"),
        "net_revenue": Column("net_revenue", data_type="numeric"),
        "is_revenue": Column("is_revenue", data_type="boolean"),
        "order_date": Column("order_date", data_type="date"),
    })
    reps = Model("dim_sales_reps", "marts", "reps", {
        "sales_rep_id": Column("sales_rep_id", data_type="integer"),
        "region": Column("region", data_type="text"),
        "annual_salary": Column("annual_salary", data_type="integer", blocked_reason="restricted"),
    })
    return Catalog({m.relation: m for m in (cust, orders, reps)})


@pytest.fixture(scope="session")
def settings():
    """Needs the warehouse built by dbt and `dbt-sql-agent setup` run (see README); skipped otherwise."""
    if not os.environ.get("DSA_TEST_DB") or not MANIFEST.exists():
        pytest.skip("set DSA_TEST_DB=1 with a built warehouse (dbt build) and DSA_PG* settings")
    from dbt_sql_agent.config import Settings
    s = Settings.from_env()
    s.manifest = str(MANIFEST)
    return s


@pytest.fixture(scope="session")
def catalog(settings):
    from dbt_sql_agent import db
    return Catalog.from_manifest(settings.manifest, db.column_types(settings.admin_dsn))
