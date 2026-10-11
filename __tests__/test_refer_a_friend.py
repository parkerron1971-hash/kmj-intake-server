"""Refer a friend: give $10, get $10 (2026-10-11, the Reach plan's step 3).

The approved Offers board: each regular gets their own link; their friend
saves on a first visit; the regular saves on their next one after the
friend's visit is paid. Kevin, 2026-10-10 ("go" on default 3): the friend's
code works on a first visit only; the regular's code is sent when the
friend's visit is paid.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import offers as of  # noqa: E402
import refer_a_friend as rf  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
PID = "0ff00000-0000-4000-8000-0000000000ff"
RID = "7e000000-0000-4000-8000-000000000001"
C_REF = "c1000000-0000-4000-8000-000000000001"
C_FRIEND = "c1000000-0000-4000-8000-000000000002"
C_OTHER = "c1000000-0000-4000-8000-000000000003"
E1, E2, E3 = ("e1000000-0000-4000-8000-000000000001", "e1000000-0000-4000-8000-000000000002",
              "e1000000-0000-4000-8000-000000000003")
CHI = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)                # Thursday, noon in Chicago
BOOK = "https://northside.mysolutionist.app/book"


def run(x):
    return asyncio.run(x)


def prog(**over):
    return {"id": PID, "business_id": BIZ, "code": "REFER-A-FRIEND", "kind": "amount_off", "amount_cents": 1000,
            "percent": None, "free_item": None, "title": "Refer a friend", "who": "first_visit", "hours": None,
            "starts_on": None, "ends_on": None, "one_per_person": True, "max_uses": None, "status": "on",
            "source": "referral", "reward_cents": 1000, "in_notes": True, **over}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    import business_marketing
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: CHI)


# ── the words and the codes ───────────────────────────────────────────

def test_the_words():
    assert rf.friend_title(prog(), "Andre Smith") == "$10 off your first visit, from Andre"
    assert rf.friend_title(prog(amount_cents=1500), None) == "$15 off your first visit"
    assert rf.thanks_title(1000) == "$10 off your next visit, for sending a friend"
    assert rf.ps_words(prog(reward_cents=1500), "L") == (
        "P.S. Bring a friend: they get $10 off their first visit, and you get $15 off your next one once "
        "they've been in. Your own link: L")
    assert rf.ps_words(prog(), "L", "sms") == "Bring a friend: $10 off for them, $10 off for you. L"
    w = rf.thanks_words(business={"name": "Northside Cuts"}, referrer={"name": "Andre Smith"},
                        friend={"name": "Maya Lee"}, reward={"amount_cents": 1000, "code": "THANKS-7KQ2"},
                        book=BOOK, own_link=f"{BOOK}?offer=ANDRE-7K")
    assert w["subject"] == "Thank you for sending Maya"
    assert w["email"].startswith("Hi Andre,\n\nMaya came in, thanks to you. Here's $10 off your next visit: "
                                 "use the code THANKS-7KQ2 when you book, or say it at the counter.\n"
                                 f"{BOOK}?offer=THANKS-7KQ2\n")
    assert f"Your own link still works:\n{BOOK}?offer=ANDRE-7K\n\nNorthside Cuts" in w["email"]
    assert w["text"] == ("Thanks for sending Maya, Andre! $10 off your next visit with the code THANKS-7KQ2. "
                         f"Book: {BOOK}?offer=THANKS-7KQ2")
    bare = rf.thanks_words(business={"name": "Northside Cuts"}, referrer={"name": ""}, friend=None,
                           reward={"amount_cents": 1000, "code": "THANKS-7KQ2"}, book=None, own_link=None)
    assert bare["subject"] == "Thank you for sending a friend" and "Your friend came in" in bare["email"]
    assert "http" not in bare["email"] and "Hi there," in bare["email"]


def test_codes_are_sayable_and_fit_an_offer_code():
    for name, lead in (("Andre Smith", "ANDRE-"), ("José", "JOSE-"), ("Bartholomew-Jones", "BARTHOLOME-")):
        code = rf.name_code(name)
        assert code.startswith(lead) and of.CODE.match(code), code
    for name in ("李", "", None, "A"):
        code = rf.name_code(name)
        assert re.fullmatch(r"FRIEND-[A-Z2-9]{4}", code) and of.CODE.match(code), code
    assert not set(rf.SAFE) & set("01OIL")


# ── at booking ────────────────────────────────────────────────────────

class Reads:
    def __init__(self, monkeypatch, *, link=None, reward=None, program=prog(), visits=0, used=False, names=None,
                 owner=()):
        self.paths = []

        def read(path):
            self.paths.append(path)
            if path.startswith("/offers?") and "code=eq." in path:
                code = path.split("code=eq.")[1].split("&")[0]
                return [o for o in owner if o["code"] == code]
            if path.startswith("/offers?") and "source=eq.referral" in path:
                return [program] if program else []
            if path.startswith("/referral_links?") and "code=eq." in path:
                return [link] if link else []
            if path.startswith("/referral_rewards?") and "code=eq." in path:
                return [reward] if reward else []
            if path.startswith("/contacts?"):
                return [{"id": k, "name": v} for k, v in (names or {}).items()]
            if path.startswith("/sessions?"):
                return [{"id": f"s{i}"} for i in range(visits)]
            if path.startswith("/module_entries?"):
                return [{"id": "b0"}] if used else []
            raise AssertionError(path)

        monkeypatch.setattr(of, "_read", read)


LINK = {"contact_id": C_REF, "code": "ANDRE-7K"}


def ev(code, contact=C_FRIEND, cents=4000):
    return of.evaluate({"id": BIZ}, code, contact_id=contact, slot_iso=NOW.isoformat(), service_cents=cents, now=NOW)


def test_a_friend_gets_the_offer_on_a_first_visit(monkeypatch):
    r = Reads(monkeypatch, link=LINK, names={C_REF: "Andre Smith"})
    assert ev("andre-7k") == {
        "id": PID, "code": "ANDRE-7K", "title": "$10 off your first visit, from Andre", "kind": "amount_off",
        "source": "referral", "part": "friend", "referrer_contact_id": C_REF, "at": NOW.isoformat(),
        "applies": True, "why": None, "discount_cents": 1000}
    assert all(f"business_id=eq.{BIZ}" in p for p in r.paths)               # this business's records only
    Reads(monkeypatch, link=LINK, visits=2)
    assert ev("ANDRE-7K")["why"] == "This offer is for a first visit."
    Reads(monkeypatch, link=LINK, used=True)
    assert ev("ANDRE-7K")["why"] == "You've already used this offer."
    Reads(monkeypatch, link=LINK, program=prog(status="paused"))
    assert ev("ANDRE-7K")["why"] == "This offer is paused right now."


def test_a_client_cannot_use_their_own_link(monkeypatch):
    Reads(monkeypatch, link=LINK)
    d = ev("ANDRE-7K", contact=C_REF)
    assert d["applies"] is False and d["why"].startswith("That's your own link.") and d["discount_cents"] == 0


def test_the_programs_own_code_is_not_a_code_anyone_can_use(monkeypatch):
    Reads(monkeypatch, owner=[prog()])
    assert ev("REFER-A-FRIEND") is None
    Reads(monkeypatch)
    assert ev("NOPE") is None


def test_a_thank_you_is_for_the_regular_once(monkeypatch):
    reward = {"id": RID, "code": "THANKS-7KQ2", "referrer_contact_id": C_REF, "amount_cents": 1000}
    Reads(monkeypatch, reward=reward)
    d = ev("thanks-7kq2", contact=C_REF)
    assert d == {"id": RID, "code": "THANKS-7KQ2", "title": "$10 off your next visit, for sending a friend",
                 "kind": "amount_off", "source": "referral", "part": "thanks", "applies": True, "why": None,
                 "discount_cents": 1000}
    assert ev("THANKS-7KQ2", contact=C_REF, cents=600)["discount_cents"] == 600
    assert ev("THANKS-7KQ2", contact=C_FRIEND)["why"].startswith("This thank-you is for the client who sent a friend")
    assert ev("THANKS-7KQ2", contact=None)["applies"] is False
    Reads(monkeypatch, reward=reward, used=True)
    assert ev("THANKS-7KQ2", contact=C_REF)["why"] == "You've already used this thank-you."


def test_the_booking_page_shows_the_friends_offer_while_it_is_on(monkeypatch):
    Reads(monkeypatch, link=LINK, names={C_REF: "Andre Smith"})
    assert rf.public_words(BIZ, "andre-7k") == {"code": "ANDRE-7K", "title": "$10 off your first visit, from Andre",
                                                "when": ""}
    Reads(monkeypatch, link=LINK, program=prog(status="paused"))
    assert rf.public_words(BIZ, "ANDRE-7K") is None
    Reads(monkeypatch, reward={"amount_cents": 1500})
    assert rf.public_words(BIZ, "THANKS-7KQ2")["title"] == "$15 off your next visit, for sending a friend"
    Reads(monkeypatch)
    assert rf.public_words(BIZ, "NOPE") is None


# ── the thank-you ─────────────────────────────────────────────────────

def friend_entry(eid=E1, **over):
    return {"id": eid, "business_id": BIZ, "created_at": "2026-10-10T12:00:00+00:00",
            "paid_at": "2026-10-10T12:01:00+00:00", "status": "active", "deposit": None, "contact_id": C_FRIEND,
            "offer": {"part": "friend", "applies": True, "referrer_contact_id": C_REF,
                      "at": "2026-10-14T20:00:00+00:00"}, **over}


def test_when_a_friends_visit_counts_as_paid():
    e = friend_entry()
    assert rf.paid_how(e, [], NOW) == "online"
    assert rf.paid_how({**e, "offer": {**e["offer"], "at": "2026-10-16T20:00:00+00:00"}}, [], NOW) is None  # not yet
    assert rf.paid_how({**e, "deposit": "2026-10-10T12:01:00+00:00"}, [], NOW) is None   # only a deposit online
    unpaid = {**e, "paid_at": None}
    assert rf.paid_how(unpaid, [], NOW) is None
    assert rf.paid_how(unpaid, [{"contact_id": C_FRIEND, "paid_at": "2026-10-14T21:00:00+00:00"}], NOW) == "invoice"
    assert rf.paid_how(unpaid, [{"contact_id": C_FRIEND, "paid_at": "2026-10-01T21:00:00+00:00"}], NOW) is None
    assert rf.paid_how(unpaid, [{"contact_id": C_OTHER, "paid_at": "2026-10-14T21:00:00+00:00"}], NOW) is None


class Store:
    def __init__(self, monkeypatch, *, entries=(), rewarded=(), program=prog(), invoices=(), existing=()):
        self.posts, self.patches, self.paths = [], [], []

        def read(path):
            self.paths.append(path)
            if path.startswith("/module_entries?") and "part=eq.friend" in path:
                return [dict(e) for e in entries]
            if path.startswith("/referral_rewards?friend_booking_id=in."):
                return [{"friend_booking_id": r} for r in rewarded]
            if path.startswith("/referral_rewards?") and "or=(" in path:
                return list(existing)
            if "code=eq." in path:
                return []
            if path.startswith("/offers?") and "source=eq.referral" in path:
                return [program] if program else []
            if path.startswith("/invoices?"):
                assert f"business_id=eq.{BIZ}" in path and "status=eq.paid" in path
                return list(invoices)
            raise AssertionError(path)

        def post(path, row):
            self.posts.append((path, row))
            return [{**row, "id": RID, "issued_at": NOW.isoformat()}]

        monkeypatch.setattr(of, "_read", read)
        monkeypatch.setattr(rf.sb_clients, "sb_post_as_service", post)


def test_a_paid_friends_visit_makes_one_thank_you(monkeypatch):
    s = Store(monkeypatch, entries=[friend_entry(E1), friend_entry(E2, paid_at=None), friend_entry(E3)],
              rewarded=[E3], program=prog(reward_cents=1500))
    assert rf.issue_paid(NOW) == 1
    [(path, row)] = s.posts
    assert path == "/referral_rewards" and row["friend_booking_id"] == E1 and row["paid_how"] == "online"
    assert row["referrer_contact_id"] == C_REF and row["friend_contact_id"] == C_FRIEND
    assert row["amount_cents"] == 1500 and re.fullmatch(r"THANKS-[A-Z2-9]{4}", row["code"])
    s = Store(monkeypatch, entries=[friend_entry(E2, paid_at=None)],
              invoices=[{"contact_id": C_FRIEND, "paid_at": "2026-10-14T21:00:00+00:00"}])
    assert rf.issue_paid(NOW) == 1 and s.posts[0][1]["paid_how"] == "invoice"


def test_never_twice_and_never_for_your_own_link(monkeypatch):
    s = Store(monkeypatch, existing=[{"id": "x"}])
    assert rf.issue(BIZ, friend_entry(), "online", 1000) is None and s.posts == []
    s = Store(monkeypatch)
    assert rf.issue(BIZ, friend_entry(contact_id=C_REF), "online", 1000) is None and s.posts == []
    assert rf.issue(BIZ, friend_entry(), "owner", 1000)["code"].startswith("THANKS-")


class Mail:
    def __init__(self, monkeypatch, *, channel="email", claim=True, reward=None, contacts=None):
        import outreach_journeys as journeys
        self.order, self.sent = [], []
        reward = reward or {"id": RID, "business_id": BIZ, "referrer_contact_id": C_REF, "friend_contact_id": C_FRIEND,
                            "code": "THANKS-7KQ2", "amount_cents": 1000, "sent_at": None}
        people = contacts if contacts is not None else [
            {"id": C_REF, "name": "Andre Smith", "email": "andre@example.com"}, {"id": C_FRIEND, "name": "Maya Lee"}]

        def read(path):
            if path.startswith("/referral_rewards?sent_at=is.null"):
                return [dict(reward)]
            if path.startswith("/businesses?"):
                return [{"id": BIZ, "name": "Northside Cuts", "settings": {}}]
            if path.startswith("/contacts?"):
                return list(people)
            if path.startswith("/referral_links?") and "contact_id=eq." in path:
                return [{"code": "ANDRE-7K"}]
            raise AssertionError(path)

        def patch(path, body):
            self.order.append(("claim", path, body))
            return [body] if claim else []

        async def pick(client, business, contact):
            return channel

        async def send(client, business, contact, ch, **kw):
            self.order.append(("send", ch))
            self.sent.append({"to": contact, "channel": ch, **kw})

        monkeypatch.setattr(of, "_read", read)
        monkeypatch.setattr(rf.sb_clients, "sb_patch_as_service", patch)
        monkeypatch.setattr(rf, "booking_page", lambda b: BOOK)
        monkeypatch.setattr(journeys, "_channel", pick)
        monkeypatch.setattr(journeys, "send", send)


def test_the_thank_you_is_claimed_then_sent_in_the_daytime(monkeypatch):
    m = Mail(monkeypatch)
    assert run(rf.send_unsent(NOW)) == {"email": 1, "sms": 0, "none": 0}
    assert [o[0] for o in m.order] == ["claim", "send"]                     # claimed before anything is sent
    assert "sent_at=is.null" in m.order[0][1] and m.order[0][2]["sent_by"] == "email"
    [mail] = m.sent
    assert mail["to"]["email"] == "andre@example.com" and mail["subject"] == "Thank you for sending Maya"
    assert f"{BOOK}?offer=THANKS-7KQ2" in mail["email"] and f"{BOOK}?offer=ANDRE-7K" in mail["email"]
    assert mail["event"] == {"journey": "referral_thanks", "channel": "email"}
    m = Mail(monkeypatch, claim=False)                                       # another worker has it
    assert run(rf.send_unsent(NOW))["email"] == 0 and m.sent == []
    night = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)               # 3 AM in Chicago
    m = Mail(monkeypatch)
    assert run(rf.send_unsent(night)) == {"email": 0, "sms": 0, "none": 0} and m.order == []


def test_no_way_to_reach_them_leaves_it_for_the_counter(monkeypatch):
    m = Mail(monkeypatch, channel=None)
    assert run(rf.send_unsent(NOW)) == {"email": 0, "sms": 0, "none": 1}
    assert m.order == [("claim", m.order[0][1], {"sent_at": NOW.isoformat(), "sent_by": "none"})] and m.sent == []


def test_the_sweep_has_a_kill_switch(monkeypatch):
    monkeypatch.setenv("REFER_A_FRIEND", "off")
    monkeypatch.setattr(of, "_read", lambda path: (_ for _ in ()).throw(AssertionError(path)))
    assert run(rf.rewards_tick(NOW)) == {"issued": 0, "email": 0, "sms": 0, "none": 0}


# ── the owner's routes ────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    state = {"program": None, "ready": True, "posts": [], "patches": [], "entries": {}, "existing": []}
    app = FastAPI()
    app.include_router(rf.router)

    def biz():
        return {"id": BIZ, "name": "Northside Cuts", "settings": {}}

    def read(path):
        if path.startswith("/offers?") and "source=eq.referral" in path:
            return [state["program"]] if state["program"] else []
        if "code=eq." in path:
            return []
        if path.startswith("/contacts?"):
            return [{"id": C_REF, "name": "Andre Smith"}] if C_REF in path else []
        if path.startswith("/referral_links?") and "contact_id=eq." in path:
            return []
        if path.startswith("/module_entries?id=eq."):
            eid = path.split("id=eq.")[1].split("&")[0]
            return [state["entries"][eid]] if eid in state["entries"] else []
        if path.startswith("/referral_rewards?") and "or=(" in path:
            return list(state["existing"])
        raise AssertionError(path)

    def post(path, row):
        state["posts"].append((path, row))
        if path == "/offers":
            state["program"] = {**row, "id": PID}
        return [{**row, "id": RID}]

    def patch(path, body):
        state["patches"].append((path, body))
        state["program"].update(body)
        return [body]

    async def overview(b, now=None):
        return {"on": bool(state["program"] and state["program"]["status"] == "on")}

    monkeypatch.setattr(of, "_read", read)
    monkeypatch.setattr(of, "payments_ready", lambda b: state["ready"])
    monkeypatch.setattr(rf, "overview", overview)
    monkeypatch.setattr(rf, "booking_page", lambda b: BOOK)
    monkeypatch.setattr(rf.sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(rf.sb_clients, "sb_patch_as_service", patch)
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for d in r.dependant.dependencies:
                if d.name == "biz":
                    app.dependency_overrides[d.call] = biz
    return TestClient(app), state


def test_switching_it_on_needs_card_payments_and_makes_the_program(api):
    client, state = api
    state["ready"] = False
    r = client.put(f"/offers/{BIZ}/referral", json={"on": True})
    assert r.status_code == 409 and "Connect card payments in Payments" in r.json()["detail"]
    state["ready"] = True
    r = client.put(f"/offers/{BIZ}/referral", json={"on": True, "friend_cents": 1500})
    assert r.status_code == 200 and r.json()["referral"] == {"on": True}
    [(path, row)] = state["posts"]
    assert path == "/offers" and row["source"] == "referral" and row["who"] == "first_visit"
    assert row["amount_cents"] == 1500 and row["reward_cents"] == 1000 and row["in_notes"] is True
    assert row["one_per_person"] is True and row["code"] == "REFER-A-FRIEND"
    r = client.put(f"/offers/{BIZ}/referral", json={"on": False, "in_notes": False})
    assert r.status_code == 200 and state["patches"][-1][1]["status"] == "paused"
    assert state["patches"][-1][1]["in_notes"] is False and "source=eq.referral" in state["patches"][-1][0]
    assert client.put(f"/offers/{BIZ}/referral", json={"on": True, "reward_cents": 50}).status_code == 422


def test_a_clients_link_to_send_yourself(api):
    client, state = api
    assert client.post(f"/offers/{BIZ}/referral/link", json={"contact_id": C_REF}).status_code == 409   # off
    state["program"] = prog()
    r = client.post(f"/offers/{BIZ}/referral/link", json={"contact_id": C_REF})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Andre Smith" and body["code"].startswith("ANDRE-")
    assert body["link"] == f"{BOOK}?offer={body['code']}"
    assert state["posts"][-1][0] == "/referral_links" and state["posts"][-1][1]["contact_id"] == C_REF
    assert client.post(f"/offers/{BIZ}/referral/link", json={"contact_id": C_OTHER}).status_code == 404


def test_the_owner_says_a_friends_visit_is_paid(api):
    client, state = api
    state["program"] = prog(reward_cents=1500)
    state["entries"][E1] = friend_entry(E1, paid_at=None)
    state["entries"][E2] = {**friend_entry(E2), "offer": {"part": "friend", "applies": False}}
    r = client.post(f"/offers/{BIZ}/referral/paid", json={"booking_id": E1})
    assert r.status_code == 200, r.text
    reward = [row for path, row in state["posts"] if path == "/referral_rewards"][0]
    assert reward["paid_how"] == "owner" and reward["amount_cents"] == 1500 and reward["friend_booking_id"] == E1
    assert client.post(f"/offers/{BIZ}/referral/paid", json={"booking_id": E2}).status_code == 404
    assert client.post(f"/offers/{BIZ}/referral/paid", json={"booking_id": E3}).status_code == 404
    state["existing"] = [{"id": "x"}]
    assert client.post(f"/offers/{BIZ}/referral/paid", json={"booking_id": E1}).status_code == 409


def test_the_routes_change_as_the_owner():
    src = pathlib.Path(rf.__file__).read_text(encoding="utf-8")
    assert src.count('business_access("owner")') == 3 and 'business_access("viewer")' not in src
    assert {r.path for r in rf.router.routes} == {
        "/offers/{business_id}/referral", "/offers/{business_id}/referral/link", "/offers/{business_id}/referral/paid"}


def test_an_owners_offer_never_takes_a_clients_code(monkeypatch):
    """A suggested code steps around one a client already has; a chosen one
    is refused."""
    calls = []
    monkeypatch.setattr(rf, "code_in_use", lambda bid, code: calls.append(code) or code == "FIRST10")
    app = FastAPI()
    app.include_router(of.router)
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for d in r.dependant.dependencies:
                if d.name == "biz":
                    app.dependency_overrides[d.call] = lambda: {"id": BIZ}
    posts = []

    async def overview(b):
        return {"offers": [], "payments_ready": True}

    monkeypatch.setattr(of, "payments_ready", lambda b: True)
    monkeypatch.setattr(of, "_read", lambda path: [])
    monkeypatch.setattr(of, "overview", overview)
    monkeypatch.setattr(of.sb_clients, "sb_post_as_service", lambda path, row: posts.append(row) or [row])
    client = TestClient(app)
    assert client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 1000,
                                               "who": "first_visit"}).status_code == 200
    assert posts[0]["code"] == "FIRST10-2"
    r = client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 1000, "code": "first10"})
    assert r.status_code == 409 and "FIRST10" in r.json()["detail"] and len(posts) == 1
