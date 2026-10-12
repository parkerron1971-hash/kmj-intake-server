"""Texting under each business's own name (Twilio ISV), steps 1 and 3 (2026-10-11).

docs/plans/ISV_TEXTING_PLAN_2026-10-11.md. Pinned here:
  1. The answers: what Twilio needs, checked; an EIN is never saved in them.
  2. The words Twilio reads name the business everywhere, follow Twilio's
     rejection reasons, and point at the business's own pages.
  3. The pages /texting-terms and /texting-privacy, in the business's name,
     with STOP, HELP, rates and the privacy line reviewers look for.
  4. The owner's routes: owner only, saving sends nothing, no changes once
     it's with Twilio.
  5. Step 3: the EIN kept with the business's legal details; sending (only
     when open and ready, once); every change told to the owner; Twilio's
     pings and the sweep moving each registration along.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_registration as tr  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
ORIGIN = "https://northside.mysolutionist.app"
GOOD = {"legal_name": "Northside Cuts LLC", "business_type": "llc", "has_ein": True, "street": "12 Main St",
        "city": "Muskegon", "state": "mi", "postal_code": "49441", "website": "https://northsidecuts.com",
        "rep_first_name": "Andre", "rep_last_name": "Smith", "rep_title": "Owner", "rep_email": "andre@example.com",
        "rep_phone": "(231) 555-0100"}


def run(x):
    return asyncio.run(x)


# ── 1. the answers ────────────────────────────────────────────────────

def test_the_answers_are_checked_and_tidied():
    a = tr.Answers(**GOOD)
    assert a.state == "MI" and a.rep_phone == "+12315550100"
    assert tr.brand_path(a.model_dump()) == "low_volume_standard"
    assert tr.brand_path({**GOOD, "business_type": "sole_proprietor", "has_ein": False}) == "sole_proprietor"
    assert tr.brand_path(None) is None
    for bad, why in (({"business_type": "empire"}, "Choose sole proprietor"), ({"state": "XX"}, "two-letter state"),
                     ({"postal_code": "4944"}, "five-digit ZIP"), ({"website": "northside.com"}, "https://"),
                     ({"rep_email": "andre"}, "email address"), ({"rep_phone": "555-0100"}, "US phone number"),
                     ({"business_type": "sole_proprietor", "has_ein": True}, "sole proprietor with an EIN")):
        with pytest.raises(ValidationError, match=re.escape(why)):
            tr.Answers(**{**GOOD, **bad})


def test_an_ein_can_never_be_saved():
    with pytest.raises(ValidationError):
        tr.Answers(**GOOD, ein="12-3456789")
    sql = pathlib.Path(tr.__file__).resolve().parent.joinpath(
        "supabase", "APPLY-2026-10-11-texting-registrations.sql").read_text(encoding="utf-8")
    assert "CHECK (NOT (answers ? 'ein'))" in sql and "ENABLE ROW LEVEL SECURITY" in sql


# ── 2. the words Twilio reads ─────────────────────────────────────────

def test_the_campaign_names_the_business_and_follows_the_rejection_reasons():
    w = tr.campaign_words("Northside Cuts", ORIGIN)
    assert w["use_case"] == "LOW_VOLUME"
    assert w["description"].startswith("Northside Cuts texts its own clients who opted in")
    assert "only to clients who separately agreed to them, occasional offers" in w["description"]
    assert len(w["samples"]) >= 2
    for s in w["samples"]:
        assert "Northside Cuts" in s and "STOP" in s, s
    for words in (w["opt_in_message"], w["opt_out_message"], w["help_message"]):
        assert words.startswith("Northside Cuts"), words
    # The opt-in boxes quoted word for word, both naming the business; offers apart.
    assert f'"{tr.booking_box("Northside Cuts")}"' in w["message_flow"]
    assert f'"{tr.offers_box("Northside Cuts")}"' in w["message_flow"]
    assert "Solutionist" not in tr.booking_box("Northside Cuts") + tr.offers_box("Northside Cuts")
    assert w["terms_url"] == f"{ORIGIN}/texting-terms" and w["privacy_url"] == f"{ORIGIN}/texting-privacy"
    links = re.findall(r"https?://\S+", " ".join(w["samples"]) + w["message_flow"])
    assert links and all(l.startswith(ORIGIN) for l in links)             # the business's own site, no shorteners


# ── 3. the pages ──────────────────────────────────────────────────────

def test_the_pages_say_what_reviewers_look_for():
    terms = tr.terms_html("Northside Cuts", ORIGIN, "hello@northsidecuts.com")
    privacy = tr.privacy_html("Northside Cuts", ORIGIN)
    for page in (terms, privacy):
        assert "Northside Cuts" in page and "<strong>STOP</strong>" in page and "<strong>HELP</strong>" in page
        assert "We do not sell or share your mobile number or your SMS opt-in data" in page
        assert f'href="{ORIGIN}/texting-terms"' in page and f'href="{ORIGIN}/texting-privacy"' in page
        assert "@media (prefers-color-scheme: dark)" in page and 'name="viewport"' in page
    assert "Message and data rates may apply" in terms and "never required to book" in terms
    assert "mailto:hello@northsidecuts.com" in terms and "mailto:" not in privacy
    evil = tr.terms_html("<script>x</script>", ORIGIN)
    assert "<script>x" not in evil and "&lt;script&gt;" in evil


def test_the_business_site_serves_the_pages(monkeypatch):
    import public_site
    assert {"/texting-terms", "/texting-privacy"} <= set(public_site._ALWAYS_WINS_PATHS)
    reads = []

    def read(path):
        reads.append(path)
        return [{"id": BIZ, "name": "Northside Cuts", "settings": {}}]

    monkeypatch.setattr(tr, "_read", read)
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    monkeypatch.setattr(public_site, "_business_public_email", lambda s: "")
    page = run(tr.page_for(BIZ, "terms"))
    assert page and "<title>Text messaging terms | Northside Cuts</title>" in page
    assert "Text messaging privacy policy" in run(tr.page_for(BIZ, "privacy"))
    monkeypatch.setattr(tr, "site_origin", lambda bid: None)                  # no site: no page
    assert run(tr.page_for(BIZ, "terms")) is None
    src = pathlib.Path(public_site.__file__).read_text(encoding="utf-8")
    assert 'if normalized_path in ("/texting-terms", "/texting-privacy"):' in src


# ── 4. the owner's routes ─────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    import business_marketing_links as links
    state = {"row": None, "posts": []}
    app = FastAPI()
    app.include_router(tr.router)

    def post(path, row, prefer=None):
        state["posts"].append((path, row, prefer))
        state["row"] = {**(state["row"] or {}), **row}
        return [state["row"]]

    monkeypatch.setattr(tr, "registration", lambda bid: state["row"])
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    monkeypatch.setattr(tr, "ein_for", lambda bid, biz=None: state.get("ein"))
    monkeypatch.setattr(links, "bookable", lambda bid, biz: True)
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", post)
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for d in r.dependant.dependencies:
                if d.name == "biz":
                    app.dependency_overrides[d.call] = lambda: {"id": BIZ, "name": "Northside Cuts", "settings": {}}
    return TestClient(app), state


def test_the_owner_reads_what_twilio_will_see(api):
    client, state = api
    body = client.get(f"/texting/registration/{BIZ}").json()
    assert body["status"] == "not_started" and body["answers"] is None and body["brand_path"] is None
    checks = {c["key"]: c["ok"] for c in body["readiness"]}
    assert checks == {"site": True, "booking": True, "pages": True, "answers": False}
    assert body["words"]["description"].startswith("Northside Cuts texts")
    assert body["pages"] == {"terms": f"{ORIGIN}/texting-terms", "privacy": f"{ORIGIN}/texting-privacy"}


def test_saving_the_answers_sends_nothing_and_stops_once_with_twilio(api):
    client, state = api
    r = client.put(f"/texting/registration/{BIZ}", json=GOOD)
    assert r.status_code == 200, r.text
    [(path, row, prefer)] = state["posts"]
    assert path == "/texting_registrations?on_conflict=business_id" and "merge-duplicates" in prefer
    assert row["status"] == "draft" and row["answers"]["rep_phone"] == "+12315550100" and "ein" not in row["answers"]
    assert r.json()["brand_path"] == "low_volume_standard"
    assert {c["key"]: c["ok"] for c in r.json()["readiness"]}["answers"] is True
    assert client.put(f"/texting/registration/{BIZ}", json={**GOOD, "ein": "12-3456789"}).status_code == 422
    state["row"]["status"] = "brand_pending"
    r = client.put(f"/texting/registration/{BIZ}", json=GOOD)
    assert r.status_code == 409 and "with Twilio already" in r.json()["detail"]


def test_owner_only_and_twilio_only_through_texting_isv():
    src = pathlib.Path(tr.__file__).read_text(encoding="utf-8")
    # get, save, EIN, send: owner only. The status ping takes no business id.
    assert src.count('business_access("owner")') == 4 and 'business_access("viewer")' not in src
    # Twilio only through texting_isv; twilio_sms only to take a number off our shared pool (step 4).
    assert set(re.findall(r"twilio_sms\.(\w+)", src)) == {"detach_from_service"}
    assert not re.search(r"^import twilio$", src, re.M) and "twilio.com" not in src


# ── 5. step 3: the EIN, sending, updates ──────────────────────────────

READY = {**GOOD, "industry": "CONSUMER"}


@pytest.fixture
def sending(api, monkeypatch):
    """The routes, plus the status writes and the background send recorded."""
    client, state = api
    state.update(patches=[], sent=[], told=[], ein="12-3456789")

    def patch(bid, fields, *, when=None):
        state["patches"].append((fields, when))
        row = state["row"]
        if row is None or (when and row.get("status") not in when):
            return []
        row.update(fields)
        return [dict(row)]

    async def fake_send(biz, row):
        state["sent"].append(row)
        return "brand_pending"

    monkeypatch.setattr(tr, "_patch", patch)
    monkeypatch.setattr(tr, "_send", fake_send)
    monkeypatch.setenv("TEXTING_REGISTRATION_OPEN", BIZ)
    return client, state


def test_the_ein_is_kept_with_the_business_details_never_the_registration(sending, monkeypatch):
    client, state = sending
    import business_identity
    writes = []
    monkeypatch.setattr(business_identity, "set_identity",
                        lambda bid, **f: writes.append((bid, f)) or {"business_id": bid, **f})
    r = client.put(f"/texting/registration/{BIZ}/ein", json={"ein": "123456789"})
    assert r.status_code == 200, r.text
    assert writes == [(BIZ, {"ein": "12-3456789"})] and state["posts"] == []      # not the registration
    for bad in ("1234", "12-34567890", "AB-CDEFGHI"):
        assert client.put(f"/texting/registration/{BIZ}/ein", json={"ein": bad}).status_code == 422
    client.put(f"/texting/registration/{BIZ}", json=READY)
    body = client.get(f"/texting/registration/{BIZ}").json()
    assert body["ein"] == {"on_file": True, "last4": "6789"}
    assert "12-3456789" not in json.dumps(body)                                   # only the last four go out
    checks = {c["key"]: c["ok"] for c in body["readiness"]}
    assert checks["ein"] is True and checks["industry"] is True
    state["ein"] = None
    checks = {c["key"]: c["ok"] for c in client.get(f"/texting/registration/{BIZ}").json()["readiness"]}
    assert checks["ein"] is False


def test_sending_only_when_open_and_ready_and_only_once(sending, monkeypatch):
    client, state = sending
    client.put(f"/texting/registration/{BIZ}", json=GOOD)                         # no industry yet
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 400 and "industry" in r.json()["detail"] and not state["sent"]
    client.put(f"/texting/registration/{BIZ}", json=READY)
    monkeypatch.setenv("TEXTING_REGISTRATION_OPEN", "")
    view = client.get(f"/texting/registration/{BIZ}").json()
    assert view["open"] is False and view["can_send"] is False
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 409 and "isn't open" in r.json()["detail"] and not state["sent"]
    monkeypatch.setenv("TEXTING_REGISTRATION_OPEN", "*")
    assert client.get(f"/texting/registration/{BIZ}").json()["can_send"] is True
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 200, r.text
    assert state["patches"][-1] == ({"status": "submitted", "failure": None}, tr.EDITABLE)
    assert [row["status"] for row in state["sent"]] == ["submitted"]               # marked before it leaves
    assert r.json()["status"] == "submitted" and r.json()["steps"][0]["state"] == "now"
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 409 and len(state["sent"]) == 1                        # a second press sends nothing


def test_no_ein_and_sent_back_after_review_are_not_resent(sending):
    client, state = sending
    client.put(f"/texting/registration/{BIZ}", json={**READY, "business_type": "sole_proprietor",
                                                      "has_ein": False, "industry": None})
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 409 and "with an EIN" in r.json()["detail"]
    client.put(f"/texting/registration/{BIZ}", json=READY)
    state["row"].update(status="failed", twilio={"rejected_after_review": True}, failure="TAX_ID mismatch")
    view = client.get(f"/texting/registration/{BIZ}").json()
    assert view["can_send"] is False and view["failure"] == "TAX_ID mismatch" and view["rejected_after_review"]
    r = client.post(f"/texting/registration/{BIZ}/send")
    assert r.status_code == 409 and "taking it up with Twilio" in r.json()["detail"] and not state["sent"]


def _rig(monkeypatch, row):
    """_send/_check against a fake texting_isv and a recorded owner."""
    state = {"row": dict(row), "told": [], "patches": []}

    def patch(bid, fields, *, when=None):
        state["patches"].append((fields, when))
        if when and state["row"].get("status") not in when:
            return []
        state["row"].update(fields)
        return [dict(state["row"])]

    async def tell(biz, status, reasons=None):
        state["told"].append((status, reasons))
        return {}

    monkeypatch.setattr(tr, "_patch", patch)
    monkeypatch.setattr(tr, "_tell_owner", tell)
    monkeypatch.setattr(tr, "ein_for", lambda bid, biz=None: "12-3456789")
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    return state


BUSINESS = {"id": BIZ, "name": "Northside Cuts", "owner_id": "u1", "settings": {}}


def test_a_send_tells_the_owner_how_it_went(monkeypatch):
    state = _rig(monkeypatch, {"status": "submitted", "answers": READY, "twilio": {}})
    seen = {}

    def ok(t, **kw):
        seen.update(kw, t=dict(t))
        return t

    monkeypatch.setattr(tr.texting_isv, "send", ok)
    assert run(tr._send(BUSINESS, state["row"])) == "brand_pending"
    assert state["row"]["status"] == "brand_pending" and state["told"] == [("brand_pending", None)]
    assert seen["ein"] == "12-3456789" and seen["website"] == "https://northsidecuts.com"
    assert seen["callback"].endswith("/texting/twilio-status")
    words = seen["t"]["campaign_words"]                                    # the words the owner saw, kept
    assert words["description"].startswith("Northside Cuts texts") and seen["t"]["sent_at"]

    def needs_fix(t, **kw):
        raise tr.texting_isv.NeedsFix(["The Business Name is missing."])

    state = _rig(monkeypatch, {"status": "submitted", "answers": READY, "twilio": {}})
    monkeypatch.setattr(tr.texting_isv, "send", needs_fix)
    assert run(tr._send(BUSINESS, state["row"])) == "failed"
    assert state["row"]["failure"] == "The Business Name is missing."
    assert state["told"] == [("failed", ["The Business Name is missing."])]

    def down(t, **kw):
        raise tr.texting_isv.TwilioDown("503")

    state = _rig(monkeypatch, {"status": "submitted", "answers": READY, "twilio": {}})
    monkeypatch.setattr(tr.texting_isv, "send", down)
    assert run(tr._send(BUSINESS, state["row"])) == "submitted"
    assert state["row"]["status"] == "submitted" and state["told"] == []     # nothing to tell; the sweep retries


def test_where_it_stands_is_told_once_per_change(monkeypatch):
    sent = {"account_sid": "AC" + "2" * 32, "brand_sid": "BN1", "service_sid": "MG1"}
    state = _rig(monkeypatch, {"status": "brand_pending", "twilio": sent})
    stages = iter([{"stage": "brand", "reasons": []}, {"stage": "campaign", "reasons": []},
                   {"stage": "campaign", "reasons": []}, {"stage": "approved", "reasons": []}])
    monkeypatch.setattr(tr.texting_isv, "check", lambda t, save: next(stages))
    for _ in range(4):
        run(tr._check(BUSINESS, state["row"]))
    assert state["row"]["status"] == "approved"
    assert [s for s, _ in state["told"]] == ["campaign_pending", "approved"]

    state = _rig(monkeypatch, {"status": "campaign_pending", "twilio": sent})
    monkeypatch.setattr(tr.texting_isv, "check",
                        lambda t, save: {"stage": "failed", "reasons": ["Opt-in names a different business."]})
    assert run(tr._check(BUSINESS, state["row"])) == "failed"
    assert state["row"]["twilio"]["rejected_after_review"] is True
    assert state["told"] == [("failed", ["Opt-in names a different business."])]


def test_the_sweep_resumes_a_stalled_send_but_not_a_running_one(monkeypatch):
    now = tr._now()
    rows = {"fresh": {"status": "submitted", "updated_at": now.isoformat(), "twilio": {}},
            "stale": {"status": "submitted", "updated_at": (now - tr.timedelta(minutes=30)).isoformat(),
                      "twilio": {}}}
    resumed = []

    async def fake_send(biz, row):
        resumed.append(row)
        return "brand_pending"

    monkeypatch.setattr(tr, "_send", fake_send)
    monkeypatch.setattr(tr, "_business", lambda bid: BUSINESS)
    for key, expect in (("fresh", "submitted"), ("stale", "brand_pending")):
        monkeypatch.setattr(tr, "registration", lambda bid, r=rows[key]: r)
        assert run(tr.advance(BIZ)) == expect
    assert len(resumed) == 1

    monkeypatch.setattr(tr, "_read", lambda path: [{"business_id": BIZ, "status": "brand_pending"}])
    monkeypatch.setattr(tr, "advance", lambda bid: _done("campaign_pending"))
    assert run(tr.sweep_tick()) == {"checked": 1, "moved": 1}


async def _done(value):
    return value


def test_twilios_ping_only_names_which_registration_to_ask_about(monkeypatch):
    app = FastAPI()
    app.include_router(tr.router)
    client = TestClient(app)
    queries, advanced = [], []
    monkeypatch.setattr(tr, "_read", lambda path: queries.append(path) or [{"business_id": BIZ}])
    monkeypatch.setattr(tr, "_background", lambda coro: advanced.append(coro) or coro.close())
    monkeypatch.setattr(tr, "_POKED", {})
    sub = "AC" + "2" * 32
    assert client.post("/texting/twilio-status", data={"AccountSid": sub, "Status": "twilio-approved"}).status_code == 204
    assert f"twilio->>account_sid.eq.{sub}" in queries[0] and len(advanced) == 1
    client.post("/texting/twilio-status", data={"AccountSid": sub})
    assert len(advanced) == 1                                                # at most once a minute
    queries.clear()
    client.post("/texting/twilio-status", data={"AccountSid": "AC1);drop", "BundleSid": "nope"})
    assert queries == []                                                     # nothing odd reaches the query


def test_the_owner_hears_in_the_app_by_push_and_by_email(monkeypatch):
    import email_domain_monitor
    import email_sender
    import push_notifications
    posts, pushes, emails = [], [], []
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", lambda path, row, *a: posts.append((path, row)) or [row])
    monkeypatch.setattr(push_notifications, "send_to_business", lambda bid, **kw: pushes.append(kw) or 1)

    async def owner_email(uid):
        return "andre@example.com"

    async def resend(**kw):
        emails.append(kw)

    monkeypatch.setattr(email_domain_monitor, "_owner_email", owner_email)
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    out = run(tr._tell_owner(BUSINESS, "failed", ["The EIN doesn't match the legal name."]))
    assert out == {"in_app": True, "push": True, "email": True}
    [(path, row)] = posts
    assert path == "/chief_notifications" and row["data"]["nav"] == {"tab": "operate", "sub": "sms"}
    assert row["title"] == "Your texting registration needs a fix" and row["priority"] == "high"
    assert row["body"].startswith("The EIN doesn't match the legal name. Open Operate, Text")
    assert pushes[0]["nav"] == "operate:sms" and emails[0]["to_email"] == "andre@example.com"
    assert run(tr._tell_owner(BUSINESS, "approved"))["in_app"]
    assert posts[-1][1]["title"] == "Northside Cuts can text under its own name"

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", boom)
    monkeypatch.setattr(push_notifications, "send_to_business", boom)
    assert run(tr._tell_owner(BUSINESS, "brand_pending"))["in_app"] is False     # never raises


def test_who_can_send_is_a_switch():
    import os
    for raw, expect in (("", False), ("*", True), (BIZ, True), (f"x, {BIZ}", True), ("someone-else", False)):
        os.environ["TEXTING_REGISTRATION_OPEN"] = raw
        assert tr.is_open(BIZ) is expect, raw
    os.environ.pop("TEXTING_REGISTRATION_OPEN", None)
