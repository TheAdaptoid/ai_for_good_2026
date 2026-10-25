import subprocess
from contextlib import closing
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from analysis_db import staff
from analysis_db.contracts import DataError
from analysis_db.storage import connect_database, initialize_database, staff_table_counts

STAFF_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "staff.py"
PASSWORD = "correct horse"


def test_init_adds_empty_staff_tables_idempotently(tmp_path):
    db = tmp_path / "a.sqlite"
    initialize_database(db)
    initialize_database(db)
    with closing(connect_database(db, must_exist=True)) as connection:
        assert staff_table_counts(connection) == {"StaffAccount": 0, "StaffSession": 0, "ImportRun": 0}


def test_password_is_only_stored_as_argon2_hash(review_db):
    staff.create_account(review_db, "alex", PASSWORD)
    (stored,) = review_db.execute("SELECT password_hash FROM StaffAccount").fetchone()
    assert PASSWORD not in stored and stored.startswith("$argon2id$")


def test_authenticate_success_and_generic_failures(review_db):
    account = staff.create_account(review_db, "alex", PASSWORD)
    assert staff.authenticate(review_db, "alex", PASSWORD) == account
    assert staff.authenticate(review_db, "ALEX", PASSWORD) == account  # usernames ignore case
    assert staff.authenticate(review_db, "alex", "wrong password") is None
    assert staff.authenticate(review_db, "nobody", PASSWORD) is None


@pytest.mark.parametrize("username, password", [("", PASSWORD), (" alex", PASSWORD),
                                                ("alex", "short")])
def test_create_account_validation(review_db, username, password):
    with pytest.raises(DataError):
        staff.create_account(review_db, username, password)


def test_duplicate_username_refused(review_db):
    staff.create_account(review_db, "alex", PASSWORD)
    with pytest.raises(DataError, match="already exists"):
        staff.create_account(review_db, "Alex", PASSWORD)


def test_session_lifecycle(review_db):
    account = staff.create_account(review_db, "alex", PASSWORD)
    token = staff.create_session(review_db, account)
    assert staff.resolve_session(review_db, token) == account
    (stored,) = review_db.execute("SELECT token_hash FROM StaffSession").fetchone()
    assert token not in stored
    staff.end_session(review_db, token)
    assert staff.resolve_session(review_db, token) is None
    assert staff.resolve_session(review_db, None) is None
    assert staff.resolve_session(review_db, "made-up") is None


def test_expired_session_refused_and_removed(review_db):
    account = staff.create_account(review_db, "alex", PASSWORD)
    token = staff.create_session(review_db, account)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="seconds")
    review_db.execute("UPDATE StaffSession SET expires_at = ?", (past.replace("+00:00", "Z"),))
    assert staff.resolve_session(review_db, token) is None
    assert review_db.execute("SELECT COUNT(*) FROM StaffSession").fetchone() == (0,)


def test_disabled_account_cannot_sign_in_or_use_sessions(review_db):
    account = staff.create_account(review_db, "alex", PASSWORD)
    token = staff.create_session(review_db, account)
    staff.set_active(review_db, "alex", False)
    assert staff.resolve_session(review_db, token) is None
    assert staff.authenticate(review_db, "alex", PASSWORD) is None
    staff.set_active(review_db, "alex", True)
    assert staff.authenticate(review_db, "alex", PASSWORD) is not None


def test_reset_password_ends_sessions(review_db):
    account = staff.create_account(review_db, "alex", PASSWORD)
    token = staff.create_session(review_db, account)
    staff.set_password(review_db, "alex", "a new password")
    assert staff.resolve_session(review_db, token) is None
    assert staff.authenticate(review_db, "alex", PASSWORD) is None
    assert staff.authenticate(review_db, "alex", "a new password") is not None


def test_unknown_account_lookup(review_db):
    with pytest.raises(LookupError):
        staff.set_active(review_db, "nobody", False)


def run_cli(*args, stdin=""):
    return subprocess.run([sys.executable, str(STAFF_SCRIPT), *args], input=stdin,
                          capture_output=True, text=True)


def test_cli_create_disable_enable_reset(tmp_path):
    db = tmp_path / "a.sqlite"
    initialize_database(db)
    created = run_cli("create", "alex", "--db", str(db), "--password-stdin", stdin=PASSWORD)
    assert created.returncode == 0, created.stderr
    assert PASSWORD not in created.stdout + created.stderr
    assert run_cli("create", "alex", "--db", str(db), "--password-stdin",
                   stdin=PASSWORD).returncode == 1
    assert run_cli("disable", "alex", "--db", str(db)).returncode == 0
    assert run_cli("enable", "alex", "--db", str(db)).returncode == 0
    reset = run_cli("reset-password", "alex", "--db", str(db), "--password-stdin",
                    stdin="another password")
    assert reset.returncode == 0, reset.stderr
    missing = run_cli("disable", "nobody", "--db", str(db))
    assert missing.returncode == 1 and "does not exist" in missing.stderr
    assert "Traceback" not in missing.stderr


def test_cli_missing_database(tmp_path):
    result = run_cli("disable", "alex", "--db", str(tmp_path / "missing.sqlite"))
    assert result.returncode == 1 and not (tmp_path / "missing.sqlite").exists()
