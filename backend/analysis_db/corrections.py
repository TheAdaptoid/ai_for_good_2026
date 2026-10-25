"""Explicit user corrections. Automated prediction writers do not call these."""

from datetime import datetime, timezone
import math
import sqlite3

from analysis_db.storage import write_transaction


def _correct(connection, table, record_id, columns, values, audit_columns, changed_by):
    if changed_by is not None and not isinstance(changed_by, str):
        raise ValueError("changed_by must be text or None")
    key = table.lower() + "_id"
    with write_transaction(connection):
        old = connection.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE {key}=?",
            (record_id,),
        ).fetchone()
        if old is None:
            raise LookupError(f"{table} {record_id} does not exist")
        if old == values:
            return False
        connection.execute(
            f"UPDATE {table} SET {','.join(column + '=?' for column in columns)} WHERE {key}=?",
            (*values, record_id),
        )
        pairs = tuple(value for pair in zip(old, values) for value in pair)
        names = (key, *audit_columns, "changed_at", "changed_by")
        connection.execute(
            f"INSERT INTO {table}Audit ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
            (record_id, *pairs, datetime.now(timezone.utc).isoformat(), changed_by),
        )
    return True


def correct_activity(connection: sqlite3.Connection, activity_id: int,
                     new_label: str, *, changed_by: str | None = None) -> bool:
    """Update the current label and append history atomically; False on no-op.

    Model scores and result_json remain the original prediction provenance.
    activity_label is the authoritative current, potentially corrected label.
    """
    if not isinstance(new_label, str) or not new_label.strip():
        raise ValueError("Activity label must be nonempty text")
    return _correct(connection, "Activity", activity_id, ("activity_label",),
                    (new_label,), ("old_label", "new_label"), changed_by)


def correct_engagement(connection: sqlite3.Connection, engagement_id: int,
                       positive_score: float, neutral_score: float,
                       negative_score: float, *, changed_by: str | None = None) -> bool:
    """Update all current scores and append history atomically; False on no-op."""
    values = (positive_score, neutral_score, negative_score)
    for value in values:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Engagement scores must be finite numbers between 0 and 1")
    columns = ("positive_score", "neutral_score", "negative_score")
    audit_columns = tuple(prefix + column for column in columns for prefix in ("old_", "new_"))
    return _correct(connection, "Engagement", engagement_id, columns,
                    values, audit_columns, changed_by)
