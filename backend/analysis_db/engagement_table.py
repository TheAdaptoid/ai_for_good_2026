import sqlite3
from pathlib import Path

from analysis_db.contracts import DataError
from analysis_db.csv_input import finite_number
from analysis_db.identity_tables import _integer, read_table
from analysis_db.storage import assert_schema, table_counts

SCORE_COLUMNS = ("positive_score", "neutral_score", "negative_score")


def replace_engagement(connection: sqlite3.Connection, source: Path) -> dict[str, int]:
    """Replace Engagement from the face-expression notebook's per-detection CSV.

    Rows whose three scores are all empty (observations the notebook could not score) are
    skipped. Returns {"inserted", "skipped", "detections_without_engagement"}. All or nothing.
    """
    if connection.in_transaction:
        raise DataError("replacement requires an idle database connection")
    assert_schema(connection)
    skipped = 0

    def score_row(values):
        nonlocal skipped
        if not any(values[c].strip() for c in SCORE_COLUMNS):
            skipped += 1
            return None
        scores = [finite_number(values, c) for c in SCORE_COLUMNS]
        if not all(0.0 <= s <= 1.0 for s in scores):
            raise ValueError("scores must be between 0 and 1")
        return (_integer(values, "detection_id"), *scores)

    rows = sorted(read_table(source, ("detection_id", *SCORE_COLUMNS), score_row))
    duplicates = len(rows) - len({row[0] for row in rows})
    if duplicates:
        raise DataError(f"{source}: {duplicates} duplicate detection_id value(s)")

    connection.execute("BEGIN")
    try:
        connection.execute("DELETE FROM Engagement")
        connection.executemany(
            "INSERT INTO Engagement (detection_id, positive_score, neutral_score, negative_score)"
            " VALUES (?, ?, ?, ?)", rows)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DataError("foreign key validation failed")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise DataError("database integrity check failed")
        counts = table_counts(connection)
        if counts["Engagement"] != len(rows):
            raise DataError("Engagement row count differs from input")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"inserted": len(rows), "skipped": skipped,
            "detections_without_engagement": counts["FaceDetection"] - len(rows)}
