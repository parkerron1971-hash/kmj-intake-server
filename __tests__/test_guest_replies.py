"""A guest's reply reaches their caller, and the automatic texts wait for a
person (guest_replies.py; the hooks in sms_routing.route_inbound,
sms_service.send_sms and church_follow_up._note).

Kevin, 2026-11-20, on the Welcome Path mock (the rule "A reply holds the
automatic texts until a person answers"), then "build".

Pins:
  * only a guest on the path (texted_at within 6 weeks, not ended) is held;
    STOP/START/HELP, GIVE, DAILY, the church's New here word and its texting
    keyword never count
  * the hold: hold true + hold_since, merged beside every other key, kept on a
    second reply, every write compare-and-swap (a lost race reads again)
  * a note on the open guest follow-up with the reply; the History lines
    never carry the words
  * who hears: a login caller (push + email opening their texts), a member
    caller (email: the reply, the number, the Lead tab), nobody (whoever
    does First-time guests), nobody at all (the office); quiet hours wait
  * one alert a guest every 10 minutes, claimed in the guest's row
  * a person's text from Text clears it (Chief's and the automatic ones
    never do), and so does the caller logging Talked / Left a message
  * a day later the caller is reminded once; three days later the office's
    alert once; never cleared by time
  * the switch off is nothing; a failed read decides nothing
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import guest_calls as gc  # noqa: E402
import guest_path  # noqa: E402
import guest_replies as gr  # noqa: E402
import sb_clients  # noqa: E402
import test_church_follow_up as tcf  # noqa: E402
from test_church_follow_up import BIZ, OWNER, TASHA, cid  # noqa: E402
from test_guest_calls import RENEE, RENEE_SEAT, g, told  # noqa: E402,F401  (fixtures)

ET = ZoneInfo("America/New_York")
SUNDAY = datetime(2026, 11, 22, 11, 0, tzinfo=ET).astimezone(timezone.utc)
MONDAY = datetime(2026, 11, 23, 10, 20, tzinfo=ET).astimezone(timezone.utc)
LENA, OLD, CARD = cid(40), cid(41), cid(42)
FU, FU2 = "aaaaaaaa-0000-0000-0000-0000000000f1", "aaaaaaaa-0000-0000-0000-0000000000f2"
PHONE = "+15551230001"
_ORIG_CMP = tcf._cmp
_REAL_LATER = gr.later


def _json_cmp(row, col, op, val):
    """The fake database reads JSON paths (metadata->new_here->>hold) and LIKE,
    as PostgREST does."""
    if "->" in col:
        parts = re.split(r"->>?", col)
        v = row.get(parts[0])
        for p in parts[1:]:
            v = v.get(p) if isinstance(v, dict) else None
        return _ORIG_CMP({col: v}, col, op, val)
    if op == "like":
        v = row.get(col)
        pat = "^" + re.escape(val).replace("%", ".*") + "$"
        return v is not None and re.match(pat, str(v)) is not None
    return _ORIG_CMP(row, col, op, val)


@pytest.fixture
def w(g, told, monkeypatch):
    """Love City with one guest on the path (the kids desk on Sunday),
    handed to Renee (People & Care, an office login)."""
    monkeypatch.setattr(tcf, "_cmp", _json_cmp)
    g.t["contacts"].append({
        "id": LENA, "business_id": BIZ, "name": "Lena Brooks", "email": "lena@example.com", "phone": PHONE,
        "created_at": "2026-11-22T16:00:00Z",
        "metadata": {"kids": {"family": "f-1"}, "new_here": {
            "door": "kids", "texted_at": gr._iso(SUNDAY), "texts_ok": True, "code": "K7M2QX4P", "texts": "on"}}})
    g.t["church_follow_ups"].append({
        "id": FU, "business_id": BIZ, "contact_id": LENA, "card_key": "checkin:first", "card_name": "",
        "path_kind": "connect", "status": "open", "step": 0, "leader_contact_id": RENEE,
        "leader_role": gc.MARK, "assigned_by": "guest_calls:people_care", "created_at": "2026-11-22T16:01:00Z"})
    g.t.setdefault("sms_messages", [])
    g.t.setdefault("sms_keywords", []).append({"business_id": BIZ, "keyword": "LOVECITY"})
    g.t.setdefault("sms_numbers", []).append({"business_id": BIZ, "phone_number": "+15557770001",
                                              "status": "active"})
    sent = {"login": [], "email": [], "history": []}

    def tell_login(ctx, uid, words, ref, *, nav=gc.NAV, link=None, label="Open the Follow-up board"):
        sent["login"].append({"uid": uid, "words": words, "ref": ref, "nav": nav, "link": link, "label": label,
                              "tell": ctx.conf.get("tell")})
        return True
    monkeypatch.setattr(gc, "tell_login", tell_login)

    async def email(biz, to, name, subject, body, key):
        sent["email"].append({"to": to, "subject": subject, "body": body, "key": key})
        return True
    monkeypatch.setattr(cfu, "_email", email)
    import church_history
    monkeypatch.setattr(church_history, "note",
                        lambda biz, verb, line, **kw: sent["history"].append((verb, line, kw.get("target_id"))) or True)
    import member_push
    quiet = {"on": False}
    monkeypatch.setattr(member_push, "quiet_hour", lambda business, now=None: quiet["on"])
    import new_here
    monkeypatch.setattr(new_here, "tz_of", lambda business: ET)
    monkeypatch.setattr(gr, "later", lambda fn, *a: fn(*a))
    # The fake keeps rows in the order they came; the latest reply is read
    # newest first, as PostgREST's order= gives it.
    plain_get = g.get

    def get(path, **kw):
        if path.startswith("/sms_messages") and "order=created_at.desc" in path:
            rows = plain_get(re.sub(r"&limit=\d+", "", path), **kw)
            rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
            m = re.search(r"&limit=(\d+)", path)
            return rows[:int(m.group(1))] if m else rows
        return plain_get(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    g.get = get
    clock = {"now": MONDAY}
    monkeypatch.setattr(gr, "_now", lambda: clock["now"])
    g.sent, g.quiet, g.gr_clock = sent, quiet, clock
    g.told = told
    return g


def _lena(w):
    return next(c for c in w.t["contacts"] if c["id"] == LENA)


def _mine(w, who=LENA):
    return next(c for c in w.t["contacts"] if c["id"] == who)["metadata"].get("new_here") or {}


def _notes(w, fid=FU):
    return [n for n in w.t["church_follow_up_notes"] if n["follow_up_id"] == fid]


def _reply(w, body, at=MONDAY, phone=PHONE):
    return gr.on_reply(BIZ, phone, body, now=at)


# ─── A guest texts back ───────────────────────────────────────────────

def test_a_path_guests_reply_holds_their_texts_and_reaches_their_caller(w):
    said = "Thank you! Is there anything for kids on Wednesday nights?"
    assert _reply(w, said) == "told"
    mine = _mine(w)
    assert mine["hold"] is True and mine["hold_since"] == gr._iso(MONDAY)
    # Merged: New here's keys and every other metadata key kept.
    assert (mine["door"], mine["code"], mine["texts_ok"], mine["texts"]) == ("kids", "K7M2QX4P", True, "on")
    assert _lena(w)["metadata"]["kids"] == {"family": "f-1"}
    [note] = _notes(w)
    assert (note["kind"], note["author_kind"]) == ("note", "chief")
    assert note["body"] == f"Answered the church’s text: “{said}”"
    [alert] = w.sent["login"]
    assert alert["uid"] == RENEE_SEAT
    assert alert["words"]["title"] == "Lena Brooks answered the church’s text"
    assert alert["words"]["body"] == f"“{said}” Their texts are on hold until you reply."
    assert alert["nav"] == f"operate:sms:{LENA}" and alert["link"].endswith(f"/?nav=operate:sms:{LENA}")
    assert alert["label"] == "Open their texts"
    assert "Hi Renee," in alert["words"]["text"] and said in alert["words"]["text"]
    # History says a guest answered, never who or what.
    assert w.sent["history"] and all(said not in line and "Lena" not in line for _, line, _ in w.sent["history"])
    assert mine["hold_tell"] is False and mine["hold_told_at"] == gr._iso(MONDAY)


def test_only_a_guest_on_the_path_is_held(w):
    w.t["contacts"] += [
        {"id": OLD, "business_id": BIZ, "name": "Old Friend", "phone": "+15551230002", "metadata": {
            "new_here": {"door": "text", "texted_at": gr._iso(MONDAY - timedelta(days=gr.PATH_DAYS + 1))}}},
        {"id": CARD, "business_id": BIZ, "name": "Done Already", "phone": "+15551230003", "metadata": {
            "new_here": {"door": "web", "texted_at": gr._iso(SUNDAY), "ended_at": gr._iso(MONDAY)}}},
        {"id": cid(43), "business_id": BIZ, "name": "A Member", "phone": "+15551230004", "metadata": {}}]
    for phone in ("+15551230002", "+15551230003", "+15551230004", "+15550000000"):
        assert _reply(w, "hi there", phone=phone) == "not_a_guest"
    assert not any(_mine(w, c).get("hold") for c in (OLD, CARD))
    assert w.sent["login"] == [] and _notes(w) == []


def test_a_number_written_another_way_still_finds_the_guest(w):
    _lena(w)["phone"] = "15551230001"
    assert _reply(w, "Hi!") == "told"
    assert _mine(w)["hold"] is True


@pytest.mark.parametrize("body", ["STOP", "stop please", "Yes", "HELP", "Give", "tithe!", "DAILY", "new", " New. ",
                                  "LOVECITY"])
def test_keywords_never_count(w, body):
    assert _reply(w, body) == "keyword"
    assert not _mine(w).get("hold") and w.sent["login"] == []


def test_the_churchs_own_word_never_counts_even_while_new_here_is_off(w):
    w.t["businesses"][0]["settings"]["new_here"] = {"on": False, "word": "WELCOME"}
    assert _reply(w, "Welcome!") == "keyword"
    assert _reply(w, "new") == "told", "NEW is only the word when the church hasn't picked another"


def test_an_emoji_or_a_one_word_answer_is_a_reply(w):
    assert _reply(w, "🙏") == "told"
    assert _mine(w)["hold"] is True


def test_a_second_reply_keeps_the_first_hold_and_writes_nothing_else(w):
    _reply(w, "Thank you!")
    later = MONDAY + timedelta(minutes=3)
    assert _reply(w, "Is there anything for kids?", at=later) == "held"
    mine = _mine(w)
    assert mine["hold_since"] == gr._iso(MONDAY), "the first reply still waiting"
    assert mine["hold_reply_at"] == gr._iso(later) and mine["hold_tell"] is True
    assert [n["body"] for n in _notes(w)] == ["Answered the church’s text: “Thank you!”",
                                             "Answered the church’s text: “Is there anything for kids?”"]
    assert len(w.sent["login"]) == 1, "one alert in ten minutes"


def test_a_write_that_loses_a_race_reads_again_and_keeps_the_other_write(w, monkeypatch):
    real = w.patch
    raced = {"done": False}

    def patch(path, body, **kw):
        if path.startswith("/contacts") and not raced["done"]:
            raced["done"] = True          # another replica writes first
            row = _lena(w)
            nh = dict(row["metadata"]["new_here"], hold_v=7, card_at="2026-11-23T15:00:00Z")
            row["metadata"] = dict(row["metadata"], new_here=nh)
        return real(path, body, **kw)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    assert _reply(w, "Thank you!") == "told"
    mine = _mine(w)
    assert mine["hold"] is True and mine["card_at"] == "2026-11-23T15:00:00Z", "the other write was kept"
    assert mine["hold_v"] >= 8


def test_two_replicas_claiming_one_alert_send_it_once(w):
    _reply(w, "Thank you!")
    w.sent["login"].clear()
    nh = dict(_mine(w), hold_tell=True, hold_told_at=None)
    _lena(w)["metadata"]["new_here"] = nh
    business = w.t["businesses"][0]
    contact = dict(_lena(w))
    fu = gr._follow_up(BIZ, LENA)
    at = MONDAY + timedelta(minutes=1)
    assert gr._tell_claimed(business, contact, fu, "Thank you!", at) is True
    assert gr._tell_claimed(business, contact, fu, "Thank you!", at) is False
    assert len(w.sent["login"]) == 1


def test_a_reply_after_ten_minutes_is_told_again(w):
    _reply(w, "Thank you!")
    assert _reply(w, "Also, is there parking?", at=MONDAY + timedelta(minutes=11)) == "told"
    assert len(w.sent["login"]) == 2


def test_replies_inside_the_burst_are_told_by_the_sweep_with_the_latest_words(w):
    _reply(w, "Thank you!")
    _reply(w, "Is there anything for kids?", at=MONDAY + timedelta(minutes=2))
    w.t["sms_messages"] += [
        {"business_id": BIZ, "contact_id": LENA, "direction": "inbound", "message": "Thank you!",
         "created_at": "2026-11-23T15:20:00Z"},
        {"business_id": BIZ, "contact_id": LENA, "direction": "inbound", "message": "Is there anything for kids?",
         "created_at": "2026-11-23T15:22:00Z"}]
    assert gr.sweep(MONDAY + timedelta(minutes=5))["told"] == 0, "still inside the ten minutes"
    stats = gr.sweep(MONDAY + timedelta(minutes=12))
    assert stats["told"] == 1 and len(w.sent["login"]) == 2
    assert w.sent["login"][-1]["words"]["body"] == ("“Is there anything for kids?” Their texts are on hold "
                                                    "until you reply.")
    assert gr.sweep(MONDAY + timedelta(minutes=30))["told"] == 0


# ─── Who hears ────────────────────────────────────────────────────────

def test_a_member_caller_hears_by_email_with_the_reply_the_number_and_their_lead_tab(w):
    fu = next(r for r in w.t["church_follow_ups"] if r["id"] == FU)
    fu.update(leader_contact_id=TASHA, leader_role="team_leader", assigned_by="guest_calls:rule")
    assert _reply(w, "We'll be there!") == "told"
    assert w.sent["login"] == []
    [mail] = w.sent["email"]
    assert mail["to"] == "tasha@example.com" and mail["subject"] == "Lena Brooks answered the church’s text"
    assert "We&#x27;ll be there!" in mail["body"] or "We'll be there!" in mail["body"]
    assert "(555) 123-0001" in mail["body"]
    assert "https://love-city-church.mysolutionist.app/my/lead" in mail["body"] and "Open your Lead tab" in mail["body"]


def test_a_member_caller_with_no_email_is_the_offices_alert_without_the_words(w):
    fu = next(r for r in w.t["church_follow_ups"] if r["id"] == FU)
    fu.update(leader_contact_id=TASHA, leader_role="team_leader")
    next(c for c in w.t["contacts"] if c["id"] == TASHA)["email"] = ""
    assert _reply(w, "Please call me after 5") == "told"
    [(title, body, key)] = w.told["gc_alert"]
    assert title == "Lena Brooks answered the church’s text"
    assert "Tasha Williams has their call, with no email on file." in body and "after 5" not in body
    assert key == f"guest-reply-{LENA}-{gr._iso(MONDAY)}"


def test_no_caller_tells_whoever_does_first_time_guests(w):
    w.t["church_follow_ups"].clear()
    assert _reply(w, "Thanks so much") == "told"
    [alert] = w.sent["login"]
    assert alert["uid"] == RENEE_SEAT
    assert alert["words"]["body"] == "“Thanks so much” Their texts are on hold until someone replies."
    assert "No one has their welcome call yet." in alert["words"]["text"]
    assert _notes(w) == []


def test_a_handed_back_guest_has_no_caller(w):
    next(r for r in w.t["church_follow_ups"] if r["id"] == FU)["status"] = "handed_back"
    _reply(w, "Hello?")
    assert w.sent["login"][0]["words"]["body"].endswith("until someone replies.")
    assert len(_notes(w)) == 1, "the note still goes on their follow-up"


def test_a_nameless_guest_is_named_by_their_number(w):
    _lena(w)["name"] = PHONE
    _reply(w, "hi")
    assert w.sent["login"][0]["words"]["title"] == "A guest at (555) 123-0001 answered the church’s text"


def test_quiet_hours_hold_the_alert_for_the_sweep(w):
    w.quiet["on"] = True
    assert _reply(w, "Thank you!") == "held"
    assert w.sent["login"] == [] and _mine(w)["hold_tell"] is True and _mine(w)["hold"] is True
    w.t["sms_messages"].append({"business_id": BIZ, "contact_id": LENA, "direction": "inbound",
                                "message": "Thank you!", "created_at": "2026-11-23T15:20:00Z"})
    assert gr.sweep(MONDAY + timedelta(hours=1))["told"] == 0
    w.quiet["on"] = False
    assert gr.sweep(MONDAY + timedelta(hours=2))["told"] == 1
    assert w.sent["login"][0]["words"]["body"] == "“Thank you!” Their texts are on hold until you reply."


# ─── A person answers ─────────────────────────────────────────────────

def test_a_persons_text_from_text_lets_the_texts_go_on(w):
    _reply(w, "Thank you!")
    w.gr_clock["now"] = MONDAY + timedelta(hours=1)
    assert gr.on_person_text(BIZ, LENA, PHONE, RENEE_SEAT) == "answered"
    mine = _mine(w)
    assert mine["hold"] is False and "hold_since" not in mine and "hold_tell" not in mine
    assert mine["hold_answered_by"] == "Renee Ellis"
    assert _notes(w)[-1]["body"] == "Answered by Renee Ellis."
    assert gr.on_person_text(BIZ, LENA, PHONE, RENEE_SEAT) == "not_held"
    assert len(_notes(w)) == 2


def test_a_persons_text_found_by_number_alone(w):
    _reply(w, "Thank you!")
    assert gr.on_person_text(BIZ, None, "5551230001", RENEE_SEAT) == "answered"
    assert _mine(w)["hold"] is False


def test_the_send_endpoint_hands_over_only_a_text_that_went(w, monkeypatch):
    import sms_service
    from auth_supabase import AuthedUser
    import business_access
    monkeypatch.setattr(business_access, "assert_access", lambda *a, **k: None)
    handed = []
    monkeypatch.setattr(gr, "later", lambda fn, *a: handed.append((fn.__name__, a)))

    async def core(client, **kw):
        return {"status": "sent", "id": "m1"}
    monkeypatch.setattr(sms_service, "send_sms_core", core)
    user = AuthedUser(id=RENEE_SEAT, email="renee@example.com", role="authenticated")
    req = sms_service.SendSmsRequest(business_id=BIZ, contact_id=LENA, to=PHONE, message="Hi Lena!")
    assert asyncio.run(sms_service.send_sms(req, user)) == {"status": "sent", "id": "m1"}
    assert handed == [("on_person_text", (BIZ, LENA, PHONE, RENEE_SEAT))]

    async def refused(client, **kw):
        raise sms_service.SmsSendError("opted out", 422)
    monkeypatch.setattr(sms_service, "send_sms_core", refused)
    asyncio.run(sms_service.send_sms(req, user))
    assert len(handed) == 1, "a text that didn't go answers nobody"


def test_chiefs_and_the_automatic_texts_never_clear_a_hold():
    import new_here
    import sms_service
    assert "guest_replies" not in inspect.getsource(sms_service.send_sms_core)
    assert "guest_replies" in inspect.getsource(sms_service.send_sms)
    # The scheduler's texts are stored as "system", Chief's as "chief": neither
    # goes through POST /sms/send, the only place a person's text is heard.
    assert 'sent_by="system"' in inspect.getsource(new_here.run_scheduled)


def test_the_caller_logging_talked_or_left_a_message_lets_the_texts_go_on(w):
    fu = next(r for r in w.t["church_follow_ups"] if r["id"] == FU)
    fu.update(leader_contact_id=TASHA, leader_role="team_leader")
    _reply(w, "Thank you!")
    tasha = {"id": TASHA, "name": "Tasha Williams"}
    cfu.leader_note(BIZ, tasha, FU, "noanswer", "", False)
    assert _mine(w)["hold"] is True, "No answer isn't an answer"
    cfu.leader_note(BIZ, tasha, FU, "message", "Left a voicemail", False)
    assert _mine(w)["hold"] is False
    assert any(n["body"] == "Answered by Tasha Williams." for n in _notes(w))


def test_an_outcome_on_another_card_or_a_guest_not_held_changes_nothing(w):
    assert gr.on_outcome(BIZ, FU, "Renee Ellis") == "not_held"
    w.t["church_follow_ups"].append({"id": FU2, "business_id": BIZ, "contact_id": LENA,
                                     "card_key": "form:f-baptism", "path_kind": "baptism", "status": "open"})
    _reply(w, "Thank you!")
    assert gr.on_outcome(BIZ, FU2, "Angela Price") == "not_a_guest"
    assert _mine(w)["hold"] is True


# ─── Still waiting ────────────────────────────────────────────────────

def test_a_day_later_the_caller_is_reminded_once_and_three_days_later_the_office_once(w):
    _reply(w, "Is there anything for kids on Wednesday?")
    w.t["sms_messages"].append({"business_id": BIZ, "contact_id": LENA, "direction": "inbound",
                                "message": "Is there anything for kids on Wednesday?",
                                "created_at": "2026-11-23T15:20:00Z"})
    assert gr.sweep(MONDAY + timedelta(hours=23))["reminded"] == 0
    assert gr.sweep(MONDAY + timedelta(hours=24, minutes=5))["reminded"] == 1
    remind = w.sent["login"][-1]
    assert remind["words"]["title"] == "Lena Brooks is still waiting on a reply"
    assert remind["words"]["body"].endswith("They texted yesterday. Their texts are on hold until you reply.")
    assert gr.sweep(MONDAY + timedelta(hours=30))["reminded"] == 0, "once"
    assert gr.sweep(MONDAY + timedelta(days=2, hours=23))["office"] == 0
    assert gr.sweep(MONDAY + timedelta(days=3, minutes=5))["office"] == 1
    [(title, body, key)] = w.told["gc_alert"]
    assert title == "Lena Brooks has waited three days for a reply"
    assert "on Monday" in body and "Renee Ellis has their call." in body and "Wednesday" not in body
    assert gr.sweep(MONDAY + timedelta(days=4))["office"] == 0, "once"
    assert _mine(w)["hold"] is True, "never cleared by time"
    assert [v for v, _, _ in w.sent["history"]].count("church:guest_reply_late") == 2


def test_a_hold_answered_before_the_day_is_out_is_never_reminded(w):
    _reply(w, "Thank you!")
    gr.on_person_text(BIZ, LENA, PHONE, RENEE_SEAT)
    stats = gr.sweep(MONDAY + timedelta(days=4))
    assert stats["waiting"] == 0 and stats["reminded"] == 0 and stats["office"] == 0


def test_a_new_hold_after_an_answer_gets_its_own_reminder(w):
    _reply(w, "Thank you!")
    w.t["sms_messages"].append({"business_id": BIZ, "contact_id": LENA, "direction": "inbound",
                                "message": "Thank you!", "created_at": "2026-11-23T15:20:00Z"})
    gr.sweep(MONDAY + timedelta(hours=25))
    gr.on_person_text(BIZ, LENA, PHONE, RENEE_SEAT)
    again = MONDAY + timedelta(days=2)
    _reply(w, "One more question", at=again)
    assert "hold_reminded_at" not in _mine(w) and _mine(w)["hold_since"] == gr._iso(again)
    assert gr.sweep(again + timedelta(hours=25))["reminded"] == 1


# ─── The switch and failed reads ──────────────────────────────────────

def test_the_switch_off_does_nothing(w, monkeypatch):
    w.on["on"] = False
    assert _reply(w, "Thank you!") == "off"
    assert not _mine(w).get("hold") and _notes(w) == [] and w.sent["login"] == []
    monkeypatch.setenv("GUEST_PATH", "off")
    assert gr.sweep(MONDAY) == {"churches": 0, "waiting": 0, "told": 0, "reminded": 0, "office": 0}
    import threading
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self))
    _REAL_LATER(gr.on_reply, BIZ, PHONE, "hi")
    assert started == []


def test_a_failed_read_of_the_guest_decides_nothing(w, monkeypatch):
    real = w.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/contacts") else real(path, **kw))
    assert _reply(w, "Thank you!") == "unread"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    assert not _mine(w).get("hold") and w.sent["login"] == []


def test_a_failed_follow_up_read_holds_but_tells_no_one_until_it_can_read(w, monkeypatch):
    real = w.get
    broken = {"on": True}

    def get(path, **kw):
        if broken["on"] and path.startswith("/church_follow_ups"):
            return None
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    assert _reply(w, "Thank you!") == "held"
    assert _mine(w)["hold"] is True and _mine(w)["hold_tell"] is True
    assert w.sent["login"] == [] and _notes(w) == []
    w.t["sms_messages"].append({"business_id": BIZ, "contact_id": LENA, "direction": "inbound",
                                "message": "Thank you!", "created_at": "2026-11-23T15:20:00Z"})
    assert gr.sweep(MONDAY + timedelta(minutes=20))["told"] == 0
    broken["on"] = False
    assert gr.sweep(MONDAY + timedelta(minutes=30))["told"] == 1


def test_who_to_tell_unread_tells_no_one_and_the_alert_stays_owed(w, monkeypatch):
    real = w.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") else real(path, **kw))
    assert _reply(w, "Thank you!") == "held"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    mine = _mine(w)
    assert mine["hold_tell"] is True and not mine.get("hold_told_at")
    assert w.sent["login"] == [] and w.told["gc_alert"] == []


def test_a_failed_send_is_owed_again(w, monkeypatch):
    monkeypatch.setattr(gc, "tell_login", lambda *a, **k: False)

    async def no_alert(*a, **k):
        return False
    monkeypatch.setattr(gc, "office_alert", no_alert)
    assert _reply(w, "Thank you!") == "held"
    assert _mine(w)["hold_tell"] is True and not _mine(w).get("hold_told_at")


def test_a_login_nobody_can_reach_falls_to_the_offices_alert(w, monkeypatch):
    monkeypatch.setattr(gc, "tell_login", lambda *a, **k: False)
    assert _reply(w, "Thank you!") == "told"
    [(title, body, _)] = w.told["gc_alert"]
    assert "Renee Ellis has their call." in body and "Thank you" not in body


def test_unread_numbers_skip_the_sweep(w, monkeypatch):
    real = w.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/sms_numbers") else real(path, **kw))
    assert gr.sweep(MONDAY)["churches"] == 0


# ─── The hooks ────────────────────────────────────────────────────────

def test_routing_hands_a_plain_text_on_the_churchs_own_number_to_on_reply(monkeypatch):
    import sms_routing
    from test_sms_numbers_inbound import CUSTOMER, OWN_A, BIZ_A
    calls = []

    async def business_for_number(client, to):
        return {"business_id": BIZ_A, "status": "active"} if to == OWN_A else None

    async def nothing(*a, **k):
        return None
    for name in ("_bind", "_ensure_contact", "_sb_post"):
        monkeypatch.setattr(sms_routing, name, nothing)

    async def biz_name(client, business_id):
        return "Glow Studio"
    monkeypatch.setattr(sms_routing, "_biz_name", biz_name)

    async def record(client, **kw):
        calls.append(("recorded", kw["text"]))
        return {"id": "m1"}
    monkeypatch.setattr(sms_routing, "business_for_number", business_for_number)
    monkeypatch.setattr(sms_routing, "record_inbound_sms", record)
    import new_here
    monkeypatch.setattr(new_here, "on_text", lambda *a: None)
    monkeypatch.setattr(gr, "later", lambda fn, *a: calls.append((fn.__name__, a)))

    def run(text):
        calls.clear()
        return asyncio.run(sms_routing.route_inbound(from_number=CUSTOMER, text=text, to_number=OWN_A))
    assert run("Thank you so much!")["action"] == "routed_direct"
    assert calls == [("recorded", "Thank you so much!"), ("on_reply", (BIZ_A, CUSTOMER, "Thank you so much!"))]
    for word in ("STOP", "START", "HELP"):
        run(word)
        assert not any(c[0] == "on_reply" for c in calls), word

    def boom(*a):
        raise RuntimeError("no threads")
    monkeypatch.setattr(gr, "later", boom)
    assert run("Thank you!")["action"] == "routed_direct", "a hand-off that breaks never breaks routing"


def test_later_runs_off_the_request_path_and_never_raises(monkeypatch):
    import threading
    monkeypatch.delenv("GUEST_PATH", raising=False)
    done = threading.Event()
    seen = []

    def work(x):
        seen.append((x, threading.current_thread().name))
        done.set()
        raise ValueError("nope")
    _REAL_LATER(work, 1)
    assert done.wait(5)
    assert seen == [(1, "guest-replies")]


def test_tell_login_opens_where_its_told_and_defaults_to_the_follow_up_board(monkeypatch):
    import types
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    import push_notifications
    real = gc.tell_login
    pushes, mails = [], []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: pushes.append(kw["nav"]) or 1)
    monkeypatch.setattr(cas, "_login_email", lambda ch, uid: "renee@example.com")
    monkeypatch.setattr(cot, "render", lambda biz, text, title, link, label: f"{link}|{label}")
    monkeypatch.setattr(clt, "deliver", lambda biz, to, name, subject, html, ref, reply_to=None: mails.append(html))
    monkeypatch.setattr(clt, "_office_email", lambda biz: "")
    ctx = types.SimpleNamespace(ch=types.SimpleNamespace(b=BIZ, business={"id": BIZ, "name": "Love City Church"}),
                                conf={"tell": {"app": True, "email": True}})
    words = {"title": "t", "body": "b", "subject": "s", "text": "x"}
    assert real(ctx, RENEE_SEAT, words, "ref") is True
    assert pushes == [gc.NAV] and mails[0].endswith("|Open the Follow-up board")
    assert real(ctx, RENEE_SEAT, words, "ref", nav=f"operate:sms:{LENA}", link="https://app/x",
                label="Open their texts") is True
    assert pushes[-1] == f"operate:sms:{LENA}" and mails[-1] == "https://app/x|Open their texts"


def test_the_sweep_is_scheduled_every_ten_minutes():
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert re.search(r'g\("guest_replies_sweep", _guest_replies\.sweep\), "interval", minutes=10', src)
