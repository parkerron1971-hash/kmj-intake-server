# __tests__/test_event_spine.py
#
# Rails Arc 3 — the event spine. Two jobs:
#   1. behavior: emit() writes the row, refuses without business_id,
#      and never raises
#   2. THE DRIFT TEST: every literal event type passed to
#      event_spine.emit(...) anywhere in the source tree must exist in
#      EVENT_CATALOG — the catalog cannot rot into fiction.

import pathlib
import re
from unittest import mock

import event_spine


def test_emit_writes_the_row():
    calls = []
    with mock.patch.object(event_spine.sb_clients, "sb_post_as_service",
                           side_effect=lambda path, body, prefer=None: calls.append((path, body))):
        ok = event_spine.emit("booking_paid", "biz-1",
                              {"booking_id": "b1"}, contact_id="c1",
                              source="stripe_webhook")
    assert ok is True
    path, body = calls[0]
    assert path == "/events"
    assert body["business_id"] == "biz-1"
    assert body["event_type"] == "booking_paid"
    assert body["contact_id"] == "c1"
    assert body["source"] == "stripe_webhook"
    assert body["data"] == {"booking_id": "b1"}


def test_emit_without_business_id_is_dropped():
    with mock.patch.object(event_spine.sb_clients, "sb_post_as_service") as post:
        assert event_spine.emit("booking_paid", None, {}) is False
        assert event_spine.emit("booking_paid", "", {}) is False
        post.assert_not_called()


def test_emit_never_raises():
    with mock.patch.object(event_spine.sb_clients, "sb_post_as_service",
                           side_effect=RuntimeError("db down")):
        assert event_spine.emit("booking_paid", "biz-1", {}) is False


def test_uncataloged_type_still_writes_but_logs_error():
    calls = []
    with mock.patch.object(event_spine.sb_clients, "sb_post_as_service",
                           side_effect=lambda path, body, prefer=None: calls.append(body)), \
         mock.patch.object(event_spine.logger, "error") as err:
        ok = event_spine.emit("totally_new_thing", "biz-1", {})
    assert ok is True and calls
    err.assert_called_once()


def test_catalog_entries_are_well_formed():
    for etype, meta in event_spine.EVENT_CATALOG.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]+", etype), f"bad event name: {etype}"
        assert meta.get("source"), f"{etype} missing source"
        assert isinstance(meta.get("payload"), list), f"{etype} missing payload keys"


_EMIT_RE = re.compile(r"""event_spine\.emit\(\s*['"]([a-z0-9_]+)['"]""")


def test_drift_every_emitted_type_is_cataloged():
    root = pathlib.Path(__file__).resolve().parent.parent
    emitted = set()
    for py in root.glob("*.py"):
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        emitted.update(_EMIT_RE.findall(text))
    assert emitted, "no event_spine.emit call sites found — regex drifted?"
    missing = emitted - set(event_spine.EVENT_CATALOG)
    assert not missing, f"emitted but not in EVENT_CATALOG: {sorted(missing)}"
