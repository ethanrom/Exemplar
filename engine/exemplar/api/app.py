"""The FastAPI app implementing every path of `contracts/api.yaml`.

    from exemplar.api.app import create_app
    app = create_app()                      # settings from .env
    app = create_app(services=Services(run_cegis=fake, ...), start_background=False)   # tests

`exemplar.api.app.app` (module attribute, built on first access) is the default instance for
`uvicorn exemplar.api.app:app`; `python -m exemplar.api` is the normal entry point.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from exemplar.ring import RingError
from exemplar.settings import Settings

from .config import ApiConfig
from .errors import ApiError, error_body, ring_error
from .routes import ROUTERS
from .services import Services
from .state import AppState

log = logging.getLogger("exemplar.api")

_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for e in exc.errors()[:5]:
        loc = ".".join(str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return "invalid request: " + "; ".join(parts)


def create_app(*, state: AppState | None = None, settings: Settings | None = None, config: ApiConfig | None = None,
               services: Services | None = None, start_background: bool = True, **state_kw: Any) -> FastAPI:
    st = state or AppState(settings=settings, config=config, services=services, **state_kw)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        st.loop = asyncio.get_running_loop()
        failed = st.store.runs.fail_stale()
        if failed:
            log.warning("marked %d interrupted teach run(s) failed", failed)
        if start_background:
            st.pipeline.start()
        try:
            yield
        finally:
            await st.pipeline.stop()
            await st.close_ring()
            st.shutdown()

    app = FastAPI(title="Exemplar engine API", version="1.0.0", lifespan=lifespan,
                  description="REST + SSE contract: engine/exemplar/contracts/api.yaml")
    app.state.ex = st
    for r in ROUTERS:
        app.include_router(r)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RingError)
    async def _ring_error(_: Request, e: RingError) -> JSONResponse:
        ae = ring_error(e)
        return JSONResponse(ae.body(), status_code=ae.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        return JSONResponse(error_body(_validation_message(e), "INVALID_PAYLOAD"), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body(str(e.detail), _CODES.get(e.status_code)), status_code=e.status_code,
                            headers=getattr(e, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(error_body("internal error", "INTERNAL"), status_code=500)

    return app


_default: FastAPI | None = None


def __getattr__(name: str) -> Any:        # `exemplar.api.app:app` for uvicorn, without side effects at import time
    global _default
    if name == "app":
        if _default is None:
            _default = create_app()
        return _default
    raise AttributeError(name)
