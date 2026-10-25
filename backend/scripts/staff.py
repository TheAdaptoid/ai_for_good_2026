import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db import staff  # noqa: E402
from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.paths import WORKING_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage local staff accounts. There is no web sign-up; run this on the"
                    " machine that hosts the service.")
    parser.add_argument("command", choices=("create", "disable", "enable", "reset-password"))
    parser.add_argument("username")
    parser.add_argument("--db", type=Path, default=WORKING_DB,
                        help="existing database file (default: %(default)s)")
    parser.add_argument("--password-stdin", action="store_true",
                        help="read the password from the first line of stdin (for scripts)")
    return parser


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise DataError("passwords do not match")
    return password


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        connection = connect_database(args.db, must_exist=True)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "create":
            staff.create_account(connection, args.username, read_password(args.password_stdin))
            print(f"Created staff account {args.username!r}")
        elif args.command == "reset-password":
            staff.set_password(connection, args.username, read_password(args.password_stdin))
            print(f"Reset password for {args.username!r}; existing sessions ended")
        else:
            staff.set_active(connection, args.username, args.command == "enable")
            print(f"{args.command.capitalize()}d staff account {args.username!r}")
    except (DataError, LookupError, sqlite3.Error) as exc:
        print(f"error: {str(exc).strip(chr(34) + chr(39))}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
