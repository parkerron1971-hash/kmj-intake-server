"""The API does not publish its own map.

FastAPI serves /docs, /redoc and /openapi.json unless told not to, so the
schema for every internal route — every path, parameter and response
shape — was reachable without authentication. Default is now off, with
ENABLE_API_DOCS=1 as the local-development escape hatch.

The opt-in RULE is tested through api_docs_enabled() rather than by
reloading the module: a reload re-registers ~100 routers and 20
scheduler jobs, which is an expensive and side-effecting way to check a
string comparison. The live app object is asserted separately.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import kmj_intake_automation as kia


class TestTheLiveApp:
    """CI runs without ENABLE_API_DOCS, so the app built at import time
    is the one that would be deployed."""

    def test_schema_urls_are_unset(self):
        assert kia.app.docs_url is None
        assert kia.app.redoc_url is None
        assert kia.app.openapi_url is None

    def test_no_schema_route_is_registered(self):
        """Stronger than 'unset': not routable at all."""
        paths = {getattr(r, "path", "") for r in kia.app.routes}
        assert "/openapi.json" not in paths
        assert "/docs" not in paths
        assert "/redoc" not in paths


class TestTheOptInRule:
    def test_unset_is_off(self, monkeypatch):
        monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
        assert kia.api_docs_enabled() is False

    def test_exactly_one_opts_in(self, monkeypatch):
        monkeypatch.setenv("ENABLE_API_DOCS", "1")
        assert kia.api_docs_enabled() is True

    def test_surrounding_whitespace_still_opts_in(self, monkeypatch):
        monkeypatch.setenv("ENABLE_API_DOCS", "  1  ")
        assert kia.api_docs_enabled() is True

    @pytest.mark.parametrize("value", ["", " ", "0", "true", "TRUE", "yes",
                                       "on", "enabled", "11", "1,1"])
    def test_nothing_else_opts_in(self, monkeypatch, value):
        """A truthy-LOOKING string must not open the schema by accident —
        the common way a secure default gets undone."""
        monkeypatch.setenv("ENABLE_API_DOCS", value)
        assert kia.api_docs_enabled() is False
