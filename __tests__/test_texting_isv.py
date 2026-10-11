"""Texting under each business's own name, step 3: Twilio's side (2026-10-11).

texting_isv.py against a fake Twilio that answers like the real one (the
requests in Twilio's ISV API guide). Pinned here:
  1. A send makes the sub-account, profile, trust product, brand and
     messaging service, in Twilio's order, AS the business's sub-account,
     with what Twilio's guide asks for (EIN dashed, the business as a direct
     customer, our primary profile assigned, Low-Volume Standard).
  2. Nothing happens twice: a second run, or a run after a crash that lost
     an id, finds what exists instead of creating (or paying for) it again.
  3. Twilio's own check failing is the owner's to fix, in Twilio's words,
     and a fixed detail updates what was sent instead of adding to it.
  4. Where it stands: the campaign goes in only once the brand is approved,
     with the words the owner saw; approval and rejection are read from
     Twilio.
  5. Twilio down is "try later", Twilio refusing is "refused"; the
     sub-account's token is never saved.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from urllib.parse import parse_qsl

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_isv as ti  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
PARENT, SUB = "AC" + "1" * 32, "AC" + "2" * 32
ANSWERS = {"legal_name": "Northside Cuts LLC", "business_type": "llc", "industry": "CONSUMER", "has_ein": True,
           "street": "12 Main St", "city": "Muskegon", "state": "MI", "postal_code": "49441", "website": None,
           "rep_first_name": "Andre", "rep_last_name": "Smith", "rep_title": "Owner",
           "rep_email": "andre@example.com", "rep_phone": "+12315550100"}
WORDS = {"use_case": "LOW_VOLUME", "description": "Northside Cuts texts its own clients who opted in.",
         "message_flow": "Clients opt in on the booking page by checking an unchecked box.",
         "samples": ["Northside Cuts: Your appointment is confirmed. Reply STOP to opt out.",
                     "Reminder from Northside Cuts: tomorrow at 3:00 PM. Reply STOP to opt out."],
         "has_embedded_links": True, "has_embedded_phone": False,
         "terms_url": "https://northside.mysolutionist.app/texting-terms",
         "privacy_url": "https://northside.mysolutionist.app/texting-privacy"}


class FakeTwilio:
    """Answers like Twilio and records every request: (method, path, auth
    user, form as a list of pairs, headers)."""

    def __init__(self):
        self.calls = []
        self.n = 0
        self.accounts, self.profiles, self.trusts, self.brands, self.services, self.campaigns = [], [], [], [], [], []
        self.evaluation = "compliant"
        self.brand_status = "PENDING"
        self.campaign_status = "PENDING"
        self.bundle_status = "pending-review"
        self.fail_with = None          # (status, body) for the next request

    def sid(self, prefix):
        self.n += 1
        return f"{prefix}{self.n:032x}"

    def __call__(self, method, url, *, auth=None, data=None, params=None, headers=None):
        form = list(data.items()) if isinstance(data, dict) else list(data or [])
        path = re.sub(r"^https://[^/]+", "", url)
        self.calls.append((method, path, auth[0], form, dict(headers or {})))
        if self.fail_with:
            status, body = self.fail_with
            self.fail_with = None
            return httpx.Response(status, json=body)
        return httpx.Response(200, json=self.answer(method, path, dict(form), params or {}))

    def answer(self, method, path, f, params):
        if path == "/2010-04-01/Accounts.json":
            if method == "GET":
                return {"accounts": [a for a in self.accounts if a["friendly_name"] == params.get("FriendlyName")]}
            a = {"sid": SUB, "friendly_name": f["FriendlyName"], "status": "active", "auth_token": "subtoken"}
            self.accounts.append(a)
            return a
        if path == f"/2010-04-01/Accounts/{SUB}.json":
            return {"sid": SUB, "auth_token": "subtoken"}
        if path == "/v1/CustomerProfiles":
            if method == "GET":
                return {"results": self.profiles}
            p = {"sid": self.sid("BU"), "policy_sid": f["PolicySid"]}
            self.profiles.append(p)
            return p
        if path == "/v1/TrustProducts":
            if method == "GET":
                return {"results": self.trusts}
            p = {"sid": self.sid("BU"), "policy_sid": f["PolicySid"]}
            self.trusts.append(p)
            return p
        if path.endswith("/Evaluations"):
            if self.evaluation == "compliant":
                return {"status": "compliant", "results": []}
            return {"status": "noncompliant", "results": [{"passed": False, "invalid": [
                {"failure_reason": "The Business Name is missing."},
                {"failure_reason": "The First Name is missing."}]}]}
        if re.fullmatch(r"/v1/(CustomerProfiles|TrustProducts)/BU\w+", path):
            return {"sid": path.rsplit("/", 1)[1], "status": self.bundle_status,
                    "errors": [{"description": "The EIN doesn't match the legal name."}]
                    if self.bundle_status == "twilio-rejected" else None}
        if path == "/v1/EndUsers":
            return {"sid": self.sid("IT")}
        if path.startswith("/v1/EndUsers/"):
            return {"sid": path.rsplit("/", 1)[1]}
        if path == f"/2010-04-01/Accounts/{SUB}/Addresses.json":
            return {"sid": self.sid("AD")}
        if path.startswith(f"/2010-04-01/Accounts/{SUB}/Addresses/"):
            return {"sid": "AD"}
        if path == "/v1/SupportingDocuments":
            return {"sid": self.sid("RD")}
        if path.endswith("/EntityAssignments"):
            return {"sid": self.sid("BV")}
        if path == "/v1/a2p/BrandRegistrations":
            if method == "GET":
                return {"data": self.brands}
            b = {"sid": self.sid("BN"), "status": "PENDING"}
            self.brands.append(b)
            return b
        if path.startswith("/v1/a2p/BrandRegistrations/"):
            return {"sid": path.rsplit("/", 1)[1], "status": self.brand_status,
                    "failure_reason": "TAX_ID mismatch" if self.brand_status == "FAILED" else None, "errors": []}
        if path == "/v1/Services":
            if method == "GET":
                return {"services": self.services}
            s = {"sid": self.sid("MG"), "friendly_name": f["FriendlyName"]}
            self.services.append(s)
            return s
        if re.fullmatch(r"/v1/Services/MG\w+/Compliance/Usa2p", path):
            if method == "GET":
                return {"compliance": self.campaigns}
            c = {"sid": self.sid("QE")}
            self.campaigns.append(c)
            return c
        if re.fullmatch(r"/v1/Services/MG\w+/Compliance/Usa2p/QE\w+", path):
            return {"sid": path.rsplit("/", 1)[1], "campaign_status": self.campaign_status,
                    "errors": [{"description": "Opt-in names a different business."}]
                    if self.campaign_status == "FAILED" else []}
        raise AssertionError(f"unexpected {method} {path}")

    def posts(self, path_re):
        return [c for c in self.calls if c[0] == "POST" and re.search(path_re, c[1])]


@pytest.fixture
def tw(monkeypatch):
    fake = FakeTwilio()
    monkeypatch.setattr(ti, "_http", fake)
    monkeypatch.setattr(ti.time, "sleep", lambda s: None)
    monkeypatch.setattr(ti, "_SUB_TOKENS", {})
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", PARENT)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "parenttoken")
    monkeypatch.setenv("TWILIO_ISV_EMAIL", "isv@example.com")
    monkeypatch.delenv("TWILIO_PRIMARY_PROFILE_SID", raising=False)
    return fake


def send(t, saves=None):
    saves = saves if saves is not None else []
    return ti.send(t, business_id=BIZ, name="Northside Cuts", answers=ANSWERS, ein="123456789",
                   website="https://northside.mysolutionist.app", callback="https://api.example/texting/twilio-status",
                   save=lambda x: saves.append(json.loads(json.dumps(x))))


# ── 1. a send, in Twilio's order, as the business ─────────────────────

def test_a_send_registers_the_business_in_twilios_order(tw):
    saves = []
    t = send({}, saves)
    for key in ("account_sid", "profile_sid", "trust_sid", "brand_sid", "service_sid"):
        assert t.get(key), key
    assert t["account_sid"] == SUB and t["profile_submitted"] and t["trust_submitted"]
    creates = [p for (m, p, *_rest) in tw.calls if m == "POST" and not re.search(r"/(EndUsers|Addresses)/", p)]
    order = [re.sub(r"(AC|BU|MG)\w{32}", "*", p) for p in creates]
    assert order == [
        "/2010-04-01/Accounts.json",                                       # 0. the sub-account
        "/v1/CustomerProfiles", "/v1/EndUsers", "/v1/EndUsers",            # 1. profile + business + rep
        "/2010-04-01/Accounts/*/Addresses.json", "/v1/SupportingDocuments",
        "/v1/CustomerProfiles/*/EntityAssignments", "/v1/CustomerProfiles/*/EntityAssignments",
        "/v1/CustomerProfiles/*/EntityAssignments", "/v1/CustomerProfiles/*/EntityAssignments",
        "/v1/CustomerProfiles/*/Evaluations", "/v1/CustomerProfiles/*",
        "/v1/TrustProducts", "/v1/EndUsers",                               # 2. trust product
        "/v1/TrustProducts/*/EntityAssignments", "/v1/TrustProducts/*/EntityAssignments",
        "/v1/TrustProducts/*/Evaluations", "/v1/TrustProducts/*",
        "/v1/a2p/BrandRegistrations",                                      # 3. the brand
        "/v1/Services",                                                    # 4. the messaging service
    ]
    # Everything after the sub-account is made AS the sub-account.
    assert {user for (_m, p, user, *_r) in tw.calls if "Accounts.json" not in p and f"Accounts/{SUB}.json" not in p} \
        == {SUB}
    biz = json.loads(dict(tw.posts(r"^/v1/EndUsers$")[0][3])["Attributes"])
    assert biz == {"business_name": "Northside Cuts LLC", "business_identity": "direct_customer",
                   "business_type": "Limited Liability Corporation", "business_industry": "CONSUMER",
                   "business_registration_identifier": "EIN", "business_registration_number": "12-3456789",
                   "business_regions_of_operation": "USA_AND_CANADA",
                   "website_url": "https://northside.mysolutionist.app"}
    rep = json.loads(dict(tw.posts(r"^/v1/EndUsers$")[1][3])["Attributes"])
    assert rep["job_position"] == "CEO" and rep["business_title"] == "Owner" and rep["phone_number"] == "+12315550100"
    assigned = [dict(c[3])["ObjectSid"] for c in tw.posts(r"CustomerProfiles/BU\w+/EntityAssignments")]
    assert ti.PRIMARY_PROFILE_SID in assigned                               # tied to our primary profile
    profile = dict(tw.posts(r"^/v1/CustomerProfiles$")[0][3])
    assert profile["Email"] == "isv@example.com" and profile["PolicySid"] == ti.PROFILE_POLICY
    assert profile["StatusCallback"] == "https://api.example/texting/twilio-status"
    assert dict(tw.posts(r"^/v1/CustomerProfiles/BU\w+$")[0][3]) == {"Status": "pending-review"}
    assert dict(tw.posts(r"^/v1/a2p/BrandRegistrations$")[0][3])["SkipAutomaticSecVet"] == "true"
    service = dict(tw.posts(r"^/v1/Services$")[0][3])
    assert service["InboundRequestUrl"].endswith("/webhooks/twilio/sms")
    assert service["StatusCallback"].endswith("/webhooks/twilio/status")
    # The sub-account's token is read from Twilio and never saved.
    assert saves and all("subtoken" not in json.dumps(s) and "auth_token" not in json.dumps(s) for s in saves)


# ── 2. nothing twice ──────────────────────────────────────────────────

def test_a_second_run_creates_nothing(tw):
    t = send({})
    n = len(tw.calls)
    send(t)
    again = [c for c in tw.calls[n:] if c[0] == "POST"]
    assert again == []
    assert len(tw.brands) == 1 and len(tw.accounts) == 1


def test_a_run_that_lost_its_ids_finds_them_instead_of_paying_twice(tw):
    t = send({})
    lost = {"account_sid": None}
    # A crash after Twilio made the sub-account and the brand, before we saved:
    send(lost)
    assert len(tw.accounts) == 1 and len(tw.brands) == 1 and len(tw.services) == 1
    assert lost["account_sid"] == t["account_sid"] and lost["brand_sid"] == t["brand_sid"]


# ── 3. Twilio's check, the owner's fix ────────────────────────────────

def test_twilios_check_failing_is_the_owners_to_fix_and_the_fix_updates(tw):
    tw.evaluation = "noncompliant"
    t = {}
    with pytest.raises(ti.NeedsFix) as e:
        send(t)
    assert e.value.reasons == ["The Business Name is missing.", "The First Name is missing."]
    assert not t.get("profile_submitted") and not t.get("brand_sid") and not tw.brands   # nothing paid
    tw.evaluation = "compliant"
    n_users = len(tw.posts(r"^/v1/EndUsers$"))
    send(t)
    assert len(tw.posts(r"^/v1/EndUsers$")) == n_users + 1                 # only the trust product's own
    assert len(tw.posts(r"^/v1/EndUsers/IT\w+$")) == 2                     # business + rep updated
    assert tw.posts(rf"/Accounts/{SUB}/Addresses/AD")                       # the address updated
    assert t["profile_submitted"] and t["brand_sid"]


def test_what_twilio_needs_from_the_answers():
    assert ti.ein_dashed("12 345 6789") == "12-3456789"
    with pytest.raises(ti.NeedsFix):
        ti.ein_dashed("1234")
    assert [ti.job_position(x) for x in ("Owner", "Founder & CEO", "Lead Pastor", "Director of Ops", "Manager",
                                         "Treasurer", "Stylist")] == \
        ["CEO", "CEO", "CEO", "Director", "GM", "CFO", "Other"]
    church = {**ANSWERS, "business_type": "nonprofit", "industry": None}
    info = ti.business_information(church, ein="123456789", website="https://x.example")
    assert info["business_industry"] == "NOT_FOR_PROFIT" and info["business_type"] == "Non-profit Corporation"
    assert ti.company_type(church) == "non-profit" and ti.company_type(ANSWERS) == "private"
    with pytest.raises(ti.NeedsFix, match="industry"):
        ti.business_information({**ANSWERS, "industry": None}, ein="123456789", website="https://x.example")
    with pytest.raises(ti.NeedsFix, match="EIN"):
        ti.business_information({**ANSWERS, "business_type": "sole_proprietor"}, ein="123456789",
                                website="https://x.example")


# ── 4. where it stands ────────────────────────────────────────────────

def test_the_campaign_goes_in_only_once_the_brand_is_approved(tw):
    t = send({})
    t["campaign_words"] = WORDS
    saves = []
    assert ti.check(t, saves.append)["stage"] == "brand" and not tw.campaigns
    tw.brand_status = "APPROVED"
    assert ti.check(t, saves.append)["stage"] == "campaign"
    [(m, path, user, form, headers)] = tw.posts(r"/Compliance/Usa2p$")
    assert user == SUB and headers.get("X-Twilio-Api-Version") == "v1.2"
    assert [v for k, v in form if k == "MessageSamples"] == WORDS["samples"]
    f = dict(form)
    assert f["UsAppToPersonUsecase"] == "LOW_VOLUME" and f["BrandRegistrationSid"] == t["brand_sid"]
    assert f["PrivacyPolicyUrl"] == WORDS["privacy_url"] and f["TermsAndConditionsUrl"] == WORDS["terms_url"]
    assert f["Description"] == WORDS["description"] and f["MessageFlow"] == WORDS["message_flow"]
    assert t["campaign_sid"] and saves
    assert ti.check(t, saves.append)["stage"] == "campaign" and len(tw.campaigns) == 1   # never twice
    tw.campaign_status = "VERIFIED"
    assert ti.check(t, saves.append) == {"stage": "approved", "reasons": []}


def test_rejections_are_read_from_twilio_with_its_reasons(tw):
    t = send({})
    tw.brand_status = "FAILED"
    assert ti.check(t, lambda x: None) == {"stage": "failed", "reasons": ["TAX_ID mismatch"]}
    tw.brand_status, tw.bundle_status = "APPROVED", "twilio-rejected"
    res = ti.check(t, lambda x: None)
    assert res["stage"] == "failed" and res["reasons"] == ["The EIN doesn't match the legal name."]
    tw.bundle_status = "twilio-approved"
    t["campaign_words"] = WORDS
    ti.check(t, lambda x: None)
    tw.campaign_status = "FAILED"
    assert ti.check(t, lambda x: None) == {"stage": "failed", "reasons": ["Opt-in names a different business."]}


# ── 5. down, refused, configured ──────────────────────────────────────

def test_twilio_down_and_twilio_refusing_are_told_apart(tw):
    tw.fail_with = (503, {"message": "Service Unavailable"})
    with pytest.raises(ti.TwilioDown):
        send({})
    tw.fail_with = (400, {"code": 21211, "message": "Invalid street address"})
    with pytest.raises(ti.TwilioRefused) as e:
        send({})
    assert e.value.code == 21211 and e.value.message == "Invalid street address"


def test_it_needs_the_account_token_and_an_isv_email(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", PARENT)
    with pytest.raises(RuntimeError, match="TWILIO_AUTH_TOKEN"):
        ti.parent()
    monkeypatch.delenv("TWILIO_ISV_EMAIL", raising=False)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@example.com")
    assert ti.isv_email() == "owner@example.com"
    monkeypatch.setenv("TWILIO_PRIMARY_PROFILE_SID", "BU" + "9" * 32)
    assert ti.primary_profile_sid() == "BU" + "9" * 32
