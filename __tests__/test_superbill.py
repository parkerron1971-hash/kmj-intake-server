"""
test_superbill.py — therapist superbills: the billing artifact that must
never carry clinical data.

Pins, in order of importance:

  1. The TABLE ALLOWLIST — every read the module makes is recorded
     (PR #352 recording pattern, test_briefing_verticals.py) and checked
     against superbill.ALLOWED_TABLES; the constant itself is pinned so
     widening it is a visible, reviewable act. _read() also refuses at
     runtime, so a stray query fails closed in production.
  2. NO-DIAGNOSIS — no diagnosis/procedure-classification input path
     exists anywhere: the config body 422s on extra fields, the module
     source never names the diagnosis-code standard, the statement's
     only diagnosis line is the deliberate BLANK the provider completes
     by hand, and the rendered PDF carries that blank and nothing more.
  3. NO session content / notes / modality — the sessions query selects
     date/title/duration/status only.
  4. OWNER-ONLY — config and generation gate through _owner (the same
     TIN-class rule as the 1099 draft PDF), never the reader gate, and
     the report is deliberately NOT exposed on the reader-gated /export.
  5. Generation math — window bounds, cancelled/no-show/future
     exclusion, fee resolution (offering match → default fee →
     honestly unpriced), FIFO paid allocation per the documented
     payment-linkage rule.
  6. The vertical gate — a coach gets 403; therapist aliases pass.
"""
from __future__ import annotations

import re
import types
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Tuple
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import auth_supabase
import sb_clients
import superbill
import reports_router


# ─── fixtures ────────────────────────────────────────────────────────

_SETTINGS = {
    "superbill": {
        "practitioner_name": "Dana Rivers",
        "license_type": "LCSW",
        "license_number": "C-12345",
        "npi": "1234567890",
        "ein": "12-3456789",
        "address": "1 Main St, Springfield, IL 62701",
        "phone": "555-0100",
        "service_codes": {"off1": "90837"},
        "default_fee": 100.0,
    }
}

_BIZ = {"id": "b1", "name": "Calm Waters Counseling", "type": "therapist",
        "owner_id": "owner-1", "settings": _SETTINGS}

_CONTACT = {"id": "c1", "name": "Alex Doe", "email": "alex@x.test",
            "phone": "555-0101"}

_OFFERINGS = [{"id": "off1", "name": "Therapy Session", "current_price": 150.0,
               "duration_min": 50}]

_SESSIONS = [
    # In window, matched offering.
    {"id": "s1", "title": "Therapy Session", "scheduled_for": "2026-06-03T15:00:00Z",
     "duration_minutes": 50, "status": "completed"},
    {"id": "s2", "title": "Therapy Session", "scheduled_for": "2026-06-10T15:00:00Z",
     "duration_minutes": 50, "status": "scheduled"},
    # In window, unmatched title → default fee.
    {"id": "s6", "title": "Phone check-in", "scheduled_for": "2026-06-20T15:00:00Z",
     "duration_minutes": 20, "status": "completed"},
    # Excluded: cancelled / no-show / out of window.
    {"id": "s3", "title": "Therapy Session", "scheduled_for": "2026-06-17T15:00:00Z",
     "duration_minutes": 50, "status": "cancelled"},
    {"id": "s5", "title": "Therapy Session", "scheduled_for": "2026-06-25T15:00:00Z",
     "duration_minutes": 50, "status": "no_show"},
    {"id": "s4", "title": "Therapy Session", "scheduled_for": "2026-05-20T15:00:00Z",
     "duration_minutes": 50, "status": "completed"},
]

_INVOICES = [
    {"id": "i1", "total": 200.0, "paid_at": "2026-06-12T10:00:00Z",
     "refund_amount_cents": None},
    # Out of window — must not join the pool.
    {"id": "i2", "total": 500.0, "paid_at": "2026-07-02T10:00:00Z",
     "refund_amount_cents": None},
]


def _bounded(rows: List[Dict[str, Any]], field: str) -> Callable[[str], list]:
    """Fake PostgREST: honor gte/lte bounds + the status filters, so the
    in/out-of-window assertions prove the QUERY carries the bounds."""
    def handler(path: str) -> list:
        out = list(rows)
        g = re.search(rf"{field}=gte\.([0-9TZ:.-]+)", path)
        le = re.search(rf"{field}=lte\.([0-9TZ:.-]+)", path)
        if g:
            out = [r for r in out if (r.get(field) or "") >= g.group(1)]
        if le:
            out = [r for r in out if (r.get(field) or "") <= le.group(1)]
        if "status=not.in.(cancelled,no_show)" in path:
            out = [r for r in out if r.get("status") not in ("cancelled", "no_show")]
        if "status=eq.paid" in path:
            out = [r for r in out if r.get("status", "paid") == "paid"]
        return out
    return handler


class RecordingServiceSB:
    """Records every service-role GET; dispatches by path predicate."""

    def __init__(self, routes: List[Tuple]):
        self.routes = routes
        self.calls: List[str] = []

    def __call__(self, path: str):
        self.calls.append(path)
        for pred, rows in self.routes:
            if pred(path):
                return rows(path) if callable(rows) else list(rows)
        return []

    def tables(self) -> set:
        return {p.split("?", 1)[0].lstrip("/") for p in self.calls}


def _sb(biz=None, sessions=None, invoices=None, offerings=None, contact=None):
    return RecordingServiceSB([
        (lambda p: p.startswith("/businesses"), [dict(biz or _BIZ)]),
        (lambda p: p.startswith("/contacts?id=eq"), [dict(contact or _CONTACT)]),
        (lambda p: p.startswith("/contacts"), [dict(contact or _CONTACT)]),
        (lambda p: p.startswith("/sessions"),
         _bounded(sessions if sessions is not None else _SESSIONS, "scheduled_for")),
        (lambda p: p.startswith("/invoices"),
         _bounded(invoices if invoices is not None else _INVOICES, "paid_at")),
        (lambda p: p.startswith("/offerings"),
         list(offerings if offerings is not None else _OFFERINGS)),
    ])


# ─── 1. the table allowlist ──────────────────────────────────────────

def test_allowlist_is_pinned():
    """Widening the wall is a deliberate diff on a named constant."""
    assert superbill.ALLOWED_TABLES == frozenset(
        {"businesses", "contacts", "sessions", "invoices", "offerings"})


def test_every_query_stays_inside_the_allowlist(monkeypatch):
    sb = _sb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", sb)
    out = superbill.build_superbill("b1", "c1", month="2026-06")

    assert out["rows"], "no rows produced — the allowlist assertion would be vacuous"
    assert sb.calls, "no queries recorded"
    forbidden = sb.tables() - superbill.ALLOWED_TABLES
    assert not forbidden, (
        f"superbill read tables outside the scheduling/billing allowlist: "
        f"{sorted(forbidden)} — the therapist posture (vertical_registry.py, "
        f"vertical_scope.py) forbids this.")
    # And it used its full remit — nothing snuck in through another client.
    assert sb.tables() == {"businesses", "contacts", "sessions", "invoices",
                           "offerings"}


def test_read_refuses_foreign_tables_at_runtime(monkeypatch):
    """The wall holds even without the test harness: a stray query added
    to this module fails closed in production."""
    called = {"n": 0}
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: called.__setitem__("n", called["n"] + 1) or [])
    with pytest.raises(ValueError, match="allowlist"):
        superbill._read("/module_entries?business_id=eq.b1&select=data")
    with pytest.raises(ValueError, match="allowlist"):
        superbill._read("/restricted_module_entries?select=*")
    assert called["n"] == 0, "the forbidden read reached Supabase"


def test_sessions_query_never_selects_notes_or_modality(monkeypatch):
    """No session content, no notes, no modality — enforced at the query."""
    sb = _sb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", sb)
    superbill.build_superbill("b1", "c1", month="2026-06")
    session_calls = [p for p in sb.calls if p.lstrip("/").startswith("sessions")]
    assert session_calls, "sessions were never queried"
    for p in session_calls:
        assert "notes" not in p, f"sessions query selects notes: {p}"
        assert "session_type" not in p, f"sessions query selects modality: {p}"


# ─── 2 + 3. the no-diagnosis pins ────────────────────────────────────

def test_module_source_never_names_the_diagnosis_code_standard():
    import pathlib
    src = pathlib.Path(superbill.__file__).read_text(encoding="utf-8").lower()
    assert "icd" not in src, "superbill.py must not reference diagnosis codes"


def test_statement_diagnosis_line_is_the_deliberate_blank(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb())
    out = superbill.build_superbill("b1", "c1", month="2026-06")
    assert out["diagnosis_line"] == "Diagnosis (completed by provider):"
    # No other key in the payload carries diagnosis data, and no row does.
    diagnosis_keys = [k for k in out if "diagnos" in k.lower()]
    assert diagnosis_keys == ["diagnosis_line"]
    for r in out["rows"]:
        assert set(r.keys()) == {"date", "description", "procedure_code",
                                 "duration_minutes", "fee", "paid"}


def test_config_body_rejects_smuggled_diagnosis_fields(monkeypatch):
    """extra='forbid' on the config model: there is no input path."""
    c = _client(monkeypatch, user_id="owner-1")
    r = c.put("/reports/superbill/config?biz=b1", json={
        "practitioner_name": "Dana", "diagnosis_code": "F41.1"})
    assert r.status_code == 422
    r2 = c.put("/reports/superbill/config?biz=b1", json={
        "practitioner_name": "Dana", "icd_codes": ["F41.1"]})
    assert r2.status_code == 422


# ─── 5. generation math (the documented payment-linkage rule) ────────

def test_window_exclusions_and_fifo_allocation(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb())
    out = superbill.build_superbill("b1", "c1", month="2026-06")

    # s1 + s2 (matched, $150 each) + s6 (default fee $100); cancelled,
    # no-show and the May session are gone.
    assert [r["date"] for r in out["rows"]] == \
        ["2026-06-03", "2026-06-10", "2026-06-20"]
    assert [r["fee"] for r in out["rows"]] == [150.0, 150.0, 100.0]
    # Operator-entered code rides the matched offering; unmatched has none.
    assert [r["procedure_code"] for r in out["rows"]] == ["90837", "90837", ""]

    # Paid pool = the June invoice only ($200; July's $500 excluded),
    # allocated oldest-first, capped at each fee.
    assert [r["paid"] for r in out["rows"]] == [150.0, 50.0, 0.0]
    t = out["totals"]
    assert t == {"sessions": 3, "fees": 400.0, "paid": 200.0,
                 "payments_received": 200.0, "balance": 200.0}


def test_refunds_shrink_the_paid_pool(monkeypatch):
    invoices = [{"id": "i1", "total": 200.0, "paid_at": "2026-06-12T10:00:00Z",
                 "refund_amount_cents": 5000}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb(invoices=invoices))
    out = superbill.build_superbill("b1", "c1", month="2026-06")
    assert out["totals"]["payments_received"] == 150.0
    assert [r["paid"] for r in out["rows"]] == [150.0, 0.0, 0.0]


def test_no_payments_means_zero_paid_never_invented(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb(invoices=[]))
    out = superbill.build_superbill("b1", "c1", month="2026-06")
    assert all(r["paid"] == 0.0 for r in out["rows"])
    assert out["totals"]["balance"] == out["totals"]["fees"] == 400.0


def test_unpriced_sessions_are_flagged_not_guessed(monkeypatch):
    biz = {**_BIZ, "settings": {"superbill": {
        **_SETTINGS["superbill"]}}}
    del biz["settings"]["superbill"]  # rebuild without default_fee
    biz["settings"]["superbill"] = {k: v for k, v in _SETTINGS["superbill"].items()
                                    if k != "default_fee"}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb(biz=biz))
    out = superbill.build_superbill("b1", "c1", month="2026-06")
    unmatched = [r for r in out["rows"] if r["description"] == "Phone check-in"]
    assert unmatched and unmatched[0]["fee"] is None
    assert out["unpriced_sessions"] == 1
    # The unpriced session never inflates fees.
    assert out["totals"]["fees"] == 300.0


def test_future_sessions_never_bill(monkeypatch):
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    sessions = [
        {"id": "p1", "title": "Therapy Session",
         "scheduled_for": (now - timedelta(days=1)).strftime(fmt),
         "duration_minutes": 50, "status": "completed"},
        {"id": "f1", "title": "Therapy Session",
         "scheduled_for": (now + timedelta(days=1)).strftime(fmt),
         "duration_minutes": 50, "status": "scheduled"},
    ]
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        _sb(sessions=sessions, invoices=[]))
    start = now.date().replace(day=1).isoformat()
    end = (now.date() + timedelta(days=27)).isoformat()
    out = superbill.build_superbill("b1", "c1", date_from=start, date_to=end)
    assert [r["date"] for r in out["rows"]] == \
        [(now - timedelta(days=1)).strftime("%Y-%m-%d")]


def test_window_bounds():
    assert superbill.window_bounds("2026-06", None, None) == ("2026-06-01", "2026-06-30")
    assert superbill.window_bounds("2026-12", None, None) == ("2026-12-01", "2026-12-31")
    assert superbill.window_bounds(None, "2026-01-05", "2026-02-04") == \
        ("2026-01-05", "2026-02-04")
    with pytest.raises(HTTPException):
        superbill.window_bounds("June 2026", None, None)
    with pytest.raises(HTTPException):
        superbill.window_bounds(None, "2026-02-04", "2026-01-05")


# ─── 6. the vertical gate ────────────────────────────────────────────

def test_coach_is_refused(monkeypatch):
    coach = {**_BIZ, "type": "coach"}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb(biz=coach))
    for fn in (lambda: superbill.build_superbill("b1", "c1", month="2026-06"),
               lambda: superbill.get_config("b1"),
               lambda: superbill.list_clients("b1")):
        with pytest.raises(HTTPException) as exc:
            fn()
        assert exc.value.status_code == 403


@pytest.mark.parametrize("alias", ["therapist", "counselor", "lmft", "lcsw",
                                   "psychotherapy", "mental_health"])
def test_therapist_aliases_pass_the_gate(alias, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        _sb(biz={**_BIZ, "type": alias}))
    out = superbill.build_superbill("b1", "c1", month="2026-06")
    assert out["ok"] is True


# ─── 4. owner-only, through the routes ───────────────────────────────

def _client(monkeypatch, user_id: str, biz=None) -> TestClient:
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb(biz=biz))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: [])
    app = FastAPI()
    app.include_router(reports_router.router)
    app.dependency_overrides[auth_supabase.require_user] = (
        lambda: types.SimpleNamespace(id=user_id, email=f"{user_id}@x.test"))
    return TestClient(app)


def test_owner_reads_config(monkeypatch):
    c = _client(monkeypatch, "owner-1")
    r = c.get("/reports/superbill/config?biz=b1")
    assert r.status_code == 200
    body = r.json()
    assert body["practitioner"]["complete"] is True
    assert body["offerings"][0]["procedure_code"] == "90837"


def test_non_owner_is_403_on_every_superbill_route(monkeypatch):
    """Accountants and seats read other reports; TIN-class surfaces are
    the owner's alone — same rule as the 1099 draft PDF."""
    with mock.patch("business_collaborators_router.is_active_accountant",
                    return_value=True), \
         mock.patch("business_users_router.role_of", return_value="admin"):
        c = _client(monkeypatch, "cpa-9")
        for method, path in (
                ("GET", "/reports/superbill/config?biz=b1"),
                ("PUT", "/reports/superbill/config?biz=b1"),
                ("GET", "/reports/superbill/clients?biz=b1"),
                ("GET", "/reports/superbill?biz=b1&contact_id=c1&month=2026-06"),
                ("GET", "/reports/superbill/pdf?biz=b1&contact_id=c1&month=2026-06")):
            r = c.request(method, path, json={} if method == "PUT" else None)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code}"


def test_owner_generates_the_statement(monkeypatch):
    c = _client(monkeypatch, "owner-1")
    r = c.get("/reports/superbill?biz=b1&contact_id=c1&month=2026-06")
    assert r.status_code == 200
    assert r.json()["totals"]["fees"] == 400.0


def test_coach_route_is_403_even_for_the_owner(monkeypatch):
    c = _client(monkeypatch, "owner-1", biz={**_BIZ, "type": "coach"})
    r = c.get("/reports/superbill?biz=b1&contact_id=c1&month=2026-06")
    assert r.status_code == 403


def test_save_config_merges_settings(monkeypatch):
    saved = {}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb())
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: saved.update({"path": path, **body}) or [])
    app = FastAPI()
    app.include_router(reports_router.router)
    app.dependency_overrides[auth_supabase.require_user] = (
        lambda: types.SimpleNamespace(id="owner-1", email="o@x.test"))
    c = TestClient(app)
    r = c.put("/reports/superbill/config?biz=b1", json={
        "practitioner_name": "  Dr. Dana Rivers  ",
        "service_codes": {"off1": " 90834 ", "off2": ""},
        "default_fee": 125,
    })
    assert r.status_code == 200
    sp = saved["settings"]["superbill"]
    assert sp["practitioner_name"] == "Dr. Dana Rivers"
    assert sp["service_codes"] == {"off1": "90834"}    # blanks dropped, trimmed
    assert sp["default_fee"] == 125.0
    # Untouched practitioner fields survive the merge.
    assert sp["npi"] == "1234567890"


def test_pdf_requires_complete_practitioner_info(monkeypatch):
    incomplete = {**_BIZ, "settings": {"superbill": {"practitioner_name": "Dana"}}}
    c = _client(monkeypatch, "owner-1", biz=incomplete)
    r = c.get("/reports/superbill/pdf?biz=b1&contact_id=c1&month=2026-06")
    assert r.status_code == 409
    assert "practitioner" in r.json()["detail"].lower()


def test_superbill_routes_are_owner_gated_in_source():
    """Source pin (test_reports_read_access discipline): every superbill
    route body gates through _owner, never the reader gate, and the
    report never rides the reader-gated /export."""
    import pathlib
    src = pathlib.Path(reports_router.__file__).read_text(encoding="utf-8")
    for fn in ("superbill_config", "superbill_config_save", "superbill_clients",
               "superbill_report", "superbill_pdf"):
        m = re.search(rf"\ndef {fn}\(.*?(?=\n@router|\ndef |\Z)", src, re.S)
        assert m, f"route {fn} not found"
        body = m.group(0)
        assert "_owner(biz, user)" in body, f"{fn} lost its owner gate"
        assert "_owner_or_reader" not in body, f"{fn} must not open to seats"
        assert "require_role" not in body, f"{fn} must not open to seats"
    assert "superbill" not in reports_router._REPORT_TITLES


# ─── the PDF itself ──────────────────────────────────────────────────

def _reportlab():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


def _pdf_text(pdf: bytes) -> str:
    """Decode every content stream (reportlab: ASCII85 over Flate, or raw
    Flate) — text is written as literal strings, so words are recoverable."""
    import base64
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        raw = m.group(1).strip()
        for attempt in (lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
                        lambda b: zlib.decompress(b),
                        lambda b: b):
            try:
                out.append(attempt(raw).decode("latin-1", "ignore"))
                break
            except Exception:
                continue
    return "\n".join(out)


@pytest.mark.skipif(not _reportlab(), reason="reportlab unavailable")
def test_rendered_pdf_carries_the_blank_and_nothing_clinical(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb())
    data = superbill.build_superbill("b1", "c1", month="2026-06")
    pdf = superbill.render_pdf(data, _SETTINGS, generated_by="Dana Rivers")
    assert pdf[:5] == b"%PDF-"

    text = _pdf_text(pdf)
    assert "Diagnosis" in text and "completed by provider" in text
    assert "ICD" not in text
    # Billing facts present; clinical words absent.
    assert "Dana Rivers" in text and "1234567890" in text     # NPI
    assert "90837" in text                                    # operator code
    for word in ("treatment", "progress note", "symptom", "diagnos code"):
        assert word not in text.lower(), f"clinical language leaked: {word}"
    # "clinical" may appear ONLY inside the explicit "no ... clinical
    # information" disclaimer — nowhere else (same discipline as the
    # therapist briefing wall).
    assert "clinical" not in text.lower().replace("clinical information", "")


@pytest.mark.skipif(not _reportlab(), reason="reportlab unavailable")
def test_owner_downloads_the_pdf_through_the_route(monkeypatch):
    c = _client(monkeypatch, "owner-1")
    r = c.get("/reports/superbill/pdf?biz=b1&contact_id=c1&month=2026-06")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert "superbill_" in r.headers["content-disposition"]
