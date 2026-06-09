"""
cors_error_handlers.py — guarantee CORS headers on ALL error responses.

Problem: an unhandled exception is caught by Starlette's ServerErrorMiddleware,
which sits OUTSIDE CORSMiddleware, so the 500 response carries no
Access-Control-Allow-Origin header and the browser blocks the body — every
production error becomes invisible to the frontend.

Fix: register app-level exception handlers (Exception, HTTPException,
RequestValidationError) that build the JSON error response AND stamp the CORS
headers manually. Mirrors the app's existing CORSMiddleware config exactly
(allow_origins=["*"], no credentials) so there is never a duplicate/invalid
header — ACAO:* + ACAC:true would be rejected by browsers, so credentials are
intentionally omitted.

Full stack traces go to the logs (with a short trace_id); the client only
gets the error name + message + trace_id (no stack in the response).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("kmj.errors")

# Mirror the existing CORSMiddleware (allow_origins=["*"], allow_methods=["*"],
# allow_headers=["*"], no credentials). Same values → can't conflict with the
# middleware on responses it also touches.
_CORS_ON_ERROR = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "*",
    "Access-Control-Allow-Headers": "*",
}


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        # Faithfully replicate FastAPI's default (status + detail + headers),
        # plus CORS. Covers routing 404s and every raise HTTPException(...).
        headers = dict(exc.headers or {})
        headers.update(_CORS_ON_ERROR)
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422,
                            content={"detail": jsonable_encoder(exc.errors())},
                            headers=dict(_CORS_ON_ERROR))

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception):
        trace_id = uuid.uuid4().hex[:8]
        logger.exception(
            f"[unhandled trace={trace_id}] {request.method} {request.url.path}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}", "trace_id": trace_id},
            headers=dict(_CORS_ON_ERROR))
