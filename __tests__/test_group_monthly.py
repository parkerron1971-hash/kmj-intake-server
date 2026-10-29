# __tests__/test_group_monthly.py
#
# A group that gathers once a month (group_gatherings; groups.meet_every =
# 4, meet_nth 1-4 or 5 = the last). Pins:
#   1. the first, second, third, fourth or last of its weekday in the month
#   2. the next gathering, the coming list and the 5 PM reminder follow it
#   3. a leader sets it from the Meet tab; another choice clears it
#   4. it reads "First Thursday of the month · 7:00 PM"

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
from test_group_gatherings import DETROIT, TUESDAY_MORNING, _at, _g, _page, meet  # noqa: F401
from test_member_portal_group_space import BIZ, BUSINESS, G, TASHA, _client, _me, fake  # noqa: F401

TUE = TUESDAY_MORNING.astimezone(DETROIT)                  # Tuesday, October 20, 2026


def _monthly(nth):
    return {"meet_day": 3, "meet_time": "19:00:00", "meet_skips": [], "meet_every": 4, "meet_nth": nth}


# ── 1. which one ─────────────────────────────────────────────────────

def test_which_thursday():
    # Thursdays in October 2026: 1, 8, 15, 22, 29.
    assert [d for d in range(1, 32) if gg.on_cycle(_monthly(1), date(2026, 10, d)) and date(2026, 10, d).weekday() == 3] == [1]
    assert gg.on_cycle(_monthly(4), date(2026, 10, 22)) and not gg.on_cycle(_monthly(4), date(2026, 10, 29))
    assert gg.on_cycle(_monthly(5), date(2026, 10, 29)) and not gg.on_cycle(_monthly(5), date(2026, 10, 22))
    assert gg.on_cycle(_monthly(5), date(2026, 11, 26))                    # November's last Thursday is the 4th


# ── 2. what's next ───────────────────────────────────────────────────

def test_next_and_the_coming_list():
    assert gg.next_on(_monthly(4), TUE)[0] == date(2026, 10, 22)
    assert gg.next_on(_monthly(1), TUE)[0] == date(2026, 11, 5)
    assert gg.upcoming(_monthly(5), TUE, 3) == [date(2026, 10, 29), date(2026, 11, 26), date(2026, 12, 31)]
    skipped = {**_monthly(1), "meet_skips": ["2026-11-05"]}
    assert gg.next_on(skipped, TUE) == (date(2026, 12, 3), date(2026, 11, 5))


def test_the_reminder_only_in_its_week(meet, monkeypatch):
    import member_push
    sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: sent.append(k) or 1)
    _g(meet).update(meet_every=4, meet_nth=5)
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 0 and sent == []
    assert gg.reminders(BUSINESS, _at(2026, 10, 29, 17)) == 1


# ── 3. a leader sets it ──────────────────────────────────────────────

def test_a_leader_sets_it_and_another_choice_clears_it(meet):
    assert gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "4", "", "2") == (True, "schedule_saved")
    assert (_g(meet)["meet_every"], _g(meet)["meet_nth"]) == (4, 2)
    assert gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "4", "", "9") == (False, "schedule_bad")
    gg.set_schedule(BUSINESS, _me(TASHA, "x"), G, "3", "19:00", "", "", "1", "", "")
    assert (_g(meet)["meet_every"], _g(meet)["meet_nth"]) == (1, None)


def test_the_route_passes_it_on(meet, monkeypatch):
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post(
        "/my/groups/meet/schedule", data={"group_id": G, "day": "3", "time": "19:00", "every": "4", "nth": "5"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=schedule_saved"
    assert (_g(meet)["meet_every"], _g(meet)["meet_nth"]) == (4, 5)


# ── 4. how it reads ──────────────────────────────────────────────────

def test_how_it_reads(meet):
    assert gg.regular_text(_monthly(1)) == "First Thursday of the month · 7:00 PM"
    assert gg.regular_text(_monthly(5)) == "Last Thursday of the month · 7:00 PM"
    _g(meet).update(meet_every=4, meet_nth=5)
    html = _page(TASHA)
    assert "Last Thursday of the month · 7:00 PM" in html and "Thursday, October 29" in html
    assert '<option value="4" selected>Once a month</option>' in html and '<option value="5" selected>last one</option>' in html


def test_the_page_reads_which_one(meet, monkeypatch):
    import member_portal_groups as mpg
    import sb_clients
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: seen.append(p) or real(p, **k))
    mpg.group_row(BIZ, G)
    gg._group(BIZ, G)
    picked = [p.split("select=")[1].split("&")[0].split(",") for p in seen if p.startswith("/groups")]
    assert picked and all("meet_nth" in cols for cols in picked)


def test_a_month_whose_thursdays_fall_on_sevens():
    # Thursdays in May 2026: 7, 14, 21, 28.
    assert gg.on_cycle(_monthly(1), date(2026, 5, 7)) and gg.on_cycle(_monthly(2), date(2026, 5, 14))
    assert gg.on_cycle(_monthly(4), date(2026, 5, 28)) and gg.on_cycle(_monthly(5), date(2026, 5, 28))


def test_eight_months_ahead_for_a_dish_sign_up():
    coming = gg.upcoming(_monthly(1), TUE, 8)
    assert len(coming) == 8 and coming[-1] == date(2027, 6, 3)
