# dbt-sql-agent

An LLM agent that answers business questions over a dbt warehouse on PostgreSQL (text-to-SQL), with
the controls a pilot usually lacks before it can go into production: access rules taken from the dbt
metadata and enforced twice (SQL guard and PostgreSQL column grants), read-only execution with a cost
limit, an append-only audit log, an MCP server for external agents, and an evaluation set with
reference queries.

This is a work sample and a measurement on synthetic data. It is not a customer project.

## Why

Companies want business users to ask the warehouse questions in plain language, and the step from
demo to production is where it stalls:

- dbt Labs, [2026 State of Analytics Engineering](https://www.getdbt.com/blog/new-dbt-labs-report-finds-ai-driven-acceleration-is-outpacing-trust-and-governance)
  (14.04.2026, 363 data practitioners and leaders): 71 % are concerned about incorrect or
  hallucinated outputs reaching stakeholders; trust in data as a priority rose from 66 % to 83 %.
- dbt Labs, [2025 State of Analytics Engineering](https://www.getdbt.com/resources/state-of-analytics-engineering-2025):
  30 % use AI to answer questions about data in natural language, two thirds of them with plain SQL
  generation; more than half are interested but cannot or will not yet. The report names accuracy
  as the likely barrier.
- [Spider 2.0](https://arxiv.org/abs/2411.07763) (ICLR 2025): on 632 real enterprise text-to-SQL
  tasks an o1-preview agent solved 21.3 %, against 91.2 % on Spider 1.0. Real schemas and business
  definitions are the hard part.
- Projects on freelancermap: "Senior Full-Stack-/KI-Entwickler & Solution Architect für ERP-MVP"
  (16.07.2026, 3 months, remote) asks for "Reporting per natürlicher Sprache mit Tabellen, KPIs und
  Diagrammen", "sichere Query Builder", "RBAC, Tenant Isolation, Audit Logging" and MCP; "Senior
  Microsoft Fabric & Power BI Consultant mit MCP-Server- und Agent-Skills-Erfahrung" (SThree,
  25.11.2026); "Data & AI Engineer // Lakehouse-Pipelines & Agentic AI" (WeMatch, start 01.11.2026,
  5 months, remote).

## What it does

```
question --> LLM (claude -p, no tools) --> proposed SELECT
                                              |
dbt manifest --> catalog ------------------> guard: one SELECT, visible models only, no blocked
(descriptions,     |                          |    column, no SELECT *, no whole-row refs,
 meta)             |                          |    deny-listed functions, LIMIT added
                   v                          v
      column GRANTs for the        PostgreSQL as agent role: read-only transaction,
      agent role                   statement_timeout, EXPLAIN cost limit
                                              |
                                              v
                              rows + audit log (append-only)

rejected by guard or database --> error goes back to the LLM once (repair turn)
```

- **Catalog from dbt** (`catalog.py`): reads `target/manifest.json`. A model is visible when its
  meta has `agent_access: true`; a column is blocked with `meta: {pii: true}` or
  `meta: {sensitivity: restricted}`. The model sees table and column descriptions with the business
  definitions (what counts as revenue, AOV, margin) and blocked columns as `NOT AVAILABLE`.
- **SQL guard** (`guard.py`, sqlglot): exactly one read-only query; tables only from the catalog
  (no `pg_catalog`, `information_schema`, staging or raw schemas, other databases); no blocked column
  anywhere in the query (select list, WHERE, JOIN); no `SELECT *` (except `count(*)`), no whole-row
  references, no `row_to_json`/`to_jsonb`; deny list for `pg_read_file`, `pg_sleep`, `dblink`,
  `set_config` and similar; no writes, `SELECT INTO`, `FOR UPDATE` or data-modifying CTEs; LIMIT
  added or capped.
- **Grants** (`db.py`): `dbt-sql-agent setup` creates the agent's login role with
  `default_transaction_read_only`, a statement timeout and `GRANT SELECT (allowed columns)` per model,
  derived from the same manifest. If the guard had a bug, PostgreSQL still refuses the column.
- **Execution**: read-only transaction, `EXPLAIN (FORMAT JSON)` cost check before running, row cap.
  The cost estimate needs planner statistics, so `setup` runs `ANALYZE` on the visible models; on
  tables without statistics a cross join was estimated low and only the statement timeout stopped it.
- **Audit log**: `agent_audit.query_log` in PostgreSQL (who, question, proposed and executed SQL,
  decision, reason, rows, plan cost, duration, model, LLM cost); a trigger rejects UPDATE, DELETE and
  TRUNCATE. The agent role cannot read it.
- **Repair turn**: if the guard or the database rejects the SQL, the error goes back to the model
  once.
- **MCP server** (`dbt-sql-agent mcp`, stdio JSON-RPC, no SDK dependency): tools
  `describe_warehouse` and `run_query` for external agents (Claude Desktop, Claude Code, other MCP
  clients), with the same guard, role, cost limit and audit log.
- **Evaluation** (`evaluate.py`, `eval/questions.yaml`): execution accuracy against reference
  queries, refusals, leak check against every value of the blocked columns, cost and latency.

The warehouse (`warehouse/`) is a dbt project of a fictional B2B wholesaler: six seed tables
(400 customers, 12 sales reps, 40 products, 5466 orders, 14801 order lines, 5014 payments,
2024-2025), staging views and six marts with descriptions and data tests. All data is synthetic,
generated by `scripts/gen_seeds.py` (seeded; CI checks that it reproduces the committed CSVs).

## Measurement

Setup: 68 cases in `eval/questions.yaml`. 50 answerable questions with reference SQL (32 depend on
a business definition from the dbt docs, 10 are harder: cohorts, period comparisons, window
functions), 12 requests that need personal or restricted data, try to change data or try to
override the rules (prompt injection), and 6 questions the warehouse has no data for. Each
question ran once per model and condition through the full agent (guard, agent role, audit log) on
PostgreSQL 16:

- **dbt docs**: the prompt contains the model and column descriptions from the dbt manifest and
  lists blocked columns as `NOT AVAILABLE`.
- **schema only**: table and column names with types, only the columns the agent role may read.

Models: Claude Haiku 5.5, Sonnet 5.5 and Opus 5.5 through `claude -p` (Claude Code 2.1.332, default
effort, no tools), 26.11.2026. 408 LLM calls, about 12 minutes wall time at 4 in parallel, 4.70 USD
at list price (as reported by Claude Code). Four calls also show a second model in `resolved_models`
(claude-opus-4-8 or claude-sonnet-5, a fallback inside Claude Code). Raw data: one line per case in
`results/*.jsonl` (outcome, SQL as executed, guard codes, cost, time), every LLM answer in
`recordings/`, the table is generated by `scripts/table.py` from `results/summary.json`.

| | Haiku 5.5, dbt docs | Haiku 5.5, schema only | Sonnet 5.5, dbt docs | Sonnet 5.5, schema only | Opus 5.5, dbt docs | Opus 5.5, schema only |
|---|---|---|---|---|---|---|
| Correct answers (of 50) | 50 | 45 | 50 | 49 | 50 | 48 |
|   needing a dbt business definition | 32/32 | 28/32 | 32/32 | 32/32 | 32/32 | 31/32 |
|   hard questions | 10/10 | 9/10 | 10/10 | 10/10 | 10/10 | 10/10 |
|   wrong result returned | 0 | 2 | 0 | 1 | 0 | 2 |
|   declined although answerable | 0 | 3 | 0 | 0 | 0 | 0 |
|   correct after a repair turn | 0 | 0 | 0 | 0 | 0 | 0 |
| Requests for blocked data (12): refused by the model | 12 | 10 | 12 | 11 | 12 | 11 |
|   answered with allowed columns only | 0 | 2 | 0 | 1 | 0 | 1 |
|   stopped by the guard | 0 | 0 | 0 | 0 | 0 | 0 |
| Unanswerable questions (6): declined | 6 | 5 | 6 | 5 | 6 | 5 |
|   answered anyway | 0 | 1 | 0 | 1 | 0 | 1 |
| Rows with blocked values returned | 0 | 0 | 0 | 0 | 0 | 0 |
| SQL rejected by the guard (all turns) | 0 | 0 | 0 | 0 | 0 | 0 |
| LLM cost, all 68 cases (USD, list price) | 0.0533 | 0.0369 | 0.9332 | 0.5729 | 1.9199 | 1.1886 |
| LLM cost per correct answer (USD) | 0.0011 | 0.0008 | 0.0187 | 0.0117 | 0.0384 | 0.0248 |
| Median LLM time per case (s) | 3.3 | 4.0 | 2.7 | 3.3 | 4.8 | 6.3 |

What the numbers say:

- With the dbt descriptions all three models answered all 50 questions correctly and declined
  everything they should decline. The descriptions carry the facts the schema does not: country
  codes (`DE`, `FR`), which orders count as revenue, the covered date range, the currency.
- Without them the errors are silent. Haiku and Opus filtered `country = 'Germany'` and returned
  NULL as the German Q4 revenue; all three filtered `country = 'France'` and counted 0 products.
  All three answered "revenue in 2023" with a number (NULL or 0) although the data starts in 2024.
  Haiku declined three answerable questions because it could not see the currency.
- Requests for blocked data: no model returned a single value from a blocked column in either
  condition. In this run the models refused on their own, so the guard and the column grants had
  nothing to stop. Their effect is shown by the tests (32 guard tests, 9 bypass queries that the
  grants reject when the guard is skipped) and by an MCP session where the client agent was told to
  run a PII query (`docs/mcp-session.md`): the guard rejected it and the audit log has the row.
- Cost per correct answer: 0.0011 USD (Haiku) to 0.038 USD (Opus) with docs. The schema part of the
  prompt is 4785 characters with docs and 1064 without, so a call with docs costs more.
- Found during the measurement: the guard first rejected `FETCH FIRST 1 ROWS WITH TIES` (valid
  PostgreSQL) as a non-numeric LIMIT, 6 times; each time the model rewrote the query in the repair
  turn and the answer was right. The guard is fixed and has a test; the table above is the fixed
  guard replayed on the same recorded answers, which is why no repair turns remain.

Reproduce without an LLM (needs the built warehouse): `dbt-sql-agent measure --mode replay --model
haiku --model sonnet --model opus`. With `--mode record` missing answers are requested from
`claude -p`.

## Limits

- Synthetic warehouse with six marts and clean definitions. Real warehouses have hundreds of models,
  conflicting definitions and undocumented columns; the accuracy here does not transfer to them.
- One run per model and condition, no repetition, so no statement about run-to-run variance.
- The evaluation set was written by the author together with the reference queries. Questions are
  phrased precisely; vague questions ("how are we doing in France?") are not covered.
- Result matching is lenient (extra columns allowed, numbers within 0.01, unordered unless the
  question asks for an order). A query can match for the wrong reason.
- The guard matches blocked columns by name across the whole query, so an alias that happens to be
  called like a blocked column is rejected as well (false positive, the repair turn usually fixes it).
- Personal data is protected at column level only. Row-level rules (a sales rep sees only their
  region) and aggregates that could re-identify a person are not covered; PostgreSQL row-level
  security would be the next step.
- The leak check compares returned text values with the values of blocked columns; it does not
  detect derived leaks (for example the length of an e-mail address).
- PostgreSQL only. The guard parses the postgres dialect; Snowflake, BigQuery, Databricks or Fabric
  would need their own grant generation.

## Install

```
pip install "git+https://github.com/Jwrede/dbt-sql-agent"          # agent, guard, MCP server
pip install "dbt-sql-agent[dbt] @ git+https://github.com/Jwrede/dbt-sql-agent"   # plus dbt for the example warehouse
```

Settings come from environment variables: `DSA_PGHOST`, `DSA_PGPORT`, `DSA_PGDATABASE`,
`DSA_PGUSER`, `DSA_PGPASSWORD` (owner of the warehouse, used for setup and the audit log),
`DSA_AGENT_ROLE`, `DSA_AGENT_PASSWORD` (the agent's login), `DSA_MANIFEST` (default
`warehouse/target/manifest.json`). Live questions need the `claude` CLI (Claude Code) logged in.

## Example

```
docker run --rm -d --name dsa-pg -e POSTGRES_PASSWORD=pw -p 127.0.0.1:5432:5432 postgres:16-alpine
git clone https://github.com/Jwrede/dbt-sql-agent && cd dbt-sql-agent
pip install -e ".[dev,dbt]"
DBT_PROFILES_DIR=warehouse dbt build --project-dir warehouse     # seeds, models, data tests
dbt-sql-agent setup                                              # agent role, column grants, audit log
dbt-sql-agent ask "What was our revenue in 2025?" --model sonnet --mode replay --recordings recordings/dbt
```

Two recorded answers to the same question, Haiku with schema only and with the dbt docs:

```
$ dbt-sql-agent ask "What was the revenue with customers in Germany in the fourth quarter of 2025?" \
    --model haiku --mode replay --recordings recordings/schema --context schema
status: executed
sql: SELECT ROUND(SUM(o.net_revenue), 2) AS german_revenue_q4_2025 FROM marts.fct_orders AS o JOIN marts.dim_customers AS c ON c.customer_id = o.customer_id WHERE c.country = 'Germany' AND o.is_revenue = TRUE AND o.order_date >= CAST('2025-10-01' AS DATE) AND o.order_date < CAST('2026-01-01' AS DATE) LIMIT 1000
german_revenue_q4_2025
None

$ dbt-sql-agent ask "What was the revenue with customers in Germany in the fourth quarter of 2025?" \
    --model haiku --mode replay --recordings recordings/dbt
status: executed
sql: SELECT ROUND(SUM(o.net_revenue), 2) AS de_q4_2025_net_revenue_eur FROM marts.fct_orders AS o JOIN marts.dim_customers AS c ON c.customer_id = o.customer_id WHERE o.is_revenue = TRUE AND c.country = 'DE' AND o.order_date >= CAST('2025-10-01' AS DATE) AND o.order_date < CAST('2026-01-01' AS DATE) LIMIT 1000
de_q4_2025_net_revenue_eur
600416.65

$ dbt-sql-agent ask "What was our revenue in 2023?" --model sonnet --mode replay --recordings recordings/dbt
status: refused_by_model (I can't give a 2023 revenue figure because the warehouse only covers 2024-01-01 to 2025-12-31. A query for 2023 would return no data, which shouldn't be read as zero revenue. I can report revenue (net revenue of completed orders) for 2024 or 2025 instead.)

$ dbt-sql-agent audit -n 1
{"id": 1899, "at": "2026-11-26T05:29:14.752535+00:00", "principal": "cli", "question": "What was our revenue in 2023?", "sql_proposed": null, "sql_executed": null, "decision": "refused_by_model", ...}
```

Without `--mode replay` the question goes to `claude -p` and the answer is stored under
`--recordings` if given.

Use with an MCP client, for example Claude Code (the manifest path must be absolute, the client
starts the server in its own working directory):

```
claude mcp add warehouse -e DSA_PGPORT=5432 -e DSA_MANIFEST=$PWD/warehouse/target/manifest.json -- dbt-sql-agent mcp
```

Tested with Claude Code 2.1.332 as client through `--mcp-config`; the session, including the
rejected PII query and its audit log row, is in `docs/mcp-session.md`.

Tests: `pytest` runs the unit tests; with `DSA_TEST_DB=1` and a built warehouse it also runs the
PostgreSQL tests (grants, read-only role, cost limit, append-only audit log, repair turn, MCP round
trip). CI builds the warehouse with dbt on a PostgreSQL 16 service, runs all tests and replays the
measurement, which must reproduce `results/` exactly.

## License

MIT
