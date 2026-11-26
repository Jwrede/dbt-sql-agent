"""Print the README result table from results/summary.json."""

import json
import sys
from pathlib import Path

s = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "results/summary.json").read_text())
names = [f"{m}-{c}" for m in ("haiku", "sonnet", "opus") for c in ("dbt", "schema") if f"{m}-{c}" in s]
head = {"haiku": "Haiku 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5"}
ctx = {"dbt": "dbt docs", "schema": "schema only"}


def cell(v):
    return str(v)


first = s[names[0]]
n_ans, n_ref, n_una = first["answer_questions"], first["refuse_requests"], first["unanswerable_questions"]
rows = [
    (f"Correct answers (of {n_ans})", lambda r: f"{r['correct']}"),
    ("  needing a dbt business definition", lambda r: r["correct_definition_questions"]),
    ("  hard questions", lambda r: r["correct_hard_questions"]),
    ("  wrong result returned", lambda r: r["answer_outcomes"].get("wrong_result", 0)),
    ("  declined although answerable", lambda r: r["answer_outcomes"].get("refused_by_model", 0)),
    ("  correct after a repair turn", lambda r: r["repaired_after_rejection"]),
    (f"Requests for blocked data ({n_ref}): refused by the model",
     lambda r: r["refuse_outcomes"].get("refused_by_model", 0)),
    ("  answered with allowed columns only", lambda r: r["refuse_outcomes"].get("answered_without_blocked_data", 0)),
    ("  stopped by the guard", lambda r: r["refuse_outcomes"].get("blocked_by_guard", 0)),
    (f"Unanswerable questions ({n_una}): declined", lambda r: r["unanswerable_outcomes"].get("declined", 0)),
    ("  answered anyway", lambda r: r["unanswerable_outcomes"].get("answered_anyway", 0)),
    ("Rows with blocked values returned", lambda r: r["leaks"]),
    ("SQL rejected by the guard (all turns)", lambda r: r["guard_rejections"]),
    (f"LLM cost, all {n_ans + n_ref + n_una} cases (USD, list price)", lambda r: f"{r['llm_cost_usd_total']:.4f}"),
    ("LLM cost per correct answer (USD)", lambda r: f"{r['llm_cost_usd_per_correct']:.4f}"),
    ("Median LLM time per case (s)", lambda r: r["llm_seconds_median"]),
]
print("| | " + " | ".join(f"{head[n.split('-')[0]]}, {ctx[n.split('-')[1]]}" for n in names) + " |")
print("|---|" + "---|" * len(names))
for label, f in rows:
    print(f"| {label} | " + " | ".join(cell(f(s[n])) for n in names) + " |")
