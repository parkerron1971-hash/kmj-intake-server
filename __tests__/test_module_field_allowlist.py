"""Site-builder audit (2026-08-13) — an empty allow-list is not a licence
to publish everything.

Both public module renderers treated an empty `visible_fields` as "show
every field except three hardcoded names" (assigned_to, internal_notes,
contact_id). That turns an allow-list into a deny-list the moment it is
empty — and enabling a module WITHOUT writing that list is exactly what
Chief's ensure_module and the Resources library do.

A field called notes, phone, email, rate or client published itself.
Chief's own client-roster skill is instructed to add referral source,
rate and a note about the client's goal.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import public_site  # noqa: E402
import site_composer  # noqa: E402


ENTRY = {
    "title": "Tuesday intake",
    "client": "Dana Rowe",
    "rate": "180",
    "notes": "going through a divorce",
    "assigned_to": "sam",
}

DEFAULT_HIDDEN = ["assigned_to", "internal_notes", "contact_id"]
SENSITIVE = ("client", "rate", "notes")


# ─── the link-page / widget renderer ─────────────────────────────────


def test_chosen_fields_are_shown():
    assert public_site._filter_entry(ENTRY, ["title"], DEFAULT_HIDDEN) == {
        "title": "Tuesday intake"}


def test_hidden_wins_over_chosen():
    got = public_site._filter_entry(ENTRY, ["title", "assigned_to"], DEFAULT_HIDDEN)
    assert "assigned_to" not in got


def test_empty_allowlist_publishes_nothing():
    """The finding itself. This used to return client, rate and notes."""
    assert public_site._filter_entry(ENTRY, [], DEFAULT_HIDDEN) == {}


def test_empty_allowlist_with_no_hidden_list_publishes_nothing():
    """The worst case: a writer that set enabled:true and nothing else."""
    assert public_site._filter_entry(ENTRY, [], []) == {}


# ─── the composer renderer that feeds the LIVE site ──────────────────


class _Sb:
    """Two-call stand-in: modules, then that module's entries."""

    def __init__(self, public_display):
        self.public_display = public_display

    def sb_get_as_service(self, path: str):
        if "custom_modules" in path:
            return [{"id": "m1", "name": "Clients", "schema": {},
                     "public_display": self.public_display}]
        if "module_entries" in path:
            return [{"id": "e1", "data": dict(ENTRY), "created_at": "2026-01-01"}]
        return []


@pytest.fixture
def composer_sb(monkeypatch):
    def _install(public_display):
        monkeypatch.setattr(site_composer, "sb_clients", _Sb(public_display))
    return _install


def test_composer_publishes_only_chosen_fields(composer_sb):
    composer_sb({"enabled": True, "visible_fields": ["title"]})
    out = site_composer._fetch_public_modules("biz-1")
    assert out and out[0]["entries"] == [{"title": "Tuesday intake"}]


def test_composer_publishes_nothing_when_no_fields_were_chosen(composer_sb):
    """enabled:true with no visible_fields is exactly what
    Chief's ensure_module writes. It used to publish the whole row."""
    composer_sb({"enabled": True})
    out = site_composer._fetch_public_modules("biz-1")
    assert out and out[0]["entries"] == []


def test_composer_never_leaks_sensitive_fields_on_an_empty_allowlist(composer_sb):
    composer_sb({"enabled": True, "visible_fields": []})
    out = site_composer._fetch_public_modules("biz-1")
    published = " ".join(str(r) for r in out[0]["entries"])
    for field in SENSITIVE:
        assert field not in published


def test_composer_still_honours_hidden_fields(composer_sb):
    composer_sb({"enabled": True, "visible_fields": ["title", "assigned_to"]})
    out = site_composer._fetch_public_modules("biz-1")
    assert out[0]["entries"] == [{"title": "Tuesday intake"}]


def test_disabled_modules_are_not_fetched_at_all(composer_sb):
    composer_sb({"enabled": False, "visible_fields": ["title"]})
    assert site_composer._fetch_public_modules("biz-1") == []
