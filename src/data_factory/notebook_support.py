"""Small helpers that keep solution.ipynb a narrative: every computation lives here or in
the modules it calls; the notebook only calls, shows and explains."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Engine, text
from sqlalchemy.types import Date, Float, Integer, Numeric, String

from data_factory.benchmark import Timing, plan_nodes

SEARCH_PATH = text("SELECT set_config('search_path', :path, false)")


def use_schema(connection: Connection, schema: str) -> None:
    connection.execute(SEARCH_PATH, {"path": schema})


def plan_table(timing: Timing, max_depth: int = 4) -> pd.DataFrame:
    """The plan of one measured query as a table (depth, node, rows estimated vs actual...)."""
    rows = [n for n in plan_nodes(timing.plan) if n["depth"] <= max_depth]
    frame = pd.DataFrame(rows)[["depth", "node", "relation", "index", "estimated_rows",
                                "actual_rows", "total_ms", "sort_disk_kb"]]
    frame["node"] = ["  " * d + n for d, n in zip(frame["depth"], frame["node"])]
    return frame.drop(columns="depth")


def timings_table(timings: list[Timing]) -> pd.DataFrame:
    return pd.DataFrame([t.summary() for t in timings]).drop(columns=["label", "runs"])


def read_in_chunks(connection: Connection, statement: str, params: dict, chunk_rows: int,
                   by: str, value: str) -> tuple[pd.DataFrame, int, int]:
    """Read a large result chunk by chunk and keep only a running sum per group: the whole
    result is never in memory. Returns (sums, rows read, chunks)."""
    total, rows, chunks = None, 0, 0
    for chunk in pd.read_sql_query(text(statement), connection, params=params, chunksize=chunk_rows):
        part = chunk.groupby(by)[value].sum()
        total = part if total is None else total.add(part, fill_value=0)
        rows += len(chunk)
        chunks += 1
    return total.sort_values(ascending=False).to_frame(), rows, chunks


# Explicit column types for writing the benchmark results (not pandas' guesses).
RESULT_TYPES = {
    "query": String(64), "label": String(32), "median_ms": Float(), "p95_ms": Float(),
    "max_ms": Float(), "server_ms": Float(), "rows": Integer(), "within_budget": Integer(),
    "measured_on": Date(),
}


def write_results(connection: Connection, frame: pd.DataFrame, table: str) -> int:
    """Write the measured timings with the explicit SQLAlchemy type of every column."""
    frame = frame[list(RESULT_TYPES)].copy()
    frame["within_budget"] = frame["within_budget"].astype(int)
    return frame.to_sql(table, connection, if_exists="replace", index=False, dtype=RESULT_TYPES)


def column_types(connection: Connection, schema: str, table: str) -> pd.DataFrame:
    return pd.read_sql_query(text(
        "SELECT column_name, data_type, character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = :table ORDER BY ordinal_position"),
        connection, params={"schema": schema, "table": table})


def open_connections(engine: Engine) -> int:
    """Connections this engine's pool has handed out and not taken back."""
    return engine.pool.checkedout()


def stage1_hash_check(work_dir: Path, curated_dir: Path) -> pd.DataFrame | None:
    """Stage-1 manifest (copied once to data/work) vs the current one: same output hashes?"""
    old_path, new_path = work_dir / "stage1_manifest.json", curated_dir / "run_manifest.json"
    if not (old_path.exists() and new_path.exists()):
        return None
    old = json.loads(old_path.read_text("utf-8"))["outputs"]
    new = json.loads(new_path.read_text("utf-8"))["outputs"]
    return pd.DataFrame([{"file": name, "stage1": old[name]["sha256"][:12],
                          "now": new.get(name, {}).get("sha256", "")[:12],
                          "identical": old[name]["sha256"] == new.get(name, {}).get("sha256")}
                         for name in sorted(old)])
