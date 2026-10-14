"""
test_giving_statement_mail.py — the January run, by email.

Pins: finance seats only and an explicit confirm; a statement that needs a
value estimate is never sent; one email per giver per year (the send log,
plus Resend's idempotency key); no-email givers are counted, not guessed;
batches report what's left.
"""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import giving_statement_mail as M

BIZ = "11111111-1111-1111-1111-111111111111"
A, B, C = ("aaaaaaaa-0000-0000-0000-00000000000a", "bbbbbbbb-0000-0000-0000-00000000000b",
           "cccccccc-0000-0000-0000-00000000000c")


class Fake:
    def __init__(self, sent=(), donors=None, fail_log=False):
        self.sent_log = [{"contact_id": c} for c in sent]
        self.donors = donors if donors is not None else [
            {"contact_id": A, "name": "Ann Lee", "email": "ann@example.com", "total": 1200.0},
            {"contact_id": B, "name": "Bo Park", "email": "", "total": 300.0},
            {"contact_id": C, "name": "Cy Ruiz", "email": "cy@example.com", "total": 80.0}]
        self.posts = []
        self.fail_log = fail_log

    def get(self, path):
        if path.startswith("/businesses?"):
            return [{"id": BIZ, "name": "Love City Church", "type": "church", "settings": {}}]
        if path.startswith("/giving_statement_sends?"):
            assert f"business_id=eq.{BIZ}" in path
            return list(self.sent_log)
        return []

    def post(self, path, body, **kw):
        self.posts.append((path, body))
        return None if self.fail_log else [body]


@pytest.fixture
def env(monkeypatch):
    def install(**kw):
        f = Fake(**kw)
        import sb_clients
        monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
        monkeypatch.setattr(M.gs, "statements_for_year", lambda biz, year, org_name=None: {
            "donors": f.donors, "unattributed_total": 40.0})

        def statement(biz, cid, year, org_name=None, goods_and_services="none"):
            d = next(x for x in f.donors if x["contact_id"] == cid)
            return {"ok": True, "empty": False, "year": year, "organisation": org_name,
                    "donor": {"contact_id": cid, "name": d["name"], "email": d["email"]},
                    "gifts": [{"date": f"{year}-03-01", "amount": d["total"], "fund": "General", "refunded": False}],
                    "gift_count": 1, "total": d["total"], "declaration": "No goods or services were provided.",
                    "statement_complete": True, "disclaimer": "Not tax advice.",
                    "generated_on": "2027-01-05"}
        monkeypatch.setattr(M.gs, "statement_for_contact", statement)
        f.mails = []

        async def send(**kw):
            if kw["to_email"] == "bounce@example.com":
                raise RuntimeError("suppressed")
            f.mails.append(kw)
            return {"id": "em_1"}
        mod = types.ModuleType("email_sender")
        mod.send_via_resend = send
        monkeypatch.setitem(sys.modules, "email_sender", mod)
        return f
    return install


def test_plan_counts_who_would_get_one(env):
    env(sent=[C])
    p = M.plan(BIZ, 2025)
    assert (p["donors"], p["will_send"], p["already_sent"]) == (3, 1, 1)
    assert p["no_email"] == [{"contact_id": B, "name": "Bo Park"}]
    assert [d["contact_id"] for d in p["_to_send"]] == [A]


def test_a_batch_sends_each_giver_once_and_logs_it(env):
    f = env()
    out = asyncio.run(M.send_batch(BIZ, 2025, "none"))
    assert out["sent"] == 2 and out["remaining"] == 0 and out["failed"] == []
    assert [m["to_email"] for m in f.mails] == ["ann@example.com", "cy@example.com"]
    m = f.mails[0]
    assert m["subject"] == "Your 2025 giving statement from Love City Church"
    assert m["idempotency_key"] == f"giving-statement:{BIZ}:{A}:2025"
    assert m["business_id"] == BIZ and "Dear Ann" in m["body"] and "TOTAL 2025" in m["body"]
    assert f.posts[0] == ("/giving_statement_sends", {"business_id": BIZ, "contact_id": A, "year": 2025,
                                                       "email": "ann@example.com", "total": 1200.0})


def test_already_sent_givers_are_skipped(env):
    f = env(sent=[A, C])
    out = asyncio.run(M.send_batch(BIZ, 2025, "none"))
    assert out["sent"] == 0 and f.mails == []


def test_a_bounced_address_is_reported_not_logged(env):
    f = env(donors=[{"contact_id": A, "name": "Ann", "email": "bounce@example.com", "total": 50.0}])
    out = asyncio.run(M.send_batch(BIZ, 2025, "none"))
    assert out["sent"] == 0 and out["failed"] == [{"contact_id": A, "name": "Ann"}]
    assert f.posts == []


def test_batches_say_what_is_left(env, monkeypatch):
    donors = [{"contact_id": f"{i:08d}-0000-0000-0000-000000000000", "name": f"G{i}",
               "email": f"g{i}@example.com", "total": 10.0} for i in range(5)]
    env(donors=donors)
    monkeypatch.setattr(M, "BATCH", 2)
    out = asyncio.run(M.send_batch(BIZ, 2025, "none"))
    assert out["sent"] == 2 and out["remaining"] == 3


@pytest.mark.parametrize("goods", ["", "a dinner", "None "])
def test_goods_must_be_none_or_religious(env, goods):
    f = env()
    with pytest.raises(HTTPException) as e:
        asyncio.run(M.send_batch(BIZ, 2025, goods))
    assert e.value.status_code == 400 and f.mails == []


def test_an_incomplete_statement_is_never_sent(env, monkeypatch):
    f = env()
    monkeypatch.setattr(M.gs, "statement_for_contact",
                        lambda *a, **k: {"empty": False, "statement_complete": False})
    out = asyncio.run(M.send_batch(BIZ, 2025, "none"))
    assert out["sent"] == 0 and f.mails == []


def test_a_future_year_is_refused(env):
    env()
    from datetime import date
    with pytest.raises(HTTPException):
        M.plan(BIZ, date.today().year + 1)


# ─── the routes ──────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, env):
    import os
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_supabase import require_user
    import giving_records
    who = {"finance": True}

    def require_finance(biz, user):
        if not who["finance"]:
            raise HTTPException(403, "Giving records require owner, admin, or accountant access.")
        return "owner"
    monkeypatch.setattr(giving_records, "require_finance", require_finance)
    app = FastAPI()
    app.include_router(M.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="u1")
    f = env()
    return TestClient(app), who, f


def test_only_finance_seats_and_only_with_confirm(client):
    c, who, f = client
    assert c.get(f"/giving/{BIZ}/statements/2025/mail").json()["will_send"] == 2
    assert c.post(f"/giving/{BIZ}/statements/2025/mail", json={"goods_and_services": "none"}).status_code == 400
    who["finance"] = False
    assert c.get(f"/giving/{BIZ}/statements/2025/mail").status_code == 403
    assert c.post(f"/giving/{BIZ}/statements/2025/mail",
                  json={"goods_and_services": "none", "confirm": True}).status_code == 403
    assert f.mails == []
    who["finance"] = True
    r = c.post(f"/giving/{BIZ}/statements/2025/mail", json={"goods_and_services": "none", "confirm": True})
    assert r.status_code == 200 and r.json()["sent"] == 2


def test_the_send_log_follows_the_owner_archive_and_erasure():
    import account_lifecycle as lc
    assert lc.BUSINESS_CHILD_TABLES.index("giving_statement_sends") < lc.BUSINESS_CHILD_TABLES.index("contacts")
    assert "giving_statement_sends" in lc._IMPORT_SKIP
