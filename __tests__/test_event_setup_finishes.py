"""Setting up an event finishes: the offering, the form, the answer.

2026-09-18, Kevin, on a call, "Embrace the Shift Workshop":

- Creating the offering again on the follow-up turn (the one that added
  the address) was refused, and the refusal read the model's own hint
  aloud: "Try update_offering instead, or pick a different name."
- The registration form failed with "I couldn't save that form just
  now": the handler accepted form_type "waitlist", the database CHECK
  did not. The prompt's own example ("intake") failed the same way.
- "So there's already a workshop on file?" was answered with the bare
  receipt label "Embrace the Shift Workshop: updated" because a prose
  gap with a receipt in the turn dropped the whole answer.
- Chief told him event registration "isn't built yet on the platform".
  It is (event_roster modules + /events RSVP); the prompt never said so
  and the modules block never showed a module's archetype.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
from unittest.mock import AsyncMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

import chief_of_staff  # noqa: F401  (chief_prompt imports back from it; load the host first)
import chief_form_actions as forms
import chief_offering_actions as offerings
import chief_truth as truth

_BIZ = {"id": "biz-1", "owner_id": "user-1", "name": "KMJ Creative Solutions",
        "type": "coach", "settings": {}}


# ── the offering ──────────────────────────────────────────────────────

def _sb_recorder(routes):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        for (m, prefix), resp in routes.items():
            if method == m and path.startswith(prefix):
                return resp(body) if callable(resp) else resp
        return []

    return fake_sb, calls


def test_creating_an_offering_already_on_file_updates_it_and_says_so(monkeypatch):
    existing = {"id": "off-1", "name": "Embrace the Shift Workshop", "archived_at": None}
    fake_sb, calls = _sb_recorder({
        ("GET", "/offerings?business_id=eq.biz-1&slug=eq."): [existing],
        ("PATCH", "/offerings?id=eq.off-1"): lambda body: [{**existing, **body}],
    })
    monkeypatch.setattr(offerings, "_sb", fake_sb)
    monkeypatch.setattr(offerings, "_refresh_composed_site_bg", lambda _b: None)
    res = asyncio.run(offerings.handle_create_offering(None, _BIZ, {
        "name": "Embrace the Shift Workshop", "category": "event", "current_price": 0,
        "description": "Free workshop. 1084 Allen Avenue, Muskegon, MI 49442."}))
    assert not res.get("failed"), res
    assert res["offering_id"] == "off-1"
    assert "already on file" in res["label"]
    for leak in ("update_offering", "pick a different name", "slug"):
        assert leak not in res["label"] and leak not in res["result"]
    patched = [b for m, p, b in calls if m == "PATCH"]
    assert patched and patched[0]["description"].startswith("Free workshop")
    assert not any(m == "POST" for m, _, _ in calls)


def test_creating_an_archived_offering_again_brings_it_back(monkeypatch):
    existing = {"id": "off-2", "name": "Beard Trim", "archived_at": "2026-08-01T00:00:00Z"}
    fake_sb, calls = _sb_recorder({
        ("GET", "/offerings?business_id=eq.biz-1&slug=eq."): [existing],
        ("PATCH", "/offerings?id=eq.off-2"): lambda body: [{**existing, **body}],
    })
    monkeypatch.setattr(offerings, "_sb", fake_sb)
    monkeypatch.setattr(offerings, "_refresh_composed_site_bg", lambda _b: None)
    res = asyncio.run(offerings.handle_create_offering(None, _BIZ, {"name": "Beard Trim", "category": "service"}))
    assert not res.get("failed")
    revived = [b for m, p, b in calls if m == "PATCH" and b.get("archived_at", "x") is None]
    assert revived and revived[0]["is_active"] is True


# ── the form ──────────────────────────────────────────────────────────

def test_every_form_type_the_code_accepts_is_in_the_migration():
    sql = (ROOT / "supabase" / "APPLY-2026-09-18-intake-form-types.sql").read_text(encoding="utf-8")
    allowed = set(re.findall(r"'([a-z_]+)'", sql.split("ADD CONSTRAINT", 1)[1]))
    assert set(forms._FORM_TYPES) <= allowed, set(forms._FORM_TYPES) - allowed
    assert "event" in forms._FORM_TYPES
    assert "intake" in allowed and "waitlist" in allowed


def test_a_form_is_saved_even_when_the_database_rejects_its_label(monkeypatch):
    posted = []

    def fake_post(path, body, prefer=None):
        posted.append((path, body))
        if path == "/intake_forms" and body["form_type"] != "general":
            return None                       # what the CHECK violation looks like
        return [{"id": "form-1", **body}]

    monkeypatch.setattr(forms.sb_clients, "sb_post_as_service", fake_post)
    res = asyncio.run(forms.handle_create_client_form(None, _BIZ, {
        "name": "Embrace the Shift Workshop Registration", "form_type": "waitlist",
        "fields": [{"label": "Your Name", "type": "text", "required": True},
                   {"label": "Email", "type": "email", "required": True}]}))
    assert not res.get("failed"), res
    saved = [b for p, b in posted if p == "/intake_forms"]
    assert [b["form_type"] for b in saved] == ["waitlist", "general"]
    assert saved[-1]["settings"]["requested_form_type"] == "waitlist"


def test_event_is_a_form_type_the_handler_keeps(monkeypatch):
    posted = []

    def fake_post(path, body, prefer=None):
        posted.append((path, body))
        return [{"id": "form-2", **body}]

    monkeypatch.setattr(forms.sb_clients, "sb_post_as_service", fake_post)
    res = asyncio.run(forms.handle_create_client_form(None, _BIZ, {
        "name": "Workshop Registration", "form_type": "event",
        "fields": [{"label": "Your Name", "type": "text", "required": True}]}))
    assert not res.get("failed"), res
    assert posted[0][1]["form_type"] == "event"


# ── the answer ────────────────────────────────────────────────────────

def test_a_prose_gap_beside_a_receipt_still_delivers_the_answer():
    draft = "Yes, it is already on file. It actually already got created from your last message."
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "It actually already got created from your last message.", "kind": "fact",
         "source_id": "", "quote": "", "gap": "receipt shows an update, not a creation"}]})
    receipt = {"type": "update_offering", "result": "updated",
               "label": "Embrace the Shift Workshop: updated"}
    result, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail="",
        taken=[receipt], message="So there's already an Embrace the Shift workshop that exists?",
        business_id="biz", reviewer=AsyncMock(return_value=raw)))
    assert result.startswith("Yes, it is already on file.")
    assert "still unverified" in result
    assert meta["status"] == "caveated"


# ── the prompt ────────────────────────────────────────────────────────

def test_the_prompt_tells_chief_how_an_event_is_set_up():
    src = (ROOT / "chief_prompt.py").read_text(encoding="utf-8")
    assert "event_roster" in src and "/events" in src
    assert 'form_type "event"' in src
    assert "Never say event registration is not built" in src
    assert "never hold a date or a venue in an offering" in src
