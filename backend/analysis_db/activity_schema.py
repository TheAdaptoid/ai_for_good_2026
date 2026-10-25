"""Explicit, lossless migration of the empty legacy Activity table."""

import re
import sqlite3

from analysis_db.contracts import DataError
from analysis_db.paths import SCHEMA_PATH
from analysis_db.storage import assert_schema


LEGACY_DDL = """CREATE TABLE Activity (
    activity_id INTEGER PRIMARY KEY,
    detection_id INTEGER NOT NULL UNIQUE REFERENCES FaceDetection(detection_id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    activity_label TEXT NOT NULL,
    confidence REAL NOT NULL,
    CHECK (end_frame = start_frame + 31)
)"""


def activity_ddl():
    return re.search(
        r"CREATE TABLE IF NOT EXISTS Activity \(.*?\n\);",
        SCHEMA_PATH.read_text(encoding="utf-8"), re.S,
    ).group(0).replace("IF NOT EXISTS ", "")


def normalized(sql):
    # SQL keywords are case-insensitive; string literals (including strftime
    # formats) are not. SQLite quotes the table name after ALTER TABLE RENAME.
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\w+|[^\s]", sql.rstrip("; \n"))
    output = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if [t.casefold() for t in tokens[index:index + 3]] == ["if", "not", "exists"]:
            index += 3
            continue
        if token.casefold() == '"activity"':
            token = "activity"
        elif not token.startswith(("'", '"')):
            token = token.casefold()
        output.append(token)
        index += 1
    return "\x1f".join(output)


def check_integrity(connection):
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise DataError("Foreign key validation failed")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise DataError("Database integrity validation failed")


def require_activity_schema(connection):
    row = connection.execute("SELECT sql FROM sqlite_master WHERE name='Activity'").fetchone()
    if row is None or normalized(row[0]) != normalized(activity_ddl()):
        raise DataError("Run scripts/migrate_activity.py on this database before inference")


def migrate_activity(connection: sqlite3.Connection) -> bool:
    if connection.in_transaction:
        raise DataError("Migration requires an idle connection")
    if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise DataError("Migration requires foreign keys enabled")
    assert_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        actual = connection.execute("SELECT sql FROM sqlite_master WHERE name='Activity'").fetchone()[0]
        current = activity_ddl()
        changed = normalized(actual) != normalized(current)
        if changed:
            if normalized(actual) != normalized(LEGACY_DDL):
                raise DataError("Unknown Activity schema; database unchanged")
            if connection.execute("SELECT COUNT(*) FROM Activity").fetchone()[0]:
                raise DataError("Legacy Activity is not empty; database unchanged")
            connection.execute(current.replace("CREATE TABLE Activity", "CREATE TABLE Activity_new"))
            connection.execute("DROP TABLE Activity")
            connection.execute("ALTER TABLE Activity_new RENAME TO Activity")
        check_integrity(connection)
        connection.commit()
        return changed
    except BaseException:
        connection.rollback()
        raise
