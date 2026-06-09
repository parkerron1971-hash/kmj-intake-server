"""CORS-on-error middleware — every error response must carry the CORS header
so the browser can read the body (otherwise a 500 looks like a CORS block)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import cors_error_handlers

ORIGIN = "http://localhost:5173"


def _app() -> TestClient:
    app = FastAPI()
    # Same config as the real app.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    cors_error_handlers.install(app)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/http500")
    def http500():
        raise HTTPException(500, "deliberate http 500")

    @app.get("/needs")
    def needs(x: int):
        return {"x": x}

    return TestClient(app, raise_server_exceptions=False)


def _acao(resp):
    return resp.headers.get("access-control-allow-origin")


def test_cors_on_unhandled_500():
    c = _app()
    r = c.get("/boom", headers={"origin": ORIGIN})
    assert r.status_code == 500
    assert _acao(r) == "*"
    body = r.json()
    assert "RuntimeError" in body["detail"] and "trace_id" in body  # name+msg, no stack


def test_cors_on_httpexception_500():
    c = _app()
    r = c.get("/http500", headers={"origin": ORIGIN})
    assert r.status_code == 500
    assert _acao(r) == "*"
    assert r.json()["detail"] == "deliberate http 500"


def test_cors_on_404():
    c = _app()
    r = c.get("/does-not-exist", headers={"origin": ORIGIN})
    assert r.status_code == 404
    assert _acao(r) == "*"


def test_cors_on_422_validation():
    c = _app()
    r = c.get("/needs", headers={"origin": ORIGIN})   # missing required ?x
    assert r.status_code == 422
    assert _acao(r) == "*"


def test_success_still_has_cors():
    c = _app()
    r = c.get("/ok", headers={"origin": ORIGIN})
    assert r.status_code == 200
    assert _acao(r) == "*"          # CORSMiddleware still handles success
    # exactly one ACAO header (no duplicate from the error handlers)
    assert r.headers.get_list("access-control-allow-origin") == ["*"]
