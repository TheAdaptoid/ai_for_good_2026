"""Staff-managed labels. Labels are deactivated, never deleted (a trigger also blocks DELETE)."""

import sqlite3

from analysis_db.contracts import REVIEW_TABLES, DataError, Label, LabelCategory
from analysis_db.storage import assert_schema

_SELECT = "SELECT label_id, name, category, description, is_active FROM Label"


def _label(row: tuple) -> Label:
    label_id, name, category, description, is_active = row
    return Label(label_id, name, LabelCategory(category), description, bool(is_active))


def _get(connection: sqlite3.Connection, label_id: int) -> Label:
    row = connection.execute(_SELECT + " WHERE label_id = ?", (label_id,)).fetchone()
    if row is None:
        raise LookupError(f"label {label_id} does not exist")
    return _label(row)


def _write(connection: sqlite3.Connection, sql: str, params: tuple) -> int:
    try:
        return connection.execute(sql, params).lastrowid
    except sqlite3.IntegrityError as exc:
        raise DataError(f"invalid label: {exc}") from exc


def list_labels(connection: sqlite3.Connection, *, category: str | None = None,
                include_inactive: bool = False) -> list[Label]:
    assert_schema(connection, tables=REVIEW_TABLES)
    clauses, params = [], []
    if category is not None:
        clauses.append("category = ?")
        params.append(LabelCategory(category).value)
    if not include_inactive:
        clauses.append("is_active = 1")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return [_label(row) for row in connection.execute(
        _SELECT + where + " ORDER BY label_id", params)]


def create_label(connection: sqlite3.Connection, name: str, category: str,
                 description: str | None = None) -> Label:
    assert_schema(connection, tables=REVIEW_TABLES)
    if category not in tuple(LabelCategory):
        raise DataError(f"label category must be 'activity' or 'observation', not {category!r}")
    label_id = _write(connection,
                      "INSERT INTO Label (name, category, description) VALUES (?, ?, ?)",
                      (name, category, description))
    return _get(connection, label_id)


def update_label(connection: sqlite3.Connection, label_id: int, *, name: str | None = None,
                 description: str | None = None) -> Label:
    """Rename or redescribe; annotations reference the id, so they follow automatically."""
    assert_schema(connection, tables=REVIEW_TABLES)
    current = _get(connection, label_id)
    _write(connection, "UPDATE Label SET name = ?, description = ? WHERE label_id = ?",
           (current.name if name is None else name,
            current.description if description is None else description, label_id))
    return _get(connection, label_id)


def set_label_active(connection: sqlite3.Connection, label_id: int, active: bool) -> Label:
    assert_schema(connection, tables=REVIEW_TABLES)
    _get(connection, label_id)
    connection.execute("UPDATE Label SET is_active = ? WHERE label_id = ?",
                       (int(active), label_id))
    return _get(connection, label_id)
