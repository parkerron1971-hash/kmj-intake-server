"""
test_balance_surface.py — the drawdown ledger's product surface.

Three surfaces, three failure modes worth pinning:

  * The router's auth ladder — reads are member+, writes are manager+.
    The expensive mistake is a member seat granting itself prepaid value,
    so the 403s get asserted as hard as the 200s.
  * The round-trip — a grant and a consume through the HTTP layer must
    land as real signed ledger rows with the caller recorded, not just
    return plausible JSON.
  * The sweep — run twice over the same completed session it must
    consume exactly ONCE (the session_id dedupe is the whole design),
    and a contact with no prepaid balance must produce no rows at all.

Supabase is faked with an in-memory ledger that computes balances the
way the customer_balances view does (SUM of signed deltas), so the
assertions are against data shapes — row counts, deltas, balances —
never against accessors that cannot fail.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

import balance_sweep
import customer_balances as cb
import customer_balances_router as cbr


BIZ, OWNER, CONTACT = "biz-1", "owner-1", "contact-1"


# ─── an in-memory Supabase that behaves like the real tables ─────────

class FakeSB:
    def __init__(self):
        self.businesses = [{"id": BIZ, "name": "Six Sessions Studio",
                            "type": "coach", "owner_id": OWNER}]
        self.contacts = [{"id": CONTACT, "business_id": BIZ, "name": "Sarah"}]
        # user_id -> role on BIZ (owner resolves via businesses.owner_id)
        self.seats: Dict[str, str] = {}
        self.ledger: List[Dict[str, Any]] = []
        self.sessions: List[Dict[str, Any]] = []
        self.notifications: List[Dict[str, Any]] = []

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _params(path: str) -> Dict[str, str]:
        out = {}
        q = path.split("?", 1)[1] if "?" in path else ""
        for part in q.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    @staticmethod
    def _eq(params: Dict[str, str], key: str) -> Optional[str]:
        v = params.get(key)
        return v[3:] if v and v.startswith("eq.") else None

    def _match(self, rows, params, fields):
        out = []
        for r in rows:
            ok = True
            for f in fields:
                want = self._eq(params, f)
                if want is not None and str(r.get(f)) != want:
                    ok = False
                    break
            if ok:
                out.append(dict(r))
        return out

    # -- reads --------------------------------------------------------
    def sb_get_as_service(self, path: str):
        p = self._params(path)
        if path.startswith("/businesses"):
            return self._match(self.businesses, p, ["id"])
        if path.startswith("/business_users"):
            uid = self._eq(p, "user_id")
            role = self.seats.get(uid or "")
            return [{"role": role}] if role else []
        if path.startswith("/contacts"):
            return self._match(self.contacts, p, ["id", "business_id"])
        if path.startswith("/customer_balances"):
            return self._balances(p)
        if path.startswith("/customer_ledger"):
            rows = self._match(self.ledger, p,
                               ["business_id", "contact_id", "session_id",
                                "kind", "unit"])
            # the expiry pass filters on gte/lte/gt — approximate: only
            # positive rows with a non-null expires_at qualify
            if "expires_at=gte." in path:
                rows = [r for r in rows
                        if r.get("expires_at") and float(r["delta"]) > 0]
            return list(reversed(rows))
        if path.startswith("/sessions"):
            return [dict(s) for s in self.sessions
                    if s.get("status") == "completed"]
        if path.startswith("/chief_notifications"):
            lid = self._eq(p, "data->>ledger_id")
            if lid is not None:
                return [n for n in self.notifications
                        if (n.get("data") or {}).get("ledger_id") == lid]
            return list(self.notifications)
        return []

    def _balances(self, p):
        biz = self._eq(p, "business_id")
        contact = self._eq(p, "contact_id")
        kind, unit = self._eq(p, "kind"), self._eq(p, "unit")
        agg: Dict[Any, Dict[str, float]] = {}
        for r in self.ledger:
            if biz and r["business_id"] != biz:
                continue
            if contact and r["contact_id"] != contact:
                continue
            if kind and r["kind"] != kind:
                continue
            if unit and r["unit"] != unit:
                continue
            key = (r["business_id"], r["contact_id"], r["kind"], r["unit"])
            e = agg.setdefault(key, {"balance": 0.0, "granted": 0.0})
            e["balance"] += float(r["delta"])
            if float(r["delta"]) > 0:
                e["granted"] += float(r["delta"])
        return [{"business_id": b, "contact_id": c, "kind": k, "unit": u,
                 "currency": "usd", "balance": v["balance"],
                 "granted": v["granted"]}
                for (b, c, k, u), v in agg.items()]

    # -- writes -------------------------------------------------------
    def sb_post_as_service(self, path: str, row: Dict[str, Any]):
        if path == "/customer_ledger":
            r = dict(row)
            r["id"] = f"row-{len(self.ledger) + 1}"
            self.ledger.append(r)
            return [r]
        if path == "/chief_notifications":
            self.notifications.append(dict(row))
            return [dict(row)]
        raise AssertionError(f"unexpected POST {path}")


@pytest.fixture
def sb(monkeypatch):
    fake = FakeSB()
    import sb_clients
    import business_users_router
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.sb_get_as_service)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.sb_post_as_service)
    monkeypatch.setattr(business_users_router.sb_clients, "sb_get_as_service",
                        fake.sb_get_as_service, raising=False)
    return fake


class _U:
    def __init__(self, uid):
        self.id = uid
        self.email = f"{uid}@x.test"


def _grant_body(**kw) -> cbr.GrantBody:
    return cbr.GrantBody(**{"contact_id": CONTACT, "amount": 6, **kw})


# ─── the auth matrix ─────────────────────────────────────────────────

def test_member_can_read(sb):
    sb.seats["staff-1"] = "member"
    out = cbr.contact_balances(BIZ, CONTACT, _U("staff-1"))
    assert out["ok"] is True
    assert out["balances"] == []          # empty, but the door opened
    assert out["defaults"] == {"kind": "package", "unit": "session"}


def test_viewer_cannot_read(sb):
    sb.seats["peek-1"] = "viewer"
    with pytest.raises(HTTPException) as exc:
        cbr.contact_balances(BIZ, CONTACT, _U("peek-1"))
    assert exc.value.status_code == 403


def test_stranger_cannot_read(sb):
    with pytest.raises(HTTPException) as exc:
        cbr.business_balances(BIZ, _U("nobody"))
    assert exc.value.status_code == 403


def test_member_cannot_write(sb):
    sb.seats["staff-1"] = "member"
    with pytest.raises(HTTPException) as exc:
        cbr.grant(BIZ, _grant_body(), _U("staff-1"))
    assert exc.value.status_code == 403
    assert sb.ledger == []                # the 403 left no row behind


def test_manager_can_write(sb):
    sb.seats["mgr-1"] = "manager"
    out = cbr.grant(BIZ, _grant_body(), _U("mgr-1"))
    assert out["ok"] is True
    assert len(sb.ledger) == 1
    assert float(sb.ledger[0]["delta"]) == 6
    assert sb.ledger[0]["created_by"] == "mgr-1"


def test_owner_passes_everything(sb):
    out = cbr.grant(BIZ, _grant_body(), _U(OWNER))
    assert out["ok"] is True
    assert cbr.contact_balances(BIZ, CONTACT, _U(OWNER))["balances"][0]["balance"] == 6


def test_cross_business_contact_is_404(sb):
    with pytest.raises(HTTPException) as exc:
        cbr.grant(BIZ, _grant_body(contact_id="someone-elses-contact"), _U(OWNER))
    assert exc.value.status_code == 404
    assert sb.ledger == []


# ─── the round-trip ──────────────────────────────────────────────────

def test_grant_then_consume_round_trip(sb):
    cbr.grant(BIZ, _grant_body(amount=6), _U(OWNER))
    out = cbr.consume(BIZ, cbr.ConsumeBody(contact_id=CONTACT, amount=1),
                      _U(OWNER))
    assert out["ok"] is True
    assert out["balance"] == 5
    # two real signed rows, not a mutated counter
    assert [float(r["delta"]) for r in sb.ledger] == [6, -1]
    assert sb.ledger[0]["kind"] == "package"   # coach vertical default
    assert sb.ledger[0]["unit"] == "session"


def test_insufficient_consume_is_a_narrated_200(sb):
    cbr.grant(BIZ, _grant_body(amount=2), _U(OWNER))
    out = cbr.consume(BIZ, cbr.ConsumeBody(contact_id=CONTACT, amount=5),
                      _U(OWNER))
    assert out["ok"] is False
    assert out["available"] == 2
    assert out["shortfall"] == 3
    # the refusal wrote nothing
    assert [float(r["delta"]) for r in sb.ledger] == [2]


def test_bad_amount_is_a_400(sb):
    with pytest.raises(HTTPException) as exc:
        cbr.grant(BIZ, _grant_body(amount=-3), _U(OWNER))
    assert exc.value.status_code == 400


# ─── the sweep ───────────────────────────────────────────────────────

def _yesterday_z() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%dT10:00:00Z")


def _completed_session(sid="sess-1"):
    return {"id": sid, "business_id": BIZ, "contact_id": CONTACT,
            "status": "completed", "title": "Weekly coaching",
            "scheduled_for": _yesterday_z()}


def test_sweep_consumes_once_and_only_once(sb):
    cb.grant(BIZ, CONTACT, 3, "package", "session", "3-pack")
    sb.sessions.append(_completed_session())

    first = balance_sweep.sweep_tick()
    second = balance_sweep.sweep_tick()   # the re-run that must be free

    assert first["consumed"] == 1
    assert second["consumed"] == 0
    draws = [r for r in sb.ledger if float(r["delta"]) < 0]
    assert len(draws) == 1                # exactly one, across both runs
    assert draws[0]["session_id"] == "sess-1"
    assert cb.balance(BIZ, CONTACT, "package", "session") == 2


def test_sweep_skips_contacts_with_no_balance(sb):
    sb.sessions.append(_completed_session())
    out = balance_sweep.sweep_tick()
    assert out["sessions_checked"] == 1
    assert out["consumed"] == 0
    assert sb.ledger == []                # no rows, no negative surprise


def test_sweep_never_drives_below_zero(sb):
    cb.grant(BIZ, CONTACT, 1, "package", "session", "single")
    sb.sessions.append(_completed_session("sess-1"))
    sb.sessions.append(_completed_session("sess-2"))
    balance_sweep.sweep_tick()
    assert cb.balance(BIZ, CONTACT, "package", "session") == 0
    draws = [r for r in sb.ledger if float(r["delta"]) < 0]
    assert len(draws) == 1                # the second session was refused


def test_sweep_notifies_when_balance_hits_zero(sb):
    cb.grant(BIZ, CONTACT, 1, "package", "session", "single")
    sb.sessions.append(_completed_session())
    balance_sweep.sweep_tick()
    assert len(sb.notifications) == 1
    n = sb.notifications[0]
    assert "Sarah" in n["title"]
    assert n["data"]["contact_id"] == CONTACT


def test_sweep_kill_switch(sb, monkeypatch):
    monkeypatch.setenv("BALANCE_SWEEP", "off")
    cb.grant(BIZ, CONTACT, 3, "package", "session", "3-pack")
    sb.sessions.append(_completed_session())
    out = balance_sweep.sweep_tick()
    assert out.get("skipped")
    assert [float(r["delta"]) for r in sb.ledger] == [3]
