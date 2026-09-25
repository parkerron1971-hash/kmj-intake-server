"""_build_snapshot must hand the Platform Chief ROWS, not just counts.

The bug class this exists for: the snapshot selected only
`subscription_status,trial_days_left` from billing_status, so the Chief
saw `trials_ending_in_7d: 1` and nothing else. Asked which trial was
ending and what to do about it, it could only say it did not know and
tell Kevin to go run SQL himself — a fair answer to give when you have
been handed a number and no rows, and a useless one to receive.

Nothing was missing from the database. The columns simply were not
being asked for, and no test looked at the shape of the snapshot, so
the gap was invisible until a human hit it in conversation.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import platform_console  # noqa: E402

OWNER_ID = "11111111-1111-1111-1111-111111111111"
BIZ_ID = "22222222-2222-2222-2222-222222222222"


class _Resp:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.text = ""
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Routes by URL the way the real Supabase surface does."""

    def __init__(self, *a, **k):
        self.seen: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def head(self, url, **k):
        return _Resp(None, 200, {"content-range": "0-0/3"})

    async def get(self, url, **k):
        params = k.get("params") or {}
        self.seen.append((url, params))

        if "/auth/v1/admin/users" in url:
            return _Resp({"users": [{
                "id": OWNER_ID,
                "email": "dana@thecutbarbers.com",
                "created_at": "2026-08-01T00:00:00Z",
                "last_sign_in_at": "2026-08-30T09:00:00Z",
            }]})

        if "billing_status" in url:
            # Honour the projection. A fake that returns every column
            # whatever it is asked for cannot tell a correct select from
            # the narrow one that caused this bug — the row assertions
            # below would pass against the original code and the
            # rehearsal would prove nothing.
            cols = [c for c in (params.get("select") or "").split(",") if c]

            def _proj(row):
                return {k: v for k, v in row.items() if k in cols} if cols else row

            return _Resp([_proj(r) for r in [
                {
                    "business_id": BIZ_ID,
                    "business_name": "The Cut Barbers",
                    "owner_id": OWNER_ID,
                    "subscription_status": "trialing",
                    "subscription_plan": None,
                    "trial_ends_at": "2026-09-04T00:00:00Z",
                    "trial_days_left": 3.2,
                },
                {
                    "business_id": "33333333-3333-3333-3333-333333333333",
                    "business_name": "Late Payer LLC",
                    "owner_id": OWNER_ID,
                    "subscription_status": "past_due",
                    "trial_ends_at": None,
                    "trial_days_left": None,
                },
            ]])

        if "/rest/v1/businesses" in url:
            return _Resp([{
                "id": BIZ_ID, "type": "barber",
                "created_at": "2026-08-20T00:00:00Z",
            }])

        # Everything else the snapshot touches — return empty lists so
        # the builder walks its whole body without exploding.
        return _Resp([])


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(platform_console.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(platform_console, "SUPABASE_URL", "https://x.supabase.co")


def _snap():
    # asyncio.run, not get_event_loop().run_until_complete: the latter
    # leans on whatever global loop the rest of the suite has left
    # behind, which is why these passed alone and failed in the full
    # run. A fresh loop per call has no such history.
    return asyncio.run(platform_console._build_snapshot({"apikey": "k"}))


def test_trial_arrives_as_a_row_with_a_name_and_a_date():
    subs = _snap()["subscriptions"]
    assert subs["trials_ending_in_7d"] == 1

    rows = subs["trials_ending_soon"]
    assert len(rows) == 1, "the count was there before; the ROW is the point"
    row = rows[0]
    # Everything the Chief said it could not advise without.
    assert row["business_name"] == "The Cut Barbers"
    assert row["business_id"] == BIZ_ID
    assert row["trial_ends_at"] == "2026-09-04T00:00:00Z"
    assert row["days_left"] == 3.2
    assert row["owner_email"] == "dana@thecutbarbers.com"
    assert row["owner_last_sign_in_at"] == "2026-08-30T09:00:00Z"
    assert row["vertical"] == "barber", "advice should be trade-specific"


def test_payment_issues_name_the_business_too():
    issues = _snap()["subscriptions"]["payment_issues"]
    assert [i["business_name"] for i in issues] == ["Late Payer LLC"]
    assert issues[0]["owner_email"] == "dana@thecutbarbers.com"


def test_billing_status_is_asked_for_the_columns_it_needs():
    """The failure was a select string, so assert the select string.

    A snapshot that merely *has* the keys could still be reading a
    narrow projection and filling them with None.
    """
    client = _FakeClient()
    calls: list[tuple[str, dict]] = client.seen

    class _Capture(_FakeClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.seen = calls

    import platform_console as pc
    orig = pc.httpx.AsyncClient
    pc.httpx.AsyncClient = _Capture
    try:
        asyncio.run(pc._build_snapshot({"apikey": "k"}))
    finally:
        pc.httpx.AsyncClient = orig

    sel = next(p.get("select", "") for u, p in calls if "billing_status" in u)
    for col in ("business_id", "business_name", "owner_id", "trial_ends_at"):
        assert col in sel, f"billing_status select is missing {col}"
