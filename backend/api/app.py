from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from analysis_db.contracts import REVIEW_TABLES, STAFF_TABLES, TABLES, DataError
from analysis_db.storage import assert_schema, connect_database
from api import auth, routes


def create_app(db_path: Path, video_dir: Path) -> FastAPI:
    """Build the service; refuses to start unless the database has every required table."""
    with closing(connect_database(db_path, must_exist=True)) as connection:
        assert_schema(connection, tables=TABLES + REVIEW_TABLES + STAFF_TABLES)
    app = FastAPI(title="TPA Video Review", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.db_path = Path(db_path)
    app.state.video_dir = Path(video_dir)

    @app.exception_handler(DataError)
    def data_error(request: Request, exc: DataError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(LookupError)
    def not_found(request: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.public)
    app.include_router(auth.router)
    app.include_router(routes.router)
    return app
