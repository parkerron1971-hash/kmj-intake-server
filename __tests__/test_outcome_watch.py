"""THE FOLLOW-THROUGH — opening loops, resolving them, and speaking once.

The contract under test:
  • open_watch takes its deadline from the SUBJECT (an invoice's own
    due_date + grace) and only falls back to a flat window when the
    subject knows nothing;
  • open_watch survives the database refusing a duplicate — the
    one-open-loop-per-subject guard is a no-op here, never a crash;
  • a loop still inside its window resolves OPEN, never missed. This is
    the invariant that keeps Chief from reporting an outcome that has
    not had a chance to happen yet;
  • paid / restocked / replied resolve LANDED with the evidence
    attached; past-due-and-nothing resolves MISSED with an action
    payload the notification tap can dispatch;
  • a reply that predates the send does not close the loop;
  • a cancelled subject goes VOID and says nothing at all;
  • the sweep resolves at any hour but only ANNOUNCES inside waking
    hours, and a resolution made while quiet is carried to the next
    waking pass rather than lost;
  • Chief speaks ONCE — a second pass over the same closed loops emits
    nothing;
  • a win never rides the urgent-alert rail, and a miss always does;
  • a loop recorded missed that has since been paid is re-resolved and
    announced as the win it now is, not replayed with its stale line;
  • follow_through is registered in ACTION_HANDLERS and classified read.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

import outcome_watch as ow  # noqa: E402

BIZ = "biz1"
NOW = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    fb.rows("businesses").append(
        {"id": BIZ, "owner_id": "owner1", "name": "Studio One",
         "is_active": True, "settings": {}})
    fb.rows("contacts").append({"id": "c1", "business_id": BIZ, "name": "Maria Ruiz"})
    return fb


def _watch(fb, **kw):
    """Insert a watch row directly, the way open_watch would have."""
    row = {"id": kw.pop("id", "w1"), "business_id": BIZ, "status": "open",
           "outcome": {}, "opened_at": _iso(NOW - timedelta(days=10)),
           "due_at": _iso(NOW - timedelta(days=1)), "label": "",
           "verb": "", "subject_type": "", "announced_at": None,
           "resolved_at": None, "checked_at": None}
    row.update(kw)
    fb.rows("chief_outcome_watches").append(row)
    return row


def _invoice(fb, **kw):
    row = {"id": "inv1", "business_id": BIZ, "invoice_number": "INV-0042",
           "status": "sent", "total": 1450, "paid_at": None,
           "sent_at": _iso(NOW - timedelta(days=18)), "viewed_at": None,
           "due_date": None, "contact_id": "c1"}
    row.update(kw)
    fb.rows("invoices").append(row)
    return row


# ═══ opening ════════════════════════════════════════════════════════

def test_the_deadline_comes_from_the_invoice_not_a_flat_window(fake):
    """A net-30 invoice must get thirty days, not the fallback. If the
    window were flat, every invoice with real terms would be reported
    late or reported not-yet for the wrong reason."""
    fb = fake
    due = (NOW + timedelta(days=30)).date().isoformat()
    ok = ow.open_watch(BIZ, "invoice_paid", "inv1",
                       subject={"due_date": due}, label="Invoice INV-0042")
    assert ok
    row = fb.rows("chief_outcome_watches")[0]
    at = datetime.fromisoformat(row["due_at"].replace("Z", "+00:00"))
    # The invoice's own due date plus the grace period — NOT now+14.
    assert (at.date() - datetime.fromisoformat(due).date()).days == \
        ow.INVOICE_GRACE_DAYS
    assert (at - NOW).days > ow.INVOICE_FALLBACK_DAYS


def test_a_subject_with_no_due_date_falls_back(fake):
    fb = fake
    assert ow.open_watch(BIZ, "invoice_paid", "inv9", subject={})
    row = fb.rows("chief_outcome_watches")[0]
    at = datetime.fromisoformat(row["due_at"].replace("Z", "+00:00"))
    assert abs((at - datetime.now(timezone.utc)).days
               - ow.INVOICE_FALLBACK_DAYS) <= 1


def test_a_refused_duplicate_is_a_noop_not_a_crash(fake, monkeypatch):
    """The one-open-loop-per-subject guard lives in a partial unique
    index, so the refusal arrives as a None from sb_clients. Two taps of
    'send it' must not become two follow-ups nagging about one invoice —
    and must not turn a completed send into a reported failure."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda *a, **k: None)
    assert ow.open_watch(BIZ, "invoice_paid", "inv1", subject={}) is False


def test_an_unknown_kind_opens_nothing(fake):
    assert ow.open_watch(BIZ, "not_a_kind", "x", subject={}) is False
    assert fake.rows("chief_outcome_watches") == []


# ═══ resolving — invoices ═══════════════════════════════════════════

def test_inside_its_window_and_unpaid_is_OPEN_not_missed(fake):
    """The invariant. An outcome that has not had a chance to happen is
    not an outcome that failed."""
    fb = fake
    _invoice(fb)
    w = _watch(fb, kind="invoice_paid", subject_id="inv1",
               due_at=_iso(NOW + timedelta(days=5)))
    v = ow._resolve_invoice_paid(w, NOW)
    assert v["state"] == "open"
    assert v["line"] == ""


def test_paid_lands_with_the_evidence(fake):
    fb = fake
    _invoice(fb, paid_at=_iso(NOW - timedelta(days=12)), status="paid")
    w = _watch(fb, kind="invoice_paid", subject_id="inv1")
    v = ow._resolve_invoice_paid(w, NOW)
    assert v["state"] == "landed"
    assert "INV-0042" in v["line"] and "Maria Ruiz" in v["line"]
    assert "$1,450" in v["line"]
    # 18 days sent, paid at day 12 → six days to pay.
    assert v["facts"]["days_to_pay"] == 6
    assert "6 days after you sent it" in v["line"]


def test_past_due_and_unpaid_misses_with_a_one_tap_next_move(fake):
    fb = fake
    _invoice(fb, viewed_at=_iso(NOW - timedelta(days=9)),
             due_date=(NOW - timedelta(days=9)).date().isoformat())
    w = _watch(fb, kind="invoice_paid", subject_id="inv1")
    v = ow._resolve_invoice_paid(w, NOW)
    assert v["state"] == "missed"
    assert "9 days past due" in v["line"]
    assert "They've opened it." in v["line"]
    assert v["facts"]["viewed"] is True
    # The tap must dispatch a real verb at a real contact.
    assert v["action"]["type"] == "draft_email"
    assert v["action"]["contact_id"] == "c1"


def test_never_opened_reads_differently_from_ignored(fake):
    """'They are ignoring you' and 'it never reached them' call for
    different moves, so the line must not blur them."""
    fb = fake
    _invoice(fb, viewed_at=None)
    w = _watch(fb, kind="invoice_paid", subject_id="inv1")
    v = ow._resolve_invoice_paid(w, NOW)
    assert v["state"] == "missed"
    assert "hasn't been opened" in v["line"]
    assert v["facts"]["viewed"] is False


def test_a_cancelled_invoice_goes_void_and_says_nothing(fake):
    fb = fake
    _invoice(fb, status="cancelled")
    w = _watch(fb, kind="invoice_paid", subject_id="inv1")
    v = ow._resolve_invoice_paid(w, NOW)
    assert v["state"] == "void"
    assert v["line"] == ""


def test_a_deleted_invoice_goes_void_rather_than_missed(fake):
    w = _watch(fake, kind="invoice_paid", subject_id="gone")
    assert ow._resolve_invoice_paid(w, NOW)["state"] == "void"


# ═══ resolving — restock ════════════════════════════════════════════

def test_the_cleared_pending_stamp_is_the_arrival_signal(fake):
    fb = fake
    fb.rows("offerings").append(
        {"id": "off1", "business_id": BIZ, "name": "Fade Cream",
         "inventory_qty": 42, "reorder_at": 5, "reorder_pending_at": None})
    w = _watch(fb, kind="restock_arrived", subject_id="off1")
    v = ow._resolve_restock_arrived(w, NOW)
    assert v["state"] == "landed"
    assert "Fade Cream is back to 42" in v["line"]


def test_stock_that_never_moved_misses_and_names_the_po(fake):
    fb = fake
    fb.rows("offerings").append(
        {"id": "off1", "business_id": BIZ, "name": "Fade Cream",
         "inventory_qty": 3, "reorder_at": 5,
         "reorder_pending_at": _iso(NOW - timedelta(days=11))})
    w = _watch(fb, kind="restock_arrived", subject_id="off1",
               opened_at=_iso(NOW - timedelta(days=11)),
               outcome={"po_number": "PO-20260809-A1B2C3"})
    v = ow._resolve_restock_arrived(w, NOW)
    assert v["state"] == "missed"
    assert "PO-20260809-A1B2C3" in v["line"]
    assert "11 days ago" in v["line"] and "3 left" in v["line"]


# ═══ resolving — replies ════════════════════════════════════════════

def _reply(fb, days_ago: float, etype="email_replied"):
    fb.rows("events").append(
        {"id": f"e{len(fb.rows('events'))}", "business_id": BIZ,
         "contact_id": "c1", "event_type": etype,
         "created_at": _iso(NOW - timedelta(days=days_ago))})


def test_a_reply_after_the_send_lands(fake):
    fb = fake
    _reply(fb, 3)
    w = _watch(fb, kind="email_reply", subject_id="c1",
               opened_at=_iso(NOW - timedelta(days=5)))
    v = ow._resolve_email_reply(w, NOW)
    assert v["state"] == "landed"
    assert "Maria Ruiz wrote back" in v["line"]
    assert v["facts"]["days"] == 2


def test_a_reply_that_predates_the_send_does_not_close_the_loop(fake):
    """An old thread in the same contact's history is not an answer to
    the message Chief sent this week. Counting it would close loops
    that are still genuinely open."""
    fb = fake
    _reply(fb, 30)
    w = _watch(fb, kind="email_reply", subject_id="c1",
               opened_at=_iso(NOW - timedelta(days=5)),
               due_at=_iso(NOW + timedelta(days=2)))
    assert ow._resolve_email_reply(w, NOW)["state"] == "open"


def test_silence_past_the_window_misses_with_a_nudge(fake):
    fb = fake
    w = _watch(fb, kind="email_reply", subject_id="c1",
               opened_at=_iso(NOW - timedelta(days=6)),
               outcome={"subject": "Your quote"})
    v = ow._resolve_email_reply(w, NOW)
    assert v["state"] == "missed"
    assert "Your quote" in v["line"] and "6 days ago" in v["line"]
    assert v["action"]["type"] == "draft_email"
    assert v["action"]["contact_id"] == "c1"


# ═══ the sweep ══════════════════════════════════════════════════════

class _Spy:
    def __init__(self):
        self.urgent = []
        self.plain = []

    def install(self, monkeypatch, awake=True):
        import notification_engine as ne

        async def fake_urgent(client, bid, title, body, **kw):
            self.urgent.append({"business_id": bid, "title": title,
                                "body": body, **kw})
            return {"id": f"n{len(self.urgent)}"}

        async def fake_plain(client, bid, payload):
            self.plain.append({"business_id": bid, **payload})
            return {"id": f"p{len(self.plain)}"}

        monkeypatch.setattr(ne, "create_urgent_alert", fake_urgent)
        monkeypatch.setattr(ne, "_insert_notification", fake_plain)
        monkeypatch.setattr(ne, "_within_waking_hours", lambda now=None: awake)


def test_the_sweep_resolves_and_announces(fake, monkeypatch):
    fb = fake
    _invoice(fb, id="inv1", paid_at=_iso(NOW - timedelta(days=12)), status="paid")
    _invoice(fb, id="inv2", invoice_number="INV-0043", contact_id="c1",
             due_date=(NOW - timedelta(days=4)).date().isoformat())
    _watch(fb, id="w1", kind="invoice_paid", subject_id="inv1")
    _watch(fb, id="w2", kind="invoice_paid", subject_id="inv2")
    spy = _Spy()
    spy.install(monkeypatch)

    out = asyncio.run(ow.follow_through_sweep(NOW))
    assert out["resolved"] == 2
    assert out["announced"] == 2          # one win group, one miss group

    # A win NEVER wears the red icon: it goes out as its own type on the
    # plain rail, not through the urgent-alert path.
    assert len(spy.plain) == 1
    assert spy.plain[0]["type"] == "follow_through"
    assert "paid" in spy.plain[0]["body"]
    # The miss is actionable, so it rides the urgent rail with a payload.
    assert len(spy.urgent) == 1
    assert spy.urgent[0]["action_payload"]["type"] == "draft_email"

    rows = {r["id"]: r for r in fb.rows("chief_outcome_watches")}
    assert rows["w1"]["status"] == "landed"
    assert rows["w2"]["status"] == "missed"
    assert rows["w1"]["announced_at"] and rows["w2"]["announced_at"]


def test_chief_speaks_once(fake, monkeypatch):
    """The guard. Rehearsed by running the sweep twice: the second pass
    must emit nothing. (Removing the announced_at stamp makes this fail,
    which is the point — a passing test here has to be able to fail.)"""
    fb = fake
    _invoice(fb, paid_at=_iso(NOW - timedelta(days=12)), status="paid")
    _watch(fb, kind="invoice_paid", subject_id="inv1")
    spy = _Spy()
    spy.install(monkeypatch)

    asyncio.run(ow.follow_through_sweep(NOW))
    assert len(spy.plain) == 1
    asyncio.run(ow.follow_through_sweep(NOW + timedelta(hours=1)))
    assert len(spy.plain) == 1, "a resolved loop was announced twice"


def test_quiet_hours_resolve_but_stay_silent_and_lose_nothing(fake, monkeypatch):
    fb = fake
    _invoice(fb, paid_at=_iso(NOW - timedelta(days=12)), status="paid")
    _watch(fb, kind="invoice_paid", subject_id="inv1")
    spy = _Spy()
    spy.install(monkeypatch, awake=False)

    out = asyncio.run(ow.follow_through_sweep(NOW))
    assert out["resolved"] == 1 and out["announced"] == 0
    assert out["skipped"] == "quiet_hours"
    assert not spy.plain and not spy.urgent
    row = fb.rows("chief_outcome_watches")[0]
    assert row["status"] == "landed" and row["announced_at"] is None

    # Morning comes. The overnight resolution is picked up, not lost.
    spy.install(monkeypatch, awake=True)
    out2 = asyncio.run(ow.follow_through_sweep(NOW + timedelta(hours=6)))
    assert out2["announced"] == 1
    assert len(spy.plain) == 1


def test_a_miss_that_has_since_been_paid_announces_as_the_win(fake, monkeypatch):
    """The carry-forward re-RESOLVES rather than replaying. Pairing a
    stored 'missed' verdict with a freshly written line is how you ship
    the word 'unpaid' over evidence that says paid."""
    fb = fake
    _invoice(fb, paid_at=_iso(NOW - timedelta(days=1)), status="paid")
    # Recorded missed last night, never announced; paid since.
    _watch(fb, kind="invoice_paid", subject_id="inv1", status="missed",
           resolved_at=_iso(NOW - timedelta(hours=8)))
    spy = _Spy()
    spy.install(monkeypatch)

    asyncio.run(ow.follow_through_sweep(NOW))
    assert not spy.urgent, "announced a miss over evidence of payment"
    assert len(spy.plain) == 1
    assert "was paid" in spy.plain[0]["body"]
    assert fb.rows("chief_outcome_watches")[0]["status"] == "landed"


def test_a_win_never_rides_the_urgent_rail(fake, monkeypatch):
    fb = fake
    fb.rows("offerings").append(
        {"id": "off1", "business_id": BIZ, "name": "Fade Cream",
         "inventory_qty": 42, "reorder_at": 5, "reorder_pending_at": None})
    _watch(fb, kind="restock_arrived", subject_id="off1")
    spy = _Spy()
    spy.install(monkeypatch)
    asyncio.run(ow.follow_through_sweep(NOW))
    assert spy.urgent == []
    assert spy.plain[0]["priority"] == "low"


def test_a_still_open_loop_is_neither_announced_nor_resolved(fake, monkeypatch):
    fb = fake
    _invoice(fb)
    _watch(fb, kind="invoice_paid", subject_id="inv1",
           due_at=_iso(NOW + timedelta(days=5)))
    spy = _Spy()
    spy.install(monkeypatch)
    out = asyncio.run(ow.follow_through_sweep(NOW))
    assert out["resolved"] == 0 and out["announced"] == 0
    row = fb.rows("chief_outcome_watches")[0]
    assert row["status"] == "open" and row["checked_at"]


# ═══ the read + the registry ════════════════════════════════════════

def test_the_verb_reports_open_and_closed_from_the_rows(fake):
    fb = fake
    _watch(fb, id="w1", kind="invoice_paid", subject_id="inv1",
           label="Invoice INV-0042 to Maria Ruiz",
           due_at=_iso(NOW - timedelta(days=3)))
    _watch(fb, id="w2", kind="email_reply", subject_id="c1", status="landed",
           label="Email: Your quote",
           resolved_at=_iso(datetime.now(timezone.utc) - timedelta(days=1)))
    out = asyncio.run(ow.handle_follow_through(
        None, {"id": BIZ}, {"type": "follow_through"}))
    # Chief action return shape — result AND label, or the app blanks.
    assert out["result"] and out["label"]
    assert "INV-0042" in out["result"]
    assert "Your quote" in out["result"]
    assert out["signal"]["follow_through_open"] == 1


def test_an_empty_slate_says_so_without_inventing_anything(fake):
    out = asyncio.run(ow.handle_follow_through(
        None, {"id": BIZ}, {"type": "follow_through"}))
    assert "nothing outstanding" in out["result"].lower()
    assert out["label"] == "Nothing outstanding"


def test_follow_through_is_registered_and_classified_read():
    """The drift pin. A verb in the prompt with no handler is a promise
    the app cannot keep; a handler with no classification fails closed
    and quietly does nothing."""
    import action_registry
    from chief_of_staff import ACTION_HANDLERS
    assert "follow_through" in ACTION_HANDLERS
    cls = action_registry.classification("follow_through")
    assert cls and cls["effect"] == action_registry.READ
    assert not action_registry.is_bulk("follow_through")


def test_every_kind_has_a_resolver_and_a_window():
    """KINDS is the registry the sweep dispatches through. A kind the
    table's CHECK allows but KINDS does not know would open loops that
    can never close."""
    allowed = {"invoice_paid", "restock_arrived", "campaign_replies",
               "email_reply"}
    assert set(ow.KINDS) == allowed
    for kind, cfg in ow.KINDS.items():
        assert callable(cfg["resolver"]), kind
        assert callable(cfg["window"]), kind
        assert cfg["subject_type"] and cfg["verb"] and cfg["noun"], kind
