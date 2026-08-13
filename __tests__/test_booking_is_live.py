"""Post-audit gap list (2026-08-13) — the booking detector must not be
able to say yes about a page that will 404.

booking_is_live() short-circuited on settings.booking.enabled, a legacy
flag, returning True WITHOUT checking that a bookable page existed. The
booking page server reads only settings.booking_page.published. So the
two disagreed by design: ticking the old settings form made the composer
build a "Book now" CTA, and the visitor got

    404 — This booking page isn't published yet.

That was the default path for coach, consultant, lawyer, therapist and
church until the settings form was deleted. Nothing writes that flag any
more and no business in production has it set, so the branch was a trap
with no upside.

This is the detector's first test file — it had none, which is part of
how the two systems drifted apart in the first place.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import booking_widget_router as bwr  # noqa: E402


BIZ = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def module_exists(monkeypatch):
    def _install(exists: bool):
        monkeypatch.setattr(bwr, "_bookings_module",
                            lambda bid: {"id": "m1"} if exists else None)
    return _install


def test_published_page_with_a_module_is_live(module_exists):
    module_exists(True)
    assert bwr.booking_is_live(BIZ, {"booking_page": {"published": True}}) is True


def test_published_page_without_a_module_is_not_live(module_exists):
    """Publishing alone is not enough — the widget needs a module to
    load its config from, or it renders an error to the visitor."""
    module_exists(False)
    assert bwr.booking_is_live(BIZ, {"booking_page": {"published": True}}) is False


def test_unpublished_page_is_not_live(module_exists):
    module_exists(True)
    assert bwr.booking_is_live(BIZ, {"booking_page": {"published": False}}) is False


def test_the_legacy_flag_alone_no_longer_says_yes(module_exists):
    """THE regression. This returned True, and the CTA it authorised
    answered 404."""
    module_exists(False)
    assert bwr.booking_is_live(BIZ, {"booking": {"enabled": True}}) is False


def test_the_legacy_flag_cannot_rescue_an_unpublished_page(module_exists):
    module_exists(True)
    settings = {"booking": {"enabled": True},
                "booking_page": {"published": False}}
    assert bwr.booking_is_live(BIZ, settings) is False


def test_legacy_flag_is_simply_ignored_when_the_modern_setup_is_real(module_exists):
    module_exists(True)
    settings = {"booking": {"enabled": False},
                "booking_page": {"published": True}}
    assert bwr.booking_is_live(BIZ, settings) is True


def test_missing_or_malformed_settings_are_not_live(module_exists):
    module_exists(True)
    for settings in ({}, None, {"booking_page": None}, {"booking_page": "nope"}):
        assert bwr.booking_is_live(BIZ, settings) is False
