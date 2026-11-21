"""An event's special roles and its helpers' hours (docs/EVENT_VOLUNTEERS.md
6.10 and 6.6, step S3).

Pins, each one broken on purpose once to see it go red:
  * a kids role is offered in the member app (both looks) only to someone
    with a current background check, through church_serving.cleared (the rule
    The week reads for "Can't serve with kids yet"); anyone else reads "Needs
    a background check. Ask the office." and a signup the page didn't offer
    is refused; a full role says "Chaperones just filled up."
  * the public page shows only roles open to everyone (no `open` key: as
    before) and never a kids role; its signup refuses a hidden one
  * a special helper's yes on a past event this year counts as Events, for
    _serve_minutes (120, held to 15 to 720), with a contact, a yes, and one of
    the event's role ids; a team place at the same event counts once, the
    longer; away days earn nothing; with the switch closed every number is
    what it was, on every reader (Serving hours, My serving, The week, Reports)"""
from __future__ import annotations

import copy
import os
import sys
import types
from datetime import date, timedelta

import pytest
from urllib.parse import parse_qsl, quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_reports  # noqa: E402
import sb_clients  # noqa: E402
import church_serving as cs  # noqa: E402
import events_rsvp_router as er  # noqa: E402
import member_portal_church as mpc  # noqa: E402
from test_event_volunteers import BIZ, E_LOCK, E_PAST, MOD, NOW, church  # noqa: E402,F401
from test_sunday_planning import ANA, JO, LEE, MARCUS, TY  # noqa: E402

E_KIDS = "e4000000-0000-4000-8000-000000000001"
SVC_PAST = "5e400000-0000-4000-8000-000000000001"
ME = {"id": JO, "name": "Jo Park", "email": ""}
ROLES = [{"id": "chap", "label": "Chaperones", "needed": 2, "kids": True},
         {"id": "grill", "label": "Grill", "needed": 1, "open": True},
         {"id": "setup", "label": "Set up", "needed": 2, "open": False},
         {"id": "walk", "label": "Walkers", "needed": 3}]


def _soon(days=14):
    return (date.today() + timedelta(days=days)).isoformat() + "T18:00"


@pytest.fixture
def roles(church):
    c = church
    c.db.t["module_entries"].append(
        {"id": E_KIDS, "business_id": BIZ, "module_id": MOD, "status": "active", "created_at": NOW.isoformat(),
         "updated_at": "2026-10-21T15:00:00+00:00",
         "data": {"title": "Fall retreat", "date": _soon(), "location": "Camp Lake", "_roles": copy.deepcopy(ROLES),
                  "signups": []}})
    c.db.t["space_leaders"] = []
    c.db.t["businesses"][0]["settings"] = {"events_public": {"enabled": True}}
    return c


def kids_entry(c):
    return next(e for e in c.db.t["module_entries"] if e["id"] == E_KIDS)


def check(c, cid=JO, on=None):
    c.db.t["space_leaders"].append({"business_id": BIZ, "contact_id": cid, "space": "kids",
                                    "background_check_on": on or (date.today() - timedelta(days=60)).isoformat()})


def occasion(c, me=ME):
    return next(o for o in mpc.upcoming_for(BIZ, me) if o["entry_id"] == E_KIDS)


# ─── the member app ──────────────────────────────────────────────────


def test_a_kids_role_is_offered_only_with_a_current_check(roles):
    c = roles
    o = occasion(c)
    chap = next(r for r in o["roles"] if r["id"] == "chap")
    assert chap["kids"] is True and chap["offer"] is False
    for html in (mpc.occasion_card(o, "/my/events"), mpc._lumen_occasion(o)):
        assert 'value="chap"' not in html, "no button for it"
        assert "Chaperones: Needs a background check. Ask the office." in html
        assert 'value="grill"' in html and 'value="setup"' in html, "every other role, open or not"
    assert mpc.member_rsvp(BIZ, ME, E_KIDS, "serve", "chap") == (False, "kids")
    assert kids_entry(c)["data"]["signups"] == [], "the page didn't offer it: nothing saved"
    check(c)
    o = occasion(c)
    assert next(r for r in o["roles"] if r["id"] == "chap")["offer"] is True
    assert 'value="chap"' in mpc.occasion_card(o, "/my/events") and "Needs a background check" not in mpc._lumen_occasion(o)
    assert mpc.member_rsvp(BIZ, ME, E_KIDS, "serve", "chap") == (True, "serving")
    assert kids_entry(c)["data"]["signups"][0] == {"name": "Jo Park", "status": "yes", "contact_id": JO, "via": "member",
                                                   "role": "chap"}


@pytest.mark.parametrize("how", ["ran out", "under 18", "none"])
def test_a_check_that_isnt_current_offers_nothing(roles, how):
    c = roles
    if how == "ran out":
        check(c, on=(date.today() - timedelta(days=3 * 366)).isoformat())
    elif how == "under 18":
        check(c)
        next(p for p in c.db.t["contacts"] if p["id"] == JO)["birthdate"] = (date.today() - timedelta(days=16 * 365)).isoformat()
    assert cs.cleared(BIZ, [JO]) == set()
    assert mpc.member_rsvp(BIZ, ME, E_KIDS, "serve", "chap") == (False, "kids")


def test_the_check_is_the_weeks_own_rule(roles, monkeypatch):
    """One rule: cleared() reads checks_of, the rule The week's "Can't serve
    with kids yet" reads."""
    c = roles
    check(c)
    seen = []
    real = cs.checks_of
    monkeypatch.setattr(cs, "checks_of", lambda *a, **k: seen.append(a[1]) or real(*a, **k))
    assert cs.cleared(BIZ, [JO, LEE]) == {JO} and seen == [[JO, LEE]]


def _member_client(c, monkeypatch, me=ME):
    async def signed(request):
        return {"business": c.db.t["businesses"][0]}, me, False
    monkeypatch.setattr(mpc, "_signed_in", signed)
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: True)
    app = FastAPI()
    app.include_router(mpc.router)
    return TestClient(app)


def test_the_member_app_refuses_an_unoffered_signup_and_names_a_full_role(roles, monkeypatch):
    c = roles
    client = _member_client(c, monkeypatch)
    form = {"entry_id": E_KIDS, "action": "serve", "role": "chap", "back": "/my/events"}
    r = client.post("/my/rsvp", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/events?err=kids"
    assert mpc.flash_html(err="kids") == ('<p class="mp-err mp-flash" role="alert">Needs a background check. Ask the '
                                          'office.</p>')
    check(c)
    kids_entry(c)["data"]["signups"] = [{"name": "Ana Cruz", "contact_id": ANA, "role": "chap", "status": "yes"},
                                        {"name": "Lee Ford", "contact_id": LEE, "role": "chap"}]
    r = client.post("/my/rsvp", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/events?err=filled&entry={E_KIDS}&role=chap"
    assert len(kids_entry(c)["data"]["signups"]) == 2
    # The page names the role from the church's own data, never from the link.
    occ = mpc.upcoming_for(BIZ, ME)

    def asked(**q):
        return types.SimpleNamespace(query_params=q)
    assert "Chaperones just filled up." in mpc._flash(asked(err="filled", entry=E_KIDS, role="chap"), occ)
    for q in ({"err": "filled", "entry": E_KIDS, "role": "made-up"}, {"err": "filled", "entry": E_KIDS, "role": "<b>x</b>"},
              {"err": "filled", "entry": E_KIDS, "role": "made-up", "what": "Your account is locked"},
              {"err": "filled", "entry": "not-an-event", "role": "chap"}):
        shown = mpc._flash(asked(**q), occ)
        assert shown == mpc.flash_html(err="filled") and "locked" not in shown and "<b>" not in shown, q
    assert "That role just filled up." in mpc._flash(asked(err="filled", entry=E_KIDS, role="chap"))
    crafted = mpc._flash(asked(err="filled", entry=E_KIDS, role="chap", what="Your account is locked"), occ)
    assert "Chaperones just filled up." in crafted and "locked" not in crafted, "words in the link are never shown"


# ─── the public page ─────────────────────────────────────────────────


def test_the_public_page_shows_only_roles_open_to_everyone(roles):
    c = roles
    mods = [m for m in c.db.t["custom_modules"]]
    occ = er.build_occasions(mods, {MOD: [kids_entry(c)]})
    card = er._occasion_card(occ[0])
    for shown in ("Grill", "Walkers"):
        assert shown in card
    for hidden in ("Chaperones", "Set up", 'value="chap"', 'value="setup"'):
        assert hidden not in card
    # Roles that say nothing read exactly as before.
    assert next(r for r in occ[0]["roles"] if r["id"] == "walk") == {"id": "walk", "label": "Walkers", "needed": 3,
                                                                     "filled": 0, "full": False}


def test_the_public_signup_refuses_a_hidden_role(roles, monkeypatch):
    c = roles
    import sample_church

    async def no(biz):
        return False
    monkeypatch.setattr(sample_church, "is_sample_async", no)
    c.db.t["business_sites"] = [{"business_id": BIZ, "slug": "lovecity", "updated_at": NOW.isoformat()}]
    monkeypatch.setattr(er, "_rsvp_rate", {})
    app = FastAPI()
    app.include_router(er.router)
    client = TestClient(app)
    for role, code in (("chap", 400), ("setup", 400), ("nope", 400), ("grill", 200)):
        r = client.post("/public/events/lovecity/rsvp", json={"entry_id": E_KIDS, "name": "Pat Doe",
                                                             "email": f"pat-{role}@example.org", "role": role})
        assert r.status_code == code, (role, r.text)
    assert [s["role"] for s in kids_entry(c)["data"]["signups"]] == ["grill"]


# ─── hours (6.6) ─────────────────────────────────────────────────────


@pytest.fixture
def hours(church, monkeypatch):
    """The Prayer walk was yesterday (NOW is 21 October 2026): its own roles,
    who signed up, and its date on Who serves when with Jo on Greeter."""
    c = church
    monkeypatch.setattr(cs, "_now", lambda: NOW)
    walk = next(e for e in c.db.t["module_entries"] if e["id"] == E_PAST)
    walk["data"].update({"_roles": [{"id": "walk", "label": "Walkers", "needed": 6},
                                    {"id": "pray", "label": "Prayer", "needed": 2}],
                         "signups": [{"name": "Ana Cruz", "contact_id": ANA, "role": "walk", "status": "yes"},
                                     {"name": "Ana Cruz", "contact_id": ANA, "role": "pray"},
                                     {"name": "Jo Park", "contact_id": JO, "role": "walk"},
                                     {"name": "Lee Ford", "contact_id": LEE, "role": "walk", "status": "no"},
                                     {"name": "Ty Brooks", "contact_id": TY, "role": "walk", "status": "maybe"},
                                     {"name": "Marcus Hill", "contact_id": MARCUS, "role": "Attending"},
                                     {"name": "A guest", "role": "walk"}]})
    # A future event's helper, and last year's: neither counts this year.
    lock = next(e for e in c.db.t["module_entries"] if e["id"] == E_LOCK)
    lock["data"]["signups"].append({"name": "Lee Ford", "contact_id": LEE, "role": "grill"})
    c.db.t["module_entries"].append({"id": "e5000000-0000-4000-8000-000000000001", "business_id": BIZ,
                                     "module_id": MOD, "status": "active", "created_at": NOW.isoformat(),
                                     "data": {"title": "Old walk", "date": "2025-10-10T18:00",
                                              "_roles": [{"id": "walk", "label": "Walkers"}],
                                              "signups": [{"name": "Lee Ford", "contact_id": LEE, "role": "walk"}]}})
    c.db.t["worship_services"].append({"id": SVC_PAST, "business_id": BIZ, "title": "Prayer walk", "kind": "event",
                                       "event_entry_id": E_PAST, "starts_at": "2026-10-20T23:00:00+00:00", "items": [],
                                       "place": "", "archived_at": None, "is_template": False})
    c.db.t["serve_assignments"].append({"id": "a6600000-0000-4000-8000-000000000001", "business_id": BIZ,
                                        "service_id": SVC_PAST, "position_id": c.greeter, "slot": 1, "contact_id": JO,
                                        "status": "yes", "notified_at": NOW.isoformat(), "note": "", "swap_to": None})
    for t in ("group_meetings", "group_meeting_attendance", "space_leaders"):
        c.db.t.setdefault(t, [])
    for e in c.db.t["module_entries"]:
        e.setdefault("updated_at", "2026-09-01T00:00:00+00:00")
    c.reads = []
    plain = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: json_paths(plain, path, c.reads))
    c.walk = walk
    c.biz = c.db.t["businesses"][0]
    return c


def json_paths(plain, path, seen):
    """PostgREST's data->>key filters and alias:data->key picks, on
    module_entries (the fake database reads neither)."""
    seen.append(path)
    table, _, q = path.lstrip("/").partition("?")
    if table != "module_entries" or "data-" not in q:
        return plain(path)
    pairs = parse_qsl(q, keep_blank_values=True)
    picks = next((v for k, v in pairs if k == "select"), "")
    keep = [(k, v) for k, v in pairs if not k.startswith("data->>") and k != "select"]
    rows = plain(f"/{table}?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in keep))
    out = []
    for r in rows:
        data = r.get("data") or {}
        ok = True
        for k, v in pairs:
            if k.startswith("data->>"):
                val, (op, _, want) = data.get(k[7:]), v.partition(".")
                ok = ok and val is not None and {"gte": str(val) >= want, "lt": str(val) < want}[op]
        if not ok:
            continue
        row = {}
        for part in picks.split(","):
            alias, _, expr = part.partition(":") if ":" in part else (part, "", part)
            if expr.startswith("data->>"):
                v = data.get(expr[7:])
                row[alias] = None if v is None else str(v)
            elif expr.startswith("data->"):
                row[alias] = data.get(expr[6:])
            else:
                row[alias] = r.get(expr)
        out.append(row)
    return out


def mine(c, cid):
    return cs.member_view(c.biz, cid)


def test_a_special_helper_earns_the_events_minutes(hours):
    c = hours
    ana = mine(c, ANA)
    assert (ana["minutes"], ana["events"], ana["sundays"]) == (120, 1, 0), "one event, however many roles"
    for cid in (LEE, TY, MARCUS):
        assert mine(c, cid)["minutes"] == 0, "a no, a maybe, Attending, a future event and last year earn nothing"
    assert cs.minutes_of(c.biz, [ANA, JO, LEE]) == {ANA: 120, JO: 120, LEE: 0}


def test_a_team_place_and_a_special_role_at_one_event_count_once_the_longer(hours):
    c = hours
    jo = mine(c, JO)
    assert (jo["minutes"], jo["events"], jo["sundays"]) == (120, 1, 0), "the role's 120 over the place's 90"
    c.walk["data"]["_serve_minutes"] = 60
    jo = mine(c, JO)
    assert (jo["minutes"], jo["events"], jo["sundays"]) == (90, 0, 1), "the place's 90 over the role's 60"
    assert mine(c, ANA)["minutes"] == 60


@pytest.mark.parametrize("set_to, counts", [(5, 15), (15, 15), (300, 300), (720, 720), (9999, 720), ("90", 120),
                                            (True, 120), (None, 120)])
def test_serve_minutes_is_held_to_15_to_720(hours, set_to, counts):
    c = hours
    c.walk["data"]["_serve_minutes"] = set_to
    assert mine(c, ANA)["minutes"] == counts


def test_an_away_day_earns_nothing(hours):
    c = hours
    c.db.t["serve_away"].append({"id": "aw1", "business_id": BIZ, "contact_id": ANA, "starts_on": "2026-10-19",
                                 "ends_on": "2026-10-21", "note": ""})
    assert mine(c, ANA)["minutes"] == 0


def test_the_office_page_and_reports_count_events(hours):
    c = hours
    me = {"biz": c.biz, "checks": False, "write": True, "record": False}
    got = cs.overview(me, 2026)
    assert got["totals"]["events"] == 2 and got["totals"]["event_minutes"] == 240
    rows = {p["contact_id"]: p for p in got["people"]}
    assert (rows[ANA]["events"], rows[ANA]["event_minutes"], rows[ANA]["minutes"]) == (1, 120, 120)
    assert rows[JO]["minutes"] == 120 and rows[JO]["sunday_minutes"] == 0
    ctx = {"biz_id": BIZ, "biz": c.biz, "year": 2026, "now": NOW, "today": NOW.date(), "current": True}
    stats = {s["key"]: s["value"] for s in church_reports.serving(ctx)["stats"]}
    assert stats == {"serving_hours": church_reports._r(240 / 60), "serving_people": 2}


def test_with_the_switch_closed_every_number_is_what_it_was(hours, monkeypatch):
    c = hours
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    assert (mine(c, ANA)["minutes"], mine(c, ANA)["events"]) == (0, 0)
    assert (mine(c, JO)["minutes"], mine(c, JO)["sundays"]) == (90, 1)
    assert cs.minutes_of(c.biz, [ANA, JO]) == {ANA: 0, JO: 90}
    me = {"biz": c.biz, "checks": False, "write": True, "record": False}
    got = cs.overview(me, 2026)
    assert got["totals"]["events"] == 0 and got["totals"]["minutes"] == 90
    ctx = {"biz_id": BIZ, "biz": c.biz, "year": 2026, "now": NOW, "today": NOW.date(), "current": True}
    assert {s["key"]: s["value"] for s in church_reports.serving(ctx)["stats"]} == {
        "serving_hours": church_reports._r(90 / 60), "serving_people": 1}
    # And no event is read at all.
    seen = []
    import sb_clients
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    mine(c, ANA)
    assert not any(p.startswith("/module_entries") for p in seen)


def test_my_serving_says_events(hours):
    import member_portal_serving as mps
    c = hours
    html = mps._hours_html(mine(c, ANA), {"name": "Ana Cruz"})
    assert "an event you helped at." in html


def test_the_hours_read_is_bounded_to_the_year_and_the_keys_it_needs(hours):
    c = hours
    mine(c, ANA)
    reads = [r for r in c.reads if r.startswith("/module_entries")]
    assert reads and all("data->>date=gte.2026-01-01" in r and "data->>date=lt." in r for r in reads), reads
    assert all("select=id,module_id,status,updated_at,day:data->>date,signups:data->signups," in r for r in reads)
    assert not any(",data&" in r or "select=id,module_id,status,updated_at,data" in r for r in reads), "never the whole data"


def test_a_read_that_fails_fails_the_hours_never_fewer(hours, monkeypatch):
    """church_serving's own rule: a read that fails is a 503, never fewer
    hours, and Reports says it couldn't read Serving rather than come out short."""
    from fastapi import HTTPException
    c = hours
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: None if path.startswith("/module_entries") else real(path, **k))
    with pytest.raises(HTTPException) as got:
        mine(c, JO)
    assert got.value.status_code == 503
    ctx = {"biz_id": BIZ, "biz": c.biz, "year": 2026, "now": NOW, "today": NOW.date(), "current": True}
    assert all(s["value"] is None for s in church_reports.serving(ctx)["stats"])


@pytest.mark.parametrize("touched, counts", [("2026-10-21T09:00:00+00:00", 120), ("2026-10-19T09:00:00+00:00", 0),
                                             (None, 0)])
def test_an_event_archived_after_it_started_keeps_its_hours(hours, touched, counts):
    """Tidying up after the walk keeps its helpers' hours; archiving it
    before it started was calling it off."""
    c = hours
    c.walk["status"] = "archived"
    c.walk["updated_at"] = touched
    assert mine(c, ANA)["minutes"] == counts


def test_a_public_sign_up_never_earns_a_member_hours(hours):
    """The public page matches a contact by the email someone typed: that
    is not the member's own word, so it earns nothing."""
    import hashlib
    c = hours
    ana = next(s for s in c.walk["data"]["signups"] if s.get("contact_id") == ANA and s["role"] == "walk")
    ana["via"] = "public"
    c.walk["data"]["signups"] = [s for s in c.walk["data"]["signups"] if not (s.get("contact_id") == ANA and s is not ana)]
    assert mine(c, ANA)["minutes"] == 0
    ana["via"] = "member"
    assert mine(c, ANA)["minutes"] == 120, "the member app's own"
    # Before `via` was written: a signup matching one of the event's public
    # registrations (the key the public page keeps for an email) earns nothing.
    del ana["via"]
    next(p for p in c.db.t["contacts"] if p["id"] == ANA)["email"] = "ana@example.org"
    c.walk["data"]["_registration_keys"] = {
        hashlib.sha256(f"{BIZ}:{E_PAST}:ana@example.org".encode()).hexdigest(): True}
    assert mine(c, ANA)["minutes"] == 0
    assert mine(c, JO)["minutes"] == 120, "someone the office put on, not a public registration, still counts"
    c.walk["data"]["_registration_keys"] = {"someone-else": True}
    assert mine(c, ANA)["minutes"] == 120


def test_the_public_page_marks_its_sign_ups(roles, monkeypatch):
    c = roles
    import sample_church

    async def no(biz):
        return False
    monkeypatch.setattr(sample_church, "is_sample_async", no)
    c.db.t["business_sites"] = [{"business_id": BIZ, "slug": "lovecity", "updated_at": NOW.isoformat()}]
    monkeypatch.setattr(er, "_rsvp_rate", {})
    app = FastAPI()
    app.include_router(er.router)
    r = TestClient(app).post("/public/events/lovecity/rsvp", json={"entry_id": E_KIDS, "name": "Pat Doe",
                                                                   "email": "pat@example.org", "role": "grill"})
    assert r.status_code == 200, r.text
    assert kids_entry(c)["data"]["signups"][-1]["via"] == "public"


# ─── the office's picture says why ───────────────────────────────────


@pytest.mark.parametrize("how, words", [("ok", None), ("overdue", "Check overdue"), ("none", "No check on file"),
                                        ("teen", "Under 18")])
def test_the_event_page_says_why_a_kids_helper_isnt_cleared(church, how, words):
    c = church
    from test_event_volunteers import E_LOCK as LOCK
    c.db.t["space_leaders"] = []
    if how in ("ok", "overdue", "teen"):
        on = date.today() - timedelta(days=60 if how != "overdue" else 3 * 366)
        c.db.t["space_leaders"].append({"business_id": BIZ, "contact_id": ANA, "space": "kids",
                                        "background_check_on": on.isoformat()})
    if how == "teen":
        next(p for p in c.db.t["contacts"] if p["id"] == ANA)["birthdate"] = (date.today() - timedelta(days=16 * 365)).isoformat()
    pic = c.as_("owner").get(f"/church/event-volunteers/{LOCK}?business_id={BIZ}").json()
    ana = next(p for s in pic["special"] if s["role_id"] == "chap" for p in s["people"])
    assert (ana["checked"], ana["check"]) == (how == "ok", words)
