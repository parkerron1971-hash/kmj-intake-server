"""One switch: every adult with a birthday on record can use member messaging
(messaging_everyone; Kevin, 2026-11-24: automatic, adults only, record
birthdays only)."""
from __future__ import annotations

import pathlib
import sys
import urllib.parse
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import messaging_everyone as me_  # noqa: E402
import messaging_router as mr  # noqa: E402

BIZ = "11111111-1111-1111-1111-111111111111"
TODAY = date(2026, 11, 24)


def cid(n):
    return f"cccccccc-0000-0000-0000-{n:012d}"


ADULT, ADULT2, TEEN, NOBDAY, PAUSED, MANUAL, OFFICE_OFF, TURNS18 = (cid(i) for i in range(1, 9))


def _match(row, key, expr):
    if expr == "not.is.null":
        return row.get(key) is not None
    op, _, val = expr.partition(".")
    cur = row.get(key)
    if op == "eq":
        return str(cur).lower() == val.lower()
    if op == "in":
        return str(cur) in val.strip("()").split(",")
    return True


class Fake:
    def __init__(self):
        self.t = {"contacts": [], "msg_members": [],
                  "businesses": [{"id": BIZ, "owner_id": "o1", "type": "church", "settings": {"messaging": {}}}]}
        self.fail = set()

    def _sel(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        params = urllib.parse.parse_qsl(qs, keep_blank_values=True)
        rows = self.t.get(table, [])
        out = []
        for r in rows:
            ok = True
            for k, v in params:
                if k in ("select", "order", "limit", "offset", "on_conflict"):
                    continue
                if k.startswith("settings->"):
                    m = (r.get("settings") or {}).get("messaging") or {}
                    ok = ok and str(m.get(me_.KEY)).lower() == v.partition(".")[2]
                    continue
                ok = ok and _match(r, k, v)
            if ok:
                out.append(r)
        off = int(dict(params).get("offset") or 0)
        lim = int(dict(params).get("limit") or 10_000)
        return table, out[off:off + lim]

    def get(self, path, **kw):
        table, rows = self._sel(path)
        return None if table in self.fail else [dict(r) for r in rows]

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").partition("?")[0]
        if table in self.fail:
            return None
        out = []
        for b in body if isinstance(body, list) else [body]:
            if any(r["contact_id"] == b["contact_id"] for r in self.t[table]):
                continue          # ignore-duplicates
            self.t[table].append(dict(b))
            out.append(dict(b))
        return out

    def patch(self, path, body, **kw):
        table, rows = self._sel(path)
        if table in self.fail:
            return None
        for r in rows:
            r.update(body)
        return [dict(r) for r in rows]


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    f.t["contacts"] = [
        {"id": ADULT, "business_id": BIZ, "birthdate": "1980-05-01"},
        {"id": ADULT2, "business_id": BIZ, "birthdate": "1995-01-01"},
        {"id": TEEN, "business_id": BIZ, "birthdate": "2012-03-03"},
        {"id": NOBDAY, "business_id": BIZ, "birthdate": None},
        {"id": PAUSED, "business_id": BIZ, "birthdate": "1970-01-01"},
        {"id": MANUAL, "business_id": BIZ, "birthdate": "1990-01-01"},
        {"id": OFFICE_OFF, "business_id": BIZ, "birthdate": "1985-01-01"},
        {"id": TURNS18, "business_id": BIZ, "birthdate": "2008-11-25"},
    ]
    f.t["msg_members"] = [
        # Paused by the Safety room after the switch opened them.
        {"contact_id": PAUSED, "business_id": BIZ, "enabled": False, "enabled_by": me_.BY_SWITCH},
        # Turned on by hand by the office.
        {"contact_id": MANUAL, "business_id": BIZ, "enabled": True, "enabled_by": "u-office"},
        # Switched off by hand by the office.
        {"contact_id": OFFICE_OFF, "business_id": BIZ, "enabled": False, "enabled_by": None},
    ]
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    return f


def _row(f, c):
    return next((r for r in f.t["msg_members"] if r["contact_id"] == c), None)


def test_on_opens_adults_with_a_birthday_and_nobody_else(fake):
    assert me_.open_for_adults(BIZ, TODAY) == 2
    assert _row(fake, ADULT)["enabled"] and _row(fake, ADULT)["enabled_by"] == me_.BY_SWITCH
    assert _row(fake, ADULT2)["enabled"]
    assert _row(fake, TEEN) is None and _row(fake, NOBDAY) is None and _row(fake, TURNS18) is None
    # Someone paused, or switched off by hand, stays off.
    assert _row(fake, PAUSED)["enabled"] is False and _row(fake, OFFICE_OFF)["enabled"] is False
    # Running again opens nobody twice.
    assert me_.open_for_adults(BIZ, TODAY) == 0


def test_a_teen_who_turns_18_opens_on_the_next_pass(fake):
    me_.open_for_adults(BIZ, TODAY)
    assert _row(fake, TURNS18) is None
    assert me_.open_for_adults(BIZ, date(2026, 11, 25)) == 1
    assert _row(fake, TURNS18)["enabled"]


def test_off_closes_only_what_it_opened_and_on_brings_them_back(fake):
    me_.open_for_adults(BIZ, TODAY)
    assert me_.close_what_it_opened(BIZ) == 2
    assert _row(fake, ADULT)["enabled"] is False and _row(fake, ADULT)["enabled_by"] == me_.BY_SWITCH_OFF
    assert _row(fake, MANUAL)["enabled"] is True                       # the office's own yes stays
    assert me_.open_for_adults(BIZ, TODAY) == 2
    assert _row(fake, ADULT)["enabled"] is True
    assert _row(fake, PAUSED)["enabled"] is False                      # still paused


def test_a_failed_read_is_never_nobody(fake):
    fake.fail.add("contacts")
    assert me_.open_for_adults(BIZ, TODAY) is None
    assert me_.counts(BIZ, TODAY) is None
    fake.fail.discard("contacts")
    fake.fail.add("msg_members")
    assert me_.open_for_adults(BIZ, TODAY) is None


def test_counts(fake):
    assert me_.counts(BIZ, TODAY) == {"adults": 5, "adults_on": 1}     # MANUAL only
    me_.open_for_adults(BIZ, TODAY)
    assert me_.counts(BIZ, TODAY) == {"adults": 5, "adults_on": 3}


def test_the_sweep_runs_for_churches_with_the_switch_on(fake):
    assert me_.sweep_tick() == 0
    fake.t["businesses"][0]["settings"]["messaging"][me_.KEY] = True
    assert me_.sweep_tick() >= 2
    assert _row(fake, ADULT)["enabled"]


class _User:
    id = "u-keeper"
    email = "office@example.com"
    role = "authenticated"


def _client(monkeypatch, role="owner"):
    import kids_router
    from auth_supabase import require_user
    monkeypatch.setattr(mr, "require", lambda biz, user, minimum: role)
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: role)
    monkeypatch.setattr(mr, "officers", lambda biz: [])
    monkeypatch.setattr(mr, "member_officers", lambda biz: [])
    app = FastAPI()
    app.include_router(mr.router)
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_the_owner_turns_it_on_and_off(fake, monkeypatch):
    c = _client(monkeypatch)
    r = c.patch("/messaging/settings", json={"business_id": BIZ, "adults_with_birthday": True})
    assert r.status_code == 200 and r.json()["adults_with_birthday"] is True and r.json()["changed"] >= 2
    assert fake.t["businesses"][0]["settings"]["messaging"][me_.KEY] is True
    assert _row(fake, ADULT)["enabled"]
    got = c.get(f"/messaging/settings?business_id={BIZ}").json()
    assert got["adults_with_birthday"] is True and got["adults"]["adults_on"] >= 3
    r = c.patch("/messaging/settings", json={"business_id": BIZ, "adults_with_birthday": False})
    assert r.json()["adults_with_birthday"] is False and _row(fake, ADULT)["enabled"] is False
    assert _row(fake, MANUAL)["enabled"] is True


def test_the_sweep_is_scheduled():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("messaging_everyone_sweep", _msg_everyone.sweep_tick)' in src
