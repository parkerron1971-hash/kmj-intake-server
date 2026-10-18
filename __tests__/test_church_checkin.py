# __tests__/test_church_checkin.py
#
# Sunday check-in (church_checkin.py + member_portal_checkin.py), Kevin
# 2026-10-17: "the app checkin and online checkin for online view are all
# good. kiosk is for children." Pins:
#   · the window: the service day on the church's clock, open 30 minutes
#     before until 3 hours after, then next week's;
#   · the occasion is made once in Services & Events (church-only, named
#     after the church's own service), or a service already dated that day
#     is used;
#   · a member counts only themselves and their family's adults; unticking
#     removes only what their own phone wrote (never the door's or the
#     kiosk's); "Watching online" and back; never twice;
#   · the Kids self kiosk counts the parent once and never fails for it;
#   · Home shows the card only while check-in is open; the owner's preview
#     never writes; /here opens /my/here;
#   · the office reads its settings, link and counts, and only a manager
#     changes them.

import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_checkin as cc
import member_portal as mp
import member_portal_checkin as mpk
import member_portal_church as mpc

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
OWNER = "44444444-4444-4444-4444-444444444444"
CALVIN = "33333333-3333-3333-3333-333333333331"
DANA = "33333333-3333-3333-3333-333333333332"
GRACE = "33333333-3333-3333-3333-333333333333"
STRANGER = "33333333-3333-3333-3333-333333333339"
HOME = "55555555-5555-5555-5555-555555555555"
MOD = "66666666-6666-6666-6666-666666666666"
HOST = "love-city.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
DETROIT = ZoneInfo("America/Detroit")
# Sunday 2026-10-18, Love City's 11:00 service.
SUNDAY_1045 = datetime(2026, 10, 18, 10, 45, tzinfo=DETROIT)
SAT_EVENING = datetime(2026, 10, 17, 19, 0, tzinfo=DETROIT)

BUSINESS = {"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
            "settings": {"timezone": "America/Detroit", "member_portal": {"enabled": True}}}


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Enough PostgREST: eq./in./is. filters, order, limit, the attendance
    one-per-person index, the one-occasion-per-day index and an upsert."""

    def __init__(self):
        self.t = {"church_checkin_settings": [], "attendance": [], "household_adults": [],
                  "contacts": [{"id": i, "business_id": BIZ, "name": n} for i, n in
                               ((CALVIN, "Calvin Carter"), (DANA, "Dana Carter"), (GRACE, "Grace Nguyen"))]
                  + [{"id": STRANGER, "business_id": OTHER, "name": "Sam Other"}],
                  "custom_modules": [{"id": MOD, "business_id": BIZ, "name": "Services & Events", "archetype": "event_roster",
                                      "is_active": True, "archetype_params": {}, "created_at": "2026-01-01"}],
                  "module_entries": [{"id": "77777777-7777-7777-7777-777777777770", "module_id": MOD, "business_id": BIZ,
                                      "status": "active", "created_at": "2026-10-13",
                                      "data": {"title": "Sunday Worship", "date": "", "type": "service",
                                               "location": "1084 Allen Ave, Muskegon, MI 49442"}}],
                  "business_sites": [{"business_id": BIZ, "slug": "love-city", "site_config": {"custom_domain": "lovecityc.com"}}]}
        self.n = 0
        self.fail = False

    @staticmethod
    def _match(row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            if v.startswith("eq."):
                want = v[3:]
                have = row.get(k)
                if isinstance(have, bool):
                    have = str(have).lower()
                if str(have) != want:
                    return False
            elif v.startswith("in.("):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
            elif v == "is.true" and row.get(k) is not True:
                return False
            elif v == "is.null" and row.get(k) is not None:
                return False
        return True

    def get(self, path, **_):
        if self.fail:
            return None
        table, q = _params(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        return rows[: int(q.get("limit", ["10000"])[0])]

    def post(self, path, body, prefer=None, **_):
        if self.fail:
            return None
        table, q = _params(path)
        if table == "church_checkin_settings" and q.get("on_conflict"):
            for r in self.t[table]:
                if r["business_id"] == body["business_id"]:
                    r.update(body)
                    return [dict(r)]
        self.n += 1
        row = {"id": f"00000000-0000-4000-8000-{self.n:012d}", **body}
        if table == "attendance":
            if row.get("method") not in ("staff", "station", "self", "rsvp", "online", "kids_parent"):
                return None
            if any(r["entry_id"] == row["entry_id"] and r["contact_id"] == row["contact_id"] for r in self.t[table]):
                return None
        if table == "module_entries":
            day = (row.get("data") or {}).get("_checkin_day")
            if day and any((r.get("data") or {}).get("_checkin_day") == day and r["business_id"] == row["business_id"]
                           for r in self.t[table]):
                return None
        self.t.setdefault(table, []).append(row)
        return [dict(row)]

    def patch(self, path, body):
        if self.fail:
            return None
        table, q = _params(path)
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    def delete(self, path):
        table, q = _params(path)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, q)]
        return True


@pytest.fixture
def db(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", d.delete)
    return d


def _on(d, **kw):
    d.t["church_checkin_settings"].append({"business_id": BIZ, "enabled": True, "weekday": 6, "start_time": "11:00",
                                           "timezone": "America/Detroit", "opens_before_min": 30,
                                           "closes_after_min": 180, "title": "", **kw})


def _family(d):
    d.t["household_adults"] += [{"household_id": HOME, "contact_id": CALVIN, "business_id": BIZ},
                                {"household_id": HOME, "contact_id": DANA, "business_id": BIZ}]


def _me(cid=CALVIN, name="Calvin Carter"):
    return {"id": cid, "name": name}


# ─── the window ──────────────────────────────────────────────────────

def test_the_window_is_the_service_day_on_the_churchs_clock():
    st = dict(cc.DEFAULTS, timezone="America/Detroit")
    w = cc.window(st, SAT_EVENING)
    assert w["day"].isoformat() == "2026-10-18" and not w["open"] and w["weekday"] == "Sunday"
    assert cc.clock(w["opens"]) == "10:30 AM" and cc.clock(w["closes"]) == "2:00 PM"
    assert cc.window(st, SUNDAY_1045)["open"]
    # Before it opens on the day itself: still today's, not yet open.
    early = cc.window(st, datetime(2026, 10, 18, 10, 0, tzinfo=DETROIT))
    assert early["day"].isoformat() == "2026-10-18" and not early["open"]
    # Once it closes, it's next week's.
    late = cc.window(st, datetime(2026, 10, 18, 14, 1, tzinfo=DETROIT))
    assert late["day"].isoformat() == "2026-10-25" and not late["open"]
    # The church's clock, not the server's: 15:00 UTC is 11:00 in Detroit.
    assert cc.window(st, datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc))["open"]


def test_settings_default_off_and_save_is_checked(db):
    st = cc.settings(BUSINESS)
    assert st["enabled"] is False and st["start_time"] == "11:00" and st["timezone"] == "America/Detroit"
    assert st["saved"] is False
    for bad in ({"start_time": "25:00"}, {"timezone": "Mars/Base"}, {"weekday": 9}):
        with pytest.raises(HTTPException) as e:
            cc.save_settings(BUSINESS, bad, OWNER)
        assert e.value.status_code == 400
    out = cc.save_settings(BUSINESS, {"enabled": True, "start_time": "11:00", "closes_after_min": 99999}, OWNER)
    assert out["enabled"] and out["closes_after_min"] == 720 and out["saved"]
    cc.save_settings(BUSINESS, {"enabled": False}, OWNER)
    assert len(db.t["church_checkin_settings"]) == 1 and cc.settings(BUSINESS)["enabled"] is False


def test_a_failed_read_is_never_read_as_off(db):
    db.fail = True
    assert cc.settings(BUSINESS) is None
    assert cc.card(BUSINESS, _me(), SUNDAY_1045) == {"state": "error"}


# ─── the occasion ────────────────────────────────────────────────────

def test_the_occasion_is_made_once_church_only_and_named_after_the_service(db):
    st = dict(cc.DEFAULTS, timezone="America/Detroit")
    day = cc.window(st, SUNDAY_1045)["day"]
    occ = cc.ensure_occasion(BIZ, st, day)
    made = [e for e in db.t["module_entries"] if (e["data"] or {}).get("_checkin_day")]
    assert len(made) == 1 and occ["id"] == made[0]["id"] and occ["title"] == "Sunday Worship"
    data = made[0]["data"]
    assert data["date"] == "2026-10-18T11:00" and data["_visibility"] == "private" and data["type"] == "service"
    assert data["location"].startswith("1084 Allen Ave") and made[0]["created_by"] == "sunday_checkin"
    assert cc.ensure_occasion(BIZ, st, day)["id"] == occ["id"]
    assert len([e for e in db.t["module_entries"] if (e["data"] or {}).get("_checkin_day")]) == 1


def test_a_service_the_church_already_dated_that_day_is_used(db):
    db.t["module_entries"].append({"id": "77777777-7777-7777-7777-777777777771", "module_id": MOD, "business_id": BIZ,
                                   "status": "active", "data": {"title": "Homecoming Sunday", "date": "2026-10-18T11:00",
                                                                "type": "service"}})
    st = dict(cc.DEFAULTS, timezone="America/Detroit")
    occ = cc.ensure_occasion(BIZ, st, cc.window(st, SUNDAY_1045)["day"])
    assert occ["title"] == "Homecoming Sunday"
    assert not [e for e in db.t["module_entries"] if (e["data"] or {}).get("_checkin_day")]


def test_no_services_room_means_no_occasion_and_the_member_is_told_to_try_later(db):
    db.t["custom_modules"] = []
    _on(db)
    assert cc.card(BUSINESS, _me(), SUNDAY_1045)["state"] == "error"


# ─── the member ──────────────────────────────────────────────────────

def test_a_family_is_the_member_then_the_other_adults(db):
    assert [p["id"] for p in cc.family_of(BIZ, _me())] == [CALVIN]
    _family(db)
    fam = cc.family_of(BIZ, _me())
    assert [(p["id"], p["me"]) for p in fam] == [(CALVIN, True), (DANA, False)]


def test_checking_in_a_family_and_changing_it(db):
    _on(db)
    _family(db)
    c = cc.card(BUSINESS, _me(), SUNDAY_1045)
    assert c["state"] == "open" and c["marks"] == {}
    entry = c["occasion"]["id"]
    out = cc.check_in(BIZ, entry, c["family"], [CALVIN, DANA], "in")
    assert sorted(out["counted"]) == ["Calvin Carter", "Dana Carter"]
    rows = {r["contact_id"]: r for r in db.t["attendance"]}
    assert rows[CALVIN]["method"] == "self" and rows[DANA]["method"] == "self" and rows[CALVIN]["entry_id"] == entry
    # Again: nothing doubles.
    cc.check_in(BIZ, entry, c["family"], [CALVIN, DANA], "in")
    assert len(db.t["attendance"]) == 2
    # Changed: Dana stayed home and Calvin is watching online.
    out = cc.check_in(BIZ, entry, c["family"], [CALVIN], "online")
    rows = {r["contact_id"]: r for r in db.t["attendance"]}
    assert rows[CALVIN]["method"] == "online" and DANA not in rows and out["removed"] == ["Dana Carter"]
    with pytest.raises(HTTPException) as e:
        cc.check_in(BIZ, entry, c["family"], [], "in")
    assert e.value.status_code == 400


def test_a_member_never_counts_anyone_outside_their_family_or_undoes_the_door(db):
    _on(db)
    _family(db)
    c = cc.card(BUSINESS, _me(), SUNDAY_1045)
    entry = c["occasion"]["id"]
    db.t["attendance"].append({"id": "door", "business_id": BIZ, "entry_id": entry, "contact_id": DANA, "method": "staff"})
    cc.check_in(BIZ, entry, c["family"], [CALVIN, GRACE, STRANGER], "in")
    assert {r["contact_id"] for r in db.t["attendance"]} == {CALVIN, DANA}
    cc.check_in(BIZ, entry, c["family"], [CALVIN], "online")
    assert [r["method"] for r in db.t["attendance"] if r["contact_id"] == DANA] == ["staff"]


def test_checking_in_at_church_marks_them_seen(db):
    _on(db)
    c = cc.card(BUSINESS, _me(), SUNDAY_1045)
    cc.check_in(BIZ, c["occasion"]["id"], c["family"], [CALVIN], "in")
    assert next(p for p in db.t["contacts"] if p["id"] == CALVIN).get("last_interaction")


def test_the_card_is_off_or_closed_without_writing_anything(db):
    assert cc.card(BUSINESS, _me(), SUNDAY_1045) == {"state": "off"}
    _on(db)
    assert cc.card(BUSINESS, _me(), SAT_EVENING)["state"] == "closed"
    assert not [e for e in db.t["module_entries"] if (e["data"] or {}).get("_checkin_day")]


# ─── the kiosk's parent ──────────────────────────────────────────────

def test_the_kiosk_parent_counts_once_and_never_fails_the_kiosk(db):
    entry = "77777777-7777-7777-7777-777777777770"
    assert cc.count_kids_parent(BIZ, entry, {"id": DANA, "name": "Dana Carter"})
    assert cc.count_kids_parent(BIZ, entry, {"id": DANA, "name": "Dana Carter"})
    assert [(r["contact_id"], r["method"]) for r in db.t["attendance"]] == [(DANA, "kids_parent")]
    assert cc.count_kids_parent(BIZ, "not-an-id", {"id": DANA}) is False
    db.fail = True
    assert cc.count_kids_parent(BIZ, entry, {"id": CALVIN, "name": "Calvin"}) is False


def test_counts_by_how_people_were_counted(db):
    entry = "77777777-7777-7777-7777-777777777770"
    for i, m in enumerate(("self", "self", "kids_parent", "online", "staff", "station")):
        db.t["attendance"].append({"id": f"a{i}", "business_id": BIZ, "entry_id": entry, "contact_id": f"c{i}", "method": m})
    assert cc.counts(BIZ, entry) == {"phone": 2, "kids_parents": 1, "online": 1, "office": 2, "total": 6}


# ─── the pages ───────────────────────────────────────────────────────

@pytest.fixture
def member(db, monkeypatch):
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(BUSINESS), "site": {"slug": "love-city"}})
    db.who = {"me": {"id": CALVIN, "name": "Calvin Carter", "email": "calvin@example.com"}, "preview": False}
    monkeypatch.setattr(mp, "_session_for", lambda req, church: (
        {"claims": {}, "people": [db.who["me"]], "me": db.who["me"], "preview": db.who["preview"]}))
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [])
    monkeypatch.setattr(mpc, "groups_for", lambda b, me: [])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    import live_router as lr
    monkeypatch.setattr(lr, "current", lambda b: {})
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])
    monkeypatch.setattr(cc, "_now", lambda: SUNDAY_1045.astimezone(timezone.utc))
    app = FastAPI()
    app.include_router(mpk.router)

    @app.get("/my")
    async def _home(request: mp.Request):
        return await mp.serve(request, "/my")

    @app.get("/my/here")
    async def _here(request: mp.Request):
        return await mp.serve(request, "/my/here")
    return TestClient(app, base_url=f"https://{HOST}")


def test_the_member_checks_in_from_the_code(db, member):
    _on(db)
    _family(db)
    page = member.get("/my/here").text
    assert "Are you with us today?" in page and "Sunday Worship · 11:00 AM" in page
    assert f'value="{DANA}" checked' in page and 'name="where" value="in" checked' in page
    r = member.post("/my/here", data={"where": "in", "people": [CALVIN, DANA], "back": "/my/here"},
                    headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/here?done=here"
    assert {(a["contact_id"], a["method"]) for a in db.t["attendance"]} == {(CALVIN, "self"), (DANA, "self")}
    done = member.get("/my/here").text
    assert "Welcome home." in done and "Calvin and Dana are checked in for Sunday Worship." in done
    change = member.get("/my/here?change=1").text
    assert "Save</button>" in change


def test_home_shows_the_card_only_while_check_in_is_open(db, member, monkeypatch):
    assert "Are you with us today?" not in member.get("/my").text   # off
    _on(db)
    assert "Are you with us today?" in member.get("/my").text
    monkeypatch.setattr(cc, "_now", lambda: SAT_EVENING.astimezone(timezone.utc))
    assert "Are you with us today?" not in member.get("/my").text
    closed = member.get("/my/here").text
    assert "Check-in opens <em>Sunday at 10:30 AM</em>" in closed


def test_watching_online_from_home(db, member):
    _on(db)
    r = member.post("/my/here", data={"where": "online", "people": [CALVIN], "back": "/my"},
                    headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my?done=here"
    assert [(a["contact_id"], a["method"]) for a in db.t["attendance"]] == [(CALVIN, "online")]
    assert "You are counted as watching online." in member.get("/my").text


def test_the_owners_preview_never_writes(db, member):
    _on(db)
    db.who["preview"] = True
    r = member.post("/my/here", data={"where": "in", "people": [CALVIN]}, headers=ORIGIN, follow_redirects=False)
    assert "ck=preview" in r.headers["location"] and db.t["attendance"] == []


def test_after_it_closes_a_post_is_refused(db, member, monkeypatch):
    _on(db)
    monkeypatch.setattr(cc, "_now", lambda: datetime(2026, 10, 18, 14, 30, tzinfo=DETROIT).astimezone(timezone.utc))
    r = member.post("/my/here", data={"where": "in", "people": [CALVIN]}, headers=ORIGIN, follow_redirects=False)
    assert "ck=closed" in r.headers["location"] and db.t["attendance"] == []


def test_here_opens_the_members_page():
    import public_site
    app = FastAPI()
    app.include_router(public_site.router)
    r = TestClient(app, base_url="https://lovecityc.com").get("/here", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/my/here"


# ─── the office ──────────────────────────────────────────────────────

def test_the_office_sets_it_and_reads_the_link_and_counts(db, monkeypatch):
    import church_router
    monkeypatch.setattr(cc, "_now", lambda: SUNDAY_1045.astimezone(timezone.utc))
    app = FastAPI()
    app.include_router(church_router.router)
    import sb_clients
    from types import SimpleNamespace
    role = {"r": "manager"}
    import business_access as ba
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: role["r"])
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email="kevin@example.com"))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    db.t["businesses"] = [dict(BUSINESS)]
    t = TestClient(app)
    got = t.get("/church/checkin", params={"business_id": BIZ}).json()
    assert got["settings"]["enabled"] is False and got["member_url"] == "https://lovecityc.com/here"
    assert got["next"]["start"] == "11:00 AM" and got["occasion"] is None and got["has_room"]
    saved = t.put("/church/checkin", params={"business_id": BIZ}, json={"enabled": True}).json()
    assert saved["settings"]["enabled"] and saved["occasion"]["title"] == "Sunday Worship"
    assert saved["counts"] == {"phone": 0, "kids_parents": 0, "online": 0, "office": 0, "total": 0}
    role["r"] = "member"
    assert t.put("/church/checkin", params={"business_id": BIZ}, json={"enabled": False}).status_code == 404
    assert t.get("/church/checkin", params={"business_id": BIZ}).status_code == 200
