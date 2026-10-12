"""Texting under your own name without an EIN: Twilio's sole proprietor way (2026-10-11).

Kevin, 2026-10-11: "Build it now". Twilio's "New Sole Proprietor A2P 10DLC
Registration for ISVs" walkthrough: a Starter profile, a Sole Proprietor
trust bundle carrying the owner's own cell, a SOLE_PROPRIETOR brand, the
owner's YES to Twilio's text, then a SOLE_PROPRIETOR campaign. Pinned here:
  1. The send uses the Starter and Sole Proprietor policies and attributes,
     the owner's own cell, and a SOLE_PROPRIETOR brand (no secondary vetting
     flag); everything as the business's sub-account.
  2. An approved brand waits for the owner's YES before the campaign; the
     owner is told once; the campaign is SOLE_PROPRIETOR.
  3. A new YES text, only when one is waiting, at most every ten minutes.
  4. The answers: no EIN only for a sole proprietor; the cell tidied.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import texting_isv as ti  # noqa: E402
import texting_registration as tr  # noqa: E402
from test_texting_isv import PARENT, SUB, WORDS, FakeTwilio  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
SOLE = {"legal_name": "Andre Smith", "business_type": "sole_proprietor", "industry": None, "has_ein": False,
        "street": "12 Main St", "city": "Muskegon", "state": "MI", "postal_code": "49441", "website": None,
        "rep_first_name": "Andre", "rep_last_name": "Smith", "rep_title": "Owner", "rep_email": "andre@example.com",
        "rep_phone": "+12315550100", "mobile_phone": "+12315550199"}


def run(x):
    return asyncio.run(x)


class SoleTwilio(FakeTwilio):
    def __init__(self):
        super().__init__()
        self.identity = "UNVERIFIED"

    def answer(self, method, path, f, params):
        out = super().answer(method, path, f, params)
        if path.startswith("/v1/a2p/BrandRegistrations/") and method == "GET":
            out["identity_status"] = self.identity
        if path.endswith("/SmsOtp"):
            return {"brand_registration_sid": path.split("/")[-2]}
        return out


@pytest.fixture
def tw(monkeypatch):
    fake = SoleTwilio()
    monkeypatch.setattr(ti, "_http", fake)
    monkeypatch.setattr(ti.time, "sleep", lambda s: None)
    monkeypatch.setattr(ti, "_SUB_TOKENS", {})
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", PARENT)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "parenttoken")
    monkeypatch.setenv("TWILIO_ISV_EMAIL", "isv@example.com")
    return fake


def send(t):
    return ti.send(t, business_id=BIZ, name="Andre's Cuts", answers=SOLE, ein=None,
                   website="https://andres.mysolutionist.app", callback="https://api.example/texting/twilio-status",
                   save=lambda x: None)


# ── 1. the send ───────────────────────────────────────────────────────

def test_a_sole_proprietor_registers_the_sole_proprietor_way(tw):
    t = send({})
    assert t["path"] == "sole_prop" and t["profile_submitted"] and t["trust_submitted"] and t["brand_sid"]
    profile = dict(tw.posts(r"^/v1/CustomerProfiles$")[0][3])
    assert profile["PolicySid"] == ti.STARTER_POLICY
    trust = dict(tw.posts(r"^/v1/TrustProducts$")[0][3])
    assert trust["PolicySid"] == ti.SOLE_PROP_POLICY
    users = [dict(c[3]) for c in tw.posts(r"^/v1/EndUsers$")]
    assert [u["Type"] for u in users] == ["starter_customer_profile_information", "sole_proprietor_information"]
    assert json.loads(users[0]["Attributes"]) == {"first_name": "Andre", "last_name": "Smith",
                                                  "email": "andre@example.com", "phone_number": "+12315550100"}
    assert json.loads(users[1]["Attributes"]) == {"brand_name": "Andre Smith", "mobile_phone_number": "+12315550199"}
    evals = [dict(c[3])["PolicySid"] for c in tw.posts(r"/Evaluations$")]
    assert evals == [ti.STARTER_POLICY, ti.SOLE_PROP_POLICY]
    brand = dict(tw.posts(r"^/v1/a2p/BrandRegistrations$")[0][3])
    assert brand["BrandType"] == "SOLE_PROPRIETOR" and "SkipAutomaticSecVet" not in brand
    assert {user for (_m, p, user, *_r) in tw.calls if "Accounts.json" not in p and f"Accounts/{SUB}.json" not in p} \
        == {SUB}
    assigned = [dict(c[3])["ObjectSid"] for c in tw.posts(r"CustomerProfiles/BU\w+/EntityAssignments")]
    assert ti.PRIMARY_PROFILE_SID in assigned and len(assigned) == 3          # person, address, our primary


def test_a_business_with_an_ein_still_needs_it(tw):
    with pytest.raises(ti.NeedsFix, match="EIN"):
        ti.send({}, business_id=BIZ, name="X", answers={**SOLE, "has_ein": True, "business_type": "llc"}, ein=None,
                website="https://x.example", callback="https://cb", save=lambda x: None)


def test_no_cell_is_the_owners_to_fix(tw):
    with pytest.raises(ti.NeedsFix, match="cell"):
        ti.sole_proprietor_information({**SOLE, "mobile_phone": None, "rep_phone": None})


# ── 2. the YES, then the campaign ─────────────────────────────────────

def test_an_approved_brand_waits_for_the_owners_yes(tw):
    t = send({})
    t["campaign_words"] = WORDS
    tw.brand_status = "APPROVED"
    assert ti.check(t, lambda x: None) == {"stage": "confirm", "reasons": []} and not tw.campaigns
    tw.identity = "VERIFIED"
    assert ti.check(t, lambda x: None)["stage"] == "campaign"
    [(m, path, user, form, headers)] = tw.posts(r"/Compliance/Usa2p$")
    assert dict(form)["UsAppToPersonUsecase"] == "SOLE_PROPRIETOR"


def test_the_owner_is_told_once_to_reply_yes(monkeypatch):
    told, patches = [], []
    t = {"path": "sole_prop", "account_sid": SUB, "brand_sid": "BN1", "service_sid": "MG1"}
    row = {"status": "brand_pending", "twilio": t}

    def patch(bid, fields, *, when=None):
        patches.append(fields)
        row["twilio"] = fields.get("twilio", row["twilio"])
        return [row]

    async def tell(biz, status, reasons=None, number=None):
        told.append(status)

    monkeypatch.setattr(tr, "_patch", patch)
    monkeypatch.setattr(tr, "_tell_owner", tell)
    monkeypatch.setattr(tr.texting_isv, "check", lambda t, save: {"stage": "confirm", "reasons": []})
    monkeypatch.setattr(tr, "_saver", lambda bid: lambda x: None)
    biz = {"id": BIZ, "name": "Andre's Cuts"}
    assert run(tr._check(biz, row)) == "brand_pending"
    assert run(tr._check(biz, row)) == "brand_pending"
    assert told == ["confirm"] and row["twilio"]["confirm_told"] is True
    steps = tr._stage("brand_pending", row["twilio"])
    assert [s["key"] for s in steps] == ["business", "confirm", "campaign", "live"]
    assert [s["state"] for s in steps] == ["done", "now", "next", "next"]
    title, body = tr.UPDATES["confirm"]
    assert title == "Reply YES to Twilio's text" and "+1 (915) 278-2000" in body and "24 hours" in body


# ── 3. a new YES text ─────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    state = {"row": None, "resent": [], "patches": []}
    app = FastAPI()
    app.include_router(tr.router)
    monkeypatch.setattr(tr, "registration", lambda bid: state["row"])
    monkeypatch.setattr(tr.texting_isv, "resend_code", lambda t: state["resent"].append(t["brand_sid"]))

    def patch(bid, fields, *, when=None):
        state["patches"].append(fields)
        state["row"].update(fields)
        return [state["row"]]

    async def view(biz):
        return {"status": state["row"]["status"]}

    monkeypatch.setattr(tr, "_patch", patch)
    monkeypatch.setattr(tr, "overview", view)
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for d in r.dependant.dependencies:
                if d.name == "biz":
                    app.dependency_overrides[d.call] = lambda: {"id": BIZ, "name": "Andre's Cuts"}
    return TestClient(app), state


def test_a_new_yes_text_only_when_one_is_waiting_and_not_too_often(client):
    c, state = client
    state["row"] = {"status": "brand_pending", "twilio": {"path": "standard", "brand_sid": "BN1"}}
    assert c.post(f"/texting/registration/{BIZ}/resend-code").status_code == 409
    state["row"] = {"status": "brand_pending", "twilio": {
        "path": "sole_prop", "brand_sid": "BN1", "confirm_told": True,
        "confirm_told_at": (tr._now() - timedelta(hours=25)).isoformat()}}
    r = c.post(f"/texting/registration/{BIZ}/resend-code")
    assert r.status_code == 200 and state["resent"] == ["BN1"] and state["row"]["twilio"]["code_sent_at"]
    r = c.post(f"/texting/registration/{BIZ}/resend-code")
    assert r.status_code == 429 and "few minutes ago" in r.json()["detail"] and state["resent"] == ["BN1"]


# ── 4. the answers ────────────────────────────────────────────────────

def test_no_ein_is_only_for_a_sole_proprietor():
    a = tr.Answers(**{**SOLE, "mobile_phone": "(231) 555-0199"})
    assert a.mobile_phone == "+12315550199" and tr.brand_path(a.model_dump()) == "sole_proprietor"
    with pytest.raises(ValidationError, match=re.escape("Without one, choose sole proprietor")):
        tr.Answers(**{**SOLE, "business_type": "llc"})
    with pytest.raises(ValidationError, match="US phone number"):
        tr.Answers(**{**SOLE, "mobile_phone": "555-0199"})
