"""client_timeline — one dated record per client.

What is pinned here:
  * every source is read scoped by business AND contact, and a contact
    id that is not a uuid never reaches a query string;
  * rows from eleven tables merge into one list, newest first, and an
    event that merely mirrors a table row (sms_sent beside its
    sms_messages row) is dropped so nothing shows twice;
  * a refused read is reported as a missing source, not rendered as an
    empty history;
  * contracts are matched by the contact's email, and not looked up at
    all when there is no email;
  * the router is owner-gated and Chief's contact_deep_dive reads the
    same assembler while keeping the keys the card already renders.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
import typing

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import sb_clients
import client_timeline as ct

BIZ = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
CONTACT = {"id": CID, "name": "Maria Lopez", "email": "Maria@Example.com",
           "phone": "+12165550100", "status": "active"}


def _install(monkeypatch, gets, log=None):
    """Route sb_get_as_service by path fragment; first match wins.
    A result of None models a refused read (the real helper returns
    None on a non-2xx, [] on an empty 200)."""
    def _get(path):
        if log is not None:
            log.append(path)
        for frag, result in gets:
            if frag in path:
                return result
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)


def _contact_get():
    return (f"/contacts?id=eq.{CID}", [CONTACT])


def _run(coro):
    return asyncio.run(coro)


# ─── Scope and ids ──────────────────────────────────────────────────────

def test_a_non_uuid_contact_id_never_reaches_a_query(monkeypatch):
    log = []
    _install(monkeypatch, [], log)
    assert _run(ct.assemble(BIZ, "1 or 1=1")) is None
    assert _run(ct.assemble("biz", CID)) is None
    assert log == []


def test_every_read_is_scoped_by_business_and_contact(monkeypatch):
    log = []
    _install(monkeypatch, [_contact_get()], log)
    rec = _run(ct.assemble(BIZ, CID))
    assert rec is not None
    for path in log:
        assert f"business_id=eq.{BIZ}" in path, path
        if path.startswith(("/contacts", "/custom_modules", "/esign_documents")):
            continue
        assert (f"contact_id=eq.{CID}" in path) or (f"data->>contact_id=eq.{CID}" in path), path


def test_unknown_contact_is_none_not_an_empty_record(monkeypatch):
    _install(monkeypatch, [(f"/contacts?id=eq.{CID}", [])])
    assert _run(ct.assemble(BIZ, CID)) is None


# ─── The merge ──────────────────────────────────────────────────────────

def test_rows_from_many_tables_merge_newest_first_and_mirrors_drop(monkeypatch):
    _install(monkeypatch, [
        _contact_get(),
        ("/events?", [
            {"id": "e1", "event_type": "contact_note", "data": {"note": "Loves the Tuesday slot"},
             "created_at": "2026-09-01T10:00:00+00:00"},
            {"id": "e2", "event_type": "sms_sent", "data": {"to": "+1", "preview": "hi"},
             "created_at": "2026-09-02T10:00:00+00:00"},      # mirrored → dropped
            {"id": "e3", "event_type": "form_submit", "data": {"form_name": "Intake"},
             "created_at": "2026-08-20T09:00:00+00:00"},
        ]),
        ("/sessions?", [{"id": "s1", "title": "Deep tissue", "status": "scheduled",
                         "scheduled_for": "2026-09-10T15:00:00+00:00", "duration_minutes": 60}]),
        ("/invoices?", [{"id": "i1", "invoice_number": "1042", "status": "sent",
                         "total": "120.00", "currency": "usd", "due_date": "2026-09-15",
                         "created_at": "2026-09-03T12:00:00+00:00"}]),
        ("/sms_messages?", [{"id": "m1", "direction": "outbound", "message": "See you Tuesday",
                             "status": "sent", "sent_by": "practitioner",
                             "created_at": "2026-09-02T10:00:00+00:00"}]),
        ("/time_entries?", [{"id": "t1", "description": "Prep", "minutes": 90,
                             "status": "unbilled", "occurred_on": "2026-08-30"}]),
    ])
    rec = _run(ct.assemble(BIZ, CID))
    ats = [e["at"] for e in rec["entries"]]
    assert ats == sorted(ats, reverse=True)
    ids = [e["id"] for e in rec["entries"]]
    assert "events:e2" not in ids, "the sms_sent event mirrors the sms_messages row"
    assert "sms_messages:m1" in ids
    kinds = {e["id"]: e["kind"] for e in rec["entries"]}
    assert kinds["events:e1"] == "note"
    assert kinds["events:e3"] == "form"
    assert kinds["sessions:s1"] == "booking"
    assert kinds["invoices:i1"] == "invoice"
    assert kinds["time_entries:t1"] == "time"
    note = next(e for e in rec["entries"] if e["id"] == "events:e1")
    assert note["detail"] == "Loves the Tuesday slot"
    inv = next(e for e in rec["entries"] if e["id"] == "invoices:i1")
    assert inv["title"] == "Invoice #1042" and "$120.00" in inv["detail"]
    assert inv["ref"] == {"invoice_id": "i1"}
    t = next(e for e in rec["entries"] if e["id"] == "time_entries:t1")
    assert t["at"] == "2026-08-30T00:00:00Z" and t["title"] == "1.5h logged"
    assert rec["partial"] is False


def test_limit_and_kinds_filter(monkeypatch):
    _install(monkeypatch, [
        _contact_get(),
        ("/events?", [{"id": f"e{i}", "event_type": "contact_note", "data": {"note": str(i)},
                       "created_at": f"2026-08-{i:02d}T10:00:00Z"} for i in range(1, 10)]),
        ("/sessions?", [{"id": "s1", "title": "x", "scheduled_for": "2026-09-10T15:00:00Z"}]),
    ])
    rec = _run(ct.assemble(BIZ, CID, limit=3))
    assert len(rec["entries"]) == 3 and rec["summary"]["count"] == 10
    rec = _run(ct.assemble(BIZ, CID, kinds=["booking"]))
    assert [e["kind"] for e in rec["entries"]] == ["booking"]


# ─── Honesty about reads ────────────────────────────────────────────────

def test_a_refused_read_is_a_missing_source_not_an_empty_history(monkeypatch):
    _install(monkeypatch, [
        _contact_get(),
        ("/sessions?", None),                       # refused
        ("/events?", [{"id": "e1", "event_type": "contact_note", "data": {},
                       "created_at": "2026-09-01T10:00:00Z"}]),
    ])
    rec = _run(ct.assemble(BIZ, CID))
    assert rec["partial"] is True
    assert rec["sources"]["sessions"] is None
    assert rec["sources"]["events"] == 1
    assert [e["id"] for e in rec["entries"]] == ["events:e1"]
    assert "could not read: sessions" in ct.narrate(rec)


def test_one_bad_row_does_not_hide_the_rest(monkeypatch):
    _install(monkeypatch, [
        _contact_get(),
        ("/customer_ledger?", [{"id": "l1", "delta": "not-a-number", "unit": None, "kind": None,
                                "created_at": "2026-09-01T10:00:00Z"},
                               {"id": "l2", "delta": "-1", "unit": "session", "kind": "package",
                                "reason": "used", "created_at": "2026-09-02T10:00:00Z"}]),
    ])
    rec = _run(ct.assemble(BIZ, CID))
    ids = [e["id"] for e in rec["entries"]]
    assert "customer_ledger:l2" in ids
    l2 = next(e for e in rec["entries"] if e["id"] == "customer_ledger:l2")
    assert l2["title"] == "Package: −1 session"


# ─── Contracts by email ─────────────────────────────────────────────────

def test_contracts_are_looked_up_by_the_contacts_email_in_both_cases(monkeypatch):
    log = []
    _install(monkeypatch, [
        _contact_get(),
        ("/esign_documents?", [{"id": "d1", "document_id": "x", "title": "Retainer",
                                "status": "completed", "sent_at": "2026-08-01T00:00:00Z",
                                "completed_at": "2026-08-03T00:00:00Z"}]),
    ], log)
    rec = _run(ct.assemble(BIZ, CID))
    path = next(p for p in log if p.startswith("/esign_documents"))
    assert 'signer_email.eq."Maria@Example.com"' in path
    assert 'signer_email.eq."maria@example.com"' in path
    c = next(e for e in rec["entries"] if e["kind"] == "contract")
    assert c["title"] == "Signed: Retainer" and c["at"] == "2026-08-03T00:00:00Z"


def test_no_email_means_no_contract_lookup(monkeypatch):
    log = []
    _install(monkeypatch, [(f"/contacts?id=eq.{CID}", [{**CONTACT, "email": None}])], log)
    rec = _run(ct.assemble(BIZ, CID))
    assert not any(p.startswith("/esign_documents") for p in log)
    assert rec["sources"]["esign_documents"] == 0


# ─── The summary ────────────────────────────────────────────────────────

def test_summary_reads_the_record_not_the_wording(monkeypatch):
    _install(monkeypatch, [
        _contact_get(),
        ("/invoices?", [
            {"id": "i1", "status": "sent", "total": "100", "created_at": "2026-09-01T00:00:00Z"},
            {"id": "i2", "status": "paid", "total": "50", "created_at": "2026-08-01T00:00:00Z"},
            {"id": "i3", "status": "overdue", "total": "25.5", "created_at": "2026-07-01T00:00:00Z"},
        ]),
        ("/time_entries?", [{"id": "t1", "minutes": 30, "status": "unbilled", "occurred_on": "2026-09-01"},
                            {"id": "t2", "minutes": 45, "status": "billed", "occurred_on": "2026-08-01"}]),
        ("/customer_ledger?", [{"id": "l1", "delta": "5", "unit": "session", "kind": "package",
                                "reason": "bought", "created_at": "2026-08-01T00:00:00Z"},
                               {"id": "l2", "delta": "-2", "unit": "session", "kind": "package",
                                "reason": "used", "created_at": "2026-08-15T00:00:00Z"}]),
        ("/sms_messages?", [{"id": "m1", "direction": "inbound", "message": "thanks!",
                             "created_at": "2026-09-02T10:00:00Z"}]),
        ("/sessions?", [{"id": "s1", "title": "Next", "status": "scheduled",
                         "scheduled_for": "2099-01-01T10:00:00Z"}]),
    ])
    s = _run(ct.assemble(BIZ, CID))["summary"]
    assert s["open_invoices"] == 2 and s["open_invoice_total"] == 125.5
    assert s["unbilled_minutes"] == 30
    assert s["balances"] == {"session": 3.0}
    assert s["last_touch_at"] == "2026-09-02T10:00:00Z" and s["last_touch"] == "Texted you"
    assert s["next_booking_at"] == "2099-01-01T10:00:00Z"
    assert s["by_kind"]["invoice"] == 3


# ─── The router ─────────────────────────────────────────────────────────

class _User:
    def __init__(self, uid):
        self.id = uid


def test_timeline_endpoint_is_owner_gated(monkeypatch):
    import contacts_router as cr
    _install(monkeypatch, [
        (f"/businesses?id=eq.{BIZ}", [{"owner_id": "owner-1"}]),
        _contact_get(),
    ])
    with pytest.raises(HTTPException) as ex:
        _run(cr.timeline(CID, business_id=BIZ, limit=50, kinds=None, user=_User("someone-else")))
    assert ex.value.status_code == 403
    out = _run(cr.timeline(CID, business_id=BIZ, limit=50, kinds=None, user=_User("owner-1")))
    assert out["ok"] is True and out["contact"]["id"] == CID
    assert set(out) == {"ok", "contact", "entries", "summary", "sources", "partial"}
    assert "raw" not in out


def test_timeline_endpoint_404s_for_a_contact_outside_the_business(monkeypatch):
    import contacts_router as cr
    _install(monkeypatch, [
        (f"/businesses?id=eq.{BIZ}", [{"owner_id": "owner-1"}]),
        (f"/contacts?id=eq.{CID}", []),
    ])
    with pytest.raises(HTTPException) as ex:
        _run(cr.timeline(CID, business_id=BIZ, limit=50, kinds=None, user=_User("owner-1")))
    assert ex.value.status_code == 404


def test_contacts_router_annotations_resolve():
    import contacts_router as cr
    for route in cr.router.routes:
        fn = getattr(route, "endpoint", None)
        if fn is not None:
            typing.get_type_hints(fn)


# ─── Chief reads the same record ────────────────────────────────────────

def test_contact_deep_dive_reads_the_assembler_and_keeps_its_old_keys(monkeypatch):
    import chief_of_staff as cos

    async def _validate(client, biz_id, contact_id):
        return CONTACT
    monkeypatch.setattr(cos, "_validate_contact", _validate)

    async def _sb(client, method, path, body=None):
        assert method == "GET" and path.startswith("/agent_queue?")
        return [{"id": "q1", "status": "draft", "subject": "Follow up"}]
    monkeypatch.setattr(cos, "_sb", _sb)

    _install(monkeypatch, [
        _contact_get(),
        ("/events?", [{"id": "e1", "event_type": "contact_note", "data": {"note": "n"},
                       "created_at": "2026-09-01T10:00:00Z"}]),
        ("/sessions?", [{"id": "s1", "title": "Deep tissue", "status": "done",
                         "scheduled_for": "2026-08-10T15:00:00Z"}]),
        ("/module_entries?", [{"id": "me1", "module_id": "mod1", "data": {"contact_id": CID, "goal": "Sleep"},
                               "status": "active", "created_at": "2026-08-05T00:00:00Z"}]),
        ("/custom_modules?", [{"id": "mod1", "name": "Care plans", "slug": "care-plans"}]),
    ])
    out = _run(cos.handle_contact_deep_dive(None, {"id": BIZ}, {"contact_id": CID}))
    assert out["result"] and out["label"] == "Deep dive: Maria Lopez"
    # the card's keys, as before
    assert [e["id"] for e in out["events"]] == ["e1"]
    assert [s["id"] for s in out["sessions"]] == ["s1"]
    assert [m["id"] for m in out["module_entries"]] == ["me1"]
    assert [q["id"] for q in out["queue_history"]] == ["q1"], "drafts stay on the card"
    # and the one record
    assert [e["id"] for e in out["timeline"]] == ["events:e1", "sessions:s1", "module_entries:me1"]
    rec_entry = out["timeline"][-1]
    assert rec_entry["title"] == "Care plans record" and rec_entry["detail"] == "Sleep"
    assert out["summary"]["count"] == 3 and out["partial"] is False
    assert "[booking] Deep tissue" in out["timeline_text"]


def test_the_mcp_description_says_timeline_because_that_is_what_comes_back():
    import mcp_server
    src = inspect.getsource(mcp_server)
    i = src.index('"contact_deep_dive": (')
    assert "one dated timeline" in src[i:i + 600]
