"""Reconnecting a mailbox that is already connected must replace the
row, not collide with it.

google_mailboxes has a generated uuid primary key and a UNIQUE on
(business_id, google_email). PostgREST's merge-duplicates resolves
against the primary key unless the conflict columns are named, so an
un-named upsert inserts a second row and the unique constraint rejects
it. The first connect always worked; every reconnect failed.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import google_oauth  # noqa: E402
import oauth_connect_ticket  # noqa: E402
import sb_clients  # noqa: E402


def test_reconnect_upsert_names_the_unique_columns(monkeypatch):
    posted = {}

    monkeypatch.setattr(oauth_connect_ticket, "verify",
                        lambda state, max_age_s=None: ("biz-1", "user-1"))

    async def _exchange(client, code):
        return {"access_token": "a", "refresh_token": "r",
                "expires_in": 3600, "scope": google_oauth.GOOGLE_SCOPES}

    async def _profile(client, token):
        return {"email": "owner@example.com"}

    def _post(path, body, prefer=None):
        posted["path"] = path
        posted["prefer"] = prefer
        return [dict(body, id="row-1")]

    monkeypatch.setattr(google_oauth, "_exchange_code", _exchange)
    monkeypatch.setattr(google_oauth, "_fetch_gmail_address", _profile)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _post)

    resp = asyncio.run(google_oauth.google_callback(code="code", state="state"))

    assert resp.status_code == 200
    assert posted["path"].startswith("/google_mailboxes?")
    assert "on_conflict=business_id,google_email" in posted["path"]
    assert "resolution=merge-duplicates" in (posted["prefer"] or "")
