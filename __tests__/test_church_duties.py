"""Church duties (church_duties.py, docs/CHURCH_DUTIES.md). Kevin, 2026-11-01:
"a general structure plan and customize roles as well ... yes the duties part
would be great". A duty is one job an office login does; a lane is a bundle
of them; a church moves a duty one at a time.

Pins:
  * the catalog: every duty in a real area and real lanes, money only the
    Treasurer's, and each lane's starter set read from it
  * the owner and every Admin login hold every duty, money ones too
  * a Manager holds its lane's duties by default: the lane stored on its
    login, else the lane its picked areas are exactly; no lane, none
  * a row moves a duty: then only the rows decide it, and the lane's other
    Managers no longer hold it
  * a money duty is never a Manager's, whatever a row says
  * the Executive Pastor is a lane: a login whose person holds the role, by
    its key or the catalog's, tied by its record or one email
  * a read that fails is a 503, never a yes
  * require() says whose job it is
  * PUT and undo: the owner or an admin; a money duty only to a money login;
    only logins on the church's office; one log row a change; undo steps back
  * the switch on the routes, and holds() whatever it says
  * /team/my-role carries `duties`, and never fails for them

The tables are the role tests' in-memory PostgREST, with church_duty_set
modelled on the migration's function (the PGlite check runs the real one)."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_follow_up import BIZ, OWNER  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

PLATFORM = "kmjcreativesolution@gmail.com"
ADMIN = "a1000000-0000-4000-8000-000000000001"     # Minnie, the treasurer (an Admin login)
NAIYA = "a2000000-0000-4000-8000-000000000002"     # Office & Leadership, stored
TIARA = "a3000000-0000-4000-8000-000000000003"     # People & Care, by her picked areas
LAQ = "a4000000-0000-4000-8000-000000000004"       # Sunday & Serving, stored
JESS = "a5000000-0000-4000-8000-000000000005"      # no lane; the Executive Pastor by her record
SHAP = "a6000000-0000-4000-8000-000000000006"      # Media & Communications, stored
MEM = "a7000000-0000-4000-8000-000000000007"       # a Member login
GONE = "a8000000-0000-4000-8000-000000000008"      # a login that left
STRANGER = "a9000000-0000-4000-8000-000000000009"  # no login here at all
C_JESS = "c5000000-0000-4000-8000-000000000005"
C_NAIYA = "c2000000-0000-4000-8000-000000000002"

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class DutyDB(FakeDB):
    """The role tests' fake, plus church_duty_set as the migration writes it."""

    def __init__(self, **tables):
        super().__init__(**tables)
        self.rpcs = []
        self.ticks = 0

    def post(self, path, body, prefer=None, **kw):
        if path.startswith("/rpc/church_duty_set"):
            self.rpcs.append(dict(body))
            return self.duty_set(body)
        return super().post(path, body, prefer, **kw)

    def _now(self):
        self.ticks += 1
        return (T0 + timedelta(seconds=self.ticks)).isoformat()

    def duty_set(self, b):
        biz, duty, by, undoes = b["p_business_id"], b["p_duty"], b["p_by"], b.get("p_undoes")
        to = sorted({str(u) for u in (b.get("p_user_ids") or []) if u})
        rows = self.t.setdefault("church_duty_holders", [])
        mine = [r for r in rows if r["business_id"] == biz and r["duty"] == duty]
        frm = sorted(r["user_id"] for r in mine) or None
        changes = self.t.setdefault("church_duty_changes", [])
        now = self._now()
        if undoes:
            target = next((c for c in changes if c["id"] == undoes and c["business_id"] == biz and c["duty"] == duty
                           and not c.get("undoes") and not c.get("undone_at")), None)
            if not target:
                return None   # the function raises; PostgREST answers 400; sb_clients gives None
            target["undone_at"] = now
        self.t["church_duty_holders"] = [r for r in rows if not (r["business_id"] == biz and r["duty"] == duty
                                                                 and r["user_id"] not in to)]
        for u in to:
            if not any(r["business_id"] == biz and r["duty"] == duty and r["user_id"] == u for r in mine):
                self.t["church_duty_holders"].append({"id": str(uuid.uuid4()), "business_id": biz, "duty": duty,
                                                      "user_id": u, "given_by": by, "given_at": now})
        row = {"id": str(uuid.uuid4()), "business_id": biz, "duty": duty, "from_holders": frm,
               "to_holders": to or None, "changed_by": by, "changed_at": now, "undoes": undoes, "undone_at": None}
        changes.append(row)
        return dict(row)


def _seat(uid, role, email, lane=None, areas=None, contact_id=None, name=None, status="active"):
    return {"business_id": BIZ, "user_id": uid, "role": role, "invited_email": email, "lane": lane,
            "areas": areas, "contact_id": contact_id, "name": name, "status": status}


@pytest.fixture
def db(monkeypatch):
    fake = DutyDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}}],
        business_users=[
            _seat(ADMIN, "admin", "minnie@lovecity.org", lane="treasurer", name="Minnie Tatum"),
            _seat(NAIYA, "manager", "naiya@lovecity.org", lane="office_leadership", contact_id=C_NAIYA),
            _seat(TIARA, "manager", "tiara@lovecity.org", areas=["kids_youth", "people_care", "groups_classes"],
                  name="Tiara Adams"),
            _seat(LAQ, "manager", "laquesha@lovecity.org", lane="sunday_serving", name="Laquesha Bailey-Smith"),
            _seat(JESS, "manager", "jessica@lovecity.org"),
            _seat(SHAP, "manager", "shapretta@lovecity.org", lane="media_comms", name="Shapretta McClain"),
            _seat(MEM, "member", "web@lovecity.org"),
            _seat(GONE, "manager", "gone@lovecity.org", lane="office_leadership", status="revoked"),
        ],
        contacts=[{"id": C_NAIYA, "business_id": BIZ, "name": "Naiya  Clark", "email": "naiya@lovecity.org"},
                  {"id": C_JESS, "business_id": BIZ, "name": "Jessica McCloud", "email": "Jessica@LoveCity.org"}],
        church_role_defs=[{"business_id": BIZ, "key": "executive_pastor", "catalog_key": "executive_pastor",
                           "title": "Executive Pastor", "job": "pastoral", "status": "active"}],
        church_leader_roles=[{"business_id": BIZ, "contact_id": C_JESS, "role": "executive_pastor", "status": "active"}],
        church_duty_holders=[], church_duty_changes=[],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    for k in ("CHURCH_DUTIES", "CHURCH_AREAS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PLATFORM)
    return fake


@pytest.fixture(autouse=True)
def _fresh_cache():
    cd._CACHE.clear()
    cd._FAILED.clear()
    yield
    cd._CACHE.clear()
    cd._FAILED.clear()


def _u(uid, email=None):
    return SimpleNamespace(id=uid, email=email)


def _held(uid):
    return {k for k in cd.CATALOG if cd.holds(BIZ, _u(uid), k)}


def _move(db, duty, *uids):
    for u in uids:
        db.t["church_duty_holders"].append({"business_id": BIZ, "duty": duty, "user_id": u})
    cd._CACHE.clear()


MONEY = {k for k, d in cd.CATALOG.items() if d["money"]}


# ─── The catalog ──────────────────────────────────────────────────────

def test_every_duty_is_in_a_real_area_and_real_lanes_with_its_day_and_training_line():
    assert len(cd.CATALOG) >= 20
    for key, d in cd.CATALOG.items():
        assert key == key.lower() and 2 <= len(key) <= 40, key
        assert d["area"] in ca.AREA_ORDER, key
        assert d["lanes"] and all(ln in cd.LANE_KEYS for ln in d["lanes"]), key
        assert d["label"] and d["day"] and d["does"].endswith(".") and d["opens"], key
        assert isinstance(d["money"], bool)
    assert cd.LANE_KEYS == tuple(ca.LANES) + ("executive_pastor",)


def test_money_is_only_the_treasurers_and_only_in_giving():
    assert MONEY == {"deposit", "books", "pay", "store"}
    for k, d in cd.CATALOG.items():
        assert d["money"] == (d["lanes"] == ["treasurer"]) == (d["area"] == "giving_money"), k
    # The Treasurer's lane is an Admin login: money opens only to admins.
    assert ca.LANES["treasurer"]["role"] == "admin"


def test_each_lanes_starter_set_is_read_from_the_catalog():
    assert cd.STARTER["office_leadership"] == ["weekly_text", "leaders_note", "meetings", "rooms", "chat_rules",
                                               "leaders_list"]
    assert cd.STARTER["people_care"] == ["care_board", "shepherding", "kids"]
    assert cd.STARTER["sunday_serving"] == ["rooms", "sunday_plan", "serve_schedule", "events", "attendance",
                                            "churchsavvy_team"]
    assert cd.STARTER["media_comms"] == ["serve_schedule", "events", "posts", "clips", "stream", "website",
                                         "churchsavvy_team"]
    assert cd.STARTER["executive_pastor"] == ["monthly_report", "oversee_lanes"]
    assert cd.STARTER["treasurer"] == ["deposit", "books", "pay", "store"]
    # Every duty starts with somebody.
    assert set(cd.CATALOG) == {k for keys in cd.STARTER.values() for k in keys}


# ─── Who holds what ───────────────────────────────────────────────────

def test_the_owner_and_admins_hold_every_duty_money_too(db):
    assert _held(OWNER) == set(cd.CATALOG)
    assert _held(ADMIN) == set(cd.CATALOG)
    # Even a duty moved to someone else.
    _move(db, "weekly_text", NAIYA)
    assert cd.holds(BIZ, _u(OWNER), "weekly_text") and cd.holds(BIZ, _u(ADMIN), "weekly_text")


def test_a_manager_holds_its_lanes_duties_by_default(db):
    assert _held(NAIYA) == set(cd.STARTER["office_leadership"])           # stored
    assert _held(TIARA) == set(cd.STARTER["people_care"])                 # her picked areas are the lane, exactly
    assert _held(LAQ) == set(cd.STARTER["sunday_serving"])
    assert _held(SHAP) == set(cd.STARTER["media_comms"])


def test_a_manager_with_no_lane_a_member_a_login_that_left_and_a_stranger_hold_none(db):
    db.t["church_leader_roles"].clear()
    assert _held(JESS) == set()
    assert _held(MEM) == set()
    assert _held(GONE) == set()
    assert _held(STRANGER) == set()
    # Areas that aren't exactly a lane make no lane.
    next(s for s in db.t["business_users"] if s["user_id"] == TIARA)["areas"] = ["people_care"]
    cd._CACHE.clear()
    assert _held(TIARA) == set()


def test_a_row_moves_a_duty_and_the_lane_default_no_longer_decides_it(db):
    _move(db, "weekly_text", TIARA)
    assert cd.holds(BIZ, _u(TIARA), "weekly_text")
    assert not cd.holds(BIZ, _u(NAIYA), "weekly_text")
    # Only that duty moved: the rest of each lane is as it was.
    assert _held(NAIYA) == set(cd.STARTER["office_leadership"]) - {"weekly_text"}
    assert _held(TIARA) == set(cd.STARTER["people_care"]) | {"weekly_text"}
    # Rooms is two lanes' by default; moved to Laquesha, it's hers alone.
    _move(db, "rooms", LAQ)
    assert cd.holds(BIZ, _u(LAQ), "rooms") and not cd.holds(BIZ, _u(NAIYA), "rooms")


def test_a_money_duty_is_never_a_managers_whatever_a_row_says(db):
    _move(db, "books", NAIYA)
    assert not cd.holds(BIZ, _u(NAIYA), "books")
    # Nor by a lane stored on a Manager's login.
    next(s for s in db.t["business_users"] if s["user_id"] == LAQ)["lane"] = "treasurer"
    cd._CACHE.clear()
    assert _held(LAQ) & MONEY == set()
    # The admins still do.
    assert cd.holds(BIZ, _u(ADMIN), "books")


def test_the_executive_pastor_is_a_lane_by_her_record(db):
    # No contact tied to her login: her email names exactly one person, who holds the role.
    assert _held(JESS) == {"monthly_report", "oversee_lanes"}
    # Tied to her record, the record decides, not the email.
    seat = next(s for s in db.t["business_users"] if s["user_id"] == JESS)
    seat["contact_id"] = C_NAIYA
    cd._CACHE.clear()
    assert _held(JESS) == set()
    seat["contact_id"] = C_JESS
    cd._CACHE.clear()
    assert _held(JESS) == {"monthly_report", "oversee_lanes"}
    # On top of a lane of her own.
    seat["lane"] = "people_care"
    cd._CACHE.clear()
    assert _held(JESS) == {"monthly_report", "oversee_lanes", *cd.STARTER["people_care"]}


def test_the_executive_pastor_by_the_catalogs_key_and_only_once_she_said_yes(db):
    db.t["church_role_defs"][0].update({"key": "exec_pastor_lc", "title": "Executive Pastor"})
    db.t["church_leader_roles"][0]["role"] = "exec_pastor_lc"
    assert _held(JESS) == {"monthly_report", "oversee_lanes"}
    db.t["church_leader_roles"][0]["status"] = "invited"
    cd._CACHE.clear()
    assert _held(JESS) == set()
    db.t["church_leader_roles"][0]["status"] = "active"
    db.t["church_role_defs"][0]["status"] = "archived"
    cd._CACHE.clear()
    assert _held(JESS) == set()


def test_a_shared_family_email_names_no_one_but_the_name_they_gave(db):
    db.t["contacts"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "name": "Jerome McCloud",
                             "email": "jessica@lovecity.org"})
    assert _held(JESS) == set()
    next(s for s in db.t["business_users"] if s["user_id"] == JESS)["name"] = "Jessica"
    cd._CACHE.clear()
    assert _held(JESS) == {"monthly_report", "oversee_lanes"}


def test_once_every_executive_duty_has_moved_her_role_isnt_read(db, monkeypatch):
    _move(db, "monthly_report", JESS)
    _move(db, "oversee_lanes", JESS)
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: pytest.fail(path) if "church_role_defs" in path else real(path, **kw))
    assert _held(NAIYA) == set(cd.STARTER["office_leadership"])
    assert _held(JESS) == {"monthly_report", "oversee_lanes"}


@pytest.mark.parametrize("table", ["businesses", "business_users", "church_duty_holders", "church_role_defs",
                                   "church_leader_roles", "contacts"])
def test_a_failed_read_is_a_503_never_a_yes(db, monkeypatch, table):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    with pytest.raises(HTTPException) as e:
        cd.holds(BIZ, _u(JESS), "monthly_report")
    assert e.value.status_code == 503
    # And nothing was kept from it.
    assert not cd._CACHE


def test_a_duty_that_isnt_in_the_catalog_is_a_mistake_not_a_no(db):
    with pytest.raises(ValueError):
        cd.holds(BIZ, _u(OWNER), "sunday_lunch")


def test_outside_a_church_only_the_owner_and_admins_hold_anything(db):
    db.t["businesses"][0]["type"] = "salon"
    assert _held(NAIYA) == set()
    assert _held(OWNER) == set(cd.CATALOG)
    assert cd.duties_of(BIZ, OWNER, "owner") is None


def test_a_logins_duties_are_kept_a_minute(db, monkeypatch):
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")
    _move_quietly = db.t["church_duty_holders"].append
    _move_quietly({"business_id": BIZ, "duty": "weekly_text", "user_id": TIARA})
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")          # still the minute-old answer
    now = cd.time.monotonic()
    monkeypatch.setattr(cd.time, "monotonic", lambda: now + cd.CACHE_SECONDS + 1)
    assert not cd.holds(BIZ, _u(NAIYA), "weekly_text")


def test_the_minute_old_answers_are_dropped_as_new_ones_come(db, monkeypatch):
    cd.holds(BIZ, _u(NAIYA), "weekly_text")
    cd.holds(BIZ, _u(TIARA), "care_board")
    assert len(cd._CACHE) == 2
    now = cd.time.monotonic()
    monkeypatch.setattr(cd.time, "monotonic", lambda: now + cd.CACHE_SECONDS + 1)
    cd.holds(BIZ, _u(LAQ), "rooms")
    assert list(cd._CACHE) == [(BIZ, LAQ)]


# ─── require() ────────────────────────────────────────────────────────

def test_require_says_whose_job_it_is(db):
    cd.require(BIZ, _u(NAIYA), "weekly_text")
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(TIARA), "weekly_text")
    assert e.value.status_code == 403
    assert e.value.detail == ("“The weekly text” is the Office & Leadership lane's job here. "
                              "The owner or an admin can give it to you in Logins & areas.")
    _move(db, "weekly_text", NAIYA)
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(TIARA), "weekly_text")
    assert e.value.detail.startswith("“The weekly text” is Naiya's job here.")
    _move(db, "weekly_text", LAQ, OWNER)
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(TIARA), "weekly_text")
    assert e.value.detail.startswith("“The weekly text” is ") and "'s job here." in e.value.detail
    assert all(n in e.value.detail for n in ("Naiya", "Laquesha", "Pastor Kevin"))
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(TIARA), "rooms")
    assert "the Office & Leadership and Sunday & Serving lanes' job" in e.value.detail
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(NAIYA), "monthly_report")
    assert e.value.detail.startswith("“The monthly report” is the Executive Pastor's job here.")
    with pytest.raises(HTTPException) as e:
        cd.require(BIZ, _u(NAIYA), "books")
    assert e.value.detail == "“The books” is a money job, so it stays with the owner and the admins."


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    who = {"role": "owner", "email": PLATFORM, "id": OWNER}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    app = FastAPI()
    app.include_router(cd.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    client = TestClient(app)
    client.who = who
    return client


def _duty(page, key):
    return next(d for d in page["duties"] if d["key"] == key)


def test_the_page_lists_each_duty_and_who_does_it(office, db):
    page = office.get(f"/church/duties?business_id={BIZ}").json()
    assert [d["key"] for d in page["duties"]] == list(cd.CATALOG)
    wt = _duty(page, "weekly_text")
    assert wt["follows_lanes"] and wt["day"] == "Wed" and wt["lane_labels"] == ["Office & Leadership"]
    assert wt["area_label"] == "Office"
    assert [(h["user_id"], h["name"]) for h in wt["holders"]] == [(NAIYA, "Naiya Clark")]
    assert {h["user_id"] for h in _duty(page, "rooms")["holders"]} == {NAIYA, LAQ}
    assert {h["user_id"] for h in _duty(page, "monthly_report")["holders"]} == {JESS}
    # Money by default: the Treasurer's Admin login.
    assert [(h["user_id"], h["active"]) for h in _duty(page, "books")["holders"]] == [(ADMIN, True)]
    assert not wt["can_undo"] and wt["last_change"] is None
    # Each login, the owner first, with its lanes and whether money can go to it.
    assert page["logins"][0] == {"user_id": OWNER, "name": "Pastor Kevin", "role": "owner", "lanes": [], "money": True}
    jess = next(x for x in page["logins"] if x["user_id"] == JESS)
    assert jess["lanes"] == ["executive_pastor"] and jess["money"] is False
    assert GONE not in {x["user_id"] for x in page["logins"]}
    assert {ln["key"]: ln["duties"] for ln in page["lanes"]} == cd.STARTER


def test_the_page_is_for_a_manager_and_up_at_a_church(office, db):
    for role, code in (("admin", 200), ("manager", 200), ("member", 404), (None, 404)):
        office.who["role"] = role
        assert office.get(f"/church/duties?business_id={BIZ}").status_code == code, role
    office.who["role"] = "owner"
    db.t["businesses"][0]["type"] = "salon"
    assert office.get(f"/church/duties?business_id={BIZ}").status_code == 404


def test_the_switch_keeps_the_routes_to_the_platform_owner_then_everyone_or_no_one(office, db, monkeypatch):
    put = lambda: office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [NAIYA]})  # noqa: E731
    office.who["email"] = "pastor@lovecity.org"
    assert office.get(f"/church/duties?business_id={BIZ}").status_code == 404
    assert put().status_code == 404
    assert office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ}).status_code == 404
    monkeypatch.setenv("CHURCH_DUTIES", "on")
    assert office.get(f"/church/duties?business_id={BIZ}").status_code == 200
    assert put().status_code == 200
    monkeypatch.setenv("CHURCH_DUTIES", "off")
    assert office.get(f"/church/duties?business_id={BIZ}").status_code == 404
    # holds() answers whatever the switch says: it reads only rows an owner wrote.
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text") and not cd.holds(BIZ, _u(LAQ), "weekly_text")
    monkeypatch.setenv("CHURCH_DUTIES", "sometimes")
    assert office.get(f"/church/duties?business_id={BIZ}").status_code == 404


def test_an_admin_moves_a_duty_and_it_is_logged_once(office, db):
    office.who.update(role="admin", id=ADMIN)
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")      # remembered for the minute
    r = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA, TIARA]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["holders"] == [TIARA] and out["changed"] and not out["follows_lanes"]
    assert db.rpcs == [{"p_business_id": BIZ, "p_duty": "weekly_text", "p_user_ids": [TIARA], "p_by": ADMIN,
                        "p_undoes": None}]
    assert [(r["user_id"], r["given_by"]) for r in db.t["church_duty_holders"]] == [(TIARA, ADMIN)]
    [log] = db.t["church_duty_changes"]
    assert (log["from_holders"], log["to_holders"], log["changed_by"]) == (None, [TIARA], ADMIN)
    assert log["changed_at"]
    # Followed at once: the minute-old answer went with the change.
    assert not cd.holds(BIZ, _u(NAIYA), "weekly_text") and cd.holds(BIZ, _u(TIARA), "weekly_text")
    # The same names again change nothing and log nothing.
    again = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA]}).json()
    assert again["changed"] is False and len(db.t["church_duty_changes"]) == 1
    page = office.get(f"/church/duties?business_id={BIZ}").json()
    wt = _duty(page, "weekly_text")
    assert not wt["follows_lanes"] and [h["name"] for h in wt["holders"]] == ["Tiara Adams"]
    assert wt["can_undo"] and wt["last_change"]["by"] == "Minnie Tatum"


def test_none_puts_a_duty_back_to_the_lanes(office, db):
    office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA]})
    out = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": []}).json()
    assert out["follows_lanes"] and out["changed"] and db.t["church_duty_holders"] == []
    assert db.t["church_duty_changes"][-1]["to_holders"] is None
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")
    out = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": None}).json()
    assert out["changed"] is False


def test_who_a_duty_can_go_to(office, db):
    def put(duty, ids):
        return office.put(f"/church/duties/{duty}", json={"business_id": BIZ, "user_ids": ids})
    # A money duty only to a money login: the owner or an Admin.
    r = put("books", [NAIYA])
    assert r.status_code == 400 and "money job" in r.json()["detail"]
    assert put("books", [ADMIN, OWNER]).status_code == 200
    # Only logins on this church's office, and only ones that do office jobs.
    for who, words in ((STRANGER, "isn't on this church"), (GONE, "isn't on this church"), (MEM, "Member or Viewer")):
        r = put("weekly_text", [who])
        assert r.status_code == 400 and words in r.json()["detail"], who
    assert put("weekly_text", ["not-a-login"]).status_code == 400
    assert put("weekly_text", "naiya").status_code == 400
    assert put("weekly_text", [str(uuid.uuid4()) for _ in range(cd.MAX_HOLDERS + 1)]).status_code == 400
    assert put("sunday_lunch", [NAIYA]).status_code == 404
    # Nothing refused was written.
    assert {r["duty"] for r in db.t["church_duty_holders"]} == {"books"}
    assert len(db.t["church_duty_changes"]) == 1


def test_moving_is_the_owners_or_an_admins(office, db):
    for role in ("manager", "member", None):
        office.who["role"] = role
        assert office.put("/church/duties/weekly_text",
                          json={"business_id": BIZ, "user_ids": [TIARA]}).status_code == 404, role
        assert office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ}).status_code == 404, role
    assert db.rpcs == []
    office.who["role"] = "owner"
    assert office.put("/church/duties/weekly_text", json={"business_id": "nope", "user_ids": []}).status_code == 400
    db.t["businesses"][0]["type"] = "salon"
    assert office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": []}).status_code == 404


def test_undo_puts_the_last_change_back_then_the_one_before(office, db):
    office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [NAIYA]})
    office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [NAIYA, LAQ]})
    first, second = db.t["church_duty_changes"]
    # The read comes back in any order; the newest is put back first.
    db.t["church_duty_changes"].reverse()
    r = office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    assert r.json()["holders"] == [NAIYA] and r.json()["change"]["undoes"] == second["id"]
    assert second["undone_at"] and not cd.holds(BIZ, _u(LAQ), "weekly_text")
    r = office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ})
    assert r.json()["follows_lanes"] and r.json()["change"]["undoes"] == first["id"]
    assert db.t["church_duty_holders"] == [] and cd.holds(BIZ, _u(NAIYA), "weekly_text")
    # Every change logged: two moves and two undos. Nothing left to put back.
    assert len(db.t["church_duty_changes"]) == 4
    r = office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ})
    assert r.status_code == 404 and "Nothing to put back" in r.json()["detail"]
    # Another duty's change is its own.
    assert office.post("/church/duties/rooms/undo", json={"business_id": BIZ}).status_code == 404


def test_undo_wont_give_a_duty_back_to_someone_who_left(office, db):
    office.put("/church/duties/rooms", json={"business_id": BIZ, "user_ids": [LAQ]})
    office.put("/church/duties/rooms", json={"business_id": BIZ, "user_ids": [NAIYA]})
    next(s for s in db.t["business_users"] if s["user_id"] == LAQ)["status"] = "revoked"
    r = office.post("/church/duties/rooms/undo", json={"business_id": BIZ})
    assert r.status_code == 409 and "can't be put back" in r.json()["detail"]
    assert [h["user_id"] for h in db.t["church_duty_holders"]] == [NAIYA]


def test_a_write_that_fails_is_a_503_and_changes_nothing_remembered(office, db, monkeypatch):
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    r = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA]})
    assert r.status_code == 503


@pytest.mark.parametrize("table", ["business_users", "church_duty_holders"])
def test_a_move_whose_check_cant_be_read_is_a_503_and_writes_nothing(office, db, monkeypatch, table):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    r = office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA]})
    assert r.status_code == 503
    assert db.rpcs == [] and db.t["church_duty_holders"] == []


def test_an_undo_whose_log_cant_be_read_is_a_503(office, db, monkeypatch):
    office.put("/church/duties/weekly_text", json={"business_id": BIZ, "user_ids": [TIARA]})
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_duty_changes?") else real(path, **kw))
    assert office.post("/church/duties/weekly_text/undo", json={"business_id": BIZ}).status_code == 503
    assert len(db.rpcs) == 1


def test_a_duty_moved_to_logins_that_all_left_says_it_needs_someone(office, db):
    office.put("/church/duties/rooms", json={"business_id": BIZ, "user_ids": [LAQ]})
    page = office.get(f"/church/duties?business_id={BIZ}").json()
    assert not _duty(page, "rooms")["needs_someone"] and page["needs_someone"] == []
    next(s for s in db.t["business_users"] if s["user_id"] == LAQ)["status"] = "revoked"
    page = office.get(f"/church/duties?business_id={BIZ}").json()
    rooms = _duty(page, "rooms")
    assert rooms["needs_someone"] and page["needs_someone"] == ["rooms"]
    assert [(h["name"], h["active"]) for h in rooms["holders"]] == [("Someone who has left the office", False)]
    # The lanes don't take it back by themselves: only the owner and the admins do it now.
    assert not cd.holds(BIZ, _u(NAIYA), "rooms")


# ─── /team/my-role ────────────────────────────────────────────────────

def _my_role(uid):
    import business_users_router as bur
    return bur.my_role(BIZ, _u(uid, "someone@lovecity.org"))


def test_my_role_carries_the_logins_duties(db):
    assert _my_role(OWNER)["duties"] == list(cd.CATALOG)
    assert _my_role(ADMIN)["duties"] == list(cd.CATALOG)
    assert _my_role(NAIYA)["duties"] == cd.STARTER["office_leadership"]
    assert _my_role(JESS)["duties"] == ["monthly_report", "oversee_lanes"]
    assert _my_role(MEM)["duties"] == []
    # No standing here, or not a church: no duties at all.
    assert "duties" not in _my_role(STRANGER)
    db.t["businesses"][0]["type"] = "salon"
    cd._CACHE.clear()
    assert "duties" not in _my_role(OWNER)


def test_my_role_never_fails_for_its_duties(db, monkeypatch):
    real = db.get
    asked = []

    def get(path, **kw):
        if path.lstrip("/").startswith("church_duty_holders"):
            asked.append(path)
            return None   # the table before its migration
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    out = _my_role(NAIYA)
    assert out["ok"] and out["role"] == "manager" and "duties" not in out
    # The next app loads don't try again for a while...
    assert "duties" not in _my_role(NAIYA) and len(asked) == 1
    # ...but a job gate always asks, and a failed read is still a 503.
    with pytest.raises(HTTPException) as e:
        cd.holds(BIZ, _u(NAIYA), "weekly_text")
    assert e.value.status_code == 503 and len(asked) == 2
    # Once the wait is over, my-role asks again, and answers once it can.
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    now = cd.time.monotonic()
    monkeypatch.setattr(cd.time, "monotonic", lambda: now + cd.FAILED_SECONDS + 1)
    assert _my_role(NAIYA)["duties"] == cd.STARTER["office_leadership"]
    assert not cd._FAILED
    monkeypatch.setattr(cd, "duties_of", lambda *a: 1 / 0)
    out = _my_role(OWNER)
    assert out["ok"] and out["role"] == "owner" and "duties" not in out
