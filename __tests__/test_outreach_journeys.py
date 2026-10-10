"""Outreach that runs by itself (2026-10-09, the Reach plan's step 2).

Kevin, 2026-10-08: the after-visit review ask on every plan; win-back,
rebook and birthday from the Week level up. 2026-10-09, how texts go out:
"Build now, texts after": email now; a text only to someone who ticked the
optional "texts about offers" box, and only once JOURNEY_TEXTS is on.
"""
from __future__ import annotations

import asyncio
import copy
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import outreach_journeys as oj  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
NOW = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)      # noon in Chicago
CHI = ZoneInfo("America/Chicago")
C1, C2, C3 = ("c1000000-0000-4000-8000-000000000001", "c1000000-0000-4000-8000-000000000002",
              "c1000000-0000-4000-8000-000000000003")


def run(x):
    return asyncio.run(x)


def biz(level="week", **settings):
    return {"id": BIZ, "name": "Northside Cuts", "settings": settings, "_level": level}


@pytest.fixture(autouse=True)
def levels(monkeypatch):
    import business_marketing
    monkeypatch.setattr(business_marketing, "level_for",
                        lambda row: {"level": row.get("_level", "suggest"), "plan": "x", "upgrade": None})
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: CHI)


# ── the owner's switches ──────────────────────────────────────────────

def test_defaults_and_saved_words():
    cfg = oj.config({"journeys": {"win_back": {"on": True, "days": 90, "text": "Come back {{first_name}} {{link}}"}}}, "win_back")
    assert cfg["on"] is True and cfg["days"] == 90 and cfg["text"].startswith("Come back")
    assert cfg["email"] == oj.DEFAULTS["win_back"]["email"]
    assert oj.config({}, "review_ask")["on"] is False                       # nothing runs until switched on


def test_change_checks_every_value_before_saving():
    b = biz()
    with pytest.raises(oj.JourneyError):
        oj.change(b, "win_back", {"days": 5})
    with pytest.raises(oj.JourneyError):
        oj.change(b, "rebook", {"text": "x" * 400})
    with pytest.raises(oj.JourneyError):
        oj.change(b, "birthday", {"days": 30})                             # birthday takes no days
    with pytest.raises(oj.JourneyError):
        oj.change(b, "win_back", {"hours_after": 2})
    with pytest.raises(oj.JourneyError):
        oj.change(b, "rebook", {"email": "   "})
    with pytest.raises(oj.JourneyError):
        oj.change(b, "nope", {"on": True})
    saved = oj.change(b, "rebook", {"on": True, "days": 42, "text": "Time for a fresh cut {{link}}"})
    assert saved["journeys"]["rebook"] == {"on": True, "days": 42, "text": "Time for a fresh cut {{link}}"}
    reset = oj.change({**b, "settings": saved}, "rebook", {"reset_words": True})
    assert "text" not in reset["journeys"]["rebook"] and reset["journeys"]["rebook"]["days"] == 42


def test_week_journeys_are_locked_below_the_week_level_and_the_review_ask_is_not():
    starter = biz(level="suggest")
    for kind in ("win_back", "rebook", "birthday"):
        with pytest.raises(oj.JourneyError) as e:
            oj.change(starter, kind, {"on": True})
        assert e.value.status == 409
    with pytest.raises(oj.JourneyError) as e:
        oj.change(starter, "review_ask", {"on": True})                      # every plan, but needs the link
    assert e.value.status == 409 and "review link" in str(e.value)
    saved = oj.change(starter, "review_ask", {"on": True, "review_url": "https://g.page/r/abc/review"})
    assert saved["journeys"]["review_ask"]["on"] is True and saved["get_found"]["review_url"].startswith("https://")
    with pytest.raises(oj.JourneyError):
        oj.change(starter, "review_ask", {"review_url": "http://not-safe.example"})
    off = oj.change({**starter, "settings": saved}, "review_ask", {"review_url": ""})
    assert off["journeys"]["review_ask"]["on"] is False                     # no link: the note stops


# ── who is due ────────────────────────────────────────────────────────

def session(sid, cid, hours_ago, minutes=60):
    return {"id": sid, "contact_id": cid, "scheduled_for": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "duration_minutes": minutes}


def test_visits_last_ahead_and_ended():
    last, ahead, ended = oj.visits([session("s1", C1, 24 * 70), session("s2", C1, 24 * 40), session("s3", C2, -48),
                                    session("s4", C3, 0.5)], NOW)
    assert last[C1]["id"] == "s2" and ahead == {C2} and C3 not in last          # still in the chair
    assert {v["id"] for v in ended} == {"s1", "s2"}


def due(kind, sessions=(), sent=(), birthdays=(), **cfg):
    last, ahead, ended = oj.visits(list(sessions), NOW)
    return oj.due(kind, {**oj.DEFAULTS[kind], **cfg}, now=NOW, local_today=NOW.astimezone(CHI).date(), last=last,
                  ahead=ahead, ended=ended, birthdays=list(birthdays), sent=list(sent))


def test_review_ask_after_the_visit_once_and_not_every_week():
    s = [session("s1", C1, 5), session("s2", C2, 2), session("s3", C3, 24 * 5)]
    assert due("review_ask", s) == [(C1, "visit:s1")]                       # C2 too soon, C3 too long ago
    assert due("review_ask", s, sent=[{"journey": "review_ask", "key": "visit:s1", "contact_id": C1,
                                       "sent_at": (NOW - timedelta(hours=1)).isoformat()}]) == []
    asked_lately = [{"journey": "review_ask", "key": "visit:old", "contact_id": C1,
                     "sent_at": (NOW - timedelta(days=30)).isoformat()}]
    assert due("review_ask", s, sent=asked_lately) == []                    # a regular isn't asked every visit
    assert due("review_ask", [session("s1", C1, 5), session("s9", C1, 6)]) == [(C1, "visit:s9")]  # one per person


def test_win_back_and_rebook_once_per_last_visit_and_never_with_something_booked():
    s = [session("s1", C1, 24 * 61), session("s2", C2, 24 * 61), session("s3", C2, -24), session("s4", C3, 24 * 120)]
    assert due("win_back", s) == [(C1, "last:s1")]                          # C2 has a booking; C3 lapsed long ago
    assert due("win_back", s, sent=[{"journey": "win_back", "key": "last:s1"}]) == []
    assert due("rebook", [session("s5", C1, 24 * 36)]) == [(C1, "last:s5")]
    assert due("rebook", [session("s5", C1, 24 * 50)]) == []                # past the rebook window
    assert due("win_back", [session("s6", C1, 24 * 91)], days=90) == [(C1, "last:s6")]


def test_birthday_on_the_business_clock_once_a_year():
    today = NOW.astimezone(CHI).date()
    bd = [{"id": C1, "birthdate": date(1990, today.month, today.day).isoformat()},
          {"id": C2, "birthdate": "1985-01-01"}, {"id": C3, "birthdate": "not a date"}]
    assert due("birthday", birthdays=bd) == [(C1, f"{C1}:birthday:{today.year}")]
    assert due("birthday", birthdays=bd, sent=[{"journey": "birthday", "key": f"{C1}:birthday:{today.year}"}]) == []
    leap = oj.due("birthday", oj.DEFAULTS["birthday"], now=NOW, local_today=date(2027, 3, 1), last={}, ahead=set(),
                  ended=[], birthdays=[{"id": C1, "birthdate": "2000-02-29"}], sent=[])
    assert leap == [(C1, f"{C1}:birthday:2027")]                            # a leap-day birthday, in a common year


# ── sending ───────────────────────────────────────────────────────────

class World:
    def __init__(self, monkeypatch, business, sessions=(), contacts=None, consent=(), sent=None):
        self.business, self.sessions = business, list(sessions)
        self.contacts = contacts or {C1: {"id": C1, "name": "Pat Doe", "email": "pat@example.com", "phone": "+13125550101"}}
        self.consent, self.sent = set(consent), list(sent or [])
        self.emails, self.texts, self.claims, self.events = [], [], [], []
        import business_marketing_sent_links as sl
        import email_sender
        import sms_alerts
        import sms_routing
        import sms_service

        def get(path):
            if path.startswith("/sessions"):
                assert f"business_id=eq.{BIZ}" in path
                return copy.deepcopy(self.sessions)
            if path.startswith("/journey_sends"):
                return copy.deepcopy(self.sent)
            if path.startswith("/contacts?") and "birthdate=not.is.null" in path:
                return []
            if path.startswith("/contacts"):
                return [copy.deepcopy(c) for c in self.contacts.values()]
            raise AssertionError(path)

        def post(path, body):
            if path == "/journey_sends":
                key = (body["journey"], body["key"])
                if any((r["journey"], r["key"]) == key for r in self.sent):
                    return None                                             # the unique key: already sent
                self.claims.append(body)
                self.sent.append({**body, "sent_at": NOW.isoformat()})
                return [body]
            if path == "/events":
                self.events.append(body)
                return [body]
            raise AssertionError(path)

        async def send_email(**kw):
            self.emails.append(kw)

        async def suppressed(addr):
            return None

        async def opted_out(client, phone, bid):
            return False

        async def sb_get(client, path):
            return [{"id": 1}] if ("source=eq.booking_marketing" in path and any(p in path for p in self.consent)) else []

        async def send_sms(phone, body, business_id=None):
            self.texts.append((phone, body))
            return "msg-1"

        async def store_sms(*a, **k):
            return None

        async def link(business, journey, channel):
            return f"https://northside.mysolutionist.app/go/{journey[:4]}{channel[:4]}"

        monkeypatch.setattr(oj.sb_clients, "sb_get_as_service", get)
        monkeypatch.setattr(oj.sb_clients, "sb_post_as_service", post)
        monkeypatch.setattr(email_sender, "send_via_resend", send_email)
        monkeypatch.setattr(email_sender, "is_suppressed", suppressed)
        monkeypatch.setattr(email_sender, "build_routed_reply_to", lambda b, c: None)
        monkeypatch.setattr(sms_alerts, "is_opted_out", opted_out)
        monkeypatch.setattr(sms_alerts, "_sb_get", sb_get)
        monkeypatch.setattr(sms_routing, "_send_platform_sms", send_sms)
        monkeypatch.setattr(sms_service, "_store_sms", store_sms)
        monkeypatch.setattr(sl, "journey_link", link)


def on(kind, **cfg):
    return {"journeys": {kind: {"on": True, **cfg}}}


def test_a_rebook_note_goes_by_email_with_its_tracked_link(monkeypatch):
    monkeypatch.delenv("JOURNEY_TEXTS", raising=False)
    w = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)], consent={"3125550101"})
    stats = run(oj.run_business(w.business, now=NOW, budget=50))
    assert stats == {"email": 1, "sms": 0, "skipped": 0}
    assert w.texts == []                                                     # texts wait for the registration
    [mail] = w.emails
    assert mail["subject"] == "Time for your next visit?" and "Hi Pat," in mail["body"]
    assert "https://northside.mysolutionist.app/go/reboemai" in mail["body"] and "{{" not in mail["body"]
    assert w.claims[0]["key"] == "last:s1" and w.events[0]["event_type"] == "journey_sent"
    assert run(oj.run_business(w.business, now=NOW, budget=50))["email"] == 0   # once


def test_a_text_only_with_marketing_consent_and_the_switch_on(monkeypatch):
    monkeypatch.setenv("JOURNEY_TEXTS", "on")
    w = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)])
    run(oj.run_business(w.business, now=NOW, budget=50))
    assert w.texts == [] and len(w.emails) == 1                              # no "texts about offers" tick: email
    w2 = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)], consent={"3125550101"})
    run(oj.run_business(w2.business, now=NOW, budget=50))
    [(phone, body)] = w2.texts
    assert phone == "+13125550101" and "Time for your next visit, Pat?" in body and "STOP" in body
    assert w2.emails == [] and w2.claims[0]["channel"] == "sms"


def test_the_review_ask_needs_its_link_and_names_it(monkeypatch):
    monkeypatch.delenv("JOURNEY_TEXTS", raising=False)
    no_link = biz(level="suggest", **on("review_ask"))
    w = World(monkeypatch, no_link, sessions=[session("s1", C1, 5)])
    assert run(oj.run_business(w.business, now=NOW, budget=50))["email"] == 0
    settings = {**on("review_ask"), "get_found": {"review_url": "https://g.page/r/northside/review"}}
    w = World(monkeypatch, biz(level="suggest", **settings), sessions=[session("s1", C1, 5)])
    assert run(oj.run_business(w.business, now=NOW, budget=50))["email"] == 1   # every plan
    assert "https://g.page/r/northside/review" in w.emails[0]["body"]


def test_week_journeys_do_not_run_below_the_week_level(monkeypatch):
    w = World(monkeypatch, biz(level="suggest", **on("rebook")), sessions=[session("s1", C1, 24 * 36)])
    assert run(oj.run_business(w.business, now=NOW, budget=50)) == {"email": 0, "sms": 0, "skipped": 0}


def test_only_in_the_daytime_on_the_business_clock(monkeypatch):
    w = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)])
    night = datetime(2026, 10, 16, 4, 0, tzinfo=timezone.utc)               # 11 PM in Chicago
    assert run(oj.run_business(w.business, now=night, budget=50))["email"] == 0 and w.claims == []


def test_the_daily_cap_holds(monkeypatch):
    many = {f"c1000000-0000-4000-8000-0000000001{i:02d}": {"id": f"c1000000-0000-4000-8000-0000000001{i:02d}",
                                                            "name": f"P{i}", "email": f"p{i}@example.com"} for i in range(50)}
    sessions = [session(f"s{i}", cid, 24 * 36) for i, cid in enumerate(many)]
    already = [{"journey": "win_back", "key": f"last:x{i}", "contact_id": C1, "channel": "email",
                "sent_at": (NOW - timedelta(hours=1)).isoformat()} for i in range(oj.DAILY_CAP - 3)]
    w = World(monkeypatch, biz(**on("rebook")), sessions=sessions, contacts=many, sent=already)
    assert run(oj.run_business(w.business, now=NOW, budget=500))["email"] == 3


def test_a_link_that_cannot_be_made_holds_the_journey(monkeypatch):
    import business_marketing_sent_links as sl
    w = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)])

    async def down(*a):
        raise RuntimeError("site unreadable")

    monkeypatch.setattr(sl, "journey_link", down)
    stats = run(oj.run_business(w.business, now=NOW, budget=50))
    assert stats["email"] == 0 and w.claims == [] and w.emails == []         # nothing claimed: a later sweep sends


def test_the_sweep_skips_a_paused_business_and_the_kill_switch(monkeypatch):
    import rules_engine
    w = World(monkeypatch, biz(**on("rebook")), sessions=[session("s1", C1, 24 * 36)])
    calls = []
    monkeypatch.setattr(oj.sb_clients, "sb_get_as_service",
                        lambda path: [w.business] if path.startswith("/businesses") else calls.append(path) or [])
    monkeypatch.setattr(rules_engine, "business_paused", lambda b: True)
    assert run(oj.journeys_tick(NOW))["email"] == 0 and calls == []
    monkeypatch.setenv("JOURNEYS", "off")
    assert run(oj.journeys_tick(NOW)) == {"businesses": 0, "email": 0, "sms": 0, "skipped": 0}


# ── consent and wiring ────────────────────────────────────────────────

def test_marketing_consent_never_counts_for_reminders():
    src = (pathlib.Path(oj.__file__).resolve().parent / "sms_alerts.py").read_text(encoding="utf-8")
    body = src[src.index("async def _positive_consent"):src.index("async def has_sms_consent")]
    assert "source.neq.booking_marketing" in body


def test_the_booking_records_the_texts_about_offers_box_on_its_own():
    import booking_widget_router as bw
    assert "marketing_sms_consent" in bw.BookAnonBody.model_fields and "marketing_sms_consent" in bw.BookBody.model_fields
    src = pathlib.Path(bw.__file__).read_text(encoding="utf-8")
    assert src.count('source="booking_marketing"') == 2                       # both booking doors


def test_the_routes_read_as_a_member_and_change_as_the_owner():
    import journeys_router as jr
    src = pathlib.Path(jr.__file__).read_text(encoding="utf-8")
    assert 'business_access("viewer")' in src and 'business_access("owner")' in src
    assert {r.path for r in jr.router.routes} == {"/journeys/{business_id}", "/journeys/{business_id}/{kind}"}


def test_the_overview_says_what_is_on_locked_and_sent(monkeypatch):
    import business_marketing_outcomes as outcomes

    async def for_links(bid, ids, since):
        return {"totals": {"clicks": 2}, "sources": {"clicks": "loaded"}, "per_link": {}}

    monkeypatch.setattr(outcomes, "for_links", for_links)
    monkeypatch.setattr(oj.sb_clients, "sb_get_as_service",
                        lambda path: [{"journey": "rebook", "channel": "email"}, {"journey": "rebook", "channel": "sms"}])
    out = run(oj.overview(biz(level="suggest", **on("rebook")), now=NOW))
    by = {j["kind"]: j for j in out["journeys"]}
    assert by["rebook"]["locked"] is True and by["rebook"]["on"] is False       # saved on, but the plan says no
    assert by["review_ask"]["locked"] is False and by["review_ask"]["through_link"] is None
    assert by["rebook"]["sent"] == {"email": 1, "sms": 1} and by["rebook"]["through_link"]["totals"] == {"clicks": 2}
    assert out["texts_on"] is False and out["review_url"] is None and out["daily_cap"] == oj.DAILY_CAP
