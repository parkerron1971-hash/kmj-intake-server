"""The site says "no card needed" only while signup really starts the
trial without a card (no_card_trial.py, 2026-10-03).

The card half of the trial promise is a token, filled from the same test
/access/open answers. With the no-card trial on, the home, its FAQ, the
page's own Q&A and /get-started say no card is needed; with it off, they
say what they said before — no card charged until the trial ends — which
is true either way.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import marketing_pages as mp  # noqa: E402


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import stripe_billing
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")


def _on(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.delenv("PRICE_NO_CARD_TRIAL", raising=False)


def _off(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("PRICE_NO_CARD_TRIAL", "0")


def test_on_the_site_says_no_card_needed(monkeypatch):
    _on(monkeypatch)
    home = mp.render_home()
    assert "no card needed to start" in home          # FAQ + the page's Q&A
    assert "7 days free · no card needed" in home     # the fine print
    start = mp.render_get_started()
    assert "no card needed to start" in start
    assert "no card needed" in start


def test_off_the_site_keeps_the_card_trial_wording(monkeypatch):
    _off(monkeypatch)
    home = mp.render_home()
    assert "no card needed" not in home
    assert "no card charged until the trial ends" in home
    assert "no card needed" not in mp.render_get_started()


def test_without_enforcement_nothing_promises_no_card(monkeypatch):
    """No no-card trial starts while BILLING_ENFORCE is off, so the site
    must not promise one."""
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    monkeypatch.delenv("PRICE_NO_CARD_TRIAL", raising=False)
    assert "no card needed" not in mp.render_home()


def test_the_site_and_the_signup_door_agree(monkeypatch):
    import launch_access
    for setup in (_on, _off):
        setup(monkeypatch)
        assert mp._no_card_trial_offered() is launch_access.access_open()["no_card_trial"]


def test_no_token_reaches_a_visitor(monkeypatch):
    for setup in (_on, _off):
        setup(monkeypatch)
        for html in (mp.render_home(), mp.render_get_started(), mp.render_home_v1()):
            assert mp.CARD_TOKEN not in html and mp.CARD_NOTE_TOKEN not in html
