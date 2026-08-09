# __tests__/test_audit_log.py
#
# Rails Arc 4 — the unified audit log. Pins:
#   * record() shapes rows correctly, caps blobs, never raises
#   * record_chief_turn audits failures AND navigation (the exact rows
#     chief_activity skips — the reason this table exists)
#   * the read route exists and requires auth

from unittest import mock

import audit_log


# A successful PostgREST insert under return=representation. The stub was
# `lambda ...: calls.append(...)`, and list.append returns None — which is
# precisely what sb_clients returns when the database REJECTS a row. So
# every test in this file simulated a failed write while asserting
# success, and passed only because record() could not tell the two apart.
_INSERTED = [{"id": "11111111-1111-1111-1111-111111111111"}]


def _capture(returns=_INSERTED):
    calls = []

    def _stub(path, body, prefer=None):
        calls.append((path, body))
        return returns

    patcher = mock.patch.object(
        audit_log.sb_clients, "sb_post_as_service", side_effect=_stub)
    return calls, patcher


def test_record_shapes_the_row():
    calls, p = _capture()
    with p:
        ok = audit_log.record("biz-1", actor_type="chief", verb="create_invoice",
                              actor_id="user-9", summary="Invoice for Jane",
                              payload={"label": "Invoice for Jane"},
                              result={"invoice_id": "inv-1"},
                              source="mobile")
    assert ok is True
    path, row = calls[0]
    # ?select=id is appended so a rejected insert is distinguishable from
    # a successful one — under prefer=None both returned an empty body.
    assert path.startswith("/audit_log")
    assert "select=id" in path
    assert row["business_id"] == "biz-1"
    assert row["actor_type"] == "chief"
    assert row["verb"] == "create_invoice"
    assert row["ok"] is True
    assert row["result"] == {"invoice_id": "inv-1"}
    assert row["source"] == "mobile"


def test_record_caps_oversized_results():
    calls, p = _capture()
    with p:
        audit_log.record("biz-1", actor_type="system", verb="x",
                         result={"blob": "y" * 10000})
    row = calls[0][1]
    assert "truncated" in row["result"]
    assert len(row["result"]["truncated"]) <= audit_log._RESULT_CAP


def test_record_never_raises():
    with mock.patch.object(audit_log.sb_clients, "sb_post_as_service",
                           side_effect=RuntimeError("db down")):
        assert audit_log.record("biz-1", actor_type="chief", verb="x") is False


def test_chief_turn_audits_failures_and_navigation():
    taken = [
        {"type": "create_invoice", "label": "Invoice", "result": {"ok": True}},
        {"type": "send_email", "label": "Send", "result": "error: suppressed"},
        {"type": "navigate", "label": "Go to Bookkeeping", "nav": "operate:bookkeeping"},
    ]

    def failed(t):
        return t.get("type") == "send_email"

    calls, p = _capture()
    with p:
        n = audit_log.record_chief_turn(
            user_id="u1", business_id="biz-1", source="desktop",
            taken=taken, action_failed=failed)

    assert n == 3  # ALL of them — including the failure and the navigate
    rows = [c[1] for c in calls]
    by_verb = {r["verb"]: r for r in rows}
    assert by_verb["create_invoice"]["ok"] is True
    assert by_verb["send_email"]["ok"] is False
    assert "suppressed" in (by_verb["send_email"]["error"] or "")
    assert by_verb["navigate"]["ok"] is True
    assert all(r["actor_type"] == "chief" for r in rows)


def test_audit_route_exists_and_requires_auth():
    from auth_supabase import require_user

    paths = {r.path for r in audit_log.router.routes}
    assert "/audit" in paths
    for r in audit_log.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"
