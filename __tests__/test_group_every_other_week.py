# __tests__/test_group_every_other_week.py
#
# A group that gathers every other week (group_gatherings; groups.meet_every
# and meet_from). Pins:
#   1. the weeks count from a date the group gathers; weekly is as before
#   2. the next gathering, the coming list and the 5 PM reminder skip the
#      off weeks
#   3. a leader picks it from their phone: from the coming one or the week
#      after (today's, once it's over, isn't "coming"); back to weekly clears it
#   4. it reads "Every other Thursday · 7:00 PM"

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
from test_group_gatherings import DETROIT, THURSDAY_NIGHT, TUESDAY_MORNING, _at, _g, _page, meet  # noqa: F401
from test_member_portal_group_space import BIZ, BUSINESS, G, MONIQUE, TASHA, _client, _me, fake  # noqa: F401

TUE = TUESDAY_MORNING.astimezone(DETROIT)


def _every_other(anchor):
    return {"meet_day": 3, "meet_time": "19:00:00", "meet_skips": [], "meet_every": 2, "meet_from": anchor}


# ── 1. the cycle ─────────────────────────────────────────────────────

def test_the_weeks_count_from_a_gathering():
    g = _every_other("2026-10-22")
    assert gg.on_cycle(g, date(2026, 10, 22)) and gg.on_cycle(g, date(2026, 11, 5)) and gg.on_cycle(g, date(2026, 10, 8))
    assert not gg.on_cycle(g, date(2026, 10, 29)) and not gg.on_cycle(g, date(2026, 10, 15))
    assert gg.on_cycle({"meet_every": 1, "meet_from": "2026-10-22"}, date(2026, 10, 29))     # weekly
    assert gg.on_cycle({"meet_every": 2, "meet_from": None}, date(2026, 10, 29))             # no anchor yet: weekly


# ── 2. what's next ───────────────────────────────────────────────────

def test_next_and_the_coming_list_skip_the_off_weeks():
    assert gg.next_on(_every_other("2026-10-22"), TUE)[0] == date(2026, 10, 22)
    assert gg.next_on(_every_other("2026-10-29"), TUE)[0] == date(2026, 10, 29)
    assert gg.next_on(_every_other("2026-10-15"), TUE)[0] == date(2026, 10, 29)
    assert gg.upcoming(_every_other("2026-10-22"), TUE, 3) == [date(2026, 10, 22), date(2026, 11, 5), date(2026, 11, 19)]


def test_no_reminder_in_an_off_week(meet, monkeypatch):
    import member_push
    sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: sent.append(k) or 1)
    _g(meet).update(meet_every=2, meet_from="2026-10-29")
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 0 and sent == []
    assert gg.reminders(BUSINESS, _at(2026, 10, 29, 17)) == 1


# ── 3. a leader sets it ──────────────────────────────────────────────

def test_from_the_coming_one_or_the_week_after(meet):
    assert gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "2", "0") == (True, "schedule_saved")
    assert (_g(meet)["meet_every"], _g(meet)["meet_from"]) == (2, "2026-10-22")
    gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "2", "1")
    assert _g(meet)["meet_from"] == "2026-10-29"
    gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "1", "")
    assert (_g(meet)["meet_every"], _g(meet)["meet_from"]) == (1, None)


def test_tonights_once_its_over_isnt_the_coming_one(meet):
    meet.clock["now"] = _at(2026, 10, 22, 23, 30)          # Thursday, after 11 PM
    gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "2", "0")
    assert _g(meet)["meet_from"] == "2026-10-29"
    meet.clock["now"] = THURSDAY_NIGHT                      # five minutes in: tonight's still counts
    gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "2", "0")
    assert _g(meet)["meet_from"] == "2026-10-22"


def test_only_a_leader(meet):
    assert gg.set_schedule(BUSINESS, _me(MONIQUE, "x"), G, "3", "19:00", "", "", "2", "0") == (False, "not_group_leader")
    assert _g(meet).get("meet_every", 1) in (1, None)


def test_the_route_passes_it_on(meet, monkeypatch):
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post(
        "/my/groups/meet/schedule", data={"group_id": G, "day": "3", "time": "19:00", "every": "2", "first": "1"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=schedule_saved"
    assert (_g(meet)["meet_every"], _g(meet)["meet_from"]) == (2, "2026-10-29")


# ── 4. how it reads ──────────────────────────────────────────────────

def test_how_it_reads(meet):
    assert gg.regular_text(_every_other("2026-10-22")) == "Every other Thursday · 7:00 PM"
    assert gg.regular_text({"meet_day": 3, "meet_time": "19:00:00"}) == "Thursdays · 7:00 PM"
    _g(meet).update(meet_every=2, meet_from="2026-10-29")
    html = _page(TASHA)
    assert "Every other Thursday · 7:00 PM" in html and "Thursday, October 29" in html
    assert '<option value="2" selected>Every other week</option>' in html


def test_the_page_reads_the_cycle(meet, monkeypatch):
    # The fake hands back whole rows whatever is selected; the live database doesn't.
    import member_portal_groups as mpg
    import sb_clients
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: seen.append(p) or real(p, **k))
    mpg.group_row(BIZ, G)
    gg._group(BIZ, G)
    picked = [p.split("select=")[1].split("&")[0].split(",") for p in seen if p.startswith("/groups")]
    assert picked and all({"meet_every", "meet_from"} <= set(cols) for cols in picked)
