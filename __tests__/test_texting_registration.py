"""Texting under each business's own name (Twilio ISV), step 1 (2026-10-11).

docs/plans/ISV_TEXTING_PLAN_2026-10-11.md. Pinned here:
  1. The answers: what Twilio needs, checked; an EIN can never be saved.
  2. The words Twilio reads name the business everywhere, follow Twilio's
     rejection reasons, and point at the business's own pages.
  3. The pages /texting-terms and /texting-privacy, in the business's name,
     with STOP, HELP, rates and the privacy line reviewers look for.
  4. The owner's routes: owner only, nothing sent to Twilio, no changes once
     it's with Twilio.
"""
from __future__ import annotations

import asyncio
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


def test_owner_only_and_no_twilio_calls():
    src = pathlib.Path(tr.__file__).read_text(encoding="utf-8")
    assert src.count('business_access("owner")') == 2 and 'business_access("viewer")' not in src
    assert "twilio_sms" not in src and "import twilio" not in src
