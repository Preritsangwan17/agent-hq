"""FastAPI app factory. Run with `python -m hq.api` (uvicorn, 127.0.0.1:HQ_PORT or 0.0.0.0 when HQ_LAN=1)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from hq import __version__, settings
from hq.api.jsonsafe import SafeJSONResponse as JSONResponse
from hq.api import routes_ai, auth, routes, routes_career, routes_email_module, routes_insights, routes_gmail, routes_inbox, routes_models, routes_pipeline, routes_settings, spa, stream
from hq.db.conn import connect, tx
from hq.db.migrate import migrate
from hq.db.seed import seed_all

log = logging.getLogger("hq.api")


def create_app() -> FastAPI:
    settings.load_env()
    settings.ensure_dirs()
    auth.ensure_session_secret()
    conn = connect()
    try:
        migrate(conn)
        with tx(conn):
            seed_all(conn)
    finally:
        conn.close()

    app = FastAPI(title="Agent HQ", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
                  default_response_class=JSONResponse)
    app.state.login_limiter = auth.RateLimiter(limit=5, window_s=60)
    app.add_middleware(auth.SecurityMiddleware)

    @app.exception_handler(auth.ApiError)
    async def api_error(_: Request, exc: auth.ApiError) -> JSONResponse:
        body = {"error": exc.error}
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = [{"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": "invalid request", "detail": detail}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # full traceback in data/logs/api.log; the page shows the one-line reason instead of a bare 500
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": f"server error: {type(exc).__name__}: {str(exc)[:200]}",
                             "detail": "details in data/logs/api.log"}, status_code=500)

    app.include_router(routes.public)
    app.include_router(routes.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_insights.router)
    app.include_router(routes_models.router)
    app.include_router(routes_ai.router)
    app.include_router(routes_pipeline.router)
    app.include_router(routes_gmail.router)
    app.include_router(routes_inbox.router)
    app.include_router(routes_career.router)
    app.include_router(routes_email_module.router)
    app.include_router(stream.router)
    spa.mount_spa(app)
    return app
