"""Site-builder audit (2026-08-13) — a booking page that can't take a
booking must not go live.

Publishing checked nothing: no module, no services, no availability. The
toggle flipped regardless, and the page went live telling every visitor
"No services available right now" while the site's hero still said Book
now. The widget's empty state was honest; the site around it was not.

Availability is deliberately NOT a blocker — no availability means
bookable 24/7, which is permissive rather than broken. Pinned below so a
future change doesn't quietly make it one.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import booking_page_router as bpr  # noqa: E402


BIZ = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

MODULE_ROW = [{"id": "mod-1"}]
OFFERING_ROW = [{"id": "off-1"}]


class _Sb:
    """Answers each PostgREST path by what it is asking for, so a test
    can describe a business by what it HAS rather than by call order."""

    def __init__(self, *, has_module: bool, has_bookable: bool):
        self.has_module = has_module
        self.has_bookable = has_bookable
        self.paths: list = []

    def sb_get_as_service(self, path: str):
        self.paths.append(path)
        if "custom_modules" in path:
            return MODULE_ROW if self.has_module else []
        if "offerings" in path:
            return OFFERING_ROW if self.has_bookable else []
        return []


@pytest.fixture
def sb(monkeypatch):
    def _install(**kw):
        fake = _Sb(**kw)
        monkeypatch.setattr(bpr, "sb_clients", fake)
        return fake

    return _install


def test_ready_business_has_no_blockers(sb):
    sb(has_module=True, has_bookable=True)
    assert bpr.publish_blockers(BIZ) == []


def test_no_booking_module_blocks_publish(sb):
    sb(has_module=False, has_bookable=True)
    blockers = bpr.publish_blockers(BIZ)
    assert len(blockers) == 1
    assert "hasn't been built yet" in blockers[0]


def test_no_bookable_service_blocks_publish(sb):
    """The exact state that produced 'No services available right now'
    on a live page whose site said Book now."""
    sb(has_module=True, has_bookable=False)
    blockers = bpr.publish_blockers(BIZ)
    assert len(blockers) == 1
    assert "at least one service" in blockers[0]


def test_empty_business_reports_both(sb):
    sb(has_module=False, has_bookable=False)
    assert len(bpr.publish_blockers(BIZ)) == 2


def test_bookable_query_requires_a_real_duration(sb):
    """A service with no duration is skipped by the slot engine, so it
    shows in the picker and then offers zero times. It must not count as
    bookable."""
    fake = sb(has_module=True, has_bookable=True)
    bpr.publish_blockers(BIZ)
    offerings_q = next(p for p in fake.paths if "offerings" in p)
    assert "duration_min=gt.0" in offerings_q
    assert "is_active=eq.true" in offerings_q
    assert f"business_id=eq.{BIZ}" in offerings_q


def test_availability_is_not_consulted(sb):
    """No availability means bookable 24/7 — permissive, not broken.
    Making it a blocker would stop legitimate publishes."""
    fake = sb(has_module=True, has_bookable=True)
    bpr.publish_blockers(BIZ)
    assert not any("availability" in p for p in fake.paths)
