"""The website form door's bot checks (site_form_guard.py, M-5 2026-11-27).

Two website connect cards at Love City were one sales campaign. The door
they came through, POST /sites/{id}/contact-submit, checked its honeypot only
in the visitor's browser and limited per replica. Pinned here:
  1. the token: ours, this church's, not too fast; stale or missing never
     stops a person;
  2. the honeypot, checked on the server;
  3. the door: a bot is thanked and nothing is kept; a person goes on;
  4. the limiter is the shared one;
  5. every served site page carries the script, once.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import public_site
import rate_limit
import site_form_guard as g

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER = "11111111-1111-1111-1111-111111111111"
NOW = 1_795_000_000


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SITE_FORM_SECRET", "test-secret")
    monkeypatch.delenv("SITE_FORM_GUARD", raising=False)


# ── 1. the token ──────────────────────────────────────────────────────

def test_a_token_is_good_for_its_own_church_after_a_human_moment():
    t = g.token(BIZ, now=NOW)
    assert t.startswith("v1.") and str(NOW) in t
    assert g.token_says(BIZ, t, now=NOW + 40) == ""
    assert g.token_says(BIZ, t, now=NOW + 1) == "too_fast"
    assert g.token_says(OTHER, t, now=NOW + 40) == "missing", "another church's page: never thrown away"


def test_a_forged_or_garbled_token_is_a_bot():
    t = g.token(BIZ, now=NOW)
    for bad in (t[:-1] + ("0" if t[-1] != "0" else "1"), "v1.abc.def", "v1.123.def", "v2." + t[3:],
                "x" * 200, 12, ["v1"]):
        assert g.token_says(BIZ, bad, now=NOW + 40) == "bad", bad
    assert g.token_says(BIZ, g.token(BIZ, now=NOW + 3600), now=NOW) == "bad", "from the future"


def test_no_token_or_a_stale_one_never_stops_a_person():
    assert g.token_says(BIZ, None, now=NOW) == "missing"
    assert g.token_says(BIZ, "", now=NOW) == "missing"
    assert g.token_says(BIZ, g.token(BIZ, now=NOW), now=NOW + g.MAX_AGE + 5) == "missing", "a tab left open"
    assert g.verdict(BIZ, {"name": "Dana"}, now=NOW) == ""


def test_with_no_secret_or_switched_off_nothing_is_made_or_checked(monkeypatch):
    t = g.token(BIZ, now=NOW)
    monkeypatch.setenv("SITE_FORM_GUARD", "off")
    assert g.token(BIZ) == "" and g.verdict(BIZ, {"_t": "garbage", "website": "x"}) == ""
    monkeypatch.delenv("SITE_FORM_GUARD")
    monkeypatch.delenv("SITE_FORM_SECRET")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert g.token(BIZ) == "" and g.token_says(BIZ, t, now=NOW + 40) == "missing"


# ── 2. the honeypot ───────────────────────────────────────────────────

@pytest.mark.parametrize("field", ["_hp", "sol-hp"])
def test_a_filled_honeypot_is_a_bot(field):
    assert g.verdict(BIZ, {"name": "Sofia", field: "https://touristsector.com"}) == "honeypot"
    assert g.verdict(BIZ, {"name": "Dana", field: ""}) == ""


@pytest.mark.parametrize("form", ["connect_card", "prayer_request", "connect-card"])
def test_the_church_cards_hidden_website_field_is_a_honeypot(form):
    assert g.verdict(BIZ, {"form": form, "website": "touristsector.com"}) == "honeypot"


def test_a_real_your_website_answer_on_a_business_form_is_kept():
    """The review of #2101, should-fix 1: a coach's or designer's own form
    may ask "Your website" for real."""
    assert g.verdict(BIZ, {"name": "Ana", "email": "ana@studio.example", "website": "https://anastudio.example",
                           "message": "Can we talk?"}) == ""
    assert g.verdict(BIZ, {"form": "contact", "website": "https://anastudio.example"}) == ""


def test_the_verdict_never_raises():
    assert g.verdict(BIZ, None) == "" and g.verdict(BIZ, ["x"]) == ""


# ── 3. the door ───────────────────────────────────────────────────────

@pytest.fixture
def door(monkeypatch):
    state = SimpleNamespace(captured=[], validated=0, rate=[])
    import website_forms

    def validate(body):
        state.validated += 1
        raise ValueError("stop here: a person's card goes on to validation")
    monkeypatch.setattr(website_forms, "validate", validate)
    monkeypatch.setattr(public_site, "_capture_contact_from_form",
                        lambda *a, **kw: state.captured.append(a) or "c1")

    def shared(bucket, key, **kw):
        state.rate.append((bucket, key))
        return True
    monkeypatch.setattr(rate_limit, "allow_shared", shared)
    import sample_church

    async def no(bid):
        return False
    monkeypatch.setattr(sample_church, "is_sample_async", no)
    app = FastAPI()
    app.include_router(public_site.router)
    state.client = TestClient(app)
    return state


CARD = {"name": "Sofia Marino", "email": "sofia@touristsector.com", "phone": "1000000000",
        "message": "Connect card", "form": "connect_card", "fields": {"notes": "Write yes to sofia@..."}}


def test_a_scripted_card_with_the_hidden_field_filled_is_thanked_and_never_kept(door):
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json={**CARD, "website": "touristsector.com"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert door.validated == 0 and door.captured == [], "nothing read, stored, alerted or mailed"


def test_a_card_sent_a_second_after_the_page_was_made_is_a_bot(door):
    body = {**CARD, "_t": g.token(BIZ)}
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json=body)
    assert r.json()["ok"] is True and door.validated == 0 and door.captured == []


def test_another_churchs_token_goes_on_as_a_person(door):
    """The review of #2101, should-fix 2: a sister church's page posting to
    this door is our own page, not a bot."""
    import time
    body = {**CARD, "_t": g.token(OTHER, now=time.time() - 30)}
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json=body)
    assert r.status_code == 400 and door.validated == 1


def test_a_forged_token_is_a_bot(door):
    import time
    good = g.token(BIZ, now=time.time() - 30)
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json={**CARD, "_t": good[:-4] + "beef"})
    assert r.json()["ok"] is True and door.validated == 0


def test_a_person_with_a_good_token_or_none_goes_on_to_the_card(door):
    import time
    for body in ({**CARD, "_t": g.token(BIZ, now=time.time() - 30)}, dict(CARD)):
        r = door.client.post(f"/sites/{BIZ}/contact-submit", json=body)
        assert r.status_code == 400 and "stop here" in r.json()["error"]
    assert door.validated == 2


# ── 4. the shared limiter ─────────────────────────────────────────────

def test_the_door_takes_from_the_shared_limiter_by_ip(door):
    door.client.post(f"/sites/{BIZ}/contact-submit", json=dict(CARD))
    assert door.rate and door.rate[0][0] == "site_contact" and door.rate[0][1].startswith(f"{BIZ}:")
    assert rate_limit._LIMITS["site_contact"] == (30, 60), "per church and address, 30 a minute"
    assert not hasattr(public_site, "_contact_rate"), "the per-replica dict is gone"


def test_a_shared_no_is_a_429_before_anything_else(door, monkeypatch):
    monkeypatch.setattr(rate_limit, "allow_shared", lambda bucket, key, **kw: False)
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json=dict(CARD))
    assert r.status_code == 429 and door.validated == 0


# ── 5. the page script ────────────────────────────────────────────────

def test_every_served_site_page_gets_the_script_once():
    html = "<html><body><form></form></body></html>"
    once = g.inject(html, BIZ)
    assert once.count(g.SCRIPT_MARK) >= 1 and once.index("<script>") < once.index("</body>")
    assert g.inject(once, BIZ) == once, "idempotent"
    assert f"/sites/{BIZ}/contact-submit" in once and "_t" in once and g.token(BIZ).split(".")[0] in once
    assert g.inject(html, "") == html


def test_the_brand_meta_pass_carries_the_script(monkeypatch):
    monkeypatch.setattr(public_site, "_brand_head_meta_tags", lambda *a, **kw: "")
    monkeypatch.setattr(public_site, "_inject_concierge_widget", lambda html, bid: html)
    monkeypatch.setattr(public_site, "_inject_traffic_beacon", lambda html, bid: html)
    out = public_site._inject_brand_meta("<html><head></head><body></body></html>", BIZ)
    assert g.SCRIPT_MARK in out


def test_the_script_only_adds_the_token_and_sends_nothing_itself():
    s = g.script(BIZ)
    assert s.count("fetch(") == 0 and "XMLHttpRequest" not in s and "sendBeacon" not in s
    assert "F.apply(this,arguments)" in s, "anything unexpected runs the page's own fetch as written"



def test_the_script_puts_the_token_only_on_this_churchs_own_door():
    s = g.script(BIZ)
    assert f'D="/sites/{BIZ}/contact-submit"' in s and "s.indexOf(D)>-1" in s
    assert "indexOf('/contact-submit')" not in s, "never another business's door or a third party's"


def test_one_email_sending_the_same_card_again_and_again_is_slowed(door):
    for _ in range(5):
        assert door.client.post(f"/sites/{BIZ}/contact-submit", json=dict(CARD)).status_code == 400
    r = door.client.post(f"/sites/{BIZ}/contact-submit", json=dict(CARD))
    assert r.status_code == 429 and door.validated == 5
    other = {**CARD, "email": "someone@else.example"}
    assert door.client.post(f"/sites/{BIZ}/contact-submit", json=other).status_code == 400


def test_the_shared_door_limit_never_turns_a_person_away_when_it_breaks(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("limiter bug")
    monkeypatch.setattr(rate_limit, "_check", boom)
    assert rate_limit.allow_shared("site_contact", "k") is True
    assert rate_limit.allow_strict("site_contact", "k") is False, "strict stays strict, for agents"
