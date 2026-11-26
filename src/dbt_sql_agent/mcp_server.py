"""Minimal MCP server (stdio, JSON-RPC 2.0) that gives an external agent guarded SQL access.

Tools: describe_warehouse (tables, columns and business definitions from the dbt docs; blocked
columns marked) and run_query (one SELECT; same guard, agent role, cost limit and audit log as the
built-in agent). No SDK dependency; implements initialize, tools/list, tools/call and ping.
"""

from __future__ import annotations

import json
import sys

from . import db, guard
from .catalog import Catalog

PROTOCOL_VERSION = "2025-06-18"
TOOLS = [
    {"name": "describe_warehouse",
     "description": "Tables and columns of the data warehouse with business definitions. Columns marked NOT AVAILABLE hold personal or restricted data.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "run_query",
     "description": "Run one read-only PostgreSQL SELECT over the warehouse tables (schema-qualified, no SELECT *). Returns at most max_rows rows as JSON.",
     "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}, "max_rows": {"type": "integer", "minimum": 1, "maximum": 1000}},
                     "required": ["sql"]}},
]


class Server:
    def __init__(self, catalog: Catalog, agent_dsn: str, audit: db.Audit, max_cost: float = 200000.0,
                 principal: str = "mcp"):
        self.catalog, self.agent_dsn, self.audit = catalog, agent_dsn, audit
        self.max_cost, self.principal = max_cost, principal

    def handle(self, msg: dict) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # notification
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "dbt-sql-agent", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self.call(params.get("name"), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
        except Exception as e:  # never crash the server on one bad request
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)[:300]}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, args: dict) -> dict:
        if name == "describe_warehouse":
            return _text(self.catalog.context(with_docs=True))
        if name != "run_query":
            return _text(f"unknown tool {name}", error=True)
        sql = str(args.get("sql", ""))
        max_rows = max(1, min(int(args.get("max_rows", 200)), 1000))
        try:
            checked = guard.check(sql, self.catalog, max_rows)
        except guard.GuardError as e:
            self.audit.write(principal=self.principal, sql_proposed=sql, decision="rejected_guard", reason=f"{e.code}: {e}")
            return _text(f"rejected ({e.code}): {e}", error=True)
        try:
            res = db.run_readonly(self.agent_dsn, checked.sql, max_rows, self.max_cost)
        except db.CostLimitError as e:
            self.audit.write(principal=self.principal, sql_proposed=sql, decision="rejected_cost", reason=str(e))
            return _text(f"rejected (cost): {e}", error=True)
        except Exception as e:
            reason = str(e).splitlines()[0][:300]
            self.audit.write(principal=self.principal, sql_proposed=sql, decision="db_error", reason=reason)
            return _text(f"database error: {reason}", error=True)
        self.audit.write(principal=self.principal, sql_proposed=sql, sql_executed=checked.sql, decision="executed",
                         row_count=len(res.rows), explain_cost=res.explain_cost, duration_ms=res.duration_ms)
        body = {"columns": res.columns, "rows": [[db.to_jsonable(v) for v in r] for r in res.rows],
                "truncated": res.truncated, "sql_executed": checked.sql}
        return _text(json.dumps(body, ensure_ascii=False))


def _text(s: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": s}], "isError": error}


def serve(server: Server, stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = server.handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
