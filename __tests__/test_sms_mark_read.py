"""The team's reading clears a text, not only the owner's (Kevin, 2026-10-29).

Every active seat can read sms_messages (tenant_member_read,
APPLY-2026-07-31-seat-access-data-plane.sql), but its UPDATE policy is the
owner's alone. The Text room marked texts read with a browser PATCH, so a
conversation an office login opened stayed unread for everyone until the
owner opened it too. POST /sms/read writes `read` as the server, for a
member or above, and nothing else.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import sms_service


def _run(monkeypatch, *, fail=False, rows=1, **body):
    import business_access
    calls = []
    gate = []

    async def patch_rows(client, path, data):
        calls.append((path, data))
        return None if fail else [{"id": f"m{i}"} for i in range(rows)]

    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r: gate.append((b, r)))
    monkeypatch.setattr(sms_service, "_sb_patch_rows", patch_rows)
    req = sms_service.MarkReadRequest(business_id="biz-1", **body)
    out = asyncio.run(sms_service.mark_read(req, user=SimpleNamespace(id="seat-1")))
    return out, calls, gate


def test_a_member_marks_a_persons_texts_read(monkeypatch):
    out, calls, gate = _run(monkeypatch, contact_id="c-1", rows=2)
    assert gate == [("biz-1", "member")]
    assert out == {"ok": True, "marked": 2}
    [(path, data)] = calls
    assert data == {"read": True}, "the server writes read and nothing else"
    for part in ("business_id=eq.biz-1", "direction=eq.inbound", "read=eq.false", "contact_id=eq.c-1"):
        assert part in path


def test_texts_from_a_number_not_in_people_are_marked_by_number(monkeypatch):
    out, calls, _ = _run(monkeypatch, phone="+12165550199")
    [(path, _)] = calls
    # A bare '+' reads as a space in a query string (see _pq).
    assert "phone_number=eq.%2B12165550199" in path
    assert "contact_id=is.null" in path, "by number only touches texts tied to no one"
    assert out["marked"] == 1


def test_a_person_with_older_untied_texts_gets_both(monkeypatch):
    _, calls, _ = _run(monkeypatch, contact_id="c-1", phone="(216) 555-0199")
    paths = [p for p, _ in calls]
    assert any("contact_id=eq.c-1" in p for p in paths)
    assert any("phone_number=eq.%2B12165550199" in p and "contact_id=is.null" in p for p in paths)


def test_nothing_to_mark_is_refused(monkeypatch):
    out, calls, _ = _run(monkeypatch)
    assert out.status_code == 400 and not calls


def test_a_failed_write_says_so(monkeypatch):
    out, _, _ = _run(monkeypatch, contact_id="c-1", fail=True)
    assert out.status_code == 503


def test_the_check_runs_before_the_write():
    src = inspect.getsource(sms_service.mark_read)
    assert src.index("assert_access") < src.index("httpx.AsyncClient()")
    assert '"viewer"' not in src, "a view-only seat reads without clearing the list"


def test_the_conversation_carries_who_sent_each_text():
    """The Text room labels Chief's and automatic texts; the thread for a
    person in People comes from /sms/conversation, so it must carry it."""
    src = inspect.getsource(sms_service.get_conversation)
    assert "sent_by" in src
