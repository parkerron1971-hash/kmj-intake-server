"""
test_care_desk.py — Prayer & care as a care desk (Kevin, 2026-11-18).

Kevin approved the care desk mock (artifact BJhieg2rPsVoEzqj2qCGmw) and said
"build it", with three calls of his own: help is never the treasurer's to
take (the pastor decides, the treasurer pays); the page locks when no work
has been done and asks for a password, "custom to settings because others
might like something else"; help stays with office logins.

The server half pinned here:
  * the hand-off list names each login's person and what they do, and a
    request that needs a pastor goes only to a login whose person holds a
    pastor role;
  * the teammate who has a request may give it back;
  * the owner may hand a shared prayer to a different member of the prayer
    team, never one kept with the pastors or one that needs a pastor;
  * the locked page's numbers carry no name, no word and no id;
  * the lock: by default the inbox asks for a care proof (POST /auth/step-up,
    scope care) for this church and this login; the church can change how
    long it waits and whether it asks; only the owner changes it, and only
    from behind the lock.

People, churches and requests here are made up.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-care-desk")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")

import church_areas  # noqa: E402
import church_keys  # noqa: E402
import ledger_unlock as L  # noqa: E402
import private_care as P  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER_BIZ = "11111111-1111-1111-1111-999999999999"
OWNER = "44444444-4444-4444-4444-444444444444"
PASTOR = "55555555-5555-5555-5555-555555555555"      # Associate Pastor's login
CARE = "66666666-6666-6666-6666-666666666666"        # People & Care lane
TREASURER = "77777777-7777-7777-7777-777777777777"   # Treasurer lane
STRANGER = "88888888-8888-8888-8888-888888888888"

PASTOR_P = "c0000000-0000-4000-8000-000000000001"
CARE_P = "c0000000-0000-4000-8000-000000000002"
LEADER_P = "c0000000-0000-4000-8000-000000000003"    # Intercessor leader (member app)
PRAYS_P = "c0000000-0000-4000-8000-000000000004"     # an intercessor

CRISIS = "22222222-2222-2222-2222-000000000001"
SHARED = "22222222-2222-2222-2222-000000000002"
PRIVATE = "22222222-2222-2222-2222-000000000003"
DONE = "22222222-2222-2222-2222-000000000004"
HANDED = "22222222-2222-2222-2222-000000000005"
NOTE = "33333333-3333-3333-3333-333333333333"

SEATS = [
    {"user_id": PASTOR, "role": "admin", "invited_email": "lydia@church.test", "name": "Lydia Chen",
     "contact_id": PASTOR_P, "lane": ""},
    {"user_id": CARE, "role": "manager", "invited_email": "jess@church.test", "name": "",
     "contact_id": CARE_P, "lane": "people_care"},
    {"user_id": TREASURER, "role": "admin", "invited_email": "gloria@church.test", "name": "Gloria Banks",
     "contact_id": None, "lane": "treasurer"},
]
DEFS = [
    {"key": "associate_pastor", "title": "Associate Pastor", "job": "pastoral", "handles": ["pastor_ask"]},
    {"key": "care_team", "title": "Care team", "job": "care", "handles": ["care_need"]},
]
HELD = [{"contact_id": PASTOR_P, "role": "associate_pastor"}, {"contact_id": CARE_P, "role": "care_team"}]


def _row(rid, **kw):
    base = {"id": rid, "status": "new", "prayed_at": None, "status_changed_at": None, "assigned_to": None,
            "contact_id": None, "prayer_team": False, "needs_pastor": False, "leader_contact_id": None,
            "leader_prayed_at": None, "created_at": "2026-11-17T15:00:00Z",
            "submission": {"name": "Ada Example", "prayer_request": "For my family"}}
    base.update(kw)
    return base


class Fake:
    def __init__(self, settings=None, settings_fail=False, sample=False):
        self.requests = [
            _row(CRISIS, needs_pastor=True, submission={"name": "Ada Example", "prayer_request": "My brother died"}),
            _row(SHARED, prayer_team=True, leader_contact_id=LEADER_P),
            _row(PRIVATE),
            _row(DONE, prayed_at="2026-11-16T10:00:00Z"),
            _row(HANDED, assigned_to=CARE),
        ]
        self.settings = settings
        self.settings_fail = settings_fail
        self.sample = sample
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        table, _, query = path.partition("?")
        table = table.strip("/")
        if table == "businesses":
            if "owner_name" in query:
                return [{"owner_name": "Andre Mitchell"}]
            if "is_sample" in query:
                return [{"is_sample": self.sample}]
            return [{"id": BIZ, "owner_id": OWNER}]
        if table == "business_users":
            if "user_id=eq." in query:
                uid = query.split("user_id=eq.", 1)[1].split("&", 1)[0]
                seat = next((s for s in SEATS if s["user_id"] == uid), None)
                return [{"role": seat["role"]}] if seat else []
            return [dict(s) for s in SEATS]
        if table == "church_leader_roles":
            return [dict(h) for h in HELD]
        if table == "ministry_care_settings":
            if self.settings_fail:
                return None
            return [dict(self.settings)] if self.settings else []
        if table == "ministry_care_requests":
            if query.startswith("id=eq."):
                rid = query.split("id=eq.", 1)[1].split("&", 1)[0]
                return [dict(r) for r in self.requests if r["id"] == rid]
            rows = list(self.requests)
            if "or=(" in query:
                uid = query.split("assigned_to.eq.", 1)[1].split(",", 1)[0]
                rows = [r for r in rows if r["assigned_to"] == uid
                        or (r["prayer_team"] is True and r["needs_pastor"] is False)]
            elif "assigned_to=eq." in query:
                uid = query.split("assigned_to=eq.", 1)[1].split("&", 1)[0]
                rows = [r for r in rows if r["assigned_to"] == uid]
            return [dict(r) for r in rows]
        if table == "ministry_care_notes":
            if query.startswith("id=eq."):
                return [{"request_id": HANDED, "author_id": CARE}]
            return [{"id": NOTE, "request_id": PRIVATE, "body": "Called Tuesday", "created_at": "2026-11-17",
                     "author_id": PASTOR}]
        return []

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        rid = path.split("id=eq.", 1)[1].split("&", 1)[0]
        row = next(r for r in self.requests if r["id"] == rid)
        row.update(body)
        return [dict(row)]

    def post(self, path, body, **kw):
        self.calls.append(("POST", path, body))
        if path.startswith("/ministry_care_settings"):
            self.settings = dict(body)
            return [dict(body)]
        return [dict(body, id=NOTE, created_at="now")]

    def delete(self, path):
        self.calls.append(("DELETE", path, None))
        return True


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        f = Fake(**kw)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
        monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
        monkeypatch.setattr(sb_clients, "sb_delete_as_service", f.delete)
        return f
    import church_follow_up as cfu
    import church_prayer
    import church_roles
    import member_push
    monkeypatch.setattr(church_keys, "opened", lambda biz, user, area: None)
    monkeypatch.setattr(church_areas, "my_areas",
                        lambda biz, uid, role: {"areas": ["people_care"] if uid == CARE else ["office"], "by": "picked"})
    monkeypatch.setattr(cfu, "_contacts", lambda biz, ids: {
        PASTOR_P: {"id": PASTOR_P, "name": "Lydia Chen"}, CARE_P: {"id": CARE_P, "name": "Jessica Reed"}})
    monkeypatch.setattr(church_roles, "defs", lambda biz, **k: [dict(d) for d in DEFS])
    monkeypatch.setattr(church_prayer, "office_fields", lambda rows, biz: rows)
    monkeypatch.setattr(church_prayer, "office_people", lambda biz: [
        {"contact_id": LEADER_P, "name": "Renee Ellis", "role": "intercessor_leader",
         "role_title": "Intercessor leader", "leads": True, "waiting": 1},
        {"contact_id": PRAYS_P, "name": "Marcus Taylor", "role": "intercessors",
         "role_title": "Intercessors", "leads": False, "waiting": 0}])
    monkeypatch.setattr(member_push, "tell_prayed", lambda *a, **k: None)
    return install


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import intake_endpoint
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(intake_endpoint.router)
    who = {"id": OWNER}
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=who["id"], email="x@church.test")
    return TestClient(app), who


def _token(uid, biz=BIZ, ttl=600):
    return {L.UNLOCK_HEADER: L.mint(uid, L.SCOPE_CARE, biz, ttl)["token"]}


# ─── The hand-off list ────────────────────────────────────────────────

def test_the_team_says_who_each_login_is_and_what_they_do(fake):
    fake()
    team = {t["user_id"]: t for t in P._team(BIZ)}
    assert team[PASTOR]["name"] == "Lydia Chen" and team[PASTOR]["titles"] == ["Associate Pastor"]
    assert team[PASTOR]["pastor"] is True and team[PASTOR]["treasurer"] is False
    # No name on the seat: the person behind it names it.
    assert team[CARE]["name"] == "Jessica Reed" and team[CARE]["care"] is True and team[CARE]["pastor"] is False
    assert team[CARE]["lane_label"] == "People & Care"
    assert team[TREASURER]["treasurer"] is True and team[TREASURER]["pastor"] is False
    assert team[TREASURER]["care"] is False


def test_a_request_that_needs_a_pastor_goes_only_to_a_pastor(fake):
    f = fake()
    owner = P.CareCaller(OWNER, True)
    for who in (TREASURER, CARE):
        with pytest.raises(HTTPException) as e:
            P.update_request(BIZ, CRISIS, assigned_to=who, caller=owner)
        assert e.value.status_code == 400 and "needs a pastor" in e.value.detail
    assert not any(m == "PATCH" for m, _, _ in f.calls)
    out = P.update_request(BIZ, CRISIS, assigned_to=PASTOR, caller=owner)
    assert out["request"]["assigned_to"] == PASTOR


def test_a_crisis_flag_that_couldnt_be_read_hands_nothing_on(fake, monkeypatch):
    """Review, 2026-11-18: if the read that carries needs_pastor fails, the
    fallback read has no such key; the hand-off must stop, not pass."""
    f = fake()
    real = f.get

    def without_flags(path):
        if "needs_pastor" in path and "id=eq." in path:
            return None
        rows = real(path)
        if isinstance(rows, list) and "id=eq." in path:
            return [{k: v for k, v in r.items() if k not in ("needs_pastor", "prayer_team")} for r in rows]
        return rows
    monkeypatch.setattr(sb_clients, "sb_get_as_service", without_flags)
    owner = P.CareCaller(OWNER, True)
    for kw in ({"assigned_to": TREASURER}, {"leader_contact_id": PRAYS_P}):
        with pytest.raises(HTTPException) as e:
            P.update_request(BIZ, CRISIS, caller=owner, **kw)
        assert e.value.status_code == 503
    assert not any(m == "PATCH" for m, _, _ in f.calls)


def test_a_teammate_sees_names_on_notes_never_email_addresses(fake, monkeypatch):
    f = fake()
    import church_follow_up as cfu
    real = f.get

    def notes_on_hers(path):
        if path.startswith("/ministry_care_notes") and "request_id=in." in path:
            return [{"id": NOTE, "request_id": HANDED, "body": "Called Tuesday", "created_at": "2026-11-17",
                     "author_id": PASTOR}]
        return real(path)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", notes_on_hers)
    monkeypatch.setattr(cfu, "_contacts", lambda biz, ids: {})
    monkeypatch.setitem(SEATS[0], "name", "")
    out = P.list_requests(BIZ, P.CareCaller(CARE, False, shared=True))
    names = [n.get("author_name") for r in out["requests"] for n in r.get("notes", [])]
    # No name on the seat or its person: the role title, never the address.
    assert names == ["Associate Pastor"]
    owner = P.list_requests(BIZ, P.CareCaller(OWNER, True))
    assert "Associate Pastor" in [n.get("author_name") for r in owner["requests"] for n in r.get("notes", [])]


def test_the_switch_turns_the_password_off_for_every_church(client, fake, monkeypatch):
    c, who = client
    fake(settings={"lock_minutes": 15, "require_password": True})
    monkeypatch.setenv("CHURCH_CARE_LOCK", "off")
    r = c.get(f"/intake/private-care/{BIZ}")
    assert r.status_code == 200 and r.json()["lock"] == {"lock_minutes": 15, "require_password": False}


def test_any_teammate_may_take_a_request_that_needs_no_pastor(fake):
    fake()
    out = P.update_request(BIZ, PRIVATE, assigned_to=TREASURER, caller=P.CareCaller(OWNER, True))
    assert out["request"]["assigned_to"] == TREASURER


def test_the_teammate_who_has_it_gives_it_back_and_nobody_else_can(fake):
    f = fake()
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, HANDED, assigned_to=None, caller=P.CareCaller(PASTOR, False))
    assert e.value.status_code == 404        # not theirs: reads as not there
    out = P.update_request(BIZ, HANDED, assigned_to=None, caller=P.CareCaller(CARE, False, shared=True))
    assert out["request"]["assigned_to"] is None
    assert [b for m, _, b in f.calls if m == "PATCH"][-1]["assigned_by"] == CARE


def test_the_list_names_the_notes_and_counts_what_each_teammate_has(fake):
    fake()
    out = P.list_requests(BIZ, P.CareCaller(OWNER, True))
    notes = next(r for r in out["requests"] if r["id"] == PRIVATE)["notes"]
    assert notes[0]["author_name"] == "Lydia Chen"
    team = {t["user_id"]: t for t in out["team"]}
    assert team[CARE]["waiting"] == 1 and team[PASTOR]["waiting"] == 0
    assert [p["name"] for p in out["prayer_team"]] == ["Renee Ellis", "Marcus Taylor"]


def test_a_teammate_gets_no_team_and_no_prayer_team(fake):
    fake()
    out = P.list_requests(BIZ, P.CareCaller(CARE, False, shared=True))
    assert out["team"] == [] and "prayer_team" not in out


# ─── The prayer team, from the office ─────────────────────────────────

def test_the_owner_hands_a_shared_prayer_to_another_intercessor(fake):
    f = fake()
    out = P.update_request(BIZ, SHARED, leader_contact_id=PRAYS_P, caller=P.CareCaller(OWNER, True))
    body = [b for m, _, b in f.calls if m == "PATCH"][-1]
    assert body["leader_contact_id"] == PRAYS_P and body["leader_role"] == "intercessors"
    assert body["leader_late_level"] == 0 and body["leader_told_at"] is None and body["leader_due_at"]
    assert out["request"]["leader_contact_id"] == PRAYS_P


@pytest.mark.parametrize("rid,why", [(CRISIS, "needs a pastor"), (PRIVATE, "kept this with the pastors")])
def test_never_a_request_kept_with_the_pastors_or_one_that_needs_one(fake, rid, why):
    f = fake()
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, rid, leader_contact_id=PRAYS_P, caller=P.CareCaller(OWNER, True))
    assert e.value.status_code == 400 and why in e.value.detail
    assert not any(m == "PATCH" for m, _, _ in f.calls)


def test_only_someone_on_the_prayer_team_and_only_by_the_owner(fake):
    fake()
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, SHARED, leader_contact_id=PASTOR_P, caller=P.CareCaller(OWNER, True))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, SHARED, leader_contact_id=PRAYS_P, caller=P.CareCaller(CARE, False, shared=True))
    assert e.value.status_code == 403


def test_a_prayer_already_prayed_over_stays_where_it_is(fake):
    f = fake()
    f.requests[1]["leader_prayed_at"] = "2026-11-17T20:00:00Z"
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, SHARED, leader_contact_id=PRAYS_P, caller=P.CareCaller(OWNER, True))
    assert e.value.status_code == 400


# ─── The locked page's numbers ────────────────────────────────────────

def test_the_owner_sees_how_many_in_each_lane_and_nothing_else(fake):
    fake()
    out = P.counts(BIZ, P.CareCaller(OWNER, True))
    assert out == {"scope": "all", "counts": {"needs_pastor": 1, "waiting": 1, "with": 2, "done": 1}}


def test_a_people_and_care_login_counts_only_what_she_can_open(fake):
    fake()
    out = P.counts(BIZ, P.CareCaller(CARE, False, shared=True))
    assert out == {"scope": "shared", "counts": {"mine": 1, "team": 1, "done": 0}}


def test_the_numbers_route_needs_no_password_and_carries_no_words(client, fake):
    c, who = client
    fake()
    r = c.get(f"/intake/private-care/{BIZ}/counts")
    assert r.status_code == 200
    text = r.text
    assert "Ada" not in text and "brother" not in text and CRISIS not in text


# ─── The lock ─────────────────────────────────────────────────────────

def test_by_default_the_inbox_asks_for_the_password(client, fake):
    c, who = client
    fake()
    r = c.get(f"/intake/private-care/{BIZ}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ledger_locked" and r.json()["detail"]["scope"] == "care"
    r = c.get(f"/intake/private-care/{BIZ}", headers=_token(OWNER))
    assert r.status_code == 200 and r.json()["lock"] == {"lock_minutes": 10, "require_password": True}


def test_a_proof_for_another_church_or_another_login_opens_nothing(client, fake):
    c, who = client
    fake()
    assert c.get(f"/intake/private-care/{BIZ}", headers=_token(OWNER, OTHER_BIZ)).status_code == 403
    assert c.get(f"/intake/private-care/{BIZ}", headers=_token(PASTOR)).status_code == 403
    other_scope = {L.UNLOCK_HEADER: L.mint(OWNER, L.SCOPE_DANGER, BIZ)["token"]}
    assert c.get(f"/intake/private-care/{BIZ}", headers=other_scope).status_code == 403


def test_every_route_that_reads_or_changes_a_request_is_behind_it(client, fake):
    c, who = client
    f = fake()
    assert c.patch(f"/intake/private-care/{BIZ}/{PRIVATE}", json={"prayed": True}).status_code == 403
    assert c.post(f"/intake/private-care/{BIZ}/{PRIVATE}/notes", json={"body": "x"}).status_code == 403
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 403
    assert c.put(f"/intake/private-care/{BIZ}/settings", json={"lock_minutes": 30}).status_code == 403
    assert not any(m in ("PATCH", "POST", "DELETE") for m, _, _ in f.calls)


def test_a_church_that_doesnt_ask_opens_without_it(client, fake):
    c, who = client
    fake(settings={"lock_minutes": 0, "require_password": False})
    r = c.get(f"/intake/private-care/{BIZ}")
    assert r.status_code == 200 and r.json()["lock"] == {"lock_minutes": 0, "require_password": False}


def test_the_made_up_sample_church_opens_without_a_password(client, fake):
    c, who = client
    fake(sample=True)
    r = c.get(f"/intake/private-care/{BIZ}")
    assert r.status_code == 200 and r.json()["lock"]["require_password"] is False
    assert c.get(f"/intake/private-care/{BIZ}/settings").json()["can_change"] is False


def test_a_failed_settings_read_keeps_the_lock_on(fake):
    fake(settings_fail=True)
    s = P.lock_settings(BIZ)
    assert s["require_password"] is True and s["lock_minutes"] == 10 and s["ready"] is False


def test_the_settings_read_says_who_may_change_them(client, fake):
    c, who = client
    fake()
    j = c.get(f"/intake/private-care/{BIZ}/settings").json()
    assert j["require_password"] is True and j["lock_minutes"] == 10 and j["can_change"] is True
    assert j["choices"] == [0, 5, 10, 15, 30, 60]
    who["id"] = CARE
    assert c.get(f"/intake/private-care/{BIZ}/settings").json()["can_change"] is False


def test_the_owner_changes_the_lock_from_behind_it(client, fake):
    c, who = client
    f = fake()
    r = c.put(f"/intake/private-care/{BIZ}/settings", json={"lock_minutes": 30, "require_password": False},
              headers=_token(OWNER))
    assert r.status_code == 200 and r.json()["lock_minutes"] == 30 and r.json()["require_password"] is False
    assert f.settings["business_id"] == BIZ and f.settings["updated_by"] == OWNER
    # Now the church doesn't ask: the inbox opens without a proof.
    assert c.get(f"/intake/private-care/{BIZ}").status_code == 200


def test_only_the_owner_changes_it_and_only_to_a_listed_choice(client, fake):
    c, who = client
    fake(settings={"lock_minutes": 10, "require_password": False})
    assert c.put(f"/intake/private-care/{BIZ}/settings", json={"lock_minutes": 7}).status_code == 400
    who["id"] = CARE
    assert c.put(f"/intake/private-care/{BIZ}/settings", json={"lock_minutes": 30}).status_code == 403


def test_saving_before_the_table_exists_is_a_plain_503(fake):
    fake(settings_fail=True)
    with pytest.raises(HTTPException) as e:
        P.save_lock_settings(BIZ, P.CareCaller(OWNER, True), lock_minutes=30)
    assert e.value.status_code == 503


# ─── The password step and renewing it ────────────────────────────────

def _stub_step_up(monkeypatch, ok=True):
    import audit_log
    import rate_limit

    async def check(email, password):
        return ok
    monkeypatch.setattr(L, "check_password", check)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)


def test_the_care_step_up_is_for_the_church_and_lasts_its_quiet_minutes(fake, monkeypatch):
    fake(settings={"lock_minutes": 15, "require_password": True})
    _stub_step_up(monkeypatch)
    user = SimpleNamespace(id=CARE, email="jess@church.test")
    out = asyncio.run(L.step_up(L._StepUpBody(business_id=BIZ, password="pw", scope="care"), user))
    assert out["expires_in"] == 15 * 60
    assert L.verify(out["token"], CARE, L.SCOPE_CARE, BIZ) and not L.verify(out["token"], CARE, L.SCOPE_CARE, OTHER_BIZ)


def test_a_church_that_never_locks_by_itself_gets_an_hour_at_a_time(fake):
    fake(settings={"lock_minutes": 0, "require_password": True})
    assert P.unlock_ttl(BIZ) == 3600


def test_a_stranger_is_refused_before_any_password_is_checked(fake, monkeypatch):
    fake()
    checked = []

    async def check(email, password):
        checked.append(email)
        return True
    monkeypatch.setattr(L, "check_password", check)
    user = SimpleNamespace(id=STRANGER, email="who@else.test")
    with pytest.raises(HTTPException) as e:
        asyncio.run(L.step_up(L._StepUpBody(business_id=BIZ, password="pw", scope="care"), user))
    assert e.value.status_code == 403 and checked == []


def test_renewing_needs_a_proof_that_hasnt_run_out(client, fake):
    c, who = client
    fake()
    assert c.post(f"/intake/private-care/{BIZ}/unlock/renew").status_code == 403
    r = c.post(f"/intake/private-care/{BIZ}/unlock/renew", headers=_token(OWNER))
    assert r.status_code == 200 and r.json()["required"] is True
    assert L.verify(r.json()["token"], OWNER, L.SCOPE_CARE, BIZ)


def test_nothing_to_renew_when_the_church_doesnt_ask(client, fake):
    c, who = client
    fake(settings={"lock_minutes": 5, "require_password": False})
    r = c.post(f"/intake/private-care/{BIZ}/unlock/renew")
    assert r.status_code == 200 and r.json() == {"ok": True, "required": False}


def test_mint_holds_a_named_lifetime_between_a_minute_and_an_hour():
    assert L.mint(OWNER, L.SCOPE_CARE, BIZ, 5)["expires_in"] == 60
    assert L.mint(OWNER, L.SCOPE_CARE, BIZ, 99999)["expires_in"] == 3600
    assert L.mint(OWNER, L.SCOPE_ACCESS, BIZ)["expires_in"] == L.UNLOCK_TTL_SECONDS
