"""THE SITE CONCIERGE QUALIFIES AND BOOKS (concierge_qualify.py + the
booking endpoints in site_concierge.py, 2026-09-05).

What matters most, in order:

  1. The RUBRIC is deterministic and reads only the VISITOR's words —
     a service the concierge mentioned is not a service the visitor
     asked for. Booked-in-chat is HOT, always. The tier never comes
     from the model; a model failure costs the answers, not the tier.
  2. The BOOKING endpoints ride agent_site (slots) and the walk-in
     flow (walkin_book → book_anon): no model call on any booking path,
     a 409 from the double-book guard reaches the widget as a 409, and
     a closed booking door is a 404 the widget turns into a link.
  3. The in-chat picker REPLACES the external link only when it is
     live; otherwise the old 'Book now' link stands. No dead doors.
  4. Lead capture writes the tier where the practitioner reads it —
     the conversation row, the contact, the notification title, the
     spine — in the same request.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

import concierge_qualify as cq  # noqa: E402
import site_concierge as sc  # noqa: E402


# ─── plumbing ────────────────────────────────────────────────────────

class FakeRequest:
    def __init__(self, ip="1.2.3.4", ua="pytest-agent"):
        self.client = type("C", (), {"host": ip})()
        self.headers = {"user-agent": ua}


OFFERINGS = [
    {"id": "o1", "name": "Deep Tissue Massage", "category": "service",
     "duration_min": 60, "current_price": 90, "currency": "USD",
     "show_price_to_customer": True, "is_active": True, "business_id": "b1"},
    {"id": "o2", "name": "Gift Card", "category": "product",
     "duration_min": None, "current_price": 50, "currency": "USD",
     "show_price_to_customer": True, "is_active": True, "business_id": "b1"},
    {"id": "o3", "name": "Private Consultation", "category": "session",
     "duration_min": 30, "current_price": 200, "currency": "USD",
     "show_price_to_customer": False, "is_active": True, "business_id": "b1"},
]

QUESTIONS = ["What are you hoping to fix?", "When would you like to start?"]


def _bundle(open_=True):
    return {
        "facts": {"id": "b1", "name": "Acme Bodywork", "timezone": "America/Chicago",
                  "booking_url": "https://acme.mysolutionist.app/book",
                  "origin": "https://acme.mysolutionist.app", "availability": {}},
        "offerings": OFFERINGS,
        "booking_open": open_,
        "biz": {"id": "b1"},
    }


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    sc._ip_rate.clear()
    sc._knowledge_cache.clear()
    sc._snippet_cache.clear()
    monkeypatch.setenv("LEAD_SCORING_MODE", "off")
    yield
    sc._ip_rate.clear()
    sc._knowledge_cache.clear()
    sc._snippet_cache.clear()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "owner1", "is_active": True,
        "name": "Acme Bodywork", "type": "custom",
        "settings": {"concierge": {"enabled": True, "qualifying": QUESTIONS}},
        "subscription_status": None, "subscription_plan": None,
        "comp_tier": None, "stripe_account_id": None})
    fb.rows("business_sites").append({
        "id": "s1", "business_id": "b1", "slug": "acme",
        "status": "published", "site_config": {}})
    for o in OFFERINGS:
        fb.rows("offerings").append(dict(o))
    for uid, role in (("m1", "member"), ("g1", "manager")):
        fb.rows("business_users").append({
            "id": f"seat_{uid}", "business_id": "b1", "user_id": uid,
            "role": role, "status": "active"})
    return fb


@pytest.fixture
def door_open(monkeypatch):
    """The booking door is live: agent_site's bundle says so, and the
    client policy allows the client to look and to book."""
    import agent_site
    import policy_engine
    monkeypatch.setattr(agent_site, "_load_bundle", lambda b: _bundle(True))
    monkeypatch.setattr(policy_engine, "evaluate_client",
                        lambda *a, **k: type("V", (), {"allowed": True, "reason": "", "rule": "client:ok"})())
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)


def _conv(fb, turns):
    conv = fb.post("/concierge_conversations", {"business_id": "b1", "visitor_key": "v", "status": "open"})[0]
    for i, (role, body) in enumerate(turns):
        fb.post("/concierge_messages", {"conversation_id": conv["id"], "role": role,
                                        "body": body, "created_at": f"2026-09-05T10:0{i}:00Z"}, prefer=None)
    return conv


def _user(uid):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


# ─── 1. the rubric ───────────────────────────────────────────────────

def test_named_service_timing_and_reach_is_hot():
    t = [{"role": "visitor", "body": "Do you do deep tissue massage? I'd love something this week."}]
    q = cq.qualify(t, questions=[], offerings=OFFERINGS, email="a@b.co", phone="555")
    assert q.tier == "hot" and q.service == "Deep Tissue Massage"
    assert "asked about Deep Tissue Massage" in q.signals
    assert "said when" in q.signals
    assert "gave a phone number" in q.signals


def test_price_curiosity_alone_is_cold():
    t = [{"role": "visitor", "body": "how much is it?"}]
    q = cq.qualify(t, questions=[], offerings=OFFERINGS, email="a@b.co")
    assert q.tier == "cold"
    assert "asked about price" in q.signals


def test_the_concierge_mentioning_a_service_is_not_evidence():
    t = [{"role": "visitor", "body": "hi"},
         {"role": "concierge", "body": "We offer Deep Tissue Massage and more."}]
    q = cq.qualify(t, questions=[], offerings=OFFERINGS)
    assert q.service is None
    assert q.signals == ["left only their details"]


def test_booked_in_chat_is_hot_no_matter_what():
    q = cq.qualify([], questions=[], offerings=[], booked=True)
    assert q.tier == "hot" and q.booked is True
    assert q.signals[0] == "booked a time in the chat"


def test_qualifying_answers_count_all_then_half():
    t = [{"role": "visitor", "body": "x"}]
    full = cq.qualify(t, questions=QUESTIONS, offerings=[],
                      answers={QUESTIONS[0]: "my back", QUESTIONS[1]: "next week"})
    half = cq.qualify(t, questions=QUESTIONS, offerings=[],
                      answers={QUESTIONS[0]: "my back"})
    none = cq.qualify(t, questions=QUESTIONS, offerings=[], answers={})
    assert "answered every qualifying question" in full.signals
    assert "answered 1 of 2 qualifying questions" in half.signals
    assert full.score > half.score > none.score
    assert full.answers[QUESTIONS[0]] == "my back"


def test_engagement_counts_visitor_turns_only():
    t = [{"role": "visitor", "body": "a"}, {"role": "concierge", "body": "b"},
         {"role": "visitor", "body": "c"}, {"role": "visitor", "body": "d"}]
    q = cq.qualify(t, questions=[], offerings=[])
    assert "stayed for 3 messages" in q.signals


def test_clean_questions_caps_dedups_and_trims():
    raw = ["  A?  ", "", "A?", "B?", "C?", "D?", "E?", "F?", 42]
    assert cq.clean_questions(raw) == ["A?", "B?", "C?", "D?", "E?"]
    assert cq.clean_questions("not a list") == []
    assert cq.clean_questions(None) == []


def test_parse_answers_tolerates_fences_and_nulls():
    raw = '```json\n{"answers": {"Q1": "my back", "Q2": null, "Q3": "none"}}\n```'
    out = cq._parse_answers(raw, ["Q1", "Q2", "Q3", "Q4"])
    assert out == {"Q1": "my back"}
    assert cq._parse_answers("not json", ["Q1"]) == {}


def test_tier_thresholds_are_pinned():
    assert cq.tier_for(70) == "hot" and cq.tier_for(69) == "warm"
    assert cq.tier_for(40) == "warm" and cq.tier_for(39) == "cold"


def test_describe_reads_like_a_line():
    q = cq.qualify([{"role": "visitor", "body": "deep tissue massage tomorrow"}],
                   questions=[], offerings=OFFERINGS, email="a@b.co", phone="555")
    assert cq.describe(q).startswith("HOT — asked about Deep Tissue Massage; said when")
    cold = cq.qualify([], questions=[], offerings=[])
    assert cq.describe(cold) == "COLD — left only their details"


# ─── 2. knowledge, prompt, actions ───────────────────────────────────

def test_knowledge_carries_questions_and_the_booking_door(fake, door_open):
    k = sc.assemble_knowledge("b1", use_cache=False)
    assert k["qualifying"] == QUESTIONS
    assert k["booking_inline"] is True
    names = [b["name"] for b in k["bookable"]]
    assert "Deep Tissue Massage" in names and "Private Consultation" in names
    assert "Gift Card" not in names          # a product is not slot-booked


def test_knowledge_door_closed_when_booking_is_closed(fake, monkeypatch):
    import agent_site
    monkeypatch.setattr(agent_site, "_load_bundle", lambda b: _bundle(False))
    k = sc.assemble_knowledge("b1", use_cache=False)
    assert k["booking_inline"] is False and k["bookable"] == []


def test_prompt_weaves_questions_and_tells_not_books(fake, door_open):
    k = sc.assemble_knowledge("b1", use_cache=False)
    p = sc.build_system_prompt(k)
    assert "QUALIFYING:" in p
    for q in QUESTIONS:
        assert f"- {q}" in p
    assert "ONE at a time" in p
    assert "BOOKING:" in p and "Never say you have booked anything yourself" in p


def test_prompt_has_no_booking_line_when_the_door_is_closed(fake, monkeypatch):
    import agent_site
    monkeypatch.setattr(agent_site, "_load_bundle", lambda b: _bundle(False))
    k = sc.assemble_knowledge("b1", use_cache=False)
    assert "BOOKING:" not in sc.build_system_prompt(k)


def test_picker_replaces_the_link_only_when_live():
    live = {"links": {"booking": "https://x/book"}, "booking_inline": True}
    closed = {"links": {"booking": "https://x/book"}, "booking_inline": False}
    none = {"links": {}, "booking_inline": False}
    assert sc._suggest_actions("can I book?", live) == [{"type": "book", "label": "Pick a time"}]
    assert sc._suggest_actions("can I book?", closed) == [
        {"type": "link", "label": "Book now", "url": "https://x/book"}]
    assert sc._suggest_actions("can I book?", none) == []
    assert sc._suggest_actions("what are your hours?", live) == []


# ─── 3. lead capture writes the tier where it is read ────────────────

def _post_lead(name="Jane Doe", email="jane@x.com", phone=None, message="",
               conversation_id=None):
    return asyncio.run(sc.public_lead(
        "acme", sc.PublicLeadBody(conversation_id=conversation_id, name=name,
                                  email=email, phone=phone, message=message),
        FakeRequest()))


def test_lead_capture_qualifies_and_writes_everywhere(fake, monkeypatch):
    conv = _conv(fake, [("visitor", "Do you do deep tissue massage? Need it this week"),
                        ("concierge", "We do! What are you hoping to fix?"),
                        ("visitor", "My lower back, from sitting all day")])

    async def _extract(questions, transcript, **kw):
        return {QUESTIONS[0]: "lower back from sitting", QUESTIONS[1]: "this week"}
    monkeypatch.setattr(cq, "extract_answers", _extract)

    out = _post_lead(phone="555-0100", message="please call", conversation_id=conv["id"])
    assert out == {"ok": True}          # the wire shape is unchanged; the tier is for the operator

    row = fake.rows("concierge_conversations")[0]
    q = row["qualification"]
    assert q["tier"] == "hot" and q["extracted"] is True
    assert q["answers"][QUESTIONS[0]] == "lower back from sitting"
    assert "answered every qualifying question" in q["signals"]
    assert row["contact_id"]

    contact = fake.rows("contacts")[0]
    assert contact["phone"] == "555-0100"
    assert contact["metadata"]["concierge_qualification"]["tier"] == "hot"

    note = fake.rows("chief_notifications")[0]
    assert note["title"].startswith("HOT lead from your website")
    assert QUESTIONS[0] in note["body"]
    assert note["data"]["tier"] == "hot"

    ev = [e for e in fake.rows("events") if e.get("event_type") == "concierge_lead_captured"]
    assert ev and ev[0]["data"]["tier"] == "hot"
    assert ev[0]["data"]["answers"][QUESTIONS[1]] == "this week"


def test_lead_capture_survives_a_dead_model(fake, monkeypatch):
    conv = _conv(fake, [("visitor", "how much is a massage?")])

    async def _dead(questions, transcript, **kw):
        return None
    monkeypatch.setattr(cq, "extract_answers", _dead)

    out = _post_lead(conversation_id=conv["id"])
    assert out["ok"] is True
    q = fake.rows("concierge_conversations")[0]["qualification"]
    assert q["extracted"] is False and q["answers"] == {}
    assert q["tier"] in ("cold", "warm")        # the rubric still ruled


def test_lead_without_a_conversation_still_qualifies(fake):
    out = _post_lead(message="I need a deep tissue massage asap")
    assert out["ok"] is True
    q = fake.rows("contacts")[0]["metadata"]["concierge_qualification"]
    assert q["service"] == "Deep Tissue Massage" and q["tier"] in ("warm", "hot")


# ─── 4. the booking endpoints ────────────────────────────────────────

def _services():
    return asyncio.run(sc.booking_services("acme", FakeRequest()))


def test_services_are_bookable_only_and_keep_the_price_rule(fake, door_open):
    out = _services()
    assert out["ok"] is True and out["booking_page"] == "https://acme.mysolutionist.app/book"
    by = {s["name"]: s for s in out["services"]}
    assert set(by) == {"Deep Tissue Massage", "Private Consultation"}
    assert by["Deep Tissue Massage"]["price"] == 90
    assert "price" not in by["Private Consultation"]     # hidden = absent


def test_booking_is_404_when_the_door_is_closed(fake, monkeypatch):
    import agent_site
    import policy_engine
    monkeypatch.setattr(agent_site, "_load_bundle", lambda b: _bundle(False))
    monkeypatch.setattr(policy_engine, "evaluate_client",
                        lambda *a, **k: type("V", (), {"allowed": True, "reason": "", "rule": "x"})())
    with pytest.raises(HTTPException) as ei:
        _services()
    assert ei.value.status_code == 404


def test_booking_is_403_when_the_client_policy_says_no(fake, monkeypatch):
    import agent_site
    import policy_engine
    monkeypatch.setattr(agent_site, "_load_bundle", lambda b: _bundle(True))
    monkeypatch.setattr(policy_engine, "evaluate_client",
                        lambda *a, **k: type("V", (), {"allowed": False, "reason": "no clients here", "rule": "x"})())
    with pytest.raises(HTTPException) as ei:
        _services()
    assert ei.value.status_code == 403


def test_availability_rides_the_shared_slot_computation(fake, door_open, monkeypatch):
    import agent_site
    seen = {}

    def _slots(b, off, start, end):
        seen["off"] = off["id"]; seen["days"] = (end - start).days
        return [{"start_utc": "2026-09-08T19:00:00+00:00", "start_local": "2026-09-08T14:00:00", "duration_min": 60}]
    monkeypatch.setattr(agent_site, "slots_for", _slots)
    out = asyncio.run(sc.booking_availability("acme", FakeRequest(), offering_id="o1",
                                              from_="2026-09-08", to="2026-09-14"))
    assert out["ok"] and seen == {"off": "o1", "days": 6}
    assert out["slots"][0]["start_local"] == "2026-09-08T14:00:00"
    assert out["timezone"] == "America/Chicago"

    with pytest.raises(HTTPException) as ei:       # a product is not slot-booked
        asyncio.run(sc.booking_availability("acme", FakeRequest(), offering_id="o2",
                                            from_=None, to=None))
    assert ei.value.status_code == 404


def _book(conversation_id=None, **over):
    body = dict(name="Jane Doe", email="jane@x.com", phone="555-0100",
                offering_id="o1", start="2026-09-08T19:00:00+00:00",
                sms_consent=True, conversation_id=conversation_id)
    body.update(over)
    return asyncio.run(sc.booking_book("acme", sc.PublicBookBody(**body), FakeRequest()))


def test_book_rides_the_walk_in_flow_and_closes_the_loop(fake, door_open, monkeypatch):
    import agent_site
    calls = []

    async def _walkin(b, off, request, **kw):
        calls.append(kw)
        fake.rows("contacts").append({"id": "c9", "business_id": "b1", "name": kw["name"],
                                      "email": kw["email"], "metadata": {}})
        return {"ok": True, "appointment_id": "appt1", "contact_id": "c9", "token": "tok"}
    monkeypatch.setattr(agent_site, "walkin_book", _walkin)
    conv = _conv(fake, [("visitor", "I'd like to book a deep tissue massage")])

    out = _book(conversation_id=conv["id"])
    assert out["ok"] is True and out["appointment_id"] == "appt1"
    assert out["offering"] == "Deep Tissue Massage"
    assert out["when"] == "Tue, Sep 8 at 2:00 PM"           # Chicago, CDT
    assert out["manage_url"] == "https://acme.mysolutionist.app/book?token=tok"

    kw = calls[0]
    assert kw["booked_via"] == "concierge" and kw["sms_consent"] is True
    assert kw["phone"] == "555-0100" and kw["email"] == "jane@x.com"

    row = fake.rows("concierge_conversations")[0]
    assert row["appointment_id"] == "appt1" and row["contact_id"] == "c9"
    assert row["qualification"]["tier"] == "hot" and row["qualification"]["booked"] is True

    bodies = [m["body"] for m in fake.rows("concierge_messages") if m["role"] == "concierge"]
    assert any(b.startswith("Booked: Deep Tissue Massage — Tue, Sep 8 at 2:00 PM") for b in bodies)

    assert fake.rows("contacts")[0]["metadata"]["concierge_qualification"]["booked"] is True

    note = fake.rows("chief_notifications")[0]
    assert note["title"] == "Booked from your website chat — Jane Doe"
    assert note["data"]["kind"] == "concierge_booking" and note["data"]["appointment_id"] == "appt1"

    ev = [e for e in fake.rows("events") if e.get("event_type") == "concierge_booking_made"]
    assert ev and ev[0]["data"]["appointment_id"] == "appt1" and ev[0]["data"]["tier"] == "hot"


def test_book_passes_the_double_book_409_through(fake, door_open, monkeypatch):
    import agent_site

    async def _taken(b, off, request, **kw):
        raise HTTPException(status_code=409, detail="Sorry — that time was just booked. Please pick another.")
    monkeypatch.setattr(agent_site, "walkin_book", _taken)
    with pytest.raises(HTTPException) as ei:
        _book()
    assert ei.value.status_code == 409
    assert fake.rows("chief_notifications") == []       # nothing claimed


def test_book_refuses_bad_input_before_touching_the_flow(fake, door_open, monkeypatch):
    import agent_site
    monkeypatch.setattr(agent_site, "walkin_book", None)   # would explode if reached
    with pytest.raises(HTTPException) as ei:
        _book(email="not-an-email")
    assert ei.value.status_code == 400
    with pytest.raises(HTTPException) as ei:
        _book(start="tomorrow at 2")
    assert ei.value.status_code == 400
    with pytest.raises(HTTPException) as ei:
        _book(offering_id="o2")
    assert ei.value.status_code == 404


def test_slot_label_is_human_and_zoned():
    assert sc._slot_label("2026-09-08T19:00:00+00:00", "America/Chicago") == "Tue, Sep 8 at 2:00 PM"
    assert sc._slot_label("2026-09-08T19:30:00Z", None) == "Tue, Sep 8 at 7:30 PM"
    assert sc._slot_label("garbage", None) == "garbage"


# ─── 5. operator settings + list ─────────────────────────────────────

def test_operator_saves_and_reads_qualifying_questions(fake, door_open):
    out = sc.patch_concierge("b1", sc.ConciergeSettingsPatch(
        qualifying=["  New Q?  ", "", "New Q?", "Second?"]), _user("g1"))
    assert out["qualifying"] == ["New Q?", "Second?"]
    got = sc.get_concierge("b1", _user("m1"))
    assert got["qualifying"] == ["New Q?", "Second?"]
    assert got["booking_inline"] is True
    with pytest.raises(HTTPException) as ei:
        sc.patch_concierge("b1", sc.ConciergeSettingsPatch(qualifying=[]), _user("m1"))
    assert ei.value.status_code == 403


def test_operator_list_carries_tier_and_appointment(fake):
    conv = _conv(fake, [("visitor", "hi")])
    fake.patch(f"/concierge_conversations?id=eq.{conv['id']}",
               {"qualification": {"tier": "warm", "score": 45, "signals": ["x"], "answers": {}},
                "appointment_id": "appt1"})
    out = sc.list_conversations("b1", 50, _user("m1"))
    row = out["conversations"][0]
    assert row["tier"] == "warm" and row["appointment_id"] == "appt1"
    assert row["qualification"]["score"] == 45


# ─── 6. widget, catalog, migration ───────────────────────────────────

def test_widget_carries_the_picker_and_the_phone_field(fake):
    resp = asyncio.run(sc.widget_js("acme"))
    js = resp.body.decode("utf-8")
    assert "/booking/services" in js and "/booking/availability" in js and "/booking/book" in js
    assert "a.type === 'book'" in js
    assert "Phone (optional)" in js
    assert "That time was just taken" in js
    assert "Text me confirmations and reminders" in js
    # Escape armor: nothing in the booking card lands via innerHTML.
    assert "innerHTML" not in js


def test_event_catalog_carries_the_booking_event():
    import event_spine
    cat = event_spine.EVENT_CATALOG
    assert "concierge_booking_made" in cat
    assert "tier" in cat["concierge_lead_captured"]["payload"]
    assert "appointment_id" in cat["concierge_booking_made"]["payload"]


def test_migration_sql_is_additive_and_reloads_the_schema():
    sql_path = (pathlib.Path(__file__).resolve().parent.parent
                / "supabase" / "APPLY-2026-09-05-concierge-qualification.sql")
    low = sql_path.read_text(encoding="utf-8").lower()
    assert "add column if not exists qualification jsonb" in low
    assert "add column if not exists appointment_id text" in low
    assert "drop " not in low and "delete " not in low
    assert "notify pgrst" in low
    assert "information_schema" in low


def test_agent_site_endpoints_still_ride_the_shared_helpers():
    """The refactor pulled slots_for / walkin_book out of the agent
    endpoints; both surfaces must call the SAME functions."""
    import inspect
    import agent_site
    assert "slots_for(" in inspect.getsource(agent_site.availability)
    assert "walkin_book(" in inspect.getsource(agent_site.book)
    assert "slots_for(" in inspect.getsource(sc.booking_availability)
    assert "walkin_book(" in inspect.getsource(sc.booking_book)
