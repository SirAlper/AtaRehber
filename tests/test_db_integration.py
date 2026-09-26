"""Read-only enforcement against real PostgreSQL / MySQL servers.

The SQL guard normally rejects writes before they reach the database. These tests bypass the guard to prove
the second layer (database-enforced read-only transactions and statement timeouts) works on its own.

Skipped unless a server URL is provided, e.g.:
    TEST_POSTGRES_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/olra_test
    TEST_MYSQL_URL=mysql+pymysql://root:root@localhost:3306/olra_test
CI runs them against service containers (see .github/workflows/ci.yml).
"""

import os
import time
from unittest.mock import patch

import pytest

from src.connectors import db_connector
from src.connectors.db_connector import DatabaseConnector

TABLE = "it_items"

SERVERS = [
    pytest.param("TEST_POSTGRES_URL", id="postgresql"),
    pytest.param("TEST_MYSQL_URL", id="mysql"),
]


@pytest.fixture(scope="module", params=SERVERS)
def server(request):
    url = os.getenv(request.param)
    if not url:
        pytest.skip(f"{request.param} not set")
    from sqlalchemy import create_engine, text

    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL)"))
        conn.execute(text(f"INSERT INTO {TABLE} (id, name) VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')"))

    connector = DatabaseConnector(database_url=url, allowed_tables=[])
    assert connector.is_connected, connector._last_error

    def row_count() -> int:
        with admin.connect() as conn:
            return conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()

    yield connector, row_count

    connector.engine.dispose()
    with admin.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    admin.dispose()


def _without_guard(connector):
    return patch.object(connector, "_validate_sql_safety", return_value=(True, ""))


def test_select_works_repeatedly_on_pooled_connections(server):
    connector, _ = server
    # Several queries reuse pooled connections; each must start a fresh read-only transaction
    for _ in range(3):
        result = connector.execute_query(f"SELECT id, name FROM {TABLE} ORDER BY id")
        assert result["status"] == "success", result
        assert [row["name"] for row in result["rows"]] == ["alpha", "beta", "gamma"]


def test_schema_discovery(server):
    connector, _ = server
    assert TABLE in connector.get_tables()
    assert TABLE in connector.get_schema_summary()


def test_guard_rejects_writes(server):
    connector, row_count = server
    result = connector.execute_query(f"DELETE FROM {TABLE}")
    assert result["status"] == "error"
    assert "Security Guard" in result["message"]
    assert row_count() == 3


@pytest.mark.parametrize(
    "statement",
    [
        f"INSERT INTO {TABLE} (id, name) VALUES (99, 'hacked')",
        f"UPDATE {TABLE} SET name = 'hacked'",
        f"DELETE FROM {TABLE}",
        f"DROP TABLE {TABLE}",
    ],
)
def test_database_rejects_writes_even_without_guard(server, statement):
    connector, row_count = server
    with _without_guard(connector):
        result = connector.execute_query(statement)
    assert result["status"] == "error", f"write was not blocked by the database: {statement}"
    assert row_count() == 3


def test_postgres_data_modifying_cte_is_rejected_by_database(server):
    connector, row_count = server
    if connector.dialect != "postgresql":
        pytest.skip("data-modifying CTEs are PostgreSQL-specific")
    with _without_guard(connector):
        result = connector.execute_query(f"WITH gone AS (DELETE FROM {TABLE} RETURNING id) SELECT * FROM gone")
    assert result["status"] == "error"
    assert row_count() == 3


def test_statement_timeout_stops_long_queries(server):
    connector, _ = server
    if connector.dialect == "postgresql":
        slow_query = "SELECT pg_sleep(5)"
    else:
        slow_query = f"SELECT SLEEP(5) FROM {TABLE} LIMIT 1"

    with _without_guard(connector), patch.object(db_connector, "DB_QUERY_TIMEOUT_SECONDS", 1):
        start = time.monotonic()
        result = connector.execute_query(slow_query)
        elapsed = time.monotonic() - start

    # MySQL may return the interrupted SLEEP() as a normal row, so the elapsed time is the reliable signal
    assert elapsed < 4, f"query ran {elapsed:.1f}s, timeout not applied ({result})"
    if connector.dialect == "postgresql":
        assert result["status"] == "error"

    # The connection pool is still usable afterwards
    assert connector.execute_query(f"SELECT COUNT(*) AS n FROM {TABLE}")["status"] == "success"
