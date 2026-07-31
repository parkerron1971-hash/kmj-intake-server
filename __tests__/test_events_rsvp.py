# __tests__/test_events_rsvp.py
#
# Public event RSVP for event_roster modules. Pins:
#   1. the gate — settings.events_public.enabled AND >=1 active
#      event_roster module; ANY vertical (deliberately broader than
#      giving — see events_rsvp_router's gate ruling)
#   2. signup append shape — the EXACT Signup dict internal.tsx
#      reads/writes ({contact_id?, name, status:'yes', role?}), appended
#      to data[signups_field]; existing signups untouched
#   3. contact dedup by email within the business (ilike, LIKE-escaped)
#      + the idempotent double-tap (already-on-the-list → no dup row)
#   4. capacity honored SERVER-side: full occasion refuses with 409;
#      full named role refuses with 409; unknown role 400
#   5. rate limiting runs BEFORE any read/write on the public endpoint
#   6. build_occasions — upcoming-and-dated only, soonest first,
#      spots/full math, role fills; malformed data never raises

import asyncio
import itertools
import sys
import pathlib
import urllib.parse
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import events_rsvp_router as er

BIZ = "biz-1111"
MOD = "mod-2222"
ENTRY = "ent-3333"

_ips = itertools.count(1)


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=f"10.0.0.{next(_ips)}"))


def _params(**over):
    p = {
        "title_field": "title", "date_field": "date",
        "location_field": "location", "capacity_field": "capacity",
        "signups_field": "signups",
        "roles": [{"id": "greeter", "label": "Greeter", "needed": 2},
                  {"id": "sound", "label": "Sound", "needed": 1}],
        "occasion_noun": "Service",
    }
    p.update(over)
    return p


def _entry(**data_over):
    data = {"title": "Church Picnic", "date": "2099-06-01",
            "location": "The park", "capacity": 3, "signups": []}
    data.update(data_over)
    return {"id": ENTRY, "module_id": MOD, "data": data}


class FakeSB:
    """Stateful fake: contacts POSTed become visible to later ilike GETs,
    and module_entries PATCHes update the entry — so dedup + double-tap
    tests exercise the real read-before-write logic."""

    def __init__(self, *, business=None, modules=None, entry=None):
        self.business = business if business is not None else {
            "id": BIZ, "name": "First Light", "type": "church",
            "settings": {"events_public": {"enabled": True}}}
        self.modules = modules if modules is not None else [
            {"id": MOD, "name": "Occasions", "archetype_params": _params()}]
        self.entry = entry if entry is not None else _entry()
        self.contacts = []
        self.posts = []
        self.patches = []
        self._id = 0

    def sb_get_as_service(self, path):
        if path.startswith("/business_sites?"):
            return [{"business_id": BIZ, "slug": "first-light"}]
        if path.startswith("/businesses?"):
            return [self.business] if self.business else []
        if path.startswith("/custom_modules?"):
            return list(self.modules)
        if path.startswith("/module_entries?"):
            return [self.entry] if self.entry else []
        if path.startswith("/contacts?") and "email=ilike." in path:
            pattern = urllib.parse.unquote(
                path.split("email=ilike.")[1].split("&")[0])
            email = (pattern.replace("\\%", "%").replace("\\_", "_")
                     .replace("\\\\", "\\"))
            return [{"id": c["id"]} for c in self.contacts
                    if (c.get("email") or "").lower() == email.lower()][:1]
        return []

    def sb_post_as_service(self, path, payload, **kw):
        self._id += 1
        row = dict(payload)
        row["id"] = f"row-{self._id}"
        self.posts.append((path, row))
        if path.startswith("/contacts"):
            self.contacts.append(row)
        return [row]

    def sb_patch_as_service(self, path, payload):
        self.patches.append((path, payload))
        if path.startswith("/module_entries") and self.entry:
            self.entry = {**self.entry, **payload}
        return []


class ExplodingSB:
    """Any call proves the rate limiter did NOT run first."""

    def __getattr__(self, name):
        raise AssertionError(f"sb_clients.{name} called before rate limit")


@pytest.fixture
def fake_sb(monkeypatch):
    fake = FakeSB()
    monkeypatch.setattr(er, "sb_clients", fake)
    return fake


def _rsvp(body):
    return asyncio.run(er.public_event_rsvp("first-light", body, _request()))


def _body(**over):
    b = {"entry_id": ENTRY, "name": "Sam Rivers", "email": "sam@example.com"}
    b.update(over)
    return b


# ─── 1. The gate ─────────────────────────────────────────────────────


def test_gate_off_is_404(fake_sb):
    fake_sb.business["settings"] = {}
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body())
    assert exc.value.status_code == 404


def test_gate_needs_a_roster_module(fake_sb):
    fake_sb.modules = []
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body())
    assert exc.value.status_code == 404


def test_gate_is_vertical_agnostic():
    """Deliberately broader than giving: a coach's group workshop
    qualifies — the module + the toggle are the gate, not the vertical."""
    coach = {"id": BIZ, "type": "coaching",
             "settings": {"events_public": {"enabled": True}}}
    mods = [{"id": MOD, "archetype_params": {}}]
    assert er.events_public_is_active(coach, mods) is True
    assert er.events_public_is_active(coach, []) is False
    coach_off = {**coach, "settings": {}}
    assert er.events_public_is_active(coach_off, mods) is False


def test_gate_tolerates_malformed_settings():
    junk = {"id": BIZ, "settings": {"events_public": "junk"}}
    assert er.events_public_is_active(junk, [{"id": MOD}]) is False
    assert er.events_public_is_active({"id": BIZ}, [{"id": MOD}]) is False


# ─── 2. Signup append shape ──────────────────────────────────────────


def test_signup_appends_the_internal_tsx_shape(fake_sb):
    fake_sb.entry["data"]["signups"] = [
        {"name": "Pat", "status": "yes"}]     # operator-typed, survives
    out = _rsvp(_body(role="greeter"))
    assert out["ok"] is True and out["already"] is False
    assert out["attending"] == 2
    patched = [p for (path, p) in fake_sb.patches
               if path.startswith("/module_entries")]
    assert len(patched) == 1
    signups = patched[0]["data"]["signups"]
    assert signups[0] == {"name": "Pat", "status": "yes"}
    new = signups[1]
    assert new["name"] == "Sam Rivers"
    assert new["status"] == "yes"
    assert new["role"] == "greeter"
    assert new["contact_id"]           # linked to the created contact
    # Nothing outside the Signup shape leaks into the roster row.
    assert set(new.keys()) <= {"contact_id", "name", "status", "role", "note"}


def test_signup_without_role_omits_the_key(fake_sb):
    _rsvp(_body())
    new = fake_sb.patches[-1][1]["data"]["signups"][-1]
    assert "role" not in new


def test_other_entry_data_is_preserved(fake_sb):
    _rsvp(_body())
    data = fake_sb.patches[-1][1]["data"]
    assert data["title"] == "Church Picnic"
    assert data["capacity"] == 3


# ─── 3. Contact dedup + idempotent double-tap ────────────────────────


def test_contact_deduped_by_email_case_insensitive(fake_sb):
    fake_sb.contacts.append({"id": "c-old", "email": "SAM@example.com"})
    _rsvp(_body())
    # No second contact created; signup linked to the existing row.
    assert not [p for (path, p) in fake_sb.posts if path.startswith("/contacts")]
    new = fake_sb.patches[-1][1]["data"]["signups"][-1]
    assert new["contact_id"] == "c-old"


def test_new_contact_created_with_rsvp_source(fake_sb):
    _rsvp(_body())
    contact_posts = [p for (path, p) in fake_sb.posts
                     if path.startswith("/contacts")]
    assert len(contact_posts) == 1
    assert contact_posts[0]["source"] == "event_rsvp"
    assert contact_posts[0]["email"] == "sam@example.com"
    assert contact_posts[0]["status"] == "lead"


def test_double_tap_is_idempotent(fake_sb):
    first = _rsvp(_body())
    assert first["already"] is False
    second = _rsvp(_body())
    assert second["already"] is True
    assert second["attending"] == 1
    # Only ONE module_entries patch — the double-tap wrote nothing.
    entry_patches = [p for (path, p) in fake_sb.patches
                     if path.startswith("/module_entries")]
    assert len(entry_patches) == 1


# ─── 4. Capacity + roles honored server-side ─────────────────────────


def test_full_occasion_refuses_409(fake_sb):
    fake_sb.entry["data"]["capacity"] = 2
    fake_sb.entry["data"]["signups"] = [
        {"name": "A", "status": "yes"}, {"name": "B", "status": "yes"}]
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body())
    assert exc.value.status_code == 409
    assert not fake_sb.patches


def test_maybes_do_not_hold_seats(fake_sb):
    fake_sb.entry["data"]["capacity"] = 2
    fake_sb.entry["data"]["signups"] = [
        {"name": "A", "status": "yes"}, {"name": "B", "status": "maybe"}]
    out = _rsvp(_body())
    assert out["ok"] is True


def test_unknown_role_is_400(fake_sb):
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body(role="pyrotechnics"))
    assert exc.value.status_code == 400


def test_full_role_refuses_409(fake_sb):
    fake_sb.entry["data"]["signups"] = [
        {"name": "A", "status": "yes", "role": "sound"}]   # sound needs 1
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body(role="sound"))
    assert exc.value.status_code == 409
    # ...but the greeter role (needs 2, has 0) still accepts.
    out = _rsvp(_body(email="other@example.com", role="greeter"))
    assert out["ok"] is True


def test_wrong_business_entry_is_404(fake_sb):
    fake_sb.entry = {"id": ENTRY, "module_id": "someone-elses-module",
                     "data": {}}
    with pytest.raises(HTTPException) as exc:
        _rsvp(_body())
    assert exc.value.status_code == 404


# ─── 5. Rate limit BEFORE any read/write ─────────────────────────────


def test_rate_limit_runs_before_any_db_call(monkeypatch):
    monkeypatch.setattr(er, "sb_clients", ExplodingSB())
    req = _request()
    ip = req.client.host
    for _ in range(er.RSVP_RATE_MAX_PER_MIN):
        assert er._check_rsvp_rate(ip) is True
    with pytest.raises(HTTPException) as exc:
        asyncio.run(er.public_event_rsvp("first-light", _body(), req))
    assert exc.value.status_code == 429


def test_validation_runs_before_any_db_call(monkeypatch):
    monkeypatch.setattr(er, "sb_clients", ExplodingSB())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(er.public_event_rsvp(
            "first-light", {"entry_id": ENTRY, "name": "Sam",
                            "email": "not-an-email"}, _request()))
    assert exc.value.status_code == 400


# ─── 6. build_occasions (pure) ───────────────────────────────────────


def _mods():
    return [{"id": MOD, "archetype_params": _params()}]


def test_occasions_upcoming_dated_sorted():
    from datetime import date
    entries = {MOD: [
        {"id": "e1", "module_id": MOD,
         "data": {"title": "Later", "date": "2099-07-01", "signups": []}},
        {"id": "e2", "module_id": MOD,
         "data": {"title": "Sooner", "date": "2099-06-01", "signups": []}},
        {"id": "e3", "module_id": MOD,
         "data": {"title": "Past", "date": "2001-01-01", "signups": []}},
        {"id": "e4", "module_id": MOD,
         "data": {"title": "Undated", "signups": []}},
    ]}
    out = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    assert [o["title"] for o in out] == ["Sooner", "Later"]


def test_occasion_capacity_and_role_math():
    from datetime import date
    entries = {MOD: [{
        "id": "e1", "module_id": MOD,
        "data": {"title": "Picnic", "date": "2099-06-01", "capacity": 3,
                 "signups": [
                     {"name": "A", "status": "yes", "role": "greeter"},
                     {"name": "B", "status": "maybe"},
                     {"name": "C", "status": "yes"},
                 ]}}]}
    (o,) = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    assert o["attending"] == 2          # the maybe holds no seat
    assert o["spots_left"] == 1
    assert o["full"] is False
    greeter = next(r for r in o["roles"] if r["id"] == "greeter")
    assert greeter["filled"] == 1 and greeter["needed"] == 2
    assert greeter["full"] is False
    sound = next(r for r in o["roles"] if r["id"] == "sound")
    assert sound["filled"] == 0


def test_occasions_tolerate_junk():
    from datetime import date
    entries = {MOD: [
        {"id": "e1", "module_id": MOD, "data": None},
        {"id": "e2", "module_id": MOD,
         "data": {"title": "OK", "date": "2099-06-01",
                  "capacity": "lots", "signups": "junk"}},
    ]}
    out = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    assert len(out) == 1
    assert out[0]["capacity"] is None
    assert out[0]["attending"] == 0


def test_no_capacity_never_full():
    from datetime import date
    entries = {MOD: [{
        "id": "e1", "module_id": MOD,
        "data": {"title": "Open", "date": "2099-06-01",
                 "signups": [{"name": n, "status": "yes"}
                             for n in "abcdefgh"]}}]}
    (o,) = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    assert o["full"] is False and o["spots_left"] is None


# ─── 7. Renderers ────────────────────────────────────────────────────


def _biz():
    return {"id": BIZ, "name": "First Light",
            "settings": {"events_public": {"enabled": True}}}


def test_page_renders_form_for_open_occasion():
    from datetime import date
    entries = {MOD: [{
        "id": "e1", "module_id": MOD,
        "data": {"title": "Picnic <script>", "date": "2099-06-01",
                 "capacity": 3, "signups": []}}]}
    occ = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    html = er.render_events_page(
        _biz(), occ, "https://first-light.mysolutionist.app/events",
        "first-light", api_origin="https://api.example")
    assert "Count me in" in html
    assert 'data-entry="e1"' in html
    assert "Picnic &lt;script&gt;" in html      # escaped
    assert "Greeter (needs 2)" in html          # open role in the select


def test_page_full_occasion_shows_full_and_no_form():
    from datetime import date
    entries = {MOD: [{
        "id": "e1", "module_id": MOD,
        "data": {"title": "Packed", "date": "2099-06-01", "capacity": 1,
                 "signups": [{"name": "A", "status": "yes"}]}}]}
    occ = er.build_occasions(_mods(), entries, today=date(2099, 5, 20))
    html = er.render_events_page(
        _biz(), occ, "https://x.mysolutionist.app/events", "x",
        api_origin="https://api.example")
    assert ">Full<" in html
    assert "Count me in" not in html


def test_page_empty_state():
    html = er.render_events_page(
        _biz(), [], "https://x.mysolutionist.app/events", "x",
        api_origin="https://api.example")
    assert "Nothing on the calendar" in html


def test_unavailable_page_is_branded_and_noindex():
    html = er.render_events_unavailable_page(
        _biz(), "https://x.mysolutionist.app/events")
    assert "First Light" in html
    assert "noindex" in html
    assert "aren't available" in html.replace("&#x27;", "'")


# ─── 8. Config payload ───────────────────────────────────────────────


def test_config_payload_reports_prerequisite():
    site = {"slug": "first-light"}
    biz_on = _biz()
    out = er._config_payload(biz_on, site, [{"id": MOD}])
    assert out["enabled"] is True and out["active"] is True
    assert out["url"] == "https://first-light.mysolutionist.app/events"
    out2 = er._config_payload(biz_on, site, [])
    assert out2["has_roster_modules"] is False and out2["active"] is False
