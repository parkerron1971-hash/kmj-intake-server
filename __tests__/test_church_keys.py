"""Church Areas, step 2: keepers and keys (church_keys.py). Kevin 2026-10-23:
"if Pastor look at money another leader is notified and have to recieve a
code from that person to get into money"; his picks 2026-10-26: the lock
binds the owner too, a tap with a code as the backup, a yes opens an hour.

Pins:
  * an area with no keeper has no lock; naming the first keeper locks it
    for everyone else, the owner too
  * every keeper hears an ask; a keeper's yes opens it for an hour, a no
    opens nothing, and nobody answers their own ask
  * the code a keeper reads out opens it too; five wrong tries close the ask
  * silence never opens anything: an ask lapses after a day
  * a keeper change by someone who isn't a keeper waits seven days, told to
    the keepers, unless a keeper says yes (now) or no (never)
  * a failed read is a 503, never an open area; the switch off takes every
    lock away; only an admin names keepers, and only someone with a login
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_keys as ck  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(("owner", "treasurer", "pastor", "admin", "member", "stranger", "second"), start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 15, 0, 0, 1, tzinfo=timezone.utc)


class KeysDB(FakeDB):
    """The two tables' defaults and the keepers' upsert, on the shared fake."""

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        if table == "church_area_keys":
            body = {"status": "asked", "asked_at": ck._iso(ck._now()), "code_tries": 0, "reason": "",
                    "answered_by": None, "opens_until": None, "how": None, **body}
        if table == "church_keepers":
            have = self.t.setdefault(table, [])
            old = next((r for r in have if (r["business_id"], r["area"], r["user_id"])
                        == (body["business_id"], body["area"], body["user_id"])), None)
            if old:
                old.update(body)
                return [dict(old)]
        return super().post(path, body, prefer=prefer, **kw)


@pytest.fixture
def db(monkeypatch):
    fake = KeysDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"]}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active", "invited_email": f"{n}@lovecity.org"}
                        for n, r in (("treasurer", "admin"), ("pastor", "admin"), ("admin", "admin"),
                                     ("member", "member"), ("second", "admin"))],
        church_keepers=[], church_area_keys=[],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_KEYS", "on")
    fake.clock = [T0]
    monkeypatch.setattr(ck, "_now", lambda: fake.clock[0])
    fake.told = []
    monkeypatch.setattr(ck, "_tell", lambda biz, to, title, body, seats, tag: fake.told.append((sorted(to), title, body)))
    return fake


def _later(db, **kw):
    db.clock[0] = db.clock[0] + timedelta(**kw)


def _refused(fn, *args, **kw):
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    return e.value


def _keep(db, name, area="giving_money", by="admin", keep=True):
    return ck.put_keeper(BIZ, PEOPLE[by], area, ID[name], keep)


def _code(db):
    return re.search(r"code: (\d{6})", db.told[-1][2]).group(1)


# ─── The lock ─────────────────────────────────────────────────────────

def test_an_area_with_no_keeper_has_no_lock(db):
    assert ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")
    assert _refused(ck.ask, BIZ, PEOPLE["pastor"], "giving_money", "").status_code == 409


def test_the_first_keeper_counts_at_once_and_locks_everyone_else_the_owner_too(db):
    assert _keep(db, "treasurer")["waits_until"] is None
    assert ck.is_open(BIZ, PEOPLE["treasurer"], "giving_money")
    for name in ("pastor", "owner", "admin"):
        assert not ck.is_open(BIZ, PEOPLE[name], "giving_money"), name
    locked = _refused(ck.wall, BIZ, PEOPLE["owner"], "giving_money")
    assert locked.status_code == 403 and locked.detail["code"] == "area_locked" and locked.detail["area"] == "giving_money"
    assert ck.is_open(BIZ, PEOPLE["pastor"], "kids_youth"), "only the area with a keeper is locked"
    assert ck.is_open(BIZ, PEOPLE["pastor"], "office"), "an area with nothing guarded has no lock"


# ─── A key ────────────────────────────────────────────────────────────

def test_every_keeper_hears_and_a_tap_opens_an_hour(db):
    _keep(db, "treasurer")
    _keep(db, "second", by="treasurer")
    got = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "Checking the building fund")
    assert got["told"] == 2
    to, title, body = db.told[-1]
    assert to == sorted([ID["treasurer"], ID["second"]]) and title == "pastor@lovecity.org asks for a key to Giving & money"
    assert "Checking the building fund" in body and re.search(r"code: \d{6}", body)
    again = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")
    assert again["told"] == 0 and again["key"]["id"] == got["key"]["id"], "asking again doesn't ring twice"
    kid = got["key"]["id"]
    assert _refused(ck.answer, BIZ, PEOPLE["admin"], kid, True).status_code == 403, "not a keeper"
    assert ck.answer(BIZ, PEOPLE["treasurer"], kid, True)["key"]["status"] == "open"
    assert db.told[-1][0] == [ID["pastor"]] and "open for an hour" in db.told[-1][1]
    assert _refused(ck.answer, BIZ, PEOPLE["second"], kid, True).status_code == 409, "answered once"
    assert ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")
    assert not ck.is_open(BIZ, PEOPLE["owner"], "giving_money"), "a key is one person's"
    _later(db, minutes=61)
    assert not ck.is_open(BIZ, PEOPLE["pastor"], "giving_money"), "an hour, then locked again"


def test_nobody_answers_their_own_ask_and_a_no_opens_nothing(db):
    _keep(db, "treasurer")
    _keep(db, "pastor", by="treasurer", area="people_care")
    kid = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")["key"]["id"]
    assert ck.answer(BIZ, PEOPLE["treasurer"], kid, False)["key"]["status"] == "declined"
    assert not ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")
    # Someone who asks and is then made a keeper still never answers that ask.
    kid = ck.ask(BIZ, PEOPLE["admin"], "giving_money", "")["key"]["id"]
    _keep(db, "admin", by="treasurer")
    assert "their own ask" in _refused(ck.answer, BIZ, PEOPLE["admin"], kid, True).detail
    # A keeper asking for an area they keep: there's nothing to ask for.
    assert _refused(ck.ask, BIZ, PEOPLE["treasurer"], "giving_money", "").status_code == 409


def test_the_code_a_keeper_reads_out_opens_it_and_keepers_hear(db):
    _keep(db, "treasurer")
    kid = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")["key"]["id"]
    code = _code(db)
    assert _refused(ck.enter_code, BIZ, PEOPLE["owner"], kid, code).status_code == 403, "only the asker enters it"
    wrong = "000000" if code != "000000" else "111111"
    assert "4 tries left" in _refused(ck.enter_code, BIZ, PEOPLE["pastor"], kid, wrong).detail
    assert ck.enter_code(BIZ, PEOPLE["pastor"], kid, code[:3] + " " + code[3:])["key"]["status"] == "open"
    row = db.t["church_area_keys"][0]
    assert row["how"] == "code" and row["answered_by"] is None and row["code_hash"] != code
    assert db.told[-1][0] == [ID["treasurer"]] and "with a code" in db.told[-1][1]
    assert ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")


def test_five_wrong_codes_close_the_ask(db):
    _keep(db, "treasurer")
    kid = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")["key"]["id"]
    code = _code(db)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert _refused(ck.enter_code, BIZ, PEOPLE["pastor"], kid, wrong).status_code == 400
    assert _refused(ck.enter_code, BIZ, PEOPLE["pastor"], kid, wrong).status_code == 403
    assert _refused(ck.enter_code, BIZ, PEOPLE["pastor"], kid, code).status_code == 409, "closed: the right code is too late"
    assert not ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")


def test_silence_never_opens_anything_an_ask_lapses_after_a_day(db):
    _keep(db, "treasurer")
    kid = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")["key"]["id"]
    code = _code(db)
    _later(db, hours=25)
    assert _refused(ck.answer, BIZ, PEOPLE["treasurer"], kid, True).status_code == 410
    assert db.t["church_area_keys"][0]["status"] == "expired"
    assert not ck.is_open(BIZ, PEOPLE["pastor"], "giving_money")
    assert ck.overview(BIZ, PEOPLE["treasurer"])["waiting"] == []
    fresh = ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "")
    assert fresh["told"] == 1 and fresh["key"]["id"] != kid
    assert _refused(ck.enter_code, BIZ, PEOPLE["pastor"], kid, code).status_code == 409


# ─── Keepers ──────────────────────────────────────────────────────────

def test_nobody_makes_themselves_a_keeper_to_get_in(db):
    _keep(db, "treasurer")
    waits = _keep(db, "owner", by="owner")["waits_until"]
    assert waits and ck._at(waits) == T0 + timedelta(days=7)
    assert not ck.is_open(BIZ, PEOPLE["owner"], "giving_money"), "not a keeper for seven days"
    assert db.told[-1][0] == [ID["treasurer"]] and "wants to add a keeper" in db.told[-1][1]
    ck.answer_change(BIZ, PEOPLE["treasurer"], "giving_money", ID["owner"], False)
    _later(db, days=8)
    assert not ck.is_open(BIZ, PEOPLE["owner"], "giving_money"), "a keeper's no cancels it"
    _keep(db, "owner", by="owner")
    ck.answer_change(BIZ, PEOPLE["treasurer"], "giving_money", ID["owner"], True)
    assert ck.is_open(BIZ, PEOPLE["owner"], "giving_money"), "a keeper's yes makes it now"


def test_nobody_takes_the_keepers_away_to_get_in(db):
    _keep(db, "treasurer")
    assert _keep(db, "treasurer", by="admin", keep=False)["waits_until"]
    assert not ck.is_open(BIZ, PEOPLE["admin"], "giving_money"), "the keeper stays for seven days"
    assert _refused(ck.answer_change, BIZ, PEOPLE["admin"], "giving_money", ID["treasurer"], True).status_code == 403
    _later(db, days=7, minutes=1)
    assert ck.is_open(BIZ, PEOPLE["admin"], "giving_money"), "after the wait, no keeper and no lock"


def test_a_keepers_own_change_counts_at_once(db):
    _keep(db, "treasurer")
    assert _keep(db, "second", by="treasurer")["waits_until"] is None
    assert _keep(db, "treasurer", by="second", keep=False)["waits_until"] is None
    assert not ck.is_open(BIZ, PEOPLE["treasurer"], "giving_money")
    assert ck.is_open(BIZ, PEOPLE["second"], "giving_money")


def test_only_an_admin_names_keepers_and_a_keeper_has_a_login(db):
    c = _client(db, "member")
    r = c.put("/church/keepers", json={"business_id": BIZ, "area": "giving_money", "user_id": ID["treasurer"]})
    assert r.status_code == 404 and db.t["church_keepers"] == []
    assert _refused(_keep, db, "stranger").status_code == 400
    r = _client(db, "admin").put("/church/keepers", json={"business_id": BIZ, "area": "office", "user_id": ID["treasurer"]})
    assert r.status_code == 400, "nothing in Office is locked"


# ─── What one person sees ─────────────────────────────────────────────

def test_the_overview_shows_keepers_my_key_and_what_waits_on_me(db):
    _keep(db, "treasurer")
    _keep(db, "owner", by="admin")
    ck.ask(BIZ, PEOPLE["pastor"], "giving_money", "Year-end statements")
    mine = ck.overview(BIZ, PEOPLE["pastor"])
    giving = next(a for a in mine["areas"] if a["area"] == "giving_money")
    assert giving["locked"] and giving["label"] == "Giving & money" and giving["me"]["keeper"] is False
    assert giving["me"]["asked"]["reason"] == "Year-end statements" and giving["me"]["open_until"] is None
    assert [(k["who"], k["pending"]) for k in giving["keepers"]] == [
        ("treasurer@lovecity.org", None), ("The owner", "adding")]
    assert mine["waiting"] == []
    theirs = ck.overview(BIZ, PEOPLE["treasurer"])
    assert [(w["who"], w["reason"]) for w in theirs["waiting"]] == [("pastor@lovecity.org", "Year-end statements")]
    assert "code_hash" not in str(theirs) and "code_hash" not in str(mine)


def test_a_failed_read_is_a_503_never_an_open_area(db, monkeypatch):
    _keep(db, "treasurer")
    real = db.get
    for table in ("church_keepers?", "church_area_keys?"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service",
                            lambda path, t=table, **kw: None if path.lstrip("/").startswith(t) else real(path, **kw))
        assert _refused(ck.is_open, BIZ, PEOPLE["pastor"], "giving_money").status_code == 503, table


def test_the_switch(db, monkeypatch):
    _keep(db, "treasurer")
    monkeypatch.setenv("CHURCH_KEYS", "owner")
    assert not ck.is_open(BIZ, PEOPLE["pastor"], "giving_money"), "a church with keepers stays locked"
    assert _client(db, "pastor").get(f"/church/keys?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_KEYS", "off")
    assert ck.is_open(BIZ, PEOPLE["pastor"], "giving_money"), "off takes every lock away"


# ─── The routes ───────────────────────────────────────────────────────

def _client(db, name):
    app = FastAPI()
    app.include_router(ck.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def test_the_routes_ask_answer_and_enter_a_code(db):
    _keep(db, "treasurer")
    r = _client(db, "pastor").post("/church/keys/ask", json={"business_id": BIZ, "area": "giving_money", "reason": "Statements"})
    assert r.status_code == 200, r.text
    kid = r.json()["key"]["id"]
    r = _client(db, "treasurer").post(f"/church/keys/{kid}/answer", json={"business_id": BIZ, "yes": True})
    assert r.status_code == 200 and r.json()["key"]["status"] == "open"
    r = _client(db, "stranger").get(f"/church/keys?business_id={BIZ}")
    assert r.status_code == 404, "no login, no keys"
    r = _client(db, "pastor").post("/church/keys/ask", json={"business_id": BIZ, "area": "office"})
    assert r.status_code == 400
