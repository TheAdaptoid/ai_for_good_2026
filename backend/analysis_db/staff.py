"""Local staff accounts and sign-in sessions. Passwords are stored only as Argon2 hashes and
session tokens only as SHA-256 digests, so a copied database yields no usable credentials.
"""

import hashlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from analysis_db.contracts import STAFF_TABLES, DataError, StaffAccount
from analysis_db.storage import assert_schema

SESSION_LIFETIME = timedelta(hours=12)
_hasher = PasswordHasher()
# Verified against for unknown usernames, so timing does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("not-a-real-password")
_SELECT = "SELECT staff_id, username, is_active, created_at FROM StaffAccount"


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    # Connections run in autocommit mode, so multi-statement changes need an explicit BEGIN.
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account(row: tuple) -> StaffAccount:
    staff_id, username, is_active, created_at = row
    return StaffAccount(staff_id, username, bool(is_active), created_at)


def _require_password(password: object) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise DataError("password must be at least 8 characters")
    return password


def get_account(connection: sqlite3.Connection, username: str) -> StaffAccount:
    assert_schema(connection, tables=STAFF_TABLES)
    row = connection.execute(_SELECT + " WHERE username = ?", (username,)).fetchone()
    if row is None:
        raise LookupError(f"staff account {username!r} does not exist")
    return _account(row)


def create_account(connection: sqlite3.Connection, username: str,
                   password: str) -> StaffAccount:
    assert_schema(connection, tables=STAFF_TABLES)
    if not isinstance(username, str) or not username.strip() or username != username.strip():
        raise DataError("username must be non-empty with no surrounding whitespace")
    password_hash = _hasher.hash(_require_password(password))
    try:
        with _transaction(connection):
            connection.execute(
                "INSERT INTO StaffAccount (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, _iso(_now())))
    except sqlite3.IntegrityError as exc:
        raise DataError(f"staff account {username!r} already exists") from exc
    return get_account(connection, username)


def set_password(connection: sqlite3.Connection, username: str, password: str) -> None:
    """Reset a password; existing sessions are ended so the old password stops mattering."""
    account = get_account(connection, username)
    password_hash = _hasher.hash(_require_password(password))
    with _transaction(connection):
        connection.execute("UPDATE StaffAccount SET password_hash = ? WHERE staff_id = ?",
                           (password_hash, account.staff_id))
        connection.execute("DELETE FROM StaffSession WHERE staff_id = ?", (account.staff_id,))


def set_active(connection: sqlite3.Connection, username: str, active: bool) -> StaffAccount:
    account = get_account(connection, username)
    with _transaction(connection):
        connection.execute("UPDATE StaffAccount SET is_active = ? WHERE staff_id = ?",
                           (int(active), account.staff_id))
        if not active:
            connection.execute("DELETE FROM StaffSession WHERE staff_id = ?",
                               (account.staff_id,))
    return get_account(connection, username)


def authenticate(connection: sqlite3.Connection, username: str,
                 password: str) -> StaffAccount | None:
    """The account for valid credentials of an active account, else None (never says why)."""
    assert_schema(connection, tables=STAFF_TABLES)
    row = connection.execute(
        "SELECT staff_id, password_hash, is_active FROM StaffAccount WHERE username = ?",
        (username,)).fetchone()
    try:
        _hasher.verify(_DUMMY_HASH if row is None else row[1], password)
    except (VerificationError, InvalidHashError):
        return None
    if row is None or not row[2]:
        return None
    if _hasher.check_needs_rehash(row[1]):
        with _transaction(connection):
            connection.execute("UPDATE StaffAccount SET password_hash = ? WHERE staff_id = ?",
                               (_hasher.hash(password), row[0]))
    return _account(connection.execute(_SELECT + " WHERE staff_id = ?", (row[0],)).fetchone())


def create_session(connection: sqlite3.Connection, account: StaffAccount) -> str:
    """Store a new session and return its raw token (the only copy)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    with _transaction(connection):
        connection.execute(
            "INSERT INTO StaffSession (token_hash, staff_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (_digest(token), account.staff_id, _iso(now), _iso(now + SESSION_LIFETIME)))
    return token


def resolve_session(connection: sqlite3.Connection, token: str | None) -> StaffAccount | None:
    """The active account behind an unexpired session token, else None."""
    if not token:
        return None
    assert_schema(connection, tables=STAFF_TABLES)
    row = connection.execute(
        "SELECT a.staff_id, a.username, a.is_active, a.created_at, s.expires_at"
        " FROM StaffSession s JOIN StaffAccount a ON a.staff_id = s.staff_id"
        " WHERE s.token_hash = ?", (_digest(token),)).fetchone()
    if row is None:
        return None
    if row[4] <= _iso(_now()):
        with _transaction(connection):
            connection.execute("DELETE FROM StaffSession WHERE token_hash = ?", (_digest(token),))
        return None
    return _account(row[:4]) if row[2] else None


def end_session(connection: sqlite3.Connection, token: str | None) -> None:
    if token:
        with _transaction(connection):
            connection.execute("DELETE FROM StaffSession WHERE token_hash = ?", (_digest(token),))
