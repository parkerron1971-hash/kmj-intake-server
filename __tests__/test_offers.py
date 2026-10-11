"""Offers: a code, a link and a QR code in one (2026-10-10, the Reach plan's step 3).

Kevin's four defaults ("go", 2026-10-10):
  1. off the online payment only when it is the full price; else the counter;
  2. who and when are checked by our booking page, never a typed code;
  3. (refer-a-friend: its own module);
  4. no card payments connected: Offers says so and links to Payments.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import offers as of  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
OID = "0ff00000-0000-4000-8000-000000000001"
C1 = "c1000000-0000-4000-8000-000000000001"
CHI = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)                # Thursday, noon in Chicago


def run(x):
    return asyncio.run(x)


def offer(**over):
    return {"id": OID, "business_id": BIZ, "code": "FIRST10", "kind": "amount_off", "amount_cents": 1000,
            "percent": None, "free_item": None, "title": "$10 off your first visit", "who": "first_visit",
            "hours": None, "starts_on": None, "ends_on": None, "one_per_person": True, "max_uses": None,
            "status": "on", "source": "owner", **over}


# ── the words ─────────────────────────────────────────────────────────

def test_the_words_say_what_who_and_when():
    assert of.what_words(offer()) == "$10 off"
    assert of.what_words(offer(kind="percent_off", percent=15)) == "15% off"
    assert of.what_words(offer(kind="free_item", free_item="Beard line-up")) == "A free beard line-up"
    assert of.default_title(offer()) == "$10 off your first visit"
    assert of.default_title(offer(who="regulars", amount_cents=500)) == "$5 off your next visit"
    assert of.default_title(offer(kind="free_item", free_item="Beard line-up", who="anyone")) == "A free beard line-up"
    slow = offer(hours={"days": [2, 3, 4], "start": "14:00", "end": "17:00"}, ends_on="2026-11-01")
    assert of.when_words(slow) == "Tue to Thu, 2 PM to 5 PM · through Sun, Nov 1"
    assert of.when_words(offer()) == "Always on"


def test_codes_are_short_sayable_and_never_taken():
    assert of.suggest_code(offer(), set()) == "FIRST10"
    assert of.suggest_code(offer(who="regulars", amount_cents=500), set()) == "BACK5"
    assert of.suggest_code(offer(who="anyone", kind="percent_off", percent=15), set()) == "SAVE15"
    assert of.suggest_code(offer(kind="free_item", free_item="x"), set()) == "FREE"
    assert of.suggest_code(offer(), {"FIRST10"}) == "FIRST10-2"


# ── the money ─────────────────────────────────────────────────────────

def test_the_discount_and_when_it_comes_off_online():
    assert of.discount_cents(offer(), 4000) == 1000
    assert of.discount_cents(offer(amount_cents=9000), 4000) == 4000           # never more than the price
    assert of.discount_cents(offer(kind="percent_off", percent=15), 4000) == 600
    assert of.discount_cents(offer(kind="free_item", free_item="x"), 4000) == 0  # given at the counter
    yes = {"applies": True, "discount_cents": 1000}
    assert of.online_discount(yes, amount_cents=4000, deposit_cents=None) == 1000
    assert of.online_discount(yes, amount_cents=4000, deposit_cents=1500) == 0   # a deposit: the counter takes it
    assert of.online_discount(yes, amount_cents=1040, deposit_cents=None) == 0   # under 50 cents left: the counter
    assert of.online_discount({**yes, "applies": False}, amount_cents=4000, deposit_cents=None) == 0
    assert of.online_discount(None, amount_cents=4000, deposit_cents=None) == 0


def test_the_checkout_charges_less_keeps_the_tip_and_stops_typed_codes():
    import stripe_checkout_helpers as h
    parts = h._booking_checkout_parts(service_name="Fade", amount_cents=4000, tip_cents=800,
                                      offer={"code": "FIRST10", "title": "$10 off your first visit", "discount_cents": 1000})
    assert parts["line_items"] == [{"name": "Fade (FIRST10: $10 off your first visit)", "amount_cents": 3000, "quantity": 1},
                                   {"name": "Tip", "amount_cents": 800, "quantity": 1}]
    assert parts["extra_metadata"]["offer_code"] == "FIRST10" and parts["extra_metadata"]["discount_cents"] == 1000
    deposit = h._booking_checkout_parts(service_name="Fade", amount_cents=4000, deposit_cents=1000,
                                        offer={"code": "FIRST10", "title": "x", "discount_cents": 1000})
    assert deposit["line_items"][0]["amount_cents"] == 1000 and "offer_code" not in deposit["extra_metadata"]
    src = pathlib.Path(h.__file__).read_text(encoding="utf-8")
    assert '"offer_code" not in parts["extra_metadata"]' in src


# ── who and when ──────────────────────────────────────────────────────

def chk(o, *, slot=NOW, past=0, used=False, uses=0, now=NOW):
    return of.check(o, now=now, tz=CHI, slot=slot, past_visits=past, used_before=used, uses=uses)


def test_every_rule_on_the_board():
    assert chk(offer()) == (True, None)
    assert chk(offer(status="paused"))[0] is False
    assert chk(offer(starts_on="2026-10-20"))[1] == "This offer starts Oct 20."
    assert chk(offer(ends_on="2026-10-14"))[1] == "This offer has ended."
    assert chk(offer(max_uses=30), uses=30)[1] == "This offer has been used up."
    assert chk(offer(), past=2)[1] == "This offer is for a first visit."
    assert chk(offer(who="regulars"))[1] == "This offer is for returning clients."
    assert chk(offer(who="regulars"), past=1) == (True, None)
    assert chk(offer(who="anyone"), used=True)[1] == "You've already used this offer."
    assert chk(offer(who="anyone", one_per_person=False), used=True) == (True, None)
    slow = offer(who="anyone", hours={"days": [2, 3, 4], "start": "14:00", "end": "17:00"})
    thu_3pm = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)          # 3 PM in Chicago
    sat_3pm = datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
    assert chk(slow, slot=thu_3pm) == (True, None)
    assert chk(slow, slot=sat_3pm)[1] == "This offer is for Tue to Thu, 2 PM to 5 PM."
    assert chk(slow, slot=datetime(2026, 10, 15, 23, 0, tzinfo=timezone.utc))[0] is False  # 6 PM


class Reads:
    def __init__(self, monkeypatch, offers=(), visits=0, used=False, uses=0, fail=False):
        self.paths = []

        def read(path):
            self.paths.append(path)
            if fail:
                raise RuntimeError("down")
            if path.startswith("/offers"):
                code = path.split("code=eq.")[1].split("&")[0]
                return [o for o in offers if o["code"] == code]
            if path.startswith("/sessions"):
                return [{"id": f"s{i}"} for i in range(visits)]
            if path.startswith("/module_entries") and "contact_id" in path:
                return [{"id": "b0"}] if used else []
            if path.startswith("/module_entries"):
                return [{"id": f"b{i}"} for i in range(uses)]
            raise AssertionError(path)

        import business_marketing
        monkeypatch.setattr(of, "_read", read)
        monkeypatch.setattr(business_marketing, "business_tz", lambda row: CHI)


def test_a_booking_records_whether_the_offer_applies_and_why(monkeypatch):
    r = Reads(monkeypatch, offers=[offer()])
    d = of.evaluate({"id": BIZ}, "first10", contact_id=C1, slot_iso=NOW.isoformat(), service_cents=4000, now=NOW)
    assert d == {"id": OID, "code": "FIRST10", "title": "$10 off your first visit", "kind": "amount_off",
                 "applies": True, "why": None, "discount_cents": 1000}
    assert all(f"business_id=eq.{BIZ}" in p for p in r.paths)               # this business's records only
    Reads(monkeypatch, offers=[offer()], visits=3)
    d = of.evaluate({"id": BIZ}, "FIRST10", contact_id=C1, slot_iso=NOW.isoformat(), service_cents=4000, now=NOW)
    assert d["applies"] is False and d["why"] == "This offer is for a first visit." and d["discount_cents"] == 0
    Reads(monkeypatch, offers=[])
    assert of.evaluate({"id": BIZ}, "NOPE", contact_id=C1, slot_iso=None, service_cents=4000, now=NOW) is None
    Reads(monkeypatch, offers=[offer(max_uses=2)], uses=2)
    assert of.evaluate({"id": BIZ}, "FIRST10", contact_id=None, slot_iso=None, service_cents=4000, now=NOW)["why"] == \
        "This offer has been used up."


def test_the_booking_keeps_the_servers_decision_and_the_owner_reads_it(monkeypatch):
    import booking_widget_router as bw
    Reads(monkeypatch, offers=[offer()])
    entry = {"price_at_booking": 40, "offer": {"applies": True, "discount_cents": 99999}}   # forged by the form
    d = bw._apply_offer({"id": BIZ}, entry, "FIRST10", C1, NOW.isoformat())
    assert entry["offer"] == d and d["discount_cents"] == 1000
    plain = {"price_at_booking": 40, "offer": {"applies": True}}
    assert bw._apply_offer({"id": BIZ}, plain, None, C1, None) is None and "offer" not in plain
    assert of.counter_note(d) == ("Offer FIRST10: $10 off your first visit ($10). If they paid online it's already "
                                  "taken off; otherwise take it off at the counter.")
    assert bw._offer_note({"offer": {**d, "applies": False}}) is None
    assert "offer_code" in bw.BookAnonBody.model_fields and "offer_code" in bw.BookBody.model_fields


# ── the links ─────────────────────────────────────────────────────────

def test_an_offer_link_opens_the_booking_page_with_the_code_in(monkeypatch):
    import business_marketing_links as links
    import business_marketing_sent_links as sl
    import business_marketing_store as store
    site = {"business_id": BIZ, "slug": "northside", "published": True, "custom_domain": None, "custom_domain_status": None}
    rows = []

    async def request(method, path, body=None):
        rows.append(body)
        return [body]

    monkeypatch.setattr(links, "site_for", lambda bid: site)
    monkeypatch.setattr(links, "bookable", lambda bid, biz: True)
    monkeypatch.setattr(store, "request", request)
    share = run(sl.offer_link({"id": BIZ}, offer(), 0))
    printed = run(sl.offer_link({"id": BIZ}, offer(), 1))
    assert share != printed and share.startswith("https://northside.mysolutionist.app/go/")
    q = parse_qs(urlsplit(rows[0]["tracked_url"]).query)
    assert urlsplit(rows[0]["tracked_url"]).path == "/book" and q["offer"] == ["FIRST10"]
    assert q["utm_source"] == ["share"] and q["utm_medium"] == ["offer"] and q["utm_campaign"] == ["FIRST10"]
    assert parse_qs(urlsplit(rows[1]["tracked_url"]).query)["utm_source"] == ["print"]
    assert rows[0]["kind"] == "offer" and rows[0]["channel"] is None
    monkeypatch.setattr(links, "bookable", lambda bid, biz: False)
    assert run(sl.offer_link({"id": BIZ}, offer(), 0)) is None              # the code still works at the counter


# ── the owner's routes ────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    from business_access import business_access
    state = {"offers": [], "ready": True, "posts": [], "patches": []}
    app = FastAPI()
    app.include_router(of.router)

    def biz():
        return {"id": BIZ, "name": "Northside Cuts"}

    import offers as module
    monkeypatch.setattr(module, "payments_ready", lambda b: state["ready"])

    def read(path):
        if path.startswith("/offers"):
            if "code=eq." in path:
                code = path.split("code=eq.")[1].split("&")[0]
                return [o for o in state["offers"] if o["code"] == code]
            return list(state["offers"])
        return []

    async def overview(b):
        return {"offers": [dict(o) for o in state["offers"]], "payments_ready": state["ready"]}

    def post(path, row):
        state["posts"].append(row)
        state["offers"].append({**row, "id": OID})
        return [row]

    def patch(path, body):
        state["patches"].append((path, body))
        return [body]

    monkeypatch.setattr(module, "_read", read)
    monkeypatch.setattr(module, "overview", overview)
    monkeypatch.setattr(module.sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(module.sb_clients, "sb_patch_as_service", patch)
    # Every business_access dependency answers as the owner of BIZ.
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute):
            for d in r.dependant.dependencies:
                if d.name == "biz":
                    app.dependency_overrides[d.call] = biz
    return TestClient(app), state


def test_making_an_offer_needs_card_payments(api):
    client, state = api
    state["ready"] = False
    r = client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 1000, "who": "first_visit"})
    assert r.status_code == 409 and "Connect card payments in Payments" in r.json()["detail"]
    assert state["posts"] == []


def test_making_an_offer_suggests_its_code_and_title(api):
    client, state = api
    r = client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 1000, "who": "first_visit",
                                            "hours": {"days": [4, 2, 3], "start": "14:00", "end": "17:00"},
                                            "ends_on": "2026-11-01", "max_uses": 30})
    assert r.status_code == 200, r.text
    row = state["posts"][0]
    assert row["code"] == "FIRST10" and row["title"] == "$10 off your first visit" and row["status"] == "on"
    assert row["hours"] == {"days": [2, 3, 4], "start": "14:00", "end": "17:00"} and row["business_id"] == BIZ
    r = client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 500, "code": "first10"})
    assert r.status_code == 409 and "FIRST10" in r.json()["detail"]
    bad = [{"kind": "amount_off"}, {"kind": "percent_off", "percent": 101}, {"kind": "free_item", "free_item": "  "},
           {"kind": "amount_off", "amount_cents": 100, "who": "everyone"},
           {"kind": "amount_off", "amount_cents": 100, "hours": {"days": [9], "start": "14:00", "end": "17:00"}},
           {"kind": "amount_off", "amount_cents": 100, "hours": {"days": [1], "start": "17:00", "end": "14:00"}},
           {"kind": "amount_off", "amount_cents": 100, "starts_on": "2026-11-02", "ends_on": "2026-11-01"},
           {"kind": "amount_off", "amount_cents": 100, "code": "no spaces"}]
    for body in bad:
        assert client.post(f"/offers/{BIZ}", json=body).status_code == 422, body


def test_pausing_an_offer_and_the_public_read(api):
    client, state = api
    client.post(f"/offers/{BIZ}", json={"kind": "amount_off", "amount_cents": 1000, "who": "first_visit"})
    r = client.patch(f"/offers/{BIZ}/{OID}", json={"status": "paused"})
    assert r.status_code == 200 and state["patches"][0][1]["status"] == "paused"
    assert f"business_id=eq.{BIZ}" in state["patches"][0][0]                # only this business's offer
    assert client.patch(f"/offers/{BIZ}/not-an-id", json={"status": "on"}).status_code == 404
    assert client.patch(f"/offers/{BIZ}/{OID}", json={}).status_code == 422
    ok = client.get(f"/offers/public/{BIZ}/first10")
    assert ok.status_code == 200 and ok.json()["title"] == "$10 off your first visit" and "who" not in ok.json()
    state["offers"][0]["status"] = "paused"
    assert client.get(f"/offers/public/{BIZ}/FIRST10").status_code == 404
    assert client.get(f"/offers/public/{BIZ}/NOPE").status_code == 404


def test_the_routes_read_as_a_member_and_change_as_the_owner():
    src = pathlib.Path(of.__file__).read_text(encoding="utf-8")
    assert 'business_access("viewer")' in src and src.count('business_access("owner")') == 2
