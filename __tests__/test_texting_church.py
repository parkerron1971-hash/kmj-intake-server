"""A church registers for texting as a church (2026-11-13).

Kevin: "finish setting up the text structure" so churches can send text
alerts. The registration (texting_registration.py) was written for a booking
business: its campaign described confirmations and "$10 off" offers and sent
the reviewers to a /book page a church doesn't have. Pinned here:
  1. A church's words: its own description, samples and message flow, the
     sign-up box quoted word for word, only the church's own links, inside
     Twilio's lengths. A business keeps the booking words.
  2. A church's pages: church news, no bookings, no Book link.
  3. Readiness asks a church for its sign-up page, never a booking page; the
     overview never reads booking for a church and hands it the sign-up link.
  4. /texts: a church's only, only once its registration is sent; a plain
     form with an unchecked box.
  5. POST /texting/signup: guarded like the contact form; the person found
     or added as a guest; the yes kept (texts_page); one confirming text;
     nothing personal in the address it sends you back to.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import texting_registration as tr  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
ORIGIN = "https://gracechapel.mysolutionist.app"
CHURCH = {"id": BIZ, "name": "Grace Chapel", "type": "church", "settings": {}}
SHOP = {"id": BIZ, "name": "Northside Cuts", "type": "barber", "settings": {}}
SENT_ROW = {"business_id": BIZ, "status": "campaign_pending", "twilio": {"sent_at": "2026-11-13T12:00:00+00:00"}}


def run(x):
    return asyncio.run(x)


# ── 1. the words ──────────────────────────────────────────────────────

def test_a_church_is_told_apart_from_a_business():
    assert tr.is_church(CHURCH) and tr.is_church({"type": "ministry"})
    assert not tr.is_church(SHOP) and not tr.is_church(None) and not tr.is_church({})


def test_a_churchs_campaign_says_what_a_church_texts():
    w = tr.campaign_words("Grace Chapel", ORIGIN, church=True)
    assert w == tr.church_campaign_words("Grace Chapel", ORIGIN)
    assert w["use_case"] == "LOW_VOLUME"
    assert w["description"].startswith("Grace Chapel is a church.")
    everything = " ".join([w["description"], w["message_flow"], *w["samples"], w["opt_in_message"]]).lower()
    for word in ("booking", "appointment", "/book", "offer code", "$10", "clients"):
        assert word not in everything, word
    for s in w["samples"]:
        assert "Grace Chapel" in s and "STOP" in s, s
    for words in (w["opt_in_message"], w["opt_out_message"], w["help_message"]):
        assert words.startswith("Grace Chapel"), words
    # The opt-in, quoted word for word, at a page a reviewer can open; the
    # box names the church and never the platform.
    assert f'"{tr.church_box("Grace Chapel")}"' in w["message_flow"]
    assert f"({ORIGIN}/texts)" in w["message_flow"]
    assert "Solutionist" not in tr.church_box("Grace Chapel") + w["message_flow"]
    assert "unchecked" in w["message_flow"] and "never required" in w["message_flow"]
    assert w["terms_url"] == f"{ORIGIN}/texting-terms" and w["privacy_url"] == f"{ORIGIN}/texting-privacy"
    links = re.findall(r"https?://[^\s)\"]+", " ".join(w["samples"]) + w["message_flow"])
    assert links and all(l.startswith(ORIGIN) for l in links)             # the church's own site, no shorteners
    # Twilio's limits on the campaign form.
    assert 40 <= len(w["description"]) <= 4096 and 40 <= len(w["message_flow"]) <= 2048
    assert all(20 <= len(s) <= 1024 for s in w["samples"]) and 2 <= len(w["samples"]) <= 5


def test_a_business_keeps_the_booking_words():
    w = tr.campaign_words("Northside Cuts", ORIGIN)
    assert w["description"].startswith("Northside Cuts texts its own clients")
    assert f'"{tr.booking_box("Northside Cuts")}"' in w["message_flow"]


def test_the_send_registers_a_church_with_the_church_words():
    src = pathlib.Path(tr.__file__).read_text(encoding="utf-8")
    assert 't.setdefault("campaign_words", campaign_words(shown, origin, church=is_church(business)))' in src


# ── 2. the pages ──────────────────────────────────────────────────────

def test_a_churchs_pages_say_church_news_not_bookings():
    terms = tr.terms_html("Grace Chapel", ORIGIN, "office@gracechapel.org", church=True)
    privacy = tr.privacy_html("Grace Chapel", ORIGIN, church=True)
    for page in (terms, privacy):
        assert "Grace Chapel" in page and "<strong>STOP</strong>" in page and "<strong>HELP</strong>" in page
        assert "We do not sell or share your mobile number or your SMS opt-in data" in page
        assert "booking" not in page.lower() and f'href="{ORIGIN}/book"' not in page
        assert f'href="{ORIGIN}/">Home</a>' in page
    assert "Church news" in terms and "never required to attend" in terms
    assert f'href="{ORIGIN}/texts"' in terms and "Message and data rates may apply" in terms
    assert "our church software" in privacy
    # A business's pages are as they were.
    shop = tr.terms_html("Northside Cuts", ORIGIN)
    assert "About your bookings" in shop and f'href="{ORIGIN}/book">Book</a>' in shop


def test_the_church_site_serves_its_church_pages(monkeypatch):
    import public_site
    monkeypatch.setattr(tr, "_read", lambda path: [CHURCH])
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    monkeypatch.setattr(public_site, "_business_public_email", lambda s: "")
    assert "Church news" in run(tr.page_for(BIZ, "terms"))
    assert "our church software" in run(tr.page_for(BIZ, "privacy"))


# ── 3. readiness and the owner's screen ───────────────────────────────

def test_readiness_asks_a_church_for_its_sign_up_page_not_a_booking_page():
    checks = tr.readiness(CHURCH, answers=None, origin=ORIGIN, bookable=None)
    keys = {c["key"]: c["ok"] for c in checks}
    assert keys == {"site": True, "signup": True, "pages": True, "answers": False}
    signup = next(c for c in checks if c["key"] == "signup")
    assert f"{ORIGIN}/texts" in signup["label"]
    assert "booking" not in " ".join(c["label"] + c["fix"] for c in checks).lower()
    shop = {c["key"] for c in tr.readiness(SHOP, answers=None, origin=ORIGIN, bookable=True)}
    assert shop == {"site", "booking", "pages", "answers"}


def test_the_overview_never_reads_booking_for_a_church(monkeypatch):
    import business_marketing_links as links

    def boom(*a, **k):
        raise AssertionError("a church was asked about booking")

    monkeypatch.setattr(links, "bookable", boom)
    monkeypatch.setattr(tr, "registration", lambda bid: None)
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    monkeypatch.setattr(tr, "ein_for", lambda bid, biz=None: None)
    monkeypatch.setattr(tr, "about_for", lambda bid, biz=None: None)
    body = run(tr.overview(CHURCH))
    assert body["words"]["description"].startswith("Grace Chapel is a church.")
    assert body["pages"]["signup"] == f"{ORIGIN}/texts" and body["signup_live"] is False
    monkeypatch.setattr(tr, "registration", lambda bid: SENT_ROW)
    assert run(tr.overview(CHURCH))["signup_live"] is True


# ── 4. the /texts page ────────────────────────────────────────────────

@pytest.fixture
def church_site(monkeypatch):
    state = {"biz": CHURCH, "row": SENT_ROW}
    monkeypatch.setattr(tr, "_read", lambda path: [state["biz"]])
    monkeypatch.setattr(tr, "site_origin", lambda bid: ORIGIN)
    monkeypatch.setattr(tr, "registration", lambda bid: state["row"])
    return state


def test_the_sign_up_page_is_a_churchs_once_its_registration_is_sent(church_site):
    page = run(tr.page_for(BIZ, "signup"))
    assert page and "<title>Sign up for texts | Grace Chapel</title>" in page
    assert f'action="/texting/signup/{BIZ}"' in page and 'method="post"' in page
    box = re.search(r'<input type="checkbox"[^>]*>', page).group(0)
    assert "checked" not in box and "required" not in box                 # unchecked, never required
    assert tr.html.escape(tr.church_box("Grace Chapel")) in page            # the box, word for word
    assert f'href="{ORIGIN}/texting-terms"' in page and f'href="{ORIGIN}/texting-privacy"' in page
    assert 'name="website"' in page                                       # the field a person never fills
    church_site["row"] = {"status": "draft"}
    assert run(tr.page_for(BIZ, "signup")) is None                        # not sent: no page
    church_site["row"], church_site["biz"] = SENT_ROW, SHOP
    assert run(tr.page_for(BIZ, "signup")) is None                        # not a church: no page


def test_the_page_shows_how_the_sign_up_went(church_site):
    assert "You're signed up" in tr.html.unescape(run(tr.page_for(BIZ, "signup", note="done")))
    assert "US mobile number" in run(tr.page_for(BIZ, "signup", note="phone"))
    assert 'role="status"' not in run(tr.page_for(BIZ, "signup", note="<script>"))
    assert "<script>" not in run(tr.page_for(BIZ, "signup", note="<script>"))


def test_every_church_site_serves_texts():
    import public_site
    assert "/texts" in public_site._ALWAYS_WINS_PATHS
    src = pathlib.Path(public_site.__file__).read_text(encoding="utf-8")
    assert 'if normalized_path == "/texts":' in src
    assert 'texting_registration.page_for(biz_id, "signup", note=note)' in src


# ── 5. signing up ─────────────────────────────────────────────────────

@pytest.fixture
def signup(monkeypatch):
    import lead_identity
    import public_site
    import sms_routing
    import sms_service
    state = {"biz": CHURCH, "row": SENT_ROW, "person": None, "consents": [], "posts": [], "texts": [],
             "stored": [], "stopped": False, "send_fails": False, "rate_ok": True}

    def read(path):
        if path.startswith("/businesses"):
            return [state["biz"]]
        if path.startswith("/sms_consents"):
            return list(state["consents"])
        raise AssertionError(path)

    def post(path, row, prefer=None):
        state["posts"].append((path, row))
        return [{"id": "new-contact" if path == "/contacts" else "new-consent", **row}]

    async def send(phone, body, business_id=None, client=None):
        if state["send_fails"]:
            raise RuntimeError("twilio down")
        state["texts"].append((phone, body, business_id))
        return "SM1"

    async def store(client, **kw):
        state["stored"].append(kw)
        return "row-1"

    async def stopped(client, phone, business_id=None):
        return state["stopped"]

    monkeypatch.setattr(tr, "_read", read)
    monkeypatch.setattr(tr, "registration", lambda bid: state["row"])
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(lead_identity, "find", lambda bid, **kw: state["person"])
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: state["rate_ok"])
    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_service, "_store_sms", store)
    monkeypatch.setattr(sms_service, "is_opted_out", stopped)
    app = FastAPI()
    app.include_router(tr.router)
    return TestClient(app, follow_redirects=False), state


GOOD_FORM = {"name": "Dana  Reyes", "phone": "(231) 555-0142", "agree": "1"}


def _note(r):
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith("/texts?note=")
    return loc.split("=", 1)[1]


def test_a_sign_up_keeps_the_yes_adds_a_guest_and_confirms_once(signup):
    client, state = signup
    r = client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM, headers={"user-agent": "Phone"})
    assert _note(r) == "done"
    assert "5550142" not in r.headers["location"] and "Dana" not in r.headers["location"]
    (cpath, contact), (kpath, consent) = state["posts"]
    assert cpath == "/contacts" and contact["status"] == "lead" and contact["source"] == "texts_signup"
    assert contact["phone"] == "+12315550142" and contact["name"] == "Dana Reyes" and contact["business_id"] == BIZ
    assert kpath == "/sms_consents" and consent["source"] == "texts_page" and consent["business_id"] == BIZ
    assert consent["phone"] == "+12315550142" and consent["consented_at"] and consent["user_agent"] == "Phone"
    [(phone, body, bid)] = state["texts"]
    assert phone == "+12315550142" and bid == BIZ
    assert body.startswith("Grace Chapel: You're signed up for texts") and "STOP" in body and "HELP" in body
    [stored] = state["stored"]
    assert stored["contact_id"] == "new-contact" and stored["sent_by"] == "system" and stored["direction"] == "outbound"


def test_someone_already_on_the_list_is_kept_not_added(signup):
    client, state = signup
    state["person"] = {"id": "c-9", "name": "Dana Reyes", "phone": "+12315550142"}
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "done"
    assert [p for p, _ in state["posts"]] == ["/sms_consents"]
    assert state["stored"][0]["contact_id"] == "c-9"


def test_signing_up_twice_sends_no_second_text(signup):
    client, state = signup
    state["consents"] = [{"id": "k-1"}]
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "again"
    assert [p for p, _ in state["posts"]] == ["/contacts"] and state["texts"] == []


def test_someone_who_said_stop_is_told_how_to_come_back_and_not_texted(signup):
    client, state = signup
    state["stopped"] = True
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "start"
    assert "/sms_consents" in [p for p, _ in state["posts"]] and state["texts"] == []


def test_a_failed_confirming_text_never_undoes_the_sign_up(signup):
    client, state = signup
    state["send_fails"] = True
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "done"
    assert "/sms_consents" in [p for p, _ in state["posts"]]


@pytest.mark.parametrize("form,note", [
    ({**GOOD_FORM, "name": "  "}, "name"),
    ({**GOOD_FORM, "phone": "555-0142"}, "phone"),
    ({**GOOD_FORM, "phone": "+447700900123"}, "phone"),
    ({k: v for k, v in GOOD_FORM.items() if k != "agree"}, "agree"),
], ids=["no-name", "short-number", "not-us", "box-unchecked"])
def test_a_sign_up_that_isnt_complete_saves_nothing(signup, form, note):
    client, state = signup
    assert _note(client.post(f"/texting/signup/{BIZ}", data=form)) == note
    assert state["posts"] == [] and state["texts"] == []


def test_the_hidden_field_and_the_rate_limit_save_nothing(signup):
    client, state = signup
    assert _note(client.post(f"/texting/signup/{BIZ}", data={**GOOD_FORM, "website": "spam.example"})) == "done"
    state["rate_ok"] = False
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "busy"
    assert state["posts"] == [] and state["texts"] == []


def test_only_a_church_whose_registration_is_sent_takes_sign_ups(signup):
    client, state = signup
    state["row"] = {"status": "draft"}
    assert client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM).status_code == 404
    state["row"], state["biz"] = SENT_ROW, SHOP
    assert client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM).status_code == 404
    assert client.post("/texting/signup/not-a-uuid", data=GOOD_FORM).status_code == 404
    assert state["posts"] == [] and state["texts"] == []


def test_a_failed_save_asks_them_to_try_again(signup, monkeypatch):
    client, state = signup
    monkeypatch.setattr(tr.sb_clients, "sb_post_as_service", lambda *a, **k: None)
    assert _note(client.post(f"/texting/signup/{BIZ}", data=GOOD_FORM)) == "error"
    assert state["texts"] == []
