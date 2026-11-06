"""A church's setup list speaks church (run-through, 2026-11-05).

The new church's first-steps card said "Bring your client list over"
because "history, campaigns, invoices ... reads from your contacts", and
"Connect how you get paid" because it "turns an invoice from a PDF into
money". The steps and their doors are right for a church; the words
weren't. business_track_actions.VERTICAL_WORDS gives a church its own.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import business_track_actions as bta  # noqa: E402

BUSINESS_WORDS = ("client", "invoice", "customer", "sell", "pay when they book")


def test_a_church_is_told_to_bring_its_people_and_connect_stripe_for_giving():
    assert bta.words_for("import_contacts", "church")["title"] == "Bring your people over"
    assert bta.words_for("payments", "ministry")["title"] == "Connect Stripe for giving"


def test_none_of_a_churchs_words_are_business_words():
    for key, words in bta.VERTICAL_WORDS["ministry"].items():
        assert key in bta.PLUGIN_CATALOG, key
        for field in ("title", "why", "chief"):
            text = (words.get(field) or "").lower()
            for w in BUSINESS_WORDS:
                assert w not in text, (key, field, w)


def test_every_step_a_church_is_shown_reads_clean():
    """Title and why of every step on a church's list, as resolve_plugins
    builds them, carry no business word."""
    for key in bta.plugins_for_vertical("church"):
        spec = bta.PLUGIN_CATALOG[key]
        words = bta.words_for(key, "church")
        title = (words.get("title") or spec["title"]).lower()
        why = (words.get("why") or spec["why"]).lower()
        for w in ("client", "invoice", "customer"):
            assert w not in title and w not in why, (key, w)


def test_a_business_keeps_the_catalogs_words():
    assert bta.words_for("import_contacts", "barber") == {}
    assert bta.words_for("payments", "coach") == {}


def test_chief_is_told_the_churchs_why_for_payments():
    assert "gifts" in bta.plugin_how("payments", business_type="church")
    assert "invoice" in bta.plugin_how("payments", business_type="barber")


def test_chiefs_menu_of_steps_uses_the_churchs_titles():
    menu = bta._plugin_menu_for_prompt("church")
    assert "Bring your people over" in menu and "client list" not in menu


def test_resolve_plugins_hands_the_church_its_words(monkeypatch):
    import business_track_router as btr
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    monkeypatch.setattr(btr, "_probe", lambda key, biz: False)
    items = btr.resolve_plugins({"id": "b1", "type": "church", "settings": {}})
    by = {i["key"]: i for i in items}
    assert by["import_contacts"]["title"] == "Bring your people over"
    assert by["payments"]["title"] == "Connect Stripe for giving"
    assert "invoice" not in by["payments"]["why"].lower()
    shop = {i["key"]: i for i in btr.resolve_plugins({"id": "b2", "type": "barber", "settings": {}})}
    assert shop["import_contacts"]["title"] == "Bring your client list over"
