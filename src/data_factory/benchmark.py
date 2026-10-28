"""Timing and execution plans of the dashboard queries (stage 2).

Measurement method (the budget is 200 ms per query, judged on the 95th percentile):
  - the query text comes from a versioned file in sql/queries/; every value (dates, top
    N) is a bound parameter, never part of the text;
  - each measurement opens no new connection: one connection is reused, as a dashboard
    with a connection pool would; the time measured is the client's wall-clock time for
    executing the query AND fetching every row (what the dashboard waits for);
  - `warmup` runs first (cache and plan warm, as on a dashboard that is opened often),
    then `runs` timed runs; median, 95th percentile and maximum are reported;
  - the plan comes from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) with the same parameters,
    so it shows the real row counts and the server's own execution time.
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Connection, text

QUERY_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"
# EXPLAIN is put in front of the fixed query text from the repo; no value is ever part of
# the text (values are bound parameters), so this is not building SQL from data.
EXPLAIN_PREFIX = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n"


def query_text(name: str, folder: Path = QUERY_DIR) -> str:
    return (folder / f"{name}.sql").read_text(encoding="utf-8")


@dataclass
class Timing:
    query: str
    label: str
    runs: int
    median_ms: float
    p95_ms: float
    max_ms: float
    rows: int
    server_ms: float                  # Execution Time reported by EXPLAIN ANALYZE
    within_budget: bool
    plan: dict[str, Any] = field(repr=False)

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("plan")
        return data


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile (no interpolation: an observed time)."""
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * share // 1))           # ceil(n * share)
    return ordered[int(rank) - 1]


def explain(connection: Connection, name: str, params: dict[str, Any], folder: Path = QUERY_DIR) -> dict:
    result = connection.execute(text(EXPLAIN_PREFIX + query_text(name, folder)), params).scalar_one()
    plan = result if isinstance(result, list) else json.loads(result)
    return plan[0]


def measure(connection: Connection, name: str, params: dict[str, Any], label: str = "",
            warmup: int = 3, runs: int = 30, budget_ms: float = 200.0, folder: Path = QUERY_DIR) -> Timing:
    statement = text(query_text(name, folder))
    rows = 0
    for _ in range(warmup):
        rows = len(connection.execute(statement, params).all())
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        rows = len(connection.execute(statement, params).all())
        times.append((time.perf_counter() - started) * 1000)
    plan = explain(connection, name, params, folder)
    p95 = percentile(times, 0.95)
    return Timing(query=name, label=label, runs=runs, median_ms=round(statistics.median(times), 2),
                  p95_ms=round(p95, 2), max_ms=round(max(times), 2), rows=rows,
                  server_ms=round(plan["Execution Time"], 2), within_budget=p95 < budget_ms, plan=plan)


# ---------------------------------------------------------------- reading a plan
def plan_nodes(plan: dict) -> Iterator[dict[str, Any]]:
    """Every node of a plan, depth first, with the facts used to read it."""
    def walk(node: dict, depth: int) -> Iterator[dict[str, Any]]:
        loops = node.get("Actual Loops", 1)
        yield {
            "depth": depth,
            "node": node["Node Type"] + (f" ({node['Strategy']})" if "Strategy" in node else ""),
            "relation": node.get("Relation Name") or node.get("CTE Name") or "",
            "index": node.get("Index Name", ""),
            "estimated_rows": node.get("Plan Rows"),
            "actual_rows": node.get("Actual Rows", 0) * loops,
            "loops": loops,
            "total_ms": round(node.get("Actual Total Time", 0.0) * loops, 2),
            "cost": node.get("Total Cost"),
            "shared_hit": node.get("Shared Hit Blocks", 0),
            "shared_read": node.get("Shared Read Blocks", 0),
            "sort_disk_kb": node.get("Sort Space Used", 0) if node.get("Sort Space Type") == "Disk" else 0,
        }
        for child in node.get("Plans", []):
            yield from walk(child, depth + 1)
    yield from walk(plan["Plan"], 0)


# ---------------------------------------------------------------- the dashboard set
DASHBOARD_QUERIES = (
    "q1_sales_by_month_category",
    "q2_late_delivery_by_state_month",
    "q3_delay_vs_review_score",
    "q4_top_sellers",
    "q5_payments_by_installments",
)


def dashboard_params(settings) -> dict[str, dict[str, Any]]:
    """The parameters each dashboard query is measured with (from [dashboard])."""
    period = {"start": settings.start.to_pydatetime(), "end": settings.end.to_pydatetime()}
    return {name: ({**period, "top_n": settings.top_n} if name == "q4_top_sellers" else dict(period))
            for name in DASHBOARD_QUERIES}


def run_dashboard(connection: Connection, settings, label: str) -> list[Timing]:
    return [measure(connection, name, params, label, settings.warmup_runs, settings.timed_runs,
                    settings.budget_ms)
            for name, params in dashboard_params(settings).items()]


def save_timings(timings: list[Timing], path: Path) -> None:
    """Summaries and full plans, so every number in the report can be traced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {t.query: {**t.summary(), "plan": t.plan} for t in timings}
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str) + "\n",
                    encoding="utf-8", newline="\n")
