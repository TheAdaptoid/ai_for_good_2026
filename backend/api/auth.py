import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from analysis_db import staff
from analysis_db.contracts import StaffAccount
from analysis_db.storage import connect_database
from api.schemas import LoginRequest

COOKIE = "tpa_session"


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(connect_database(request.app.state.db_path, must_exist=True)) as connection:
        yield connection


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def current_staff(request: Request, connection: Db) -> StaffAccount:
    account = staff.resolve_session(connection, request.cookies.get(COOKIE))
    if account is None:
        raise HTTPException(401, "sign in required")
    return account


Staff = Annotated[StaffAccount, Depends(current_staff)]

public = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(current_staff)])


@public.post("/login")
def login(body: LoginRequest, response: Response, connection: Db) -> StaffAccount:
    account = staff.authenticate(connection, body.username, body.password)
    if account is None:
        raise HTTPException(401, "invalid username or password")
    # shortcut: no Secure flag because the service runs on plain-HTTP localhost; set it if
    # the service is ever exposed over HTTPS.
    response.set_cookie(COOKIE, staff.create_session(connection, account), httponly=True,
                        samesite="strict", max_age=int(staff.SESSION_LIFETIME.total_seconds()))
    return account


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, connection: Db) -> None:
    staff.end_session(connection, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, httponly=True, samesite="strict")


@router.get("/me")
def me(account: Staff) -> StaffAccount:
    return account
