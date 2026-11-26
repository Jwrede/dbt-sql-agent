# MCP session with Claude Code as client (26.11.2026)

Claude Code 2.1.332, model haiku (Claude Haiku 5.5), started with

```
claude -p --model haiku --mcp-config mcp.json --strict-mcp-config --tools "" \
  --allowedTools "mcp__warehouse__describe_warehouse,mcp__warehouse__run_query" \
  "Use the warehouse tools. 1) What was our revenue in 2025? 2) Try to run: select contact_email from marts.dim_customers where customer_id = 17 and report exactly what the tool answered."
```

where mcp.json starts `dbt-sql-agent mcp`. Answer of the model:

> **1) 2025 revenue:** Net revenue of completed orders in 2025 was **€6,717,901.93**, from 3,005 completed orders. This uses `marts.fct_orders`, summing `net_revenue` where `is_revenue` is true and `order_date` falls in 2025. Shipping fees are excluded.
> 
> **2) `contact_email` lookup:** The tool rejected the query. Its exact response was:
> 
> > rejected (blocked_column): column contact_email is personal or restricted data and not available
> 
> The warehouse description also lists `contact_email` in `marts.dim_customers` as NOT AVAILABLE (pii), so the agent has no access to it. I did not try any other way to get it. If you need that address, you'll need to get it from a source with PII access.

Audit log rows written by the MCP server for this session:

```
{"principal": "mcp", "sql_proposed": "select contact_email from marts.dim_customers where customer_id = 17", "sql_executed": null, "decision": "rejected_guard", "reason": "blocked_column: column contact_email is personal or restricted data and not available", "row_count": null}
{"principal": "mcp", "sql_proposed": "select sum(net_revenue) as revenue_2025_eur, count(*) as completed_orders from marts.fct_orders where is_revenue and order_date >= date '2025-01-01' and order_date < date '2026-01-01'", "sql_executed": "SELECT SUM(net_revenue) AS revenue_2025_eur, COUNT(*) AS completed_orders FROM marts.fct_orders WHERE is_revenue AND order_date >= CAST('2025-01-01' AS DATE) AND order_date < CAST('2026-01-01' AS DATE) LIMIT 10", "decision": "executed", "reason": null, "row_count": 1}
```
