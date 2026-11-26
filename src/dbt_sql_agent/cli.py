"""Command line: setup, ask, measure, mcp, audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, evaluate
from .agent import LLM, Agent
from .catalog import Catalog
from .config import Settings


def load_catalog(s: Settings) -> Catalog:
    types = db.column_types(s.admin_dsn)
    return Catalog.from_manifest(s.manifest, types)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dbt-sql-agent", description="Guarded question answering over a dbt warehouse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="create the agent role, column grants and the audit log from the dbt manifest")
    sub.add_parser("grants", help="print the grants derived from the dbt manifest")
    sub.add_parser("context", help="print the schema context the model receives")
    a = sub.add_parser("ask", help="answer one question")
    a.add_argument("question")
    a.add_argument("--model", default="sonnet")
    a.add_argument("--mode", choices=["live", "record", "replay"], default="live")
    a.add_argument("--recordings", default=None, help="recordings directory, for example recordings/dbt")
    a.add_argument("--context", choices=["dbt", "schema"], default="dbt", help="dbt docs in the prompt, or schema only")
    m = sub.add_parser("measure", help="run the evaluation set")
    m.add_argument("--model", action="append", required=True)
    m.add_argument("--context", action="append", choices=["dbt", "schema"], default=None)
    m.add_argument("--mode", choices=["record", "replay"], default="replay")
    m.add_argument("--questions", default="eval/questions.yaml")
    m.add_argument("--recordings", default="recordings")
    m.add_argument("--out", default="results")
    m.add_argument("--parallel", type=int, default=4)
    m.add_argument("--prune", action="store_true", help="delete recordings the question set no longer uses")
    sub.add_parser("mcp", help="serve the warehouse as MCP tools on stdio")
    qy = sub.add_parser("query", help="run one SQL query through the guard, the agent role and the audit log (no LLM)")
    qy.add_argument("sql")
    qy.add_argument("--max-rows", type=int, default=20)
    t = sub.add_parser("audit", help="show the newest audit log entries")
    t.add_argument("-n", type=int, default=10)
    t.add_argument("--short", action="store_true", help="one compact line per entry")
    args = ap.parse_args(argv)
    s = Settings.from_env()

    if args.cmd == "grants":
        print(";\n".join(load_catalog(s).grants_sql(s.agent_role)) + ";")
        return 0
    if args.cmd == "context":
        print(load_catalog(s).context(with_docs=True))
        return 0
    if args.cmd == "setup":
        for stmt in db.setup_role(s.admin_dsn, load_catalog(s), s.agent_role, s.agent_password):
            print(stmt)
        return 0
    if args.cmd == "audit":
        for row in reversed(db.Audit(s.admin_dsn).tail(args.n)):
            if args.short:
                what = row["question"] or row["sql_proposed"] or ""
                print(f"{row['id']:>5}  {row['at'][:19].replace('T', ' ')}  {row['principal']:<8} {row['decision']:<16} "
                      f"{' '.join(what.split())[:56]}")
            else:
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.cmd == "query":
        from .mcp_server import Server
        out = Server(load_catalog(s), s.agent_dsn, db.Audit(s.admin_dsn), principal="cli").call(
            "run_query", {"sql": args.sql, "max_rows": args.max_rows})
        text = out["content"][0]["text"]
        if out["isError"]:
            print(text)
            return 1
        body = json.loads(text)
        print(" | ".join(body["columns"]))
        for r in body["rows"]:
            print(" | ".join(str(v) for v in r))
        return 0
    if args.cmd == "mcp":
        from .mcp_server import Server, serve
        serve(Server(load_catalog(s), s.agent_dsn, db.Audit(s.admin_dsn)))
        return 0
    if args.cmd == "ask":
        mode = "record" if args.mode == "live" else args.mode
        llm = LLM(args.model, args.recordings, mode=mode)
        agent = Agent(load_catalog(s), llm, s.agent_dsn, db.Audit(s.admin_dsn), with_docs=(args.context == "dbt"),
                      principal="cli")
        ans = agent.ask(args.question)
        print(f"status: {ans.status}" + (f" ({ans.reason})" if ans.reason else ""))
        if ans.sql:
            print(f"sql: {ans.sql}")
        if ans.explanation:
            print(f"explanation: {ans.explanation}")
        if ans.columns:
            print(" | ".join(ans.columns))
            for r in ans.rows[:20]:
                print(" | ".join(str(db.to_jsonable(v)) for v in r))
            if len(ans.rows) > 20:
                print(f"... {len(ans.rows)} rows")
        return 0 if ans.status in ("executed", "refused_by_model") else 1
    if args.cmd == "measure":
        catalog = load_catalog(s)
        questions = evaluate.load_questions(args.questions)
        summary = {}
        used: set[Path] = set()
        for model in args.model:
            for ctx in args.context or ["dbt", "schema"]:
                llm = LLM(model, Path(args.recordings) / ctx, mode=args.mode)
                agent = Agent(catalog, llm, s.agent_dsn, db.Audit(s.admin_dsn), with_docs=(ctx == "dbt"),
                              principal=f"measure:{model}:{ctx}")
                res = evaluate.evaluate(agent, questions, s.admin_dsn, args.parallel)
                used |= llm.used
                name = f"{model}-{ctx}"
                evaluate.write_results(args.out, name, res)
                summary[name] = evaluate.summarize(res)
                print(name, json.dumps(summary[name]), file=sys.stderr)
        if args.prune:
            for model in args.model:
                for ctx in args.context or ["dbt", "schema"]:
                    for f in (Path(args.recordings) / ctx / model).glob("*.json"):
                        if f not in used:
                            f.unlink()
                            print(f"pruned {f}", file=sys.stderr)
        Path(args.out, "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
