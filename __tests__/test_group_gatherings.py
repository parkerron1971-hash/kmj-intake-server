# __tests__/test_group_gatherings.py
#
# A group's gatherings (group_gatherings.py + the group page's Meet tab;
# part 3 of the approved canvas "Church Groups, Together", boards Meet, Roll
# and Settings). Pins:
#   1. the next gathering on the church's own clock: it stays "next" until 4
#      hours after it starts; a skipped date is passed over
#   2. Going / Maybe / Can't: one answer per person per gathering, only
#      people in the group, only when a gathering is coming
#   3. "I'm here" only from 30 minutes before to 4 hours after; counted once,
#      in the office's own attendance (how = self)
#   4. a leader's roll on the day: exactly who's ticked, guests, a note
#   5. a leader sets the regular time, or skips a week; nobody else
#   6. the street address and the note show only inside the group
#   7. the reminder: 5 PM, the day of an evening gathering (the day before an
#      earlier one), never to someone who said they can't come

import asyncio
import pathlib
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
import member_portal_groups as mpg
import test_member_portal_group_space as gs
from test_member_portal_group_space import (BIZ, BUSINESS, G, MONIQUE, ROCHELLE, TASHA, TEEN,  # noqa: F401
                                            _client, _me, _req, fake)

DETROIT = ZoneInfo("America/Detroit")


def _at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=DETROIT).astimezone(timezone.utc)


TUESDAY_MORNING = _at(2026, 10, 20, 10)       # Thursday's gathering is two days off
THURSDAY_NIGHT = _at(2026, 10, 22, 19, 5)      # five minutes in


@pytest.fixture
def meet(fake, monkeypatch):
    import sb_clients
    for g in fake.t["groups"]:
        if g["id"] == G:
            g.update(meet_day=3, meet_time="19:00:00", meet_address="412 Maple Ave", meet_note="Park on Maple, ring the side door",
                     meet_skips=[])
    fake.t.update(group_rsvps=[], group_meetings=[], group_meeting_attendance=[])
    monkeypatch.setattr(gg, "zone", lambda business: DETROIT)
    clock = {"now": TUESDAY_MORNING}
    monkeypatch.setattr(gg, "_now", lambda: clock["now"])
    fake.clock = clock
    real_post = fake.post

    def post(path, body, prefer=None, **kw):
        table, _ = gs._params(path)
        keys = {"group_rsvps": ("group_id", "met_on", "contact_id"), "group_meetings": ("group_id", "met_on"),
                "group_meeting_attendance": ("meeting_id", "contact_id")}.get(table)
        if keys:
            out = []
            for b in (body if isinstance(body, list) else [body]):
                hit = next((r for r in fake.t[table] if all(str(r.get(k)) == str(b.get(k)) for k in keys)), None)
                if hit:
                    if "merge-duplicates" in (prefer or ""):
                        hit.update(b)
                        out.append(hit)
                    continue
                out += real_post(path, b, prefer, **kw) or []
            return out
        return real_post(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)

    def delete(path):
        table, params = gs._params(path)
        gone = fake._rows(table, params)
        fake.t[table] = [r for r in fake.t.get(table, []) if r not in gone]
        return True
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    return fake


def _g(fake):
    return next(g for g in fake.t["groups"] if g["id"] == G)


# ── 1. the next gathering ────────────────────────────────────────────

def test_the_next_gathering_on_the_churchs_clock():
    g = {"meet_day": 3, "meet_time": "19:00:00", "meet_skips": []}
    assert gg.next_on(g, TUESDAY_MORNING.astimezone(DETROIT)) == (date(2026, 10, 22), None)
    assert gg.next_on(g, _at(2026, 10, 22, 22, 59).astimezone(DETROIT))[0] == date(2026, 10, 22)   # still tonight's
    assert gg.next_on(g, _at(2026, 10, 22, 23, 1).astimezone(DETROIT))[0] == date(2026, 10, 29)    # over
    g["meet_skips"] = ["2026-10-22"]
    assert gg.next_on(g, TUESDAY_MORNING.astimezone(DETROIT)) == (date(2026, 10, 29), date(2026, 10, 22))
    assert gg.next_on({"meet_day": None, "meet_time": None}, TUESDAY_MORNING.astimezone(DETROIT)) == (None, None)


def test_im_here_opens_half_an_hour_before():
    g = {"meet_day": 3, "meet_time": "19:00:00"}
    day = date(2026, 10, 22)
    assert not gg.can_say_here(g, day, _at(2026, 10, 22, 18, 29).astimezone(DETROIT))
    assert gg.can_say_here(g, day, _at(2026, 10, 22, 18, 30).astimezone(DETROIT))
    assert gg.can_say_here(g, day, _at(2026, 10, 22, 23, 0).astimezone(DETROIT))
    assert not gg.can_say_here(g, day, _at(2026, 10, 22, 23, 1).astimezone(DETROIT))


def test_the_reminder_day():
    assert gg.remind_day({"meet_time": "19:00:00"}, date(2026, 10, 22)) == date(2026, 10, 22)
    assert gg.remind_day({"meet_time": "10:00:00"}, date(2026, 10, 22)) == date(2026, 10, 21)


# ── 2. RSVP ──────────────────────────────────────────────────────────

def test_one_answer_per_person(meet):
    assert gg.rsvp(BUSINESS, _me(MONIQUE, "Monique"), G, "going") == (True, "rsvp_going")
    assert gg.rsvp(BUSINESS, _me(MONIQUE, "Monique"), G, "maybe") == (True, "rsvp_maybe")
    assert [(r["contact_id"], r["met_on"], r["answer"]) for r in meet.t["group_rsvps"]] == [(MONIQUE, "2026-10-22", "maybe")]
    assert gg.rsvp(BUSINESS, _me(MONIQUE, "Monique"), G, "sure") == (False, "error")


def test_only_the_group_answers_and_only_when_something_is_coming(meet):
    assert gg.rsvp(BUSINESS, _me(ROCHELLE, "Rochelle"), G, "going") == (False, "not_in_group")
    _g(meet).update(meet_day=None, meet_time=None)
    assert gg.rsvp(BUSINESS, _me(MONIQUE, "Monique"), G, "going") == (False, "no_gathering")
    assert meet.t["group_rsvps"] == []


# ── 3. I'm here ──────────────────────────────────────────────────────

def test_im_here_only_in_its_window_and_once(meet):
    assert gg.here(BUSINESS, _me(MONIQUE, "Monique"), G) == (False, "here_closed")
    meet.clock["now"] = THURSDAY_NIGHT
    assert gg.here(BUSINESS, _me(MONIQUE, "Monique"), G) == (True, "here")
    assert gg.here(BUSINESS, _me(MONIQUE, "Monique"), G) == (True, "here")
    m = meet.t["group_meetings"]
    assert len(m) == 1 and m[0]["met_on"] == "2026-10-22"
    assert [(a["contact_id"], a["how"]) for a in meet.t["group_meeting_attendance"]] == [(MONIQUE, "self")]
    assert gg.here(BUSINESS, _me(ROCHELLE, "Rochelle"), G) == (False, "not_in_group")


# ── 4. the roll ──────────────────────────────────────────────────────

def test_a_leaders_roll_on_the_day(meet):
    assert gg.roll(BUSINESS, _me(TASHA, "Tasha"), G, [MONIQUE], 0, "") == (False, "roll_closed")      # Tuesday
    meet.clock["now"] = THURSDAY_NIGHT
    gg.here(BUSINESS, _me(TEEN, "Kayla"), G)
    assert gg.roll(BUSINESS, _me(MONIQUE, "Monique"), G, [MONIQUE], 0, "") == (False, "not_group_leader")
    ok = gg.roll(BUSINESS, _me(TASHA, "Tasha"), G, [TASHA, MONIQUE, ROCHELLE], 2, "We ran long on question 3.")
    assert ok == (True, "roll_saved")
    came = {(a["contact_id"], a["how"]) for a in meet.t["group_meeting_attendance"]}
    assert came == {(TASHA, "leader"), (MONIQUE, "leader")}          # Kayla unticked; Rochelle isn't in the group
    m = meet.t["group_meetings"][0]
    assert m["visitors"] == 2 and m["notes"] == "We ran long on question 3."


# ── 5. the schedule ──────────────────────────────────────────────────

def test_a_leader_sets_the_time_or_skips_a_week(meet):
    assert gg.set_schedule(BUSINESS, _me(MONIQUE, "Monique"), G, "1", "18:30", "", "") == (False, "not_group_leader")
    assert gg.set_schedule(BUSINESS, _me(TASHA, "Tasha"), G, "1", "", "", "") == (False, "schedule_bad")
    assert gg.set_schedule(BUSINESS, _me(TASHA, "Tasha"), G, "1", "18:30", "9 Elm St", "Back door") == (True, "schedule_saved")
    g = _g(meet)
    assert (g["meet_day"], g["meet_time"], g["meet_address"], g["meet_note"]) == (1, "18:30", "9 Elm St", "Back door")
    assert gg.skip(BUSINESS, _me(TASHA, "Tasha"), G, "2026-10-26", True) == (True, "skipped")
    assert g["meet_skips"] == ["2026-10-26"]
    assert gg.skip(BUSINESS, _me(TASHA, "Tasha"), G, "2026-10-26", False) == (True, "unskipped")
    assert g["meet_skips"] == []
    assert gg.skip(BUSINESS, _me(MONIQUE, "Monique"), G, "2026-10-26", True) == (False, "not_group_leader")
    assert gg.set_schedule(BUSINESS, _me(TASHA, "Tasha"), G, "", "", "", "") == (True, "schedule_saved")
    assert g["meet_day"] is None and g["meet_time"] is None


# ── 6. the page ──────────────────────────────────────────────────────

def _page(who, tab="meet"):
    data = mpg.space(BIZ, G, _me(who, "x"), tab=tab)
    if data.get("role"):
        data["meet"] = gg.view(BUSINESS, data["group"], who, data["people"])
    html, _ = mpg.render(BUSINESS, None, _req(), _me(who, "x"), data, tab)
    return html


def test_the_meet_tab(meet):
    gg.rsvp(BUSINESS, _me(TASHA, "Tasha"), G, "going")
    gg.rsvp(BUSINESS, _me(TEEN, "Kayla"), G, "maybe")
    # Someone who answered and has since left the group isn’t counted.
    meet.t["group_rsvps"].append({"business_id": BIZ, "group_id": G, "met_on": "2026-10-22", "contact_id": ROCHELLE, "answer": "maybe"})
    html = _page(MONIQUE)
    assert "Thursday, October 22 · 7:00 PM" in html and "412 Maple Ave" in html and "Park on Maple" in html
    assert "1 going · 1 maybe" in html and 'action="/my/groups/meet/rsvp"' in html
    assert "I’m here" not in html                                    # not today
    assert "Take attendance" not in html and "When and where you meet" not in html   # not a leader
    assert f'href="/my/groups/{G}/meet"' in html


def test_the_address_never_leaves_the_group(meet):
    outsider = _page(ROCHELLE, "")
    assert "412 Maple Ave" not in outsider and "Park on Maple" not in outsider


def test_a_leader_sees_the_roll_on_the_day_and_the_settings(meet):
    meet.clock["now"] = THURSDAY_NIGHT
    html = _page(TASHA)
    assert "Take attendance" in html and 'action="/my/groups/meet/roll"' in html and "When and where you meet" in html
    assert "I’m here" in _page(MONIQUE)


def test_home_says_when_and_asks(meet):
    gg.rsvp(BUSINESS, _me(TASHA, "Tasha"), G, "going")
    html = _page(MONIQUE, "")
    assert "Thursday, October 22 · 7:00 PM · 1 going" in html and "Are you coming?" in html


def test_before_shows_who_came_and_the_note_only_to_leaders(meet):
    meet.t["group_meetings"].append({"id": "mmmmmmmm-0000-0000-0000-000000000001", "business_id": BIZ, "group_id": G,
                                     "met_on": "2026-10-15", "visitors": 1, "notes": "Keep praying for Dana's mom."})
    meet.t["group_meeting_attendance"].append({"meeting_id": "mmmmmmmm-0000-0000-0000-000000000001", "contact_id": MONIQUE,
                                               "business_id": BIZ, "how": "office"})
    member = _page(MONIQUE)
    assert "1 came · 1 guest" in member and "You were there" in member and "Keep praying" not in member
    assert "Keep praying for Dana" in _page(TASHA)


# ── 7. the reminder ──────────────────────────────────────────────────

def test_the_five_oclock_reminder(meet, monkeypatch):
    import member_push
    sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: sent.append((kind, k)) or 1)
    gg.rsvp(BUSINESS, _me(TEEN, "Kayla"), G, "no")
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 16)) == 0 and sent == []
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 1
    kind, k = sent[0]
    assert kind == "groups" and k["title"] == "Sisters in the City" and k["body"].startswith("Tonight at 7:00 PM")
    assert "412 Maple" not in k["body"]                              # the lock screen never shows the address
    assert sorted(k["contact_ids"]) == sorted([TASHA, MONIQUE]) and k["ref_id"] == f"gathering:{G}:2026-10-22"
    sent.clear()
    assert gg.reminders(BUSINESS, _at(2026, 10, 21, 17)) == 0        # Wednesday: an evening one waits for its day
    _g(meet)["meet_skips"] = ["2026-10-22"]
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 0        # skipped


# ── the routes ───────────────────────────────────────────────────────

def test_routes_land_back_on_meet(meet, monkeypatch):
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post("/my/groups/meet/rsvp", data={"group_id": G, "answer": "going"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=rsvp_going"
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post("/my/groups/meet/here", data={"group_id": G})
    assert r.headers["location"] == f"/my/groups/{G}/meet?err=here_closed"


def test_rsvps_are_in_the_export_and_never_reimported():
    import account_lifecycle as al
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("group_rsvps") < t.index("groups") < t.index("contacts")
    assert "group_rsvps" in al._IMPORT_SKIP
