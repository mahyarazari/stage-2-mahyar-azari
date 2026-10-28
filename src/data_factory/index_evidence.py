"""Evidence for every index (stage 2, part 4): plans with and without it, its size, its
cost on writes. An index the planner does not use is dropped.

Every experiment runs inside a transaction that is rolled back, so the database is left
exactly as the load stage built it. Index and table names are fixed in this module and
composed with psycopg.sql.Identifier; values are bound parameters.
"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from psycopg import sql
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, text

# Candidate indexes: name -> (definition, statement whose plan decides; same filters as
# refresh_month). The definitions are fixed text from this module.
CANDIDATES = {
    "orders_purchased_at_idx": (
        "CREATE INDEX orders_purchased_at_idx ON orders (purchased_at)",
        "SELECT count(*) FROM orders WHERE purchased_at >= :start AND purchased_at < :end"),
    "order_reviews_order_id_idx": (
        "CREATE INDEX order_reviews_order_id_idx ON order_reviews (order_id)",
        "SELECT count(*) FROM orders o JOIN order_reviews r ON r.order_id = o.order_id "
        "WHERE o.purchased_at >= :start AND o.purchased_at < :end"),
}
SIZES_SQL = text(
    "SELECT i.indexrelid::regclass::text AS index, t.relname AS table_name, "
    "pg_relation_size(i.indexrelid) AS index_bytes, pg_relation_size(i.indrelid) AS table_bytes "
    "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema ORDER BY t.relname, 1")
EXPLAIN = "EXPLAIN (ANALYZE, FORMAT JSON) "   # put in front of the fixed statements above only


@contextmanager
def experiment(engine: Engine, schema: str):
    """A connection in `schema` whose transaction is always rolled back: nothing is kept."""
    with engine.connect() as connection:
        connection.execute(text("SELECT set_config('search_path', :path, true)"), {"path": schema})
        try:
            yield connection
        finally:
            connection.rollback()


def _cursor(connection: Connection):
    return connection.connection.driver_connection.cursor()


def _plan(connection: Connection, statement: str, params: dict) -> dict[str, Any]:
    plan = connection.execute(text(EXPLAIN + statement), params).scalar_one()
    plan = (plan if isinstance(plan, list) else json.loads(plan))[0]
    nodes, stack = [], [plan["Plan"]]
    while stack:
        node = stack.pop()
        nodes.append(node["Node Type"] + (f" using {node['Index Name']}" if "Index Name" in node else ""))
        stack.extend(node.get("Plans", []))
    return {"nodes": nodes, "ms": round(plan["Execution Time"], 2)}


def _timed_refresh(connection: Connection, month: date, runs: int) -> float:
    connection.execute(text("CALL refresh_month(:m)"), {"m": month})       # warm-up (cache, plans)
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        connection.execute(text("CALL refresh_month(:m)"), {"m": month})
        times.append((time.perf_counter() - started) * 1000)
    return round(sorted(times)[len(times) // 2], 1)


def with_and_without(engine: Engine, schema: str, month: date, runs: int = 9) -> dict[str, Any]:
    """For each candidate: plan and refresh_month time without the index, then with it.
    Both states are made inside a rolled-back experiment, whatever the database has now."""
    params = {"start": month, "end": date(month.year + month.month // 12, month.month % 12 + 1, 1)}
    out = {}
    for index, (definition, statement) in CANDIDATES.items():
        with experiment(engine, schema) as connection:
            _cursor(connection).execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(index)))
            without = {"plan": _plan(connection, statement, params),
                       "refresh_ms": _timed_refresh(connection, month, runs)}
            connection.execute(text(definition))
            connection.execute(text("ANALYZE orders, order_reviews"))
            with_index = {"plan": _plan(connection, statement, params),
                          "refresh_ms": _timed_refresh(connection, month, runs),
                          "bytes": connection.execute(text("SELECT pg_relation_size(to_regclass(:name))"),
                                                      {"name": index}).scalar_one()}
            used = any(index in node for node in with_index["plan"]["nodes"])
        out[index] = {"without": without, "with": with_index, "used_by_planner": used}
    return out


def sizes(engine: Engine, schema: str) -> list[dict[str, Any]]:
    with experiment(engine, schema) as connection:
        return [dict(row._mapping) for row in connection.execute(SIZES_SQL, {"schema": schema})]


def insert_cost(engine: Engine, schema: str) -> dict[str, float]:
    """Time to insert every order into an empty copy of `orders`: no index, primary key only,
    then the primary key + purchased_at index + the unique customer_id index (as in `orders`)."""
    steps = {
        "no_index": [],
        "primary_key": ["ALTER TABLE orders_copy ADD PRIMARY KEY (order_id)"],
        "all_indexes": ["ALTER TABLE orders_copy ADD PRIMARY KEY (order_id)",
                        "ALTER TABLE orders_copy ADD UNIQUE (customer_id)",
                        "CREATE INDEX ON orders_copy (purchased_at)"],
    }
    result = {}
    for name, ddl in steps.items():
        with experiment(engine, schema) as connection:
            connection.execute(text("CREATE TEMP TABLE orders_copy (LIKE orders) ON COMMIT DROP"))
            for statement in ddl:
                connection.execute(text(statement))
            started = time.perf_counter()
            connection.execute(text("INSERT INTO orders_copy SELECT order_id, customer_id, status, purchased_at, "
                                    "approved_at, delivered_carrier_at, delivered_customer_at, "
                                    "estimated_delivery_date FROM orders"))
            result[name] = round((time.perf_counter() - started) * 1000, 1)
    return result
