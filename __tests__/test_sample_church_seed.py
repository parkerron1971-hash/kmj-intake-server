"""The sample church's seed, BE-2 (sample_church_data.py, sample_church_seed.py, 2026-11-15).

Grace Street Fellowship is the made-up church a church looks around before it
starts. Kevin, 2026-11-14: "top tier, no cut corners". What is pinned here:
  · the generator is deterministic, every date is today's and every weekday real;
  · only fake contact data (@example.org, +1<area>555-01NN);
  · the counts, and the story the approved mock tells, computed the way the
    app computes them (last Sunday 186, eight Sundays, 8 → 4 → 2, 15 of 18,
    the four who drifted, two guests not reached, four things need you);
  · every send switch off, every sweep's stamp set, no engine rows;
  · one seed under a race, a dead claim taken over, a re-seed on version,
    age and week, gifts never rewritten, every delete scoped to the sample;
  · every column is a real one (the production schema snapshot);
  · the empty-room check; the website; the books and Move-in stay out.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import sample_church as sc  # noqa: E402
import sample_church_data as d  # noqa: E402
import sample_church_seed as ss  # noqa: E402

SAMPLE, HOME, OWNER, OTHER = ("5a3c0000-0000-4000-8000-00000000000a", "5a3c0000-0000-4000-8000-00000000000b",
                              "5a3c0000-0000-4000-8000-00000000000c", "5a3c0000-0000-4000-8000-00000000000d")
TZ = "America/Chicago"
MOCK_DAY = date(2026, 11, 14)          # the approved mock's Saturday
SLUG = "sample-0a1b2c3d4e"
SCHEMA = json.loads((_here / "sample_church_schema.json").read_text(encoding="utf-8"))["tables"]

_BUILDS: dict = {}


def built(today=MOCK_DAY, tz=TZ, biz=SAMPLE):
    key = (today, tz, biz)
    if key not in _BUILDS:
        _BUILDS[key] = d.build(today=today, tz=tz, business_id=biz, slug=SLUG)
    return _BUILDS[key]


def rows(out, table):
    return dict(out["tables"])[table]


def _dt(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _local(s, tz=TZ):
    return _dt(s).astimezone(ZoneInfo(tz))


# A spread of todays: the mock's Saturday, a Sunday, a Monday, a month's first
# day, New Year's Day, and a Wednesday in spring.
DAYS = (MOCK_DAY, date(2026, 11, 15), date(2026, 11, 16), date(2026, 12, 1), date(2027, 1, 1), date(2027, 3, 3))


# ─── Pure: determinism and the calendar ───────────────────────────────

def test_the_same_inputs_give_the_same_rows():
    a = d.build(today=MOCK_DAY, tz=TZ, business_id=SAMPLE, slug=SLUG)
    b = d.build(today=MOCK_DAY, tz=TZ, business_id=SAMPLE, slug=SLUG)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_each_sample_gets_its_own_ids_and_the_same_church():
    a, b = built(), built(biz=OTHER)
    ids_a = {r["id"] for _, rs in a["tables"] for r in rs if "id" in r}
    ids_b = {r["id"] for _, rs in b["tables"] for r in rs if "id" in r}
    assert not ids_a & ids_b
    assert a["story"]["last_sunday"] == b["story"]["last_sunday"]
    assert all(r["business_id"] == SAMPLE for _, rs in a["tables"] for r in rs)


def test_a_gift_is_a_function_of_its_own_day_never_of_today():
    """A weekly refresh keeps every gift it can (the audit log): two seeds a
    week apart share every gift dated in both windows."""
    a = {r["id"]: r for r in rows(built(MOCK_DAY), "invoices")}
    b = {r["id"]: r for r in rows(built(MOCK_DAY + timedelta(days=7)), "invoices")}
    both = MOCK_DAY - timedelta(days=d.GIFT_DAYS - 7)
    a_kept = {k for k, r in a.items() if r["paid_at"][:10] >= both.isoformat()}
    assert a_kept <= set(b), "a gift both windows hold was rewritten"
    assert len(set(b) - set(a)) < 120 and len(set(a) - set(b)) < 120
    assert {r["id"] for r in rows(built(MOCK_DAY), "contacts")} == \
        {r["id"] for r in rows(built(MOCK_DAY + timedelta(days=7)), "contacts")}


def test_dates_are_last_sunday_and_next_sunday():
    assert d.last_sunday(date(2026, 11, 14)) == date(2026, 11, 8)
    assert d.last_sunday(date(2026, 11, 15)) == date(2026, 11, 8)
    assert d.last_sunday(date(2026, 11, 16)) == date(2026, 11, 15)
    assert d.next_sunday(date(2026, 11, 14)) == date(2026, 11, 15)
    assert d.next_sunday(date(2026, 11, 15)) == date(2026, 11, 15)


WEEKDAY_OF = {title: wd for wd, _, title, *_ in d.WEEK_EVENTS}


@pytest.mark.parametrize("today", DAYS)
def test_every_date_is_relative_and_on_its_real_weekday(today):
    out = built(today)
    zone = ZoneInfo(TZ)
    for e in rows(out, "module_entries"):
        data = e["data"]
        day = date.fromisoformat(data["date"][:10])
        if data["title"] == "Sunday Worship":
            assert day.weekday() == 6 and data["_checkin_day"] == day.isoformat()
        elif data["title"] in WEEKDAY_OF:
            assert day.weekday() == WEEKDAY_OF[data["title"]]
        assert today - timedelta(days=7 * (d.SUNDAYS_BACK + 1)) <= day <= today + timedelta(days=40)
    for a in rows(out, "attendance"):
        assert _local(a["checked_in_at"]).weekday() == 6 and _local(a["checked_in_at"]).date() < today
    for k in rows(out, "child_checkins"):
        assert _local(k["checked_in_at"]).weekday() == 6
    for s in rows(out, "sermons"):
        assert date.fromisoformat(s["preached_on"]).weekday() == 6 and s["preached_on"] < today.isoformat()
    for g in rows(out, "invoices"):
        paid = _local(g["paid_at"])
        assert paid.date() < today and paid.date() >= today - timedelta(days=d.GIFT_DAYS)
        assert paid.date() == _dt(g["paid_at"]).date(), "the UTC day (what the app reads) is the church's day"
        if g["payment_method"] in ("cash", "check"):
            assert paid.weekday() == 6
    for p in rows(out, "worship_services"):
        assert _local(p["starts_at"]).weekday() == 6
    assert out["story"]["last_sunday"]["date"] == d.last_sunday(today).isoformat()
    for c in rows(out, "contacts"):
        assert _dt(c["created_at"]).date() <= today
        assert date.fromisoformat(c["birthdate"]) < today
    del zone


def test_the_church_clock_follows_the_tz():
    pac = built(tz="America/Los_Angeles")
    a = rows(pac, "attendance")[0]
    assert _local(a["checked_in_at"], "America/Los_Angeles").weekday() == 6
    assert rows(pac, "church_checkin_settings")[0]["timezone"] == "America/Los_Angeles"
    assert pac["settings"]["timezone"] == "America/Los_Angeles"


# ─── Fake contact data only ───────────────────────────────────────────

_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]+")
_PHONE = re.compile(r"^\+1\d{3}55501\d{2}$")


def _strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, str):
        yield x


def test_every_email_is_at_example_org_and_every_phone_is_555_01():
    out = built()
    everything = list(_strings(out["tables"])) + list(_strings(out["settings"])) + [out["digest"]]
    everything += list(_strings(d.load_fixture("site_config.json")))
    for s in everything:
        for m in _EMAIL.findall(s):
            assert m.endswith("@example.org"), m
    phones = [c["phone"] for c in rows(out, "contacts") if c["phone"]]
    phones += [p["phone"] for p in rows(out, "household_pickups") if p["phone"]]
    assert phones and all(_PHONE.match(p) for p in phones)
    assert len(set(c["phone"] for c in rows(out, "contacts") if c["phone"])) == \
        len([c for c in rows(out, "contacts") if c["phone"]])
    site_phone = re.sub(r"\D", "", d.load_fixture("site_config.json")["facts"]["contact"]["phone"])
    assert re.fullmatch(r"\d{3}55501\d{2}", site_phone)
    # Every +1 number anywhere is a fictional one.
    for s in everything:
        for m in re.findall(r"\+1\d{10}", s):
            assert _PHONE.match(m), m


def test_addresses_are_made_up():
    for c in rows(built(), "contacts"):
        a = (c["metadata"] or {}).get("address")
        if a:
            assert a["zip"] == "00000" and a["city"] == d.TOWN


def test_names_come_from_many_backgrounds_and_the_story_people_are_there():
    names = {c["name"] for c in rows(built(), "contacts")}
    for who in ("Denise Carter", "Luis Moreno", "Angela Brooks", "Samuel Okafor", "Priya Shah", "Kofi Mensah",
                "Jordan Daniels"):
        assert who in names
    surnames = Counter(n.split()[-1] for n in names)
    assert len(surnames) >= 40 and surnames.most_common(1)[0][1] <= 6


# ─── Volumes ──────────────────────────────────────────────────────────

def test_volumes_are_a_church_of_about_190():
    out = built()
    s = out["story"]
    assert 110 <= len(rows(out, "contacts")) <= 140
    assert 38 <= len(rows(out, "households")) <= 48
    kids = [c for c in rows(out, "children")]
    assert 35 <= len(kids) <= 60
    assert len(rows(out, "household_pickups")) >= 8
    assert 1500 <= len(rows(out, "invoices")) <= 2700
    assert s["giving"]["givers"] == 55
    assert 18000 <= s["giving"]["monthly_average"] <= 26000
    groups = [g for g in rows(out, "groups") if g["kind"] != "team"]
    teams = [g for g in rows(out, "groups") if g["kind"] == "team"]
    assert len(groups) == 9 and len(teams) == 4
    for name in ("Young Adults", "Comunidad en Español", "Parents of Little Ones", "Golden Years", "Youth",
                 "Men's Breakfast", "Women's Bible Study", "Prayer Team", "Wednesday Bible Study"):
        assert name in {g["name"] for g in groups}
    assert len(rows(out, "group_meetings")) >= 50
    assert len(rows(out, "church_pledges")) == d.PLEDGERS and len(rows(out, "church_campaigns")) == 1
    assert len(rows(out, "sermons")) >= 12 and len(rows(out, "sermon_series")) == 3
    assert len(rows(out, "church_posts")) >= 5 and len(rows(out, "devotionals")) == 1
    assert len([c for c in rows(out, "ministry_care_requests")]) >= 5
    assert {r["gift_fund"] for r in rows(out, "invoices")} == set(d.FUNDS)
    assert len(out["digest"]) < 32000          # well under ~8k tokens


def test_every_seeded_column_is_a_real_column_and_required_ones_are_filled():
    out = built()
    for table, rs in out["tables"]:
        cols, req = SCHEMA[table]["columns"], SCHEMA[table]["required"]
        for r in rs:
            assert set(r) <= set(cols), (table, sorted(set(r) - set(cols)))
            for c in req:
                assert r.get(c) is not None, (table, c)
            for c, v in r.items():
                kind = cols[c]
                if v is None:
                    continue
                if kind == "uuid":
                    assert re.fullmatch(r"[0-9a-f-]{36}", str(v)), (table, c, v)
                elif kind in ("integer", "smallint", "bigint"):
                    assert isinstance(v, int) and not isinstance(v, bool), (table, c, v)
                elif kind == "boolean":
                    assert isinstance(v, bool), (table, c, v)
                elif kind == "date":
                    date.fromisoformat(v)
                elif kind == "timestamp with time zone":
                    assert _dt(v).tzinfo is not None, (table, c, v)
                elif kind == "time without time zone":
                    assert re.fullmatch(r"\d{2}:\d{2}", v), (table, c, v)
                elif kind.endswith("[]"):
                    assert isinstance(v, list), (table, c, v)


PK = {"household_adults": ("household_id", "contact_id"), "group_members": ("group_id", "contact_id"),
      "group_meeting_attendance": ("meeting_id", "contact_id"), "serve_teams": ("group_id",),
      "serve_trained": ("position_id", "contact_id"), "church_checkin_settings": ("business_id",),
      "church_role_settings": ("business_id",), "church_shepherd_settings": ("business_id",),
      "church_shepherds": ("household_id",), "church_shepherd_notices": ("business_id", "key"),
      "child_care_notes": ("child_id",), "church_help_settings": ("business_id",),
      "church_board_attendance": ("meeting_id", "member_id")}
UNIQUE = {"attendance": ("entry_id", "contact_id"), "attendance_headcounts": ("entry_id", "area"),
          "child_checkins": ("entry_id", "child_id"), "giving_counts": ("service_id", "service_date"),
          "church_pledges": ("campaign_id", "contact_id"), "group_meetings": ("group_id", "met_on"),
          "serve_assignments": ("service_id", "position_id", "slot"), "custom_modules": ("slug",),
          "church_role_defs": ("key",), "children": ("contact_id",), "invoices": ("invoice_number",),
          "church_follow_ups": ("source_event",)}


def test_every_key_and_unique_index_holds():
    out = built()
    for table, rs in out["tables"]:
        for cols in [PK.get(table, ("id",))] + ([UNIQUE[table]] if table in UNIQUE else []):
            keys = [tuple(r.get(c) for c in cols) for r in rs]
            assert len(keys) == len(set(keys)), (table, cols, Counter(keys).most_common(2))
    days = [e["data"].get("_checkin_day") for e in rows(out, "module_entries") if e["data"].get("_checkin_day")]
    assert len(days) == len(set(days))


def test_references_point_at_rows_the_seed_makes():
    out = built()
    ids = {t: {r.get("id") for r in rs} for t, rs in out["tables"]}
    contacts = ids["contacts"]
    for table, rs in out["tables"]:
        for r in rs:
            for c in ("contact_id", "leader_contact_id", "shepherd_contact_id", "dropped_off_by", "posted_by",
                      "related_contact_id"):
                if r.get(c):
                    assert r[c] in contacts, (table, c)
    entries = ids["module_entries"]
    assert all(r["entry_id"] in entries for r in rows(out, "attendance") + rows(out, "child_checkins"))
    counts = ids["giving_counts"]
    assert all(r["giving_count_id"] in counts for r in rows(out, "invoices") if r["giving_count_id"])
    mods = ids["custom_modules"]
    assert all(e["module_id"] in mods for e in rows(out, "module_entries"))
    kids = {k["id"]: k for k in rows(out, "children")}
    for k in rows(out, "child_checkins"):
        assert kids[k["child_id"]]["household_id"] == k["household_id"]
        adults = {a["contact_id"] for a in rows(out, "household_adults") if a["household_id"] == k["household_id"]}
        assert k["dropped_off_by"] in adults
        assert re.fullmatch(r"[A-Z0-9]{4}", k["code"])


def test_json_columns_have_the_shape_their_table_checks_ask_for():
    """The CHECKs in the migrations (jsonb_typeof ...), which a fake never sees."""
    out = built()
    want = {("devotionals", "audio"): dict, ("devotionals", "days"): list, ("devotionals", "practices"): list,
            ("worship_songs", "times_sung"): dict, ("worship_songs", "sections"): list,
            ("worship_songs", "arrangements"): list, ("worship_services", "items"): list,
            ("church_register_entries", "people"): list, ("church_board_items", "documents"): list,
            ("church_follow_ups", "answers"): list, ("church_follow_ups", "steps"): list,
            ("church_posts", "attach"): list, ("ministry_care_requests", "submission"): dict,
            ("module_entries", "data"): dict, ("custom_modules", "archetype_params"): dict,
            ("business_sites", "site_config"): dict}
    for (table, col), kind in want.items():
        for r in rows(out, table):
            assert isinstance(r[col], kind), (table, col)
    for r in rows(out, "church_register_entries"):
        assert 1 <= len(r["people"]) <= 12
    for r in rows(out, "devotionals"):
        assert len(r["practices"]) <= 8 and all(re.fullmatch(r"[a-z0-9]{6,16}", p["key"]) for p in r["practices"])
    for r in rows(out, "worship_songs"):
        assert r["song_key"] is None or re.fullmatch(r"[A-G](#|b)?m?", r["song_key"])
    for r in rows(out, "giving_counts"):
        assert len(r["counters"]) <= 4
    for r in rows(out, "church_role_defs"):
        assert len(r["handles"]) <= 12 and len(r["sees"]) <= 8 and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", r["key"])


def test_the_order_of_service_is_one_the_app_accepts():
    import worship_show
    for p in rows(built(), "worship_services"):
        assert worship_show.clean_items(p["items"])
        assert any(i["kind"] == "scripture" and i["ref"] for i in p["items"])


# ─── The story, computed the way the app computes it ──────────────────

def _now(today=MOCK_DAY):
    return datetime.combine(today, time(12, 0), tzinfo=ZoneInfo(TZ))


def _occasions(out):
    occ = []
    for e in rows(out, "module_entries"):
        raw = e["data"]["date"]
        at = datetime.fromisoformat(raw).replace(tzinfo=ZoneInfo(TZ))
        occ.append({"id": e["id"], "data": e["data"], "at": at})
    return sorted(occ, key=lambda o: o["at"])


def _service_counts(out, now):
    """churchData.serviceCounts + mainGatherings (the Sundays)."""
    att, heads = rows(out, "attendance"), rows(out, "attendance_headcounts")
    end = datetime.combine(now.date() + timedelta(days=1), time(0), tzinfo=now.tzinfo)
    out_counts = []
    for o in _occasions(out):
        if o["at"] >= end:
            continue
        named = [r for r in att if r["entry_id"] == o["id"]]
        counted = [h for h in heads if h["entry_id"] == o["id"]]
        total = max(sum(h["count"] for h in counted), len(named))
        if not total:
            continue
        online = min(total, max(sum(h["count"] for h in counted if h["area"].strip().lower() == "online"),
                                sum(1 for r in named if r["method"] == "online")))
        out_counts.append({"id": o["id"], "date": o["at"].date(), "sunday": o["at"].weekday() == 6,
                           "in_person": total - online, "online": online,
                           "first": sum(1 for r in named if r["first_time"])})
    sundays = [c for c in out_counts if c["sunday"]]
    return sundays if len(sundays) >= 2 else out_counts


def _key(r):
    return r["contact_id"] or "name:" + r["name"].strip().lower()


def _missed_gatherings(out, main_ids):
    att = rows(out, "attendance")
    with_names = [i for i in main_ids if any(r["entry_id"] == i for r in att)]
    if len(with_names) < 5:
        return set()
    last3, before = set(with_names[-3:]), set(with_names[-11:-3])
    seen = defaultdict(lambda: [0, 0])
    for r in att:
        if r["entry_id"] in last3:
            seen[_key(r)][1] += 1
        elif r["entry_id"] in before:
            seen[_key(r)][0] += 1
    return {k for k, (b, recent) in seen.items() if b >= 3 and recent == 0}


def _missed_groups(out, now):
    groups = [g for g in rows(out, "groups") if g["active"]]
    meetings = rows(out, "group_meetings")
    here = {(a["meeting_id"], a["contact_id"]) for a in rows(out, "group_meeting_attendance")}
    out_ids = set()
    for g in groups:
        ms = sorted([m for m in meetings if m["group_id"] == g["id"]
                     and m["met_on"] >= (now.date() - timedelta(days=400)).isoformat()],
                    key=lambda m: m["met_on"], reverse=True)[:3]
        if len(ms) < 3:
            continue
        oldest = min(m["met_on"] for m in ms)
        for mem in rows(out, "group_members"):
            if mem["group_id"] != g["id"] or mem["joined_on"] > oldest:
                continue
            if not any((m["id"], mem["contact_id"]) in here for m in ms):
                out_ids.add(mem["contact_id"])
    return out_ids


def _visitor_flow(out, now, days=90):
    att = sorted(rows(out, "attendance"), key=lambda r: r["checked_in_at"])
    since = now - timedelta(days=days)
    firsts = {}
    for r in att:
        if r["first_time"] and _dt(r["checked_in_at"]) >= since and _key(r) not in firsts:
            firsts[_key(r)] = r
    active = {g["id"] for g in rows(out, "groups") if g["active"]}
    grouped = {m["contact_id"] for m in rows(out, "group_members") if m["group_id"] in active}
    back = sum(1 for k, f in firsts.items()
               if any(_key(r) == k and r["entry_id"] != f["entry_id"] and r["checked_in_at"] > f["checked_in_at"]
                      for r in att))
    joined = sum(1 for f in firsts.values() if f["contact_id"] in grouped)
    return len(firsts), back, joined


def _lead_occasion(out, now):
    today0 = datetime.combine(now.date(), time(0), tzinfo=now.tzinfo)
    upcoming = [o for o in _occasions(out) if o["at"] >= today0]
    soon = [o for o in upcoming if o["at"] < today0 + timedelta(days=7)]
    return next((o for o in soon if o["at"].weekday() == 6), upcoming[0] if upcoming else None)


def _role_fills(out, occ):
    mod = next(m for m in rows(out, "custom_modules") if m["archetype"] == "event_roster")
    roles = occ["data"]["_roles"] if isinstance(occ["data"].get("_roles"), list) else mod["archetype_params"]["roles"]
    fills = []
    for r in roles:
        yes = sum(1 for s in occ["data"]["signups"] if s.get("role") == r["id"] and s.get("status", "yes") == "yes")
        fills.append((r["label"], min(yes, r["needed"]), r["needed"]))
    return fills


def _unreached_guests(out, now):
    """church_reads.first_time_guests: first visits in 30 days nobody has reached since."""
    cutoff = now.astimezone(timezone.utc) - timedelta(days=30)
    firsts = {}
    for r in sorted(rows(out, "attendance"), key=lambda r: r["checked_in_at"]):
        if r["first_time"] and _dt(r["checked_in_at"]) >= cutoff and r["contact_id"] not in firsts:
            firsts[r["contact_id"]] = _dt(r["checked_in_at"])
    reach = ("activity_logged", "email_sent", "sms_sent", "agent_message_sent", "journey_sent")
    reached = defaultdict(list)
    for e in rows(out, "events"):
        if e["event_type"] in reach:
            reached[e["contact_id"]].append(_dt(e["created_at"]))
    status = {c["id"]: c for c in rows(out, "contacts")}
    return sorted(status[cid]["name"] for cid, at in firsts.items()
                  if status[cid]["status"] != "inactive" and not any(t >= at for t in reached[cid]))


@pytest.mark.parametrize("today", DAYS)
def test_last_sunday_is_186_and_the_eight_sundays_are_the_mock(today):
    out = built(today)
    counts = _service_counts(out, _now(today))
    last8 = counts[-8:]
    assert [(c["in_person"], c["online"]) for c in last8] == list(d.STORY_SUNDAYS)
    last = counts[-1]
    assert last["date"] == d.last_sunday(today)
    assert last["in_person"] + last["online"] == 186 and last["in_person"] == 152 and last["online"] == 34
    assert (last["in_person"] + last["online"]) - (counts[-2]["in_person"] + counts[-2]["online"]) == 12
    assert last["first"] == 2


@pytest.mark.parametrize("today", DAYS)
def test_the_way_in_is_8_4_2(today):
    assert _visitor_flow(built(today), _now(today)) == (8, 4, 2)


@pytest.mark.parametrize("today", DAYS)
def test_exactly_the_four_regulars_have_missed_the_last_three_sundays(today):
    out = built(today)
    now = _now(today)
    main = [c["id"] for c in _service_counts(out, now)][-11:]
    missing = _missed_gatherings(out, main) | _missed_groups(out, now)
    names = {c["id"]: c["name"] for c in rows(out, "contacts")}
    assert {names[k] for k in missing} == {"Denise Carter", "Luis Moreno", "Angela Brooks", "Samuel Okafor"}
    last = {}
    for r in rows(out, "attendance"):
        if names.get(r["contact_id"]) in ("Denise Carter", "Luis Moreno", "Angela Brooks", "Samuel Okafor"):
            last[names[r["contact_id"]]] = max(last.get(names[r["contact_id"]], ""), r["checked_in_at"][:10])
    ls = d.last_sunday(today)
    assert _local(max(r["checked_in_at"] for r in rows(out, "attendance")
                      if names.get(r["contact_id"]) == "Denise Carter")).date() == ls - timedelta(days=21)
    assert _local(max(r["checked_in_at"] for r in rows(out, "attendance")
                      if names.get(r["contact_id"]) == "Angela Brooks")).date() == ls - timedelta(days=28)
    # Denise greets and Luis runs sound: they are on those teams.
    teams = {g["id"]: g["name"] for g in rows(out, "groups") if g["kind"] == "team"}
    on = {(names[m["contact_id"]], teams[m["group_id"]]) for m in rows(out, "group_members") if m["group_id"] in teams}
    assert ("Denise Carter", "Greeters") in on and ("Luis Moreno", "Sound and slides") in on
    # The shepherding signals agree with the attendance.
    homes = {h["id"] for h in rows(out, "church_shepherd_signals")}
    assert len(homes) == 4


@pytest.mark.parametrize("today", DAYS)
def test_sunday_serving_is_15_of_18_with_three_open(today):
    out = built(today)
    lead = _lead_occasion(out, _now(today))
    assert lead["at"].date() == d.next_sunday(today) and lead["at"].weekday() == 6
    fills = _role_fills(out, lead)
    assert sum(f for _, f, _ in fills) == 15 and sum(n for _, _, n in fills) == 18
    assert {label: (f, n) for label, f, n in fills} == {
        "Worship team": (5, 5), "Kids rooms": (4, 6), "Greeters": (4, 4), "Sound and slides": (2, 3)}
    # ChurchSavvy's roster for the same Sunday says the same.
    plan = next(p for p in rows(out, "worship_services") if _local(p["starts_at"]).date() == d.next_sunday(today))
    filled = [a for a in rows(out, "serve_assignments") if a["service_id"] == plan["id"]]
    assert len(filled) == 15 and all(a["status"] == "yes" and a["contact_id"] for a in filled)
    needed = sum(p["needed"] for p in rows(out, "serve_positions"))
    assert needed == 18


@pytest.mark.parametrize("today", DAYS)
def test_this_weeks_events_fill_the_seven_days(today):
    out = built(today)
    now = _now(today)
    today0 = datetime.combine(today, time(0), tzinfo=ZoneInfo(TZ))
    week = [o for o in _occasions(out) if today0 <= o["at"] < today0 + timedelta(days=7)]
    titles = {o["data"]["title"] for o in week}
    assert {"Sunday Worship", "Deacons", "Bible study", "Worship rehearsal", "Youth night", "Food pantry"} <= titles
    bible = next(o for o in week if o["data"]["title"] == "Bible study")
    assert len(bible["data"]["signups"]) == 24
    del now


@pytest.mark.parametrize("today", DAYS)
def test_two_first_time_guests_have_not_been_reached(today):
    out = built(today)
    assert _unreached_guests(out, _now(today)) == ["Kofi Mensah", "Priya Shah"]


@pytest.mark.parametrize("today", DAYS)
def test_four_things_need_you(today):
    """churchHomeModel's list: care, Sunday's open places, guests, messages;
    no approvals, no tasks due, no missing offering, a service planned."""
    out = built(today)
    now = _now(today).astimezone(timezone.utc)
    care = [r for r in rows(out, "ministry_care_requests")
            if _dt(r["created_at"]) >= now - timedelta(days=90) and (r["status"] or "new") == "new"]
    oldest = max((now - _dt(r["created_at"])).days for r in care)
    unread = [n for n in rows(out, "chief_notifications") if n["status"] == "unread" and n["type"] in ("info", "escalation")]
    lead = _lead_occasion(out, _now(today))
    open_places = sum(n - f for _, f, n in _role_fills(out, lead))
    guests = _unreached_guests(out, _now(today))
    needs = [len(care) > 0, open_places > 0, len(guests) > 0, len(unread) > 0]
    assert needs == [True, True, True, True]
    assert len(care) == 3 and oldest >= 2 and len(unread) == 5 and open_places == 3
    # Nothing else: no task due, for the whole week until the next refresh.
    for k in range(7):
        day = (today + timedelta(days=k)).isoformat()
        assert not [t for t in rows(out, "tasks") if t["status"] != "done" and t["due_date"] <= day]
    assert "agent_queue" not in dict(out["tables"])
    # Last Sunday's offering is recorded (no "isn't recorded yet").
    ls = d.last_sunday(today).isoformat()
    manual = {g["paid_at"][:10] for g in rows(out, "invoices") if g["invoice_number"].startswith("GIVE-manual-")}
    assert ls in manual


@pytest.mark.parametrize("today", DAYS)
def test_kids_last_sunday_38_across_three_rooms(today):
    out = built(today)
    entry = next(e["id"] for e in rows(out, "module_entries")
                 if e["data"].get("_checkin_day") == d.last_sunday(today).isoformat())
    last = [k for k in rows(out, "child_checkins") if k["entry_id"] == entry]
    assert len(last) == 38
    assert {k["room"] for k in last} == {"Nursery", "Preschool", "Elementary"}
    assert len({k["entry_id"] for k in rows(out, "child_checkins")}) == 8


def test_giving_by_fund_looks_like_the_mock():
    g = built()["story"]["giving"]
    f = g["by_fund"]
    assert f["General"] > f["Building"] > f["Missions"] > 0 and f["Benevolence"] > 0
    assert 0.6 <= f["General"] / g["this_month"] <= 0.85
    assert g["last_month"] > g["this_month"] > 0
    assert g["gifts_this_month"] >= 60


def test_every_active_member_has_a_family_and_most_families_a_shepherd():
    out = built()
    in_home = {a["contact_id"] for a in rows(out, "household_adults")} | \
        {c["contact_id"] for c in rows(out, "children")}
    for c in rows(out, "contacts"):
        if c["status"] == "active":
            assert c["id"] in in_home, c["name"]
    shepherds = {s["shepherd_contact_id"] for s in rows(out, "church_shepherds")}
    holders = {r["contact_id"]: r["role"] for r in rows(out, "church_leader_roles")}
    defs = {r["key"]: r for r in rows(out, "church_role_defs")}
    for sid in shepherds:
        role = defs[holders[sid]]
        assert role["job"] in ("senior", "pastoral") and role["can_shepherd"] is True
    s = out["story"]["shepherds"]
    assert 0.7 <= s["placed"] / s["families"] < 1


def test_the_digest_tells_the_story():
    text = built()["digest"]
    for bit in ("186 total", "152 in the room", "34 online", "8 first visits, 4 came back, 2 joined",
                "Priya Shah, Kofi Mensah", "Denise Carter (greeting team", "Luis Moreno (sound booth",
                "Angela Brooks", "Samuel Okafor", "15 of 18", "General $", "Missions $", "Building $",
                "Benevolence $", "Young Adults", "Comunidad en Español", "3 new prayer requests"):
        assert bit in text, bit


# ─── Nothing is sent ──────────────────────────────────────────────────

def test_every_send_switch_is_off():
    import member_push
    s = built()["settings"]
    notes = s["member_portal"]["notifications"]
    assert set(notes) == set(member_push.KIND_KEYS) and not any(notes.values())
    assert s["news"]["celebrate"] != "all" and s["news"]["ask_members"] is False and s["news"]["reach_rest"] is False
    assert s["churchsavvy"]["planning_email"] is False
    assert s["feed2"]["contribute"] is False
    assert s["autopilot"]["overall"] == "manual" and s["automations_paused"] is True
    assert s["messaging"]["enabled"] is False


def test_no_engine_rows_ever():
    out = built()
    written = {t for t, rs in out["tables"] if rs}
    banned = {"chief_scheduled_actions", "campaign_sends", "campaigns", "devotional_texts",
              "member_push_subscriptions", "member_push_sends", "journey_sends", "agent_queue", "agent_runs",
              "agent_assignments", "connected_agents", "member_celebrations", "business_users", "church_mail"}
    assert not written & banned
    assert not {t for t in d.TABLES if t.startswith(("sms_", "agent_", "journey"))}
    assert not set(d.TABLES) & set(ss.FORBIDDEN_TABLES)


def test_every_row_a_sweep_would_pick_up_is_stamped_as_done():
    import chief_agent
    out = built()
    stamps = ("notified_at", "nudged_at", "leader_told_at", "week_sent_at", "day_sent_at", "morning_sent_at",
              "swap_told_at")
    assert all(all(a[s] for s in stamps) for a in rows(out, "serve_assignments"))
    for t in rows(out, "tasks"):
        assert t["leader_told_at"] and t["late_told_at"] and t["seat_told_at"] and t["seat_late_told_at"]
        assert t["raised_at"] is None and t["check_key"] is None
    for p in rows(out, "church_posts"):
        assert p["alerted_at"] and p["reached_at"] and p["important"] is False and p["publish_at"] is None
    for c in rows(out, "ministry_care_requests"):
        assert c["leader_contact_id"] is None
    for f in rows(out, "church_follow_ups"):
        assert f["leader_told_at"] and f["late_level"] == 3 and f["source_event"].startswith("first-visit:")
    for g in rows(out, "groups"):
        assert g["study_on"] is False and g["chat_on"] is False
    for e in rows(out, "events"):
        assert e["agent_handled_at"] and e["event_type"] not in chief_agent.AGENT_EVENT_TYPES
    for s in rows(out, "sermons"):
        assert s["questions"].strip()
    for c in rows(out, "contacts"):
        assert c["first_response_at"] and c["last_interaction"] is None
    for r in rows(out, "church_leader_roles"):
        assert r["term_ends_at"] is None
    # No first check-in is under a day old at seed time (the first-visit sweep).
    for a in rows(out, "attendance"):
        if a["first_time"]:
            assert _dt(a["checked_in_at"]) < datetime.combine(MOCK_DAY, time(0), tzinfo=ZoneInfo(TZ))
    # The shepherding sweep's notes say the coming Mondays are already sent.
    keys = {n["key"] for n in rows(out, "church_shepherd_notices")}
    monday = MOCK_DAY + timedelta(days=(0 - MOCK_DAY.weekday()) % 7)
    assert f"monday-{monday.isoformat()}" in keys and f"monday-{(monday + timedelta(days=7)).isoformat()}" in keys
    assert all(f"care-{f['id']}" in keys for f in rows(out, "church_follow_ups"))
    # Stations can't be paired; giving counts never collect online gifts.
    assert all(s["token_hash"] is None and s["pair_code_hash"] is None for s in rows(out, "checkin_stations"))
    assert not any(c["collects_online"] for c in rows(out, "giving_counts"))


def test_the_first_visit_sweep_finds_its_follow_up_already_made():
    """church_first_visit keys a family by its household when it has one."""
    out = built()
    homes = defaultdict(list)
    for a in rows(out, "household_adults"):
        homes[a["contact_id"]].append(a["household_id"])
    events = {f["source_event"] for f in rows(out, "church_follow_ups")}
    for a in rows(out, "attendance"):
        if a["first_time"]:
            key = f"h:{homes[a['contact_id']][0]}" if homes.get(a["contact_id"]) else f"c:{a['contact_id']}"
            assert f"first-visit:{key}" in events


# ─── The empty-room check ─────────────────────────────────────────────

def test_no_church_room_is_left_empty():
    out = built()
    have = {t: len(rs) for t, rs in out["tables"]}
    empty = {room: [t for t in tables if not have.get(t)] for room, tables in d.ROOM_TABLES.items()}
    empty = {room: ts for room, ts in empty.items() if ts}
    assert not empty, f"rooms left empty by the seed: {empty}"
    for room, why in d.EMPTY_BY_DESIGN.items():
        assert room not in d.ROOM_TABLES and why


# ─── The website ──────────────────────────────────────────────────────

def test_the_site_renders_whole_with_no_photos(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "STATIC", tmp_path)
    html = ss.site_html(d.site_config(SLUG), MOCK_DAY, TZ)
    assert '<meta name="robots" content="noindex' in html and "made-up sample church" in html.lower()
    assert "<img" not in html and "Grace Street" in html and "When we gather" in html
    assert "Unsplash" not in html


def test_a_photo_on_disk_shows_with_its_credit(monkeypatch, tmp_path):
    (tmp_path / "hero.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "kids.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(ss, "STATIC", tmp_path)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.test")
    html = ss.site_html(d.site_config(SLUG), MOCK_DAY, TZ)
    assert "https://api.example.test/assets/sample-church/hero.jpg" in html
    assert "Photos by Rewired Digital and Stephanie Hernandez on Unsplash." in html


def test_the_fixture_lists_licensed_photos_with_credits():
    photos = d.load_fixture("site_config.json")["photos"]
    assert 8 <= len(photos) <= 12
    for p in photos:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", p["name"])
        assert p["page"] == f"https://unsplash.com/photos/{p['unsplash_id']}"
        assert p["photographer"] and p["profile"].startswith("https://unsplash.com/@") and p["alt"]


def test_the_site_row_has_a_sample_slug_and_never_grace_street():
    site = rows(built(), "business_sites")[0]
    assert site["slug"] == SLUG and site["site_config"]["noindex"] is True
    assert "grace-street" not in site["slug"]
    assert re.fullmatch(r"sample-[0-9a-f]{10}", SLUG)


def test_the_photo_route_stays_inside_its_folder():
    import public_site
    assert public_site._sample_asset_path("../secret.jpg") is None
    assert public_site._sample_asset_path("hero.png") is None
    assert public_site._sample_asset_path("Hero.jpg") is None
    assert public_site._sample_asset_path("not-there.jpg") is None


# ─── The seed against a fake database ─────────────────────────────────

class FakeDB:
    """Enough PostgREST for the seed: eq / is / in filters, JSON-path filters
    (settings->a->>b), bulk inserts that refuse mixed keys (PGRST102) and a
    duplicate key the way the database does, upserts, and a PATCH that is
    atomic like a row lock (two claims: one row back, the other none)."""

    def __init__(self):
        self.t = defaultdict(list)
        self.lock = threading.RLock()
        self.deletes, self.posts, self.patches = [], [], []
        self.err = None

    @staticmethod
    def _value(row, col):
        if "->" not in col:
            return row.get(col)
        parts = re.split(r"->>?", col)
        v = row.get(parts[0])
        for p in parts[1:]:
            v = v.get(p) if isinstance(v, dict) else None
        return v

    def _parse(self, path):
        table, _, q = path.lstrip("/").partition("?")
        cons, params = [], {}
        for part in q.split("&") if q else []:
            col, _, rest = part.partition("=")
            if col in ("select", "limit", "order", "on_conflict"):
                params[col] = rest
                continue
            op, _, val = rest.partition(".")
            cons.append((col, op, unquote(val)))
        return table, cons, params

    def _one(self, v, op, val):
        if op == "not":
            sub, _, rest = val.partition(".")
            return not self._one(v, sub, rest)
        if op == "eq":
            return str(v) == val or (isinstance(v, bool) and str(v).lower() == val)
        if op == "is":
            return (val == "true" and v is True) or (val == "null" and v is None) or (val == "false" and v is False)
        if op == "in":
            return str(v) in [unquote(x) for x in val.strip("()").split(",")]
        if op in ("gt", "lt", "gte", "lte"):
            if v is None:
                return False
            return {"gt": str(v) > val, "lt": str(v) < val, "gte": str(v) >= val, "lte": str(v) <= val}[op]
        return True                      # or=(...) trees and the like: not modelled, they match

    def _ok(self, row, cons):
        return all(self._one(self._value(row, col), op, val) for col, op, val in cons)

    def get(self, path, *, redact=False):
        table, cons, _ = self._parse(path)
        with self.lock:
            return [json.loads(json.dumps(r)) for r in self.t[table] if self._ok(r, cons)]

    def get_all(self, path, *, key="id", strict=False, redact=False):
        return sorted(self.get(path), key=lambda r: str(r.get(key)))

    def post(self, path, body, prefer="return=representation", *, redact=False):
        table, _, params = self._parse(path)
        bodies = body if isinstance(body, list) else [body]
        with self.lock:
            self.posts.append(table)
            if len({tuple(sorted(b)) for b in bodies}) > 1:
                self.err = {"status": 400, "code": "PGRST102", "message": "All object keys must match"}
                return None
            pk = PK.get(table, ("id",))
            have = {tuple(r.get(c) for c in pk): r for r in self.t[table]}
            upsert = "merge-duplicates" in (prefer or "")
            new = []
            for b in bodies:
                k = tuple(b.get(c) for c in pk)
                if k in have and not upsert:
                    self.err = {"status": 409, "code": "23505", "message": "duplicate key"}
                    return None
            for b in bodies:
                k = tuple(b.get(c) for c in pk)
                if k in have:
                    have[k].update(json.loads(json.dumps(b)))
                else:
                    row = json.loads(json.dumps(b))
                    self.t[table].append(row)
                    have[k] = row
                new.append(dict(b))
            self.err = None
            return new

    def patch(self, path, body):
        table, cons, _ = self._parse(path)
        with self.lock:
            self.patches.append(path)
            hit = [r for r in self.t[table] if self._ok(r, cons)]
            for r in hit:
                r.update(json.loads(json.dumps(body)))
            return [dict(r) for r in hit]

    def delete(self, path):
        table, cons, _ = self._parse(path)
        with self.lock:
            self.deletes.append(path)
            self.t[table] = [r for r in self.t[table] if not self._ok(r, cons)]
            return True

    def last_error(self):
        return self.err


def _sample_row(**marker):
    m = {"version": sc.SEED_VERSION, "status": "pending", "created_at": "2026-11-14T15:00:00+00:00", **marker}
    return {"id": SAMPLE, "owner_id": OWNER, "name": d.NAME, "type": "church", "is_active": False,
            "is_sample": True, "sample_of": HOME,
            "settings": {"sample_church": m, "availability": {"timezone": TZ}, "practitioner_name": "Ana"}}


SEED_NOW = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)      # noon in Chicago, the mock's day


@pytest.fixture
def db(monkeypatch, tmp_path):
    fb = FakeDB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", fb.get_all)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fb.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setattr(sb_clients, "last_error", fb.last_error)
    monkeypatch.setattr(ss, "STATIC", tmp_path)
    monkeypatch.setattr(ss, "_now", lambda: SEED_NOW)
    monkeypatch.setenv("SAMPLE_CHURCH_SEED", "sync")
    fb.t["businesses"] += [_sample_row(), {"id": HOME, "owner_id": OWNER, "name": "First Church", "type": "church",
                                           "is_sample": False, "sample_of": None, "settings": {}}]
    # Another church's rows, which no seed may ever touch.
    for table in ("contacts", "invoices", "attendance", "groups", "business_sites"):
        fb.t[table].append({"id": f"keep-{table}", "business_id": HOME})
        fb.t[table].append({"id": f"keep-other-{table}", "business_id": OTHER})
    return fb


def _marker(fb):
    return next(r for r in fb.t["businesses"] if r["id"] == SAMPLE)["settings"]["sample_church"]


def _mine(fb, table):
    return [r for r in fb.t[table] if r.get("business_id") == SAMPLE]


def test_the_seed_writes_the_church_and_marks_it_ready(db):
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "ready"
    m = _marker(db)
    assert m["status"] == "ready" and m["version"] == sc.SEED_VERSION and m["digest"]
    assert re.fullmatch(r"sample-[0-9a-f]{10}", m["slug"]) and m["tz"] == TZ
    assert m["anchor"] == ss.anchor(MOCK_DAY)
    want = built()
    for table, rs in want["tables"]:
        assert len(_mine(db, table)) == len(rs), table
    s = next(r for r in db.t["businesses"] if r["id"] == SAMPLE)["settings"]
    assert s["member_portal"]["enabled"] is True and s["giving"]["funds"] == list(d.FUNDS)
    assert s["practitioner_name"] == "Ana"                    # BE-1's, kept
    site = _mine(db, "business_sites")[0]
    assert site["html_content"].startswith("<!doctype html>") and site["slug"] == m["slug"]
    assert sc.ready(next(r for r in db.t["businesses"] if r["id"] == SAMPLE))


def test_a_seeded_sample_is_not_due_and_provision_reads_nothing(db):
    ss.run_seed(_sample_row(), now=SEED_NOW)
    row = next(r for r in db.t["businesses"] if r["id"] == SAMPLE)
    before = len(db.posts) + len(db.patches) + len(db.deletes)
    assert ss.due(row, SEED_NOW + timedelta(hours=2)) is None
    assert ss.provision(row) is None
    assert len(db.posts) + len(db.patches) + len(db.deletes) == before


def test_two_loads_at_once_make_one_seed(db, monkeypatch):
    gate = threading.Barrier(2, timeout=10)
    real = ss.claim

    def racing_claim(row, run, now=None):
        gate.wait()                     # both read "pending" before either claims
        return real(row, run, now)

    monkeypatch.setattr(ss, "claim", racing_claim)
    got = [None, None]

    def go(i):
        got[i] = ss.run_seed(_sample_row(), now=SEED_NOW)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(got) == ["ready", "taken"]
    assert len(_mine(db, "contacts")) == len(rows(built(), "contacts"))
    assert len(_mine(db, "invoices")) == len(rows(built(), "invoices"))


def test_provision_in_the_background_seeds_once(db, monkeypatch):
    monkeypatch.setenv("SAMPLE_CHURCH_SEED", "on")
    row = _sample_row()
    assert ss.provision(row) == "started"
    assert ss.provision(row) in ("running", None)          # the same process never starts a second
    for _ in range(600):
        if _marker(db)["status"] == "ready":
            break
        threading.Event().wait(0.05)
    assert _marker(db)["status"] == "ready"
    assert len(_mine(db, "invoices")) == len(rows(built(), "invoices"))


def test_off_never_seeds(db, monkeypatch):
    monkeypatch.setenv("SAMPLE_CHURCH_SEED", "off")
    assert ss.provision(_sample_row()) is None
    assert _marker(db)["status"] == "pending" and not db.posts


def test_ensure_hands_a_due_sample_to_the_seed(db, monkeypatch):
    monkeypatch.setattr(sc, "_columns_ready", lambda: True)
    home = {"id": HOME, "owner_id": OWNER, "name": "First Church", "type": "church", "is_sample": False,
            "settings": {}}
    sc._reset_for_tests()
    got = sc.ensure(home)
    assert got and got["id"] == SAMPLE
    assert _marker(db)["status"] == "ready"


@pytest.mark.parametrize("marker, why", [
    ({"status": "pending"}, "pending"),
    ({"status": "seeding", "run": "r1", "claimed_at": (SEED_NOW - timedelta(minutes=11)).isoformat()}, "stale_claim"),
    ({"status": "seeding", "run": "r1", "claimed_at": (SEED_NOW - timedelta(minutes=2)).isoformat()}, None),
    ({"status": "failed", "run": "r1", "attempts": 1, "failed_at": (SEED_NOW - timedelta(minutes=3)).isoformat()}, "retry"),
    ({"status": "failed", "run": "r1", "attempts": 3, "failed_at": (SEED_NOW - timedelta(minutes=3)).isoformat()}, None),
    ({"status": "ready", "run": "r1", "seeded_at": (SEED_NOW - timedelta(days=1)).isoformat(), "tz": TZ,
      "anchor": "2026-11-08/2026-11"}, None),
    ({"status": "ready", "run": "r1", "seeded_at": (SEED_NOW - timedelta(days=7)).isoformat(), "tz": TZ}, "age"),
    ({"status": "ready", "run": "r1", "seeded_at": (SEED_NOW - timedelta(days=1)).isoformat(), "tz": TZ,
      "anchor": "2026-11-01/2026-11"}, "week"),
    ({"status": "ready", "run": "r1", "seeded_at": (SEED_NOW - timedelta(days=1)).isoformat(), "tz": TZ,
      "anchor": "2026-11-08/2026-10"}, "week"),
    ({"status": "ending"}, None),
])
def test_when_a_sample_is_due(marker, why):
    assert ss.due(_sample_row(**marker), SEED_NOW) == why


def test_a_new_seed_version_re_seeds(db, monkeypatch):
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "ready"
    monkeypatch.setattr(sc, "SEED_VERSION", sc.SEED_VERSION + 1)
    row = next(r for r in db.t["businesses"] if r["id"] == SAMPLE)
    assert ss.due(row, SEED_NOW) == "version"
    assert ss.run_seed(row, now=SEED_NOW) == "ready"
    assert _marker(db)["version"] == sc.SEED_VERSION
    assert len(_mine(db, "attendance")) == len(rows(built(), "attendance"))


def test_a_week_later_re_seeds_in_place_and_keeps_the_gifts(db, monkeypatch):
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "ready"
    first = {r["id"] for r in _mine(db, "invoices")}
    later = SEED_NOW + timedelta(days=7)
    monkeypatch.setattr(ss, "_now", lambda: later)
    row = next(r for r in db.t["businesses"] if r["id"] == SAMPLE)
    assert ss.due(row, later) in ("age", "week")
    deletes_before = len(db.deletes)
    assert ss.run_seed(row, now=later) == "ready"
    now_ids = {r["id"] for r in _mine(db, "invoices")}
    want = built(MOCK_DAY + timedelta(days=7))
    assert now_ids == {r["id"] for r in rows(want, "invoices")}
    assert len(first - now_ids) < 120, "a refresh removes only the gifts that passed a year"
    assert len(_mine(db, "contacts")) == len(rows(want, "contacts"))
    assert len(_mine(db, "attendance")) == len(rows(want, "attendance"))
    gift_deletes = [p for p in db.deletes[deletes_before:] if p.startswith("/invoices")]
    assert gift_deletes and all("&id=in.(" in p for p in gift_deletes), "gifts are never wiped wholesale"
    assert _marker(db)["anchor"] == ss.anchor(MOCK_DAY + timedelta(days=7))


def test_a_re_seed_keeps_the_last_visit_the_cleanup_measures_idle_from(db, monkeypatch):
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "ready"
    _marker(db)["last_seen_at"] = "2026-11-14T19:00:00+00:00"
    later = SEED_NOW + timedelta(days=8)
    monkeypatch.setattr(ss, "_now", lambda: later)
    assert ss.run_seed(next(r for r in db.t["businesses"] if r["id"] == SAMPLE), now=later) == "ready"
    m = _marker(db)
    assert m["last_seen_at"] == "2026-11-14T19:00:00+00:00" and m["created_at"] == "2026-11-14T15:00:00+00:00"
    assert "claimed_at" not in m and m["status"] == "ready"


def test_the_last_visit_stamp_never_writes_over_a_seed_in_progress(db):
    ss.run_seed(_sample_row(), now=SEED_NOW)
    stale = json.loads(json.dumps(next(r for r in db.t["businesses"] if r["id"] == SAMPLE)))  # read as ready
    _marker(db).update(status="seeding", run="the-refresh", claimed_at=SEED_NOW.isoformat())
    sc.touch(stale, now=SEED_NOW + timedelta(days=1))
    assert _marker(db)["status"] == "seeding" and _marker(db)["run"] == "the-refresh"


def test_a_dead_seed_is_taken_over_and_finishes_clean(db, monkeypatch):
    real = ss.insert
    calls = {"n": 0}

    def dies(table, rs, **kw):
        calls["n"] += 1
        if table == "attendance":
            raise RuntimeError("deploy cut it short")
        return real(table, rs, **kw)

    monkeypatch.setattr(ss, "insert", dies)
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "failed"
    assert _marker(db)["status"] == "failed"
    monkeypatch.setattr(ss, "insert", real)
    later = SEED_NOW + timedelta(seconds=ss.retry_after_s(1) + 1)
    row = next(r for r in db.t["businesses"] if r["id"] == SAMPLE)
    assert ss.due(row, later) == "retry"
    assert ss.run_seed(row, now=later) == "ready"
    for table, rs in built()["tables"]:
        assert len(_mine(db, table)) == len(rs), table


def test_a_claim_taken_over_stops_the_old_seeder(db, monkeypatch):
    real = ss.insert

    def steal(table, rs, **kw):
        if table == "groups":
            m = _marker(db)
            m["run"] = "someone-else"
        return real(table, rs, **kw)

    monkeypatch.setattr(ss, "insert", steal)
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "superseded"
    assert _marker(db)["status"] == "seeding" and _marker(db)["run"] == "someone-else"


def test_an_ending_sample_is_never_seeded(db):
    row = _sample_row(status="ending")
    next(r for r in db.t["businesses"] if r["id"] == SAMPLE)["settings"]["sample_church"]["status"] = "ending"
    assert ss.run_seed(row, now=SEED_NOW) == "not_due"
    assert not db.posts and not db.deletes


@pytest.mark.parametrize("over", [{"is_sample": False}, {"sample_of": None}, {"sample_of": SAMPLE}])
def test_a_row_that_is_not_a_sample_is_refused_before_any_write(db, over):
    next(r for r in db.t["businesses"] if r["id"] == SAMPLE).update(over)
    assert ss.run_seed(_sample_row(), now=SEED_NOW) == "refused"
    assert not db.posts and not db.deletes and not db.patches


def test_every_delete_is_scoped_to_the_sample(db, monkeypatch):
    ss.run_seed(_sample_row(), now=SEED_NOW)
    later = SEED_NOW + timedelta(days=8)
    monkeypatch.setattr(ss, "_now", lambda: later)
    ss.run_seed(next(r for r in db.t["businesses"] if r["id"] == SAMPLE), now=later)
    assert db.deletes
    for p in db.deletes:
        assert f"business_id=eq.{SAMPLE}" in p, p
        assert not p.startswith("/businesses")
        assert p.split("?")[0].lstrip("/") in d.TABLES
    for table in ("contacts", "invoices", "attendance", "groups", "business_sites"):
        kept = {r["id"] for r in db.t[table] if r["business_id"] != SAMPLE}
        assert kept == {f"keep-{table}", f"keep-other-{table}"}
    # Every claim and every marker write names the sample, and only it.
    for p in db.patches:
        assert p.startswith(f"/businesses?id=eq.{SAMPLE}&is_sample=is.true")


def test_the_seed_never_writes_a_forbidden_table(db):
    ss.run_seed(_sample_row(), now=SEED_NOW)
    assert not set(db.posts) & set(ss.FORBIDDEN_TABLES)
    with pytest.raises(ss.SeedError):
        ss.insert("chief_scheduled_actions", [{"id": "x"}])
    with pytest.raises(ss.SeedError):
        ss.clear(SAMPLE, ["sms_messages"])


def test_mixed_keys_never_reach_the_database():
    out = ss._uniform([{"a": 1}, {"b": 2}])
    assert out == [{"a": 1, "b": None}, {"a": None, "b": 2}]


def test_the_settings_key_is_the_one_be1_uses():
    assert ss.KEY == sc.SETTINGS_KEY
    assert sc.seed_hook is ss.provision and sc.seed_due is ss.due


# ─── The books and the Move-in room stay out ──────────────────────────

def test_a_samples_gifts_never_reach_the_books(monkeypatch):
    import gl_engine
    import sb_clients
    fb = FakeDB()
    fb.t["gl_sync_queue"] = [{"id": "q1", "business_id": SAMPLE, "source_table": "invoices", "source_id": "g1",
                              "processed_at": None, "claimed_by": None, "claimed_at": None,
                              "enqueued_at": "2026-11-14T00:00:00Z"}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setattr(sc, "is_sample", lambda b: str(b) == SAMPLE)
    touched = []
    monkeypatch.setattr(gl_engine, "ensure_chart_of_accounts", lambda *a, **k: touched.append(a))
    monkeypatch.setattr(gl_engine, "process_source_row", lambda *a, **k: touched.append(a))
    out = gl_engine.process_queue()
    assert out["processed"] == 1 and not touched
    assert fb.t["gl_sync_queue"][0]["processed_at"]


def test_a_sample_never_opens_move_in(monkeypatch):
    import church_move_in
    monkeypatch.setenv("CHURCH_MOVE_IN", "on")
    monkeypatch.setattr(sc, "is_sample", lambda b: str(b) == SAMPLE)
    assert church_move_in.switched_on(SAMPLE) is False
    assert church_move_in.switched_on(HOME) is True
