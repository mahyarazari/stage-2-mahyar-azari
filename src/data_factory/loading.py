"""Load stage: the published outputs of the factory go into a sink (PostgreSQL in stage 2).

What is loaded (stage-2 decision):
  cases        the case-level dataset (curated/cases.csv)
  quarantine   every rejected record with its reasons (quarantine/<snapshot>/quarantine.csv)
  load_runs    one row per load: which run, which snapshot, config and commit, and the
               sha256 and row count of every loaded file. Its load_id is the run_id of the
               run manifest, so a database row leads back to its manifest.

The wide summary tables are not loaded: they are a reading format (one column per month);
the database computes the same numbers from `cases`.

All three tables are written in one sink session: either everything is loaded, or the
previous content is kept. Running the stage again replaces cases and quarantine (same
content, no duplicates) and adds one row to load_runs, which is a log.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd

from data_factory.contract import REASON_COLUMN, REASON_SEPARATOR
from data_factory.exceptions import MissingInputError
from data_factory.manifest import file_sha256
from data_factory.sinks import Sink
from data_factory.tables import read_csv_text

log = logging.getLogger(__name__)

RUNS_TABLE = "load_runs"


@dataclass(frozen=True)
class TableLoad:
    table: str                                         # target table in the sink
    path: Path                                         # published file to read
    transform: Callable[[pd.DataFrame], pd.DataFrame]  # text values -> values the sink accepts


@dataclass(frozen=True)
class LoadStats:
    load_id: str
    rows: dict[str, int]


def month_to_date(frame: pd.DataFrame) -> pd.DataFrame:
    """created_month 'YYYY-MM' -> 'YYYY-MM-01', so the database can store it as a date."""
    out = frame.copy()
    out["created_month"] = out["created_month"] + "-01"
    return out


def reasons_to_array(frame: pd.DataFrame) -> pd.DataFrame:
    """reason_codes 'A|B' -> '{A,B}', a PostgreSQL text[] literal (codes are plain upper-case names)."""
    out = frame.copy()
    out[REASON_COLUMN] = "{" + out[REASON_COLUMN].str.replace(REASON_SEPARATOR, ",", regex=False) + "}"
    return out


def _chunks(item: TableLoad, chunk_rows: int) -> Iterator[pd.DataFrame]:
    for chunk in read_csv_text(item.path, chunksize=chunk_rows):
        yield item.transform(chunk)


def _columns(path: Path) -> list[str]:
    return list(pd.read_csv(path, nrows=0).columns)


def load_tables(items: list[TableLoad], sink: Sink, chunk_rows: int, run: dict[str, str]) -> LoadStats:
    """Write every item and one load_runs row in a single sink session."""
    for item in items:
        if not item.path.exists():
            raise MissingInputError(f"{item.path} not found: run the publish stage first")
    files = {item.table: {"file": item.path.name, "sha256": file_sha256(item.path)} for item in items}

    rows = {}
    with sink.session() as out:
        for item in items:
            rows[item.table] = out.replace_table(item.table, _columns(item.path), _chunks(item, chunk_rows))
            files[item.table]["rows"] = rows[item.table]
            log.info("load: %s <- %s (%d rows)", item.table, item.path.name, rows[item.table])
        out.append_rows(RUNS_TABLE, pd.DataFrame([{
            **run,
            "loaded_at_utc": datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat(),
            "files": json.dumps(files, sort_keys=True),
        }]))
    return LoadStats(load_id=run["load_id"], rows=rows)
