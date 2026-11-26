"""Read the dbt manifest and derive what the agent may see.

The dbt project is the single source of truth: a model is visible when its meta has
`agent_access: true`; a column is blocked when its meta has `pii: true` or
`sensitivity: restricted`. The same catalog produces the prompt context, the SQL guard's allow list
and the PostgreSQL column grants, so the three cannot drift apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Column:
    name: str
    description: str = ""
    data_type: str | None = None
    blocked_reason: str | None = None  # "pii" or "restricted"


@dataclass
class Model:
    name: str
    schema: str
    description: str = ""
    columns: dict[str, Column] = field(default_factory=dict)

    @property
    def relation(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def allowed_columns(self) -> list[str]:
        return [c.name for c in self.columns.values() if not c.blocked_reason]

    @property
    def blocked_columns(self) -> list[str]:
        return [c.name for c in self.columns.values() if c.blocked_reason]


def _blocked(meta: dict) -> str | None:
    if meta.get("pii") is True:
        return "pii"
    if str(meta.get("sensitivity", "")).lower() in ("restricted", "confidential"):
        return "restricted"
    return None


@dataclass
class Catalog:
    models: dict[str, Model]

    @classmethod
    def from_manifest(cls, path: str | Path, column_types: dict[str, dict[str, str]] | None = None) -> "Catalog":
        """Load target/manifest.json. column_types maps relation -> column -> type (from the database)."""
        man = json.loads(Path(path).read_text())
        models: dict[str, Model] = {}
        for node in man["nodes"].values():
            if node.get("resource_type") != "model":
                continue
            meta = {**(node.get("config", {}).get("meta") or {}), **(node.get("meta") or {})}
            if meta.get("agent_access") is not True:
                continue
            m = Model(name=node.get("alias") or node["name"], schema=node["schema"],
                      description=" ".join((node.get("description") or "").split()))
            types = (column_types or {}).get(m.relation, {})
            for cname, col in (node.get("columns") or {}).items():
                cmeta = {**(col.get("config", {}).get("meta") or {}), **(col.get("meta") or {})}
                m.columns[cname] = Column(name=cname, description=" ".join((col.get("description") or "").split()),
                                          data_type=types.get(cname) or col.get("data_type"),
                                          blocked_reason=_blocked(cmeta))
            for cname, t in types.items():  # columns in the table but not documented: visible, no description
                m.columns.setdefault(cname, Column(name=cname, data_type=t))
            models[m.relation] = m
        return cls(models)

    @property
    def blocked_column_names(self) -> set[str]:
        return {c for m in self.models.values() for c in m.blocked_columns}

    def resolve(self, schema: str | None, name: str) -> Model | None:
        if schema:
            return self.models.get(f"{schema}.{name}")
        hits = [m for m in self.models.values() if m.name == name]
        return hits[0] if len(hits) == 1 else None

    def context(self, with_docs: bool = True) -> str:
        """Schema description for the prompt. Blocked columns are listed as not available."""
        out = []
        for m in sorted(self.models.values(), key=lambda m: m.relation):
            out.append(f"table {m.relation}")
            if with_docs and m.description:
                out.append(f"  -- {m.description}")
            for c in m.columns.values():
                if c.blocked_reason:
                    if with_docs:
                        out.append(f"  {c.name}: NOT AVAILABLE ({c.blocked_reason})")
                    continue
                line = f"  {c.name} {c.data_type or ''}".rstrip()
                if with_docs and c.description:
                    line += f"  -- {c.description}"
                out.append(line)
        return "\n".join(out)

    def grants_sql(self, role: str) -> list[str]:
        """Column-level grants for the agent's database role (second line of defence behind the guard)."""
        schemas = sorted({m.schema for m in self.models.values()})
        q = _ident
        stmts = [f"REVOKE ALL ON ALL TABLES IN SCHEMA {q(s)} FROM {q(role)}" for s in schemas]
        stmts += [f"GRANT USAGE ON SCHEMA {q(s)} TO {q(role)}" for s in schemas]
        for m in sorted(self.models.values(), key=lambda m: m.relation):
            cols = ", ".join(q(c) for c in m.allowed_columns)
            stmts.append(f"GRANT SELECT ({cols}) ON {q(m.schema)}.{q(m.name)} TO {q(role)}")
        return stmts


def _ident(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'
