"""Sandboxed in-memory SQLite loader and read-only query executor for SQL snapshots."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import sqlglot

_LOAD_ALLOWED_ACTIONS: frozenset[int] = frozenset(
    {
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
    }
)

_QUERY_ALLOWED_ACTIONS: frozenset[int] = frozenset(
    {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_PRAGMA,
    }
)


def _load_authorizer(
    action: int,
    arg1: str | None,
    _arg2: str | None,
    _dbname: str | None,
    _source: str | None,
) -> int:
    if action == sqlite3.SQLITE_ATTACH or action == sqlite3.SQLITE_DETACH:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and arg1 and arg1.lower() not in {"foreign_keys"}:
        return sqlite3.SQLITE_DENY
    if action in _LOAD_ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _readonly_authorizer(
    action: int,
    arg1: str | None,
    _arg2: str | None,
    _dbname: str | None,
    _source: str | None,
) -> int:
    if action == sqlite3.SQLITE_PRAGMA and arg1 and arg1.lower() not in {"table_info", "index_list"}:
        return sqlite3.SQLITE_DENY
    if action in _QUERY_ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class SandboxedSQLSnapshot:
    """In-memory SQLite database initialized from a SQL snapshot and locked to SELECT-only."""

    def __init__(self, sql_script: str) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.set_authorizer(_load_authorizer)
        try:
            self._conn.executescript(sql_script)
        except sqlite3.Error:
            # Fallback: transpile via sqlglot to sqlite dialect if needed
            statements = sqlglot.transpile(sql_script, read="sqlite", write="sqlite")
            cleaned_script = ";\n".join(statements) + ";"
            self._conn.executescript(cleaned_script)
        # Lock connection to strict read-only queries after initial load
        self._conn.set_authorizer(_readonly_authorizer)

    @classmethod
    def from_path(cls, path: Path) -> SandboxedSQLSnapshot:
        """Load a SQL snapshot file into an isolated in-memory SQLite instance."""
        sql_text = path.read_text(encoding="utf-8")
        return cls(sql_text)

    def list_tables(self) -> list[str]:
        """Return user table names in the snapshot."""
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [str(row["name"]) for row in cur.fetchall()]

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Execute a read-only SELECT statement."""
        stripped = sql.strip().upper()
        if not (stripped.startswith("SELECT") or stripped.startswith("PRAGMA")):
            msg = f"Only SELECT/PRAGMA queries are permitted in SandboxedSQLSnapshot; got: {sql!r}"
            raise PermissionError(msg)
        cur = self._conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def close(self) -> None:
        """Close the in-memory database."""
        self._conn.close()
