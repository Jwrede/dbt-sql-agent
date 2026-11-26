"""PostgreSQL side: agent role with column grants, read-only execution with cost limit, audit log."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import time
from dataclasses import dataclass

import psycopg

from .catalog import Catalog, _ident

AUDIT_DDL = """
CREATE SCHEMA IF NOT EXISTS agent_audit;
CREATE TABLE IF NOT EXISTS agent_audit.query_log (
    id            bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    principal     text NOT NULL,
    question      text,
    sql_proposed  text,
    sql_executed  text,
    decision      text NOT NULL CHECK (decision IN ('executed', 'rejected_guard', 'rejected_cost',
                                                    'db_error', 'refused_by_model', 'llm_error')),
    reason        text,
    row_count     integer,
    explain_cost  double precision,
    duration_ms   integer,
    model         text,
    llm_cost_usd  double precision
);
CREATE OR REPLACE FUNCTION agent_audit.append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'agent_audit.query_log is append-only';
END $$;
DROP TRIGGER IF EXISTS query_log_append_only ON agent_audit.query_log;
CREATE TRIGGER query_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON agent_audit.query_log
    FOR EACH STATEMENT EXECUTE FUNCTION agent_audit.append_only();
"""


def setup_role(admin_dsn: str, catalog: Catalog, role: str, password: str) -> list[str]:
    """Create or reset the agent's login role: read-only by default, column grants from the catalog."""
    q = _ident
    stmts = []
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            conn.execute(f"CREATE ROLE {q(role)} LOGIN PASSWORD %s".replace("%s", _lit(password)))
        stmts += [f"ALTER ROLE {q(role)} SET default_transaction_read_only = on",
                  f"ALTER ROLE {q(role)} SET statement_timeout = '10s'",
                  f"REVOKE ALL ON SCHEMA public FROM {q(role)}",
                  f"REVOKE ALL ON SCHEMA agent_audit FROM {q(role)}"]
        stmts += catalog.grants_sql(role)
        conn.execute(AUDIT_DDL)
        # The cost limit relies on planner statistics; tables freshly built by dbt have none yet.
        stmts += [f"ANALYZE {q(m.schema)}.{q(m.name)}" for m in catalog.models.values()]
        for s in stmts:
            conn.execute(s)
    return stmts


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def column_types(dsn: str, catalog_relations: list[str] | None = None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY ordinal_position").fetchall()
    for s, t, c, ty in rows:
        rel = f"{s}.{t}"
        if catalog_relations is None or rel in catalog_relations:
            out.setdefault(rel, {})[c] = ty
    return out


class CostLimitError(Exception):
    pass


@dataclass
class Result:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    explain_cost: float
    duration_ms: int


def run_readonly(dsn: str, sql: str, max_rows: int = 1000, max_cost: float = 200000.0,
                 timeout_ms: int = 10000) -> Result:
    """Run one SELECT as the agent role in a read-only transaction, after an EXPLAIN cost check."""
    t0 = time.monotonic()
    with psycopg.connect(dsn) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        plan = conn.execute("EXPLAIN (FORMAT JSON) " + sql).fetchone()[0]
        cost = float(plan[0]["Plan"]["Total Cost"])
        if cost > max_cost:
            raise CostLimitError(f"estimated cost {cost:.0f} exceeds the limit {max_cost:.0f}")
        cur = conn.execute(sql)
        cols = [d.name for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
        conn.rollback()
    return Result(cols, [tuple(r) for r in rows[:max_rows]], len(rows) > max_rows, cost,
                  int((time.monotonic() - t0) * 1000))


def to_jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


class Audit:
    def __init__(self, dsn: str | None):
        self.dsn = dsn

    def write(self, **fields) -> None:
        if not self.dsn:
            return
        cols = ", ".join(fields)
        ph = ", ".join(["%s"] * len(fields))
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(f"INSERT INTO agent_audit.query_log ({cols}) VALUES ({ph})", list(fields.values()))

    def tail(self, n: int = 20) -> list[dict]:
        with psycopg.connect(self.dsn) as conn:
            cur = conn.execute("SELECT * FROM agent_audit.query_log ORDER BY id DESC LIMIT %s", (n,))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, map(to_jsonable, r))) for r in cur.fetchall()]


def dumps(rows) -> str:
    return json.dumps(rows, default=to_jsonable, ensure_ascii=False)
