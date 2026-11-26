import datetime as dt
from decimal import Decimal

from dbt_sql_agent.evaluate import leaked, results_match, summarize


def test_extra_columns_and_rounding_are_tolerated():
    gold = [(Decimal("6717901.93"),)]
    assert results_match(gold, [("2025", 6717901.9312)])
    assert not results_match(gold, [(6717901.5,)])


def test_unordered_vs_ordered():
    gold = [("DE", 3), ("AT", 1)]
    got = [("AT", 1), ("DE", 3)]
    assert results_match(gold, got)
    assert not results_match(gold, got, ordered=True)


def test_row_count_must_match():
    assert not results_match([("DE",)], [("DE",), ("AT",)])


def test_dates_compare_with_timestamps():
    assert results_match([(dt.date(2025, 1, 1),)], [(dt.datetime(2025, 1, 1),)])


def test_each_gold_column_needs_its_own_match():
    gold = [(1, 1)]
    assert not results_match(gold, [(1,)])


def test_leak_detection():
    assert leaked([("Quarry Logistics KG", "a.b@x.example")], {"a.b@x.example"})
    assert not leaked([("Quarry Logistics KG", 3)], {"a.b@x.example"})


def test_summary_counts():
    res = [
        {"id": "a1", "kind": "answer", "tags": ["definition"], "correct": True, "outcome": "correct", "turns": 2,
         "guard_codes": ["star"], "llm_cost_usd": 0.01, "llm_ms": 4000, "leak": False},
        {"id": "a2", "kind": "answer", "tags": [], "correct": False, "outcome": "wrong_result", "turns": 1,
         "guard_codes": [], "llm_cost_usd": 0.01, "llm_ms": 6000, "leak": False},
        {"id": "r1", "kind": "refuse", "tags": ["pii"], "outcome": "refused_by_model", "turns": 1, "guard_codes": [],
         "llm_cost_usd": 0.01, "llm_ms": 2000, "leak": False, "safe": True},
    ]
    s = summarize(res)
    assert s["correct"] == 1 and s["correct_definition_questions"] == "1/1" and s["repaired_after_rejection"] == 1
    assert s["refuse_outcomes"] == {"refused_by_model": 1} and s["leaks"] == 0
    assert s["llm_cost_usd_per_correct"] == 0.03
