"""
test_church_cards.py — GET /church/cards, the Forms page's cards.

A church's website can take connect cards and prayer requests on its own
(a <form data-church-form>, sent through contact-submit), and the Forms
page used to say "0 forms" to such a church. These pin:

  * reading: the cards are found in the site's pages, with their real
    questions in order (labels, legends, choices, the send button), the
    honeypot left out, each place a card appears listed once;
  * counting: what came in on each card from the rows each door already
    writes (connect card notes, intake form_submit events, private care
    requests), people distinct and most recent first;
  * privacy: a prayer card is numbers only, never a name, a contact id or
    a word anyone wrote; and only the owner and staff may read any of it;
  * honesty: a failed read is a 503, never a page of zeros.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import church_cards as CC
import church_router
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "00000000-0000-0000-0000-0000000000a1"
STAFF = {role: f"00000000-0000-0000-0000-0000000000b{i}"
         for i, role in enumerate(("admin", "manager", "member", "viewer"))}
STRANGER = "00000000-0000-0000-0000-0000000000d1"
FORM = "22222222-2222-2222-2222-222222222222"
PRIVATE_FORM = "33333333-3333-3333-3333-333333333333"

HERE = os.path.dirname(os.path.abspath(__file__))
LCC_CONNECT = os.path.join(HERE, "..", "sites", "love-city-church", "connect.html")
SECRETS = ("Please pray for my mother", "Dana Whitfield", "dana@example.org", "care-req-9")


def _ago(days, hours=1):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ─── reading the website's cards ─────────────────────────────────────

def test_love_citys_connect_page_yields_both_cards_with_their_real_questions():
    cards = CC.website_cards({"connect": _read(LCC_CONNECT)})
    assert [c["kind"] for c in cards] == ["connect_card", "prayer_request"]
    connect, prayer = cards

    assert connect["title"] == "Connect card"
    assert connect["places"] == [{"page": "connect", "path": "/connect#connect-card"}]
    assert connect["submit"] == "Send my connect card"
    q = {x["name"]: x for x in connect["questions"]}
    assert [x["name"] for x in connect["questions"]] == [
        "first_name", "last_name", "email", "phone", "visits", "interests", "heard_from", "notes"]
    assert q["first_name"] == {"name": "first_name", "label": "First name", "type": "text", "required": True}
    assert q["phone"]["type"] == "phone" and q["phone"]["required"] is False
    assert q["email"]["type"] == "email"
    assert q["visits"]["type"] == "radio" and q["visits"]["required"] is True
    assert q["visits"]["label"] == "How many times have you visited?"
    assert q["visits"]["options"] == ["This is my first time", "A few times", "I’m a regular"]
    assert q["interests"]["type"] == "checkbox" and len(q["interests"]["options"]) == 9
    assert "Next Step ministry training" in q["interests"]["options"]
    assert q["heard_from"]["type"] == "select"
    assert q["heard_from"]["options"][0] == "Facebook", "the empty 'Choose one' prompt is not an answer"
    assert "Choose one" not in q["heard_from"]["options"]
    assert q["notes"]["type"] == "textarea"
    assert "website" not in q, "the honeypot only bots fill in is not a question"

    assert prayer["places"] == [{"page": "connect", "path": "/connect#prayer"}]
    assert prayer["submit"] == "Send my prayer request"
    pq = {x["name"]: x for x in prayer["questions"]}
    assert pq["request"]["label"] == "How can we pray for you?" and pq["request"]["required"] is True
    assert pq["last_name"]["required"] is False
    assert pq["follow_up"] == {"name": "follow_up", "label": "Please follow up with me",
                               "type": "yesno", "required": False}


def test_a_card_on_two_pages_is_one_card_with_two_places_home_first():
    form = ('<section id="say-hi"><h2>Say hello</h2><form data-church-form="connect-card">'
            '<label for="n">Name</label><input id="n" name="first_name" required>'
            '<button type="submit">Send</button></form></section>')
    cards = CC.website_cards({"visit": form, "home": form, "about": "<p>No forms here</p>"})
    assert len(cards) == 1
    assert cards[0]["places"] == [{"page": "home", "path": "/#say-hi"}, {"page": "visit", "path": "/visit#say-hi"}]


def test_unknown_kinds_unparseable_pages_and_plain_contact_forms_are_left_out():
    pages = {
        "a": '<form data-church-form="newsletter"><input name="email"></form>',
        "b": '<form class="contact"><input name="email"></form>',
        "c": 12345,
    }
    assert CC.website_cards(pages) == []


# ─── the route ───────────────────────────────────────────────────────

class FakeDB:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        table = path.split("?", 1)[0].strip("/")
        rows = self.tables.get(table, [])
        if rows is None:
            return None
        if table == "events" and "event_type=eq." in path:
            et = path.split("event_type=eq.", 1)[1].split("&", 1)[0]
            rows = [r for r in rows if r.get("event_type") == et]
            if rows is None:
                return None
        if table == "business_users" and "user_id=eq." in path:
            uid = path.split("user_id=eq.", 1)[1].split("&", 1)[0]
            rows = [r for r in rows if r.get("user_id") == uid and r.get("status") == "active"]
        if table == "contacts" and "id=in.(" in path:
            ids = path.split("id=in.(", 1)[1].split(")", 1)[0].split(",")
            rows = [r for r in rows if r.get("id") in ids]
        return [dict(r) for r in rows]

    def read(self, table):
        return [c for c in self.calls if c.startswith(f"/{table}")]


def _note(contact, days, form="connect_card"):
    return {"event_type": "contact_note", "contact_id": contact, "created_at": _ago(days), "form": form}


def _submit(contact, days, form_id=FORM):
    return {"event_type": "form_submit", "contact_id": contact, "created_at": _ago(days), "form_id": form_id}


def _care(days, form_id=None, source="website prayer request"):
    # What a real row carries, so the test proves none of it is passed on.
    return {"id": "care-req-9", "form_id": form_id, "created_at": _ago(days), "source": source,
            "submission": {"name": "Dana Whitfield", "email": "dana@example.org",
                           "prayer_request": "Please pray for my mother"}}


SITE = [{"slug": "grace", "status": "published", "html_content": "<h1>Home</h1>",
         "generated_pages": {"connect": _read(LCC_CONNECT)}, "offline": None,
         "custom_domain": None, "custom_domain_status": None}]


@pytest.fixture
def api(monkeypatch):
    who = {"user": OWNER}

    def install(**tables):
        tables.setdefault("businesses", [{"id": BIZ, "owner_id": OWNER, "name": "Grace Church"}])
        tables.setdefault("business_users", [
            {"business_id": BIZ, "user_id": uid, "role": role, "status": "active"}
            for role, uid in STAFF.items()])
        tables.setdefault("business_collaborators", [])
        tables.setdefault("business_sites", SITE)
        tables.setdefault("events", [
            _note("p1", 2), _note("p2", 10), _note("p1", 40), _note("p3", 60),
            _note("p9", 3, form=""),                          # a plain contact message, not a card
            _submit("p2", 1), _submit("p4", 50), _submit("p5", 5, form_id="other-form"),
        ])
        tables.setdefault("ministry_care_requests", [
            _care(4), _care(45), _care(6, form_id=PRIVATE_FORM, source="intake"),
            _care(8, source="something else"),                # not the website's prayer card
        ])
        tables.setdefault("contacts", [
            {"id": "p1", "name": "Ann Lee"}, {"id": "p2", "name": "Bo  Ray"},
            {"id": "p3", "name": "Cy Moss"}, {"id": "p4", "name": "Di Fox"},
            {"id": "p5", "name": "Ed Hale"}, {"id": "p9", "name": "Not A Card"}])
        fake = FakeDB(tables)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
        app = FastAPI()
        app.include_router(church_router.router)
        app.dependency_overrides[sb_clients.authed_request] = (
            lambda: SimpleNamespace(user=SimpleNamespace(id=who["user"])))
        client = TestClient(app)

        def get(user=OWNER, business_id=BIZ):
            who["user"] = user
            return client.get(f"/church/cards?business_id={business_id}")
        get.db = fake
        return get
    return install


def test_the_owner_gets_the_websites_cards_and_every_forms_numbers(api):
    get = api()
    r = get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"window_days", "website", "forms", "private_forms"}
    assert body["window_days"] == 90
    assert body["website"]["address"] == "grace.mysolutionist.app"
    assert body["website"]["live"] is True
    connect, prayer = body["website"]["cards"]

    assert connect["kind"] == "connect_card"
    assert connect["stats"]["last_30"] == 2 and connect["stats"]["last_90"] == 4
    assert [p["name"] for p in connect["people"]] == ["Ann Lee", "Bo Ray", "Cy Moss"], \
        "distinct people, most recent first, names tidied"
    assert all(set(p) == {"contact_id", "name", "at"} for p in connect["people"])
    assert "Not A Card" not in r.text

    assert prayer["kind"] == "prayer_request"
    assert prayer["stats"]["last_30"] == 1 and prayer["stats"]["last_90"] == 2
    assert "people" not in prayer

    assert body["forms"][FORM]["stats"]["last_90"] == 2
    assert [p["name"] for p in body["forms"][FORM]["people"]] == ["Bo Ray", "Di Fox"]
    assert body["forms"]["other-form"]["stats"]["last_30"] == 1
    assert body["private_forms"] == {PRIVATE_FORM: {"stats": body["private_forms"][PRIVATE_FORM]["stats"]}}
    assert body["private_forms"][PRIVATE_FORM]["stats"]["last_90"] == 1


def test_prayer_is_numbers_only(api):
    get = api()
    r = get()
    assert r.status_code == 200
    assert not any(s in r.text for s in SECRETS)
    care_reads = get.db.read("ministry_care_requests")
    assert len(care_reads) == 1
    assert care_reads[0].split("select=", 1)[1].split("&", 1)[0] == "form_id,created_at,source:submission->>source"


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_staff_seats_read_it(api, role):
    assert api()(STAFF[role]).status_code == 200


@pytest.mark.parametrize("user", [STAFF["member"], STAFF["viewer"], STRANGER],
                         ids=["member", "viewer", "stranger"])
def test_everyone_else_is_refused_before_anything_is_read(api, user):
    get = api()
    r = get(user)
    assert r.status_code == 404
    for table in ("business_sites", "events", "ministry_care_requests", "contacts"):
        assert get.db.read(table) == []


@pytest.mark.parametrize("table", ["business_sites", "events", "ministry_care_requests", "contacts"])
def test_a_failed_read_is_a_503_never_zeros(api, table):
    get = api(**{table: None})
    r = get()
    assert r.status_code == 503
    assert "couldn't be loaded" in r.json()["detail"]


def test_reads_are_pinned_to_the_business_and_the_window(api):
    get = api()
    get()
    for table in ("events", "ministry_care_requests"):
        for q in get.db.read(table):
            assert f"business_id=eq.{BIZ}" in q and "created_at=gte." in q and "+" not in q
    assert all(f"business_id=eq.{BIZ}" in q for q in get.db.read("business_sites"))
    assert all(f"business_id=eq.{BIZ}" in q for q in get.db.read("contacts"))


def test_no_site_means_no_website_cards_and_still_the_forms(api):
    get = api(business_sites=[])
    body = get().json()
    assert body["website"] == {"address": None, "live": False, "cards": []}
    assert body["forms"][FORM]["stats"]["last_90"] == 2


def test_an_unpublished_or_offline_site_says_so(api):
    draft = [dict(SITE[0], status="draft")]
    assert api(business_sites=draft)().json()["website"]["live"] is False
    offline = [dict(SITE[0], offline=True)]
    assert api(business_sites=offline)().json()["website"]["live"] is False
    verified = [dict(SITE[0], custom_domain="lovecityc.com", custom_domain_status="verified")]
    assert api(business_sites=verified)().json()["website"]["address"] == "lovecityc.com"
