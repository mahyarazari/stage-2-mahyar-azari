"""Sinks: where tables go. The mirror image of `sources.py`.

A sink opens a *session*. Inside a session, tables are replaced or rows appended; the
session is all or nothing: if anything fails, nothing of the session is kept. That is
what lets a stage be run again (idempotent) and be stopped half-way without leaving half
a result behind.

    with sink.session() as out:
        out.replace_table("cases", columns, chunks)   # chunks: an iterable of DataFrames
        out.append_rows("load_runs", frame)

Two sinks exist:
  - CsvSink       one CSV file per table, written atomically (the stage-1 rules).
  - PostgresSink  one database transaction per session; tables are filled with COPY.

A stage that writes through this interface does not know which sink it has, so a new
destination does not touch validation, quarantine or the manifest.
"""
from __future__ import annotations

import io
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Protocol, Sequence

import pandas as pd
from psycopg import sql
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

import psycopg

from data_factory.exceptions import DatabaseError, MissingInputError
from data_factory.tables import AtomicCsvWriter, read_csv_text

log = logging.getLogger(__name__)


class SinkSession(Protocol):
    def replace_table(self, table: str, columns: Sequence[str], chunks: Iterable[pd.DataFrame]) -> int: ...

    def append_rows(self, table: str, frame: pd.DataFrame) -> int: ...


class Sink(Protocol):
    def session(self) -> Iterator[SinkSession]: ...


# ---------------------------------------------------------------- CSV
class _CsvSession:
    def __init__(self, directory: Path):
        self.directory = directory
        self.writers: list[AtomicCsvWriter] = []

    def _writer(self, table: str, columns: Sequence[str]) -> AtomicCsvWriter:
        writer = AtomicCsvWriter(self.directory / f"{table}.csv", list(columns)).__enter__()
        self.writers.append(writer)
        return writer

    def replace_table(self, table, columns, chunks) -> int:
        writer = self._writer(table, columns)
        for chunk in chunks:
            writer.append(chunk)
        return writer.rows

    def append_rows(self, table, frame) -> int:
        path = self.directory / f"{table}.csv"
        old = read_csv_text(path) if path.exists() else frame.iloc[0:0]
        writer = self._writer(table, list(frame.columns))
        writer.append(old.astype("string"))
        writer.append(frame)
        return len(frame)


class CsvSink:
    """One CSV per table in `directory`. Files get their final names only if the session succeeds."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @contextmanager
    def session(self) -> Iterator[_CsvSession]:
        current = _CsvSession(self.directory)
        try:
            yield current
        except BaseException:
            for writer in current.writers:
                writer.discard()
            raise
        for writer in current.writers:
            writer.commit()


# ---------------------------------------------------------------- PostgreSQL
def _csv_text(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    """CSV body for COPY: no header, empty field = NULL."""
    buffer = io.StringIO()
    frame.reindex(columns=list(columns)).to_csv(buffer, index=False, header=False, lineterminator="\n")
    return buffer.getvalue()


class _PostgresSession:
    def __init__(self, cursor: psycopg.Cursor):
        self.cursor = cursor
        self.tables: list[str] = []      # filled tables, analysed before commit

    def _copy(self, table: str, columns: Sequence[str], chunks: Iterable[pd.DataFrame]) -> int:
        statement = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv)").format(
            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
        rows = 0
        with self.cursor.copy(statement) as copy:
            for chunk in chunks:            # one chunk in memory at a time
                copy.write(_csv_text(chunk, columns))
                rows += len(chunk)
        return rows

    def count(self, table: str) -> int:
        self.cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return self.cursor.fetchone()[0]

    def replace_table(self, table, columns, chunks) -> int:
        self.cursor.execute(sql.SQL("TRUNCATE {}").format(sql.Identifier(table)))
        rows = self._copy(table, columns, chunks)
        self.tables.append(table)
        stored = self.count(table)
        if stored != rows:
            raise DatabaseError(f"{table}: sent {rows} rows but the table holds {stored}")
        return rows

    def append_rows(self, table, frame) -> int:
        return self._copy(table, list(frame.columns), [frame])


class PostgresSink:
    """One transaction per session, in `schema`; SQL files run before and after the tables are filled.

    The SQL files use unqualified names: the session sets search_path to `schema` for the
    transaction only (set_config(..., true)), so the same files can build a test schema.
    """

    def __init__(self, engine: Engine, schema: str, before: Sequence[Path] = (), after: Sequence[Path] = ()):
        self.engine = engine
        self.schema = schema
        self.before = tuple(before)
        self.after = tuple(after)

    def _run_files(self, cursor: psycopg.Cursor, files: Sequence[Path]) -> None:
        for path in files:
            if not path.exists():
                raise MissingInputError(f"SQL file not found: {path}")
            log.info("sql: %s", path.name)
            cursor.execute(path.read_text(encoding="utf-8"))   # a fixed file from the repo, no values

    @contextmanager
    def session(self) -> Iterator[_PostgresSession]:
        try:
            with self.engine.begin() as connection:            # commit on success, rollback on error
                cursor = connection.connection.driver_connection.cursor()
                cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                connection.execute(text("SELECT set_config('search_path', :path, true)"),
                                   {"path": self.schema})
                self._run_files(cursor, self.before)
                current = _PostgresSession(cursor)
                yield current
                self._run_files(cursor, self.after)
                for table in current.tables:   # fresh planner statistics after a bulk load
                    cursor.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
                cursor.close()
        except (SQLAlchemyError, psycopg.Error) as error:
            raise DatabaseError(f"load into schema {self.schema} failed and was rolled back: "
                                f"{error.__class__.__name__}: {getattr(error, 'orig', None) or error}") from None
