"""Settings from environment variables (no secrets in files)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    admin_dsn: str      # owner of the warehouse; used for role setup and the audit log
    agent_dsn: str      # login of the agent role; the only connection that runs agent SQL
    agent_role: str
    agent_password: str
    manifest: str

    @classmethod
    def from_env(cls) -> "Settings":
        host = os.environ.get("DSA_PGHOST", "127.0.0.1")
        port = os.environ.get("DSA_PGPORT", "5432")
        dbname = os.environ.get("DSA_PGDATABASE", "postgres")
        user = os.environ.get("DSA_PGUSER", "postgres")
        pw = os.environ.get("DSA_PGPASSWORD", "pw")
        role = os.environ.get("DSA_AGENT_ROLE", "dsa_agent")
        apw = os.environ.get("DSA_AGENT_PASSWORD", "agent-pw")
        return cls(
            admin_dsn=os.environ.get("DSA_ADMIN_DSN", f"postgresql://{user}:{pw}@{host}:{port}/{dbname}"),
            agent_dsn=os.environ.get("DSA_AGENT_DSN", f"postgresql://{role}:{apw}@{host}:{port}/{dbname}"),
            agent_role=role, agent_password=apw,
            manifest=os.environ.get("DSA_MANIFEST", "warehouse/target/manifest.json"),
        )
