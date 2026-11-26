"""Static checks on the SQL the agent wants to run, before it reaches the database.

The guard is the first line of defence; the column grants of the agent role are the second. It
rejects anything that is not a single read-only SELECT over the visible dbt models, any reference to
a blocked column, star selects and whole-row references (which would expose blocked columns), and a
deny list of functions that read files, sleep, open connections or change settings. It adds a
LIMIT when the query has none.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from .catalog import Catalog

DENY_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "pg_sleep", "pg_sleep_for",
    "pg_sleep_until", "dblink", "dblink_exec", "lo_import", "lo_export", "lo_get", "set_config",
    "current_setting", "pg_terminate_backend", "pg_cancel_backend", "query_to_xml", "table_to_xml",
    "query_to_xml_and_xmlschema", "cursor_to_xml", "pg_advisory_lock", "txid_current", "pg_reload_conf",
    "row_to_json", "to_json", "to_jsonb", "json_populate_record", "hstore",
}
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
                   exp.Command, exp.Into, exp.Copy, exp.Set, exp.Transaction, exp.Grant, exp.Lock)
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema"}


class GuardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Checked:
    sql: str          # SQL as it will run (LIMIT added if missing)
    tables: list[str]


def check(sql: str, catalog: Catalog, max_rows: int = 1000) -> Checked:
    try:
        stmts = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardError("parse", f"SQL does not parse: {str(e).splitlines()[0]}") from None
    if len(stmts) != 1:
        raise GuardError("multiple_statements", "exactly one statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        raise GuardError("not_select", f"only SELECT queries are allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError("not_select", f"{node.key.upper()} is not allowed")
        if isinstance(node, exp.Lock):
            raise GuardError("not_select", "row locks are not allowed")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables, aliases = [], set()
    for t in tree.find_all(exp.Table):
        name, schema = t.name.lower(), (t.db or "").lower() or None
        if not name:
            raise GuardError("table", "table functions are not allowed")
        if schema is None and name in cte_names:
            continue
        if t.catalog:
            raise GuardError("table", f"cross-database reference {t.sql()} is not allowed")
        if schema in SYSTEM_SCHEMAS or name.startswith("pg_"):
            raise GuardError("table", f"system catalog {t.sql()} is not allowed")
        m = catalog.resolve(schema, name)
        if m is None:
            raise GuardError("table", f"table {t.sql()} is not available to the agent")
        tables.append(m.relation)
        aliases.add(t.alias_or_name.lower())
        aliases.add(name)
    if not tables:
        raise GuardError("table", "query reads no table of the warehouse")

    blocked = {c.lower() for c in catalog.blocked_column_names}
    for node in tree.walk():
        if isinstance(node, exp.Star):
            parent = node.parent
            if isinstance(parent, exp.Count):
                continue
            raise GuardError("star", "SELECT * is not allowed; name the columns")
        if isinstance(node, exp.Column):
            if isinstance(node.this, exp.Star):
                raise GuardError("star", f"{node.sql()} is not allowed; name the columns")
            cname = node.name.lower()
            if cname in blocked:
                raise GuardError("blocked_column", f"column {cname} is personal or restricted data and not available")
            if not node.table and cname in aliases and cname not in _all_columns(catalog):
                raise GuardError("whole_row", f"whole-row reference {cname} is not allowed")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if fname in DENY_FUNCTIONS:
                raise GuardError("function", f"function {fname} is not allowed")

    if isinstance(tree, exp.Select) or isinstance(tree, exp.SetOperation):
        lim = tree.args.get("limit")
        if lim is None:
            tree = tree.limit(max_rows)
        else:
            # LIMIT n, or FETCH FIRST n ROWS [ONLY | WITH TIES]
            count = lim.args.get("count") if isinstance(lim, exp.Fetch) else lim.expression
            if not isinstance(count, exp.Literal) or count.is_string:
                raise GuardError("limit", "LIMIT must be a number")
            if isinstance(lim, exp.Fetch) and (lim.args.get("limit_options") or exp.LimitOptions()).args.get("percent"):
                raise GuardError("limit", "FETCH ... PERCENT is not allowed")
            if int(count.name) > max_rows:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return Checked(sql=tree.sql(dialect="postgres"), tables=sorted(set(tables)))


def _all_columns(catalog: Catalog) -> set[str]:
    return {c.lower() for m in catalog.models.values() for c in m.columns}
