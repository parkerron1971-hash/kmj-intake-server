"""
The rate limiter's window lives in Postgres now, for the strict buckets
(2026-09-04). Every replica takes from the same window, so "10 an hour"
means 10 an hour again instead of 10 times the replica count.

The tests pin the order (local first, free), the fallback (to LOCAL,
never open), the kill switch, and that the booking widget's three
anonymous routes moved onto it with their numbers intact.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import rate_limit


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    rate_limit._buckets.clear()
    monkeypatch.setattr(rate_limit, "_shared_ok", True)
    monkeypatch.delenv("RATE_LIMIT_SHARED", raising=False)
    monkeypatch.setattr(rate_limit, "_LIMITS", {**rate_limit._LIMITS, "t": (3, 60)})


def _rpc(monkeypatch, answers):
    calls = []
    import sb_clients

    def _post(path, body, prefer=None):
        calls.append((path, body))
        a = answers.pop(0) if answers else True
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(sb_clients, "sb_post_as_service", _post)
    return calls


def test_the_shared_window_decides_when_it_answers(monkeypatch):
    calls = _rpc(monkeypatch, [True, False])
    assert rate_limit.allow_strict("t", "1.2.3.4") is True
    assert rate_limit.allow_strict("t", "1.2.3.4") is False, "the shared answer wins"
    assert calls[0][0] == "/rpc/rate_take"
    assert calls[0][1] == {"p_bucket": "t", "p_key": "1.2.3.4", "p_max": 3, "p_window_sec": 60}


def test_local_window_refuses_first_without_a_round_trip(monkeypatch):
    calls = _rpc(monkeypatch, [True, True, True, True])
    for _ in range(3):
        assert rate_limit.allow_strict("t", "k")
    assert rate_limit.allow_strict("t", "k") is False
    assert len(calls) == 3, "the fourth call never reached the database"


def test_a_list_shaped_reply_is_read(monkeypatch):
    _rpc(monkeypatch, [[False]])
    assert rate_limit.allow_strict("t", "k") is False


def test_unavailable_shared_window_falls_back_to_local_not_open(monkeypatch):
    calls = _rpc(monkeypatch, [RuntimeError("db down")] + [True] * 10)
    assert rate_limit.allow_strict("t", "k") is True, "local admitted it"
    assert rate_limit._shared_ok is False
    assert rate_limit.allow_strict("t", "k") is True
    assert rate_limit.allow_strict("t", "k") is True
    assert rate_limit.allow_strict("t", "k") is False, "the LOCAL window still holds"
    assert len(calls) == 1, "one failed round-trip, then no more until re-armed"


def test_a_missing_function_disarms_the_shared_path(monkeypatch):
    calls = _rpc(monkeypatch, [None, True])
    assert rate_limit.allow_strict("t", "k") is True
    assert rate_limit._shared_ok is False
    rate_limit.allow_strict("t", "k")
    assert len(calls) == 1


def test_the_purge_tick_rearms_and_purges(monkeypatch):
    calls = _rpc(monkeypatch, [7])
    monkeypatch.setattr(rate_limit, "_shared_ok", False)
    assert rate_limit.purge_shared() == 7
    assert rate_limit._shared_ok is True
    assert calls[0][0] == "/rpc/rate_purge"


def test_kill_switch_keeps_everything_per_process(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SHARED", "off")
    calls = _rpc(monkeypatch, [False])
    assert rate_limit.allow_strict("t", "k") is True
    assert not calls
    assert rate_limit.purge_shared() == 0


def test_allow_never_touches_the_database(monkeypatch):
    """The fail-open courtesy buckets stay in-process: they sit on hot
    paths (chat, the beacon) and a round-trip there is the wrong trade."""
    calls = _rpc(monkeypatch, [False])
    assert rate_limit.allow("t", "k") is True
    assert not calls


def test_allow_strict_still_fails_closed_when_the_local_check_breaks(monkeypatch):
    def _boom(bucket, key):
        raise RuntimeError("limiter exploded")
    monkeypatch.setattr(rate_limit, "_check", _boom)
    assert rate_limit.allow_strict("t", "k") is False


# ─── the booking widget rides it ─────────────────────────────────────

def test_booking_widget_anon_routes_use_the_strict_shared_path():
    import booking_widget_router as bw
    src = inspect.getsource(bw._rate_limit)
    assert "rate_limit.allow_strict(shared" in src
    for route, bucket in bw._SHARED_BUCKETS.items():
        assert bucket in rate_limit._LIMITS, bucket
        assert rate_limit._LIMITS[bucket] == (10, 3600), "the numbers are unchanged"
    assert set(bw._SHARED_BUCKETS) == {"config-anon", "book-anon", "request-fresh-link"}


def test_booking_widget_refuses_through_the_shared_window(monkeypatch):
    import booking_widget_router as bw
    from fastapi import HTTPException

    class _Req:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = None
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: False)
    with pytest.raises(HTTPException) as e:
        bw._rate_limit("book-anon", _Req())
    assert e.value.status_code == 429


def test_purge_tick_is_scheduled_on_the_leader():
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("rate_windows_purge", _rate_purge_tick)' in src


def test_migration_is_service_role_only_and_documented():
    root = pathlib.Path(__file__).resolve().parent.parent
    sql = root.joinpath("supabase/APPLY-2026-09-04-rate-windows.sql").read_text(encoding="utf-8")
    ddl = "\n".join(line.split("--")[0] for line in sql.splitlines())
    assert "CREATE TABLE IF NOT EXISTS public.rate_windows" in ddl
    assert "ENABLE ROW LEVEL SECURITY" in ddl and "CREATE POLICY" not in ddl
    assert "REVOKE ALL ON public.rate_windows FROM anon, authenticated" in ddl
    assert "SECURITY DEFINER" in ddl
    assert "REVOKE EXECUTE ON FUNCTION public.rate_take" in ddl
    assert "RETURN v_count <= p_max" in ddl
    ledger = root.joinpath("docs/MIGRATIONS.md").read_text(encoding="utf-8")
    assert "APPLY-2026-09-04-rate-windows.sql" in ledger
