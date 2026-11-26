"""Integration tests against PostgreSQL with the dbt-built warehouse (DSA_TEST_DB=1)."""

import io
import json

import psycopg
import pytest

from dbt_sql_agent import db
from dbt_sql_agent.agent import Agent
from dbt_sql_agent.mcp_server import Server, serve


@pytest.fixture(scope="module", autouse=True)
def role(settings, catalog):
    db.setup_role(settings.admin_dsn, catalog, settings.agent_role, settings.agent_password)


def test_catalog_from_manifest(catalog):
    assert set(catalog.models) == {"marts.dim_customers", "marts.dim_products", "marts.dim_sales_reps",
                                   "marts.fct_order_lines", "marts.fct_orders", "marts.fct_payments"}
    assert catalog.blocked_column_names == {"contact_name", "contact_email", "contact_phone", "full_name", "email",
                                            "annual_salary"}
    assert catalog.models["marts.fct_orders"].columns["net_revenue"].data_type == "numeric"


@pytest.mark.parametrize("sql", [
    "select contact_email from marts.dim_customers",
    "select * from marts.dim_customers",
    "select c from marts.dim_customers c",
    "select row_to_json(c) from marts.dim_customers c",
    "select annual_salary from marts.dim_sales_reps",
    "select contact_email from staging.stg_customers",
    "select contact_email from raw.raw_customers",
    "select question from agent_audit.query_log",
    "select pg_read_file('/etc/passwd')",
])
def test_grants_block_what_the_guard_blocks(settings, sql):
    """Second line of defence: the agent role cannot read these even if the guard had a bug."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.run_readonly(settings.agent_dsn, sql, max_cost=1e12)


def test_agent_role_is_read_only(settings):
    with psycopg.connect(settings.agent_dsn) as conn:
        with pytest.raises((psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)):
            conn.execute("update marts.fct_orders set status = 'open' where order_id = 1")


def test_cost_limit(settings):
    sql = "select a.order_id from marts.fct_orders a cross join marts.fct_orders b"
    with pytest.raises(db.CostLimitError):
        db.run_readonly(settings.agent_dsn, sql, max_cost=200000)


def test_audit_log_is_append_only(settings):
    a = db.Audit(settings.admin_dsn)
    a.write(principal="test", question="q", decision="executed", row_count=1)
    assert a.tail(1)[0]["principal"] == "test"
    with psycopg.connect(settings.admin_dsn, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("delete from agent_audit.query_log")
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("update agent_audit.query_log set decision = 'executed'")


class ScriptedLLM:
    """Stands in for `claude -p`: returns prepared outputs in order and records the prompts."""
    model = "scripted"

    def __init__(self, outputs):
        self.outputs, self.prompts = list(outputs), []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        return {"output": self.outputs.pop(0), "cost_usd": 0.001, "duration_ms": 10}


def test_agent_repairs_after_guard_rejection(settings, catalog):
    llm = ScriptedLLM([
        {"answerable": True, "sql": "select * from marts.fct_orders", "explanation": "first try"},
        {"answerable": True, "sql": "select count(*) as n from marts.fct_orders where status = 'open'", "explanation": "ok"},
    ])
    agent = Agent(catalog, llm, settings.agent_dsn, db.Audit(settings.admin_dsn), principal="test-repair")
    ans = agent.ask("How many orders are open?")
    assert ans.status == "executed" and ans.turns == 2 and ans.guard_codes == ["star"]
    assert ans.rows == [(100,)]
    assert "SELECT * is not allowed" in llm.prompts[1]
    log = [r for r in db.Audit(settings.admin_dsn).tail(5) if r["principal"] == "test-repair"]
    assert [r["decision"] for r in reversed(log)] == ["rejected_guard", "executed"]


def test_agent_blocked_column_never_reaches_db(settings, catalog):
    bad = {"answerable": True, "sql": "select contact_email from marts.dim_customers", "explanation": ""}
    agent = Agent(catalog, ScriptedLLM([bad, bad]), settings.agent_dsn, db.Audit(None))
    ans = agent.ask("emails?")
    assert ans.status == "rejected_guard" and ans.rows == [] and ans.guard_codes == ["blocked_column"] * 2


def test_agent_db_error_goes_back_to_model(settings, catalog):
    llm = ScriptedLLM([
        {"answerable": True, "sql": "select revenue from marts.fct_orders", "explanation": ""},
        {"answerable": True, "sql": "select round(sum(net_revenue), 2) from marts.fct_orders where is_revenue", "explanation": ""},
    ])
    ans = Agent(catalog, llm, settings.agent_dsn, db.Audit(None)).ask("total revenue")
    assert ans.status == "executed" and ans.turns == 2
    assert 'column "revenue" does not exist' in llm.prompts[1]


def test_mcp_server_roundtrip(settings, catalog):
    server = Server(catalog, settings.agent_dsn, db.Audit(settings.admin_dsn))
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "run_query", "arguments": {"sql": "select status, count(*) as n from marts.fct_orders group by 1 order by 1"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "run_query", "arguments": {"sql": "select contact_email from marts.dim_customers"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "describe_warehouse", "arguments": {}}},
    ]
    out = io.StringIO()
    serve(server, io.StringIO("\n".join(json.dumps(r) for r in reqs) + "\n"), out)
    resp = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["id"] for r in resp] == [1, 2, 3, 4, 5]
    assert resp[0]["result"]["serverInfo"]["name"] == "dbt-sql-agent"
    assert {t["name"] for t in resp[1]["result"]["tools"]} == {"describe_warehouse", "run_query"}
    body = json.loads(resp[2]["result"]["content"][0]["text"])
    assert body["columns"] == ["status", "n"] and ["open", 100] in body["rows"]
    assert resp[3]["result"]["isError"] and "blocked_column" in resp[3]["result"]["content"][0]["text"]
    assert "contact_email: NOT AVAILABLE (pii)" in resp[4]["result"]["content"][0]["text"]
