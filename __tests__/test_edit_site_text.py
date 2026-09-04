"""edit_site_text / revert_site_text — Chief changes one line on the site.

The verb writes the override row Studio Edit Mode writes, keyed on a
data-override-target, so it reaches composed sites (re-rendered) and
hand-built ones (served with overrides applied) alike. What the tests pin:
a quoted phrase resolves to exactly one spot or the action refuses and
names the candidates; a known target path is honored directly; the new
wording is stored escaped; the previous wording rides on the result so
undo has what it needs; hand-built sites are live at once while composed
sites get a background re-render; and the two verbs invert each other.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import chief_of_staff as cos  # noqa: E402
import action_inverse as ai  # noqa: E402
import action_registry  # noqa: E402
from __tests__._chief_source import chief_source  # noqa: E402

BIZ = {"id": "biz-1", "name": "KMJ"}
TARGETS = [
    {"page": "home", "target_path": "home.hero.lead",
     "current": "KMJ Creative Solutions is Kevin McCloud Jr.'s practice for founders."},
    {"page": "home", "target_path": "home.cta.title", "current": "Ready to step out and build?"},
    {"page": "contact", "target_path": "contact.card", "current": "No fee, no pitch. Pick a time that works."},
    {"page": "services", "target_path": "services.hero.card",
     "current": "Thirty minutes, no fee, no pitch. We listen for the calling beneath the question."},
]


class _Store:
    def __init__(self):
        self.upserts = []
        self.deleted = []
        self.rows = {}

    def upsert_override(self, biz, otype, path, value, selector=None, original=None, created_via="manual_edit"):
        self.upserts.append({"biz": biz, "type": otype, "path": path, "value": value,
                             "original": original, "via": created_via})
        self.rows[path] = {"override_value": value}
        return {"id": "ov-1"}

    def get_override(self, biz, otype, path):
        return self.rows.get(path)

    def delete_override_by_path(self, biz, otype, path):
        self.deleted.append(path)
        return self.rows.pop(path, None) is not None


@pytest.fixture
def wired(monkeypatch):
    store = _Store()
    from agents.override_system import override_storage
    monkeypatch.setattr(override_storage, "upsert_override", store.upsert_override)
    monkeypatch.setattr(override_storage, "get_override", store.get_override)
    monkeypatch.setattr(override_storage, "delete_override_by_path", store.delete_override_by_path)
    refreshed = []
    monkeypatch.setattr(cos, "_site_text_refresh_if_composed", lambda b: refreshed.append(b))
    state = {"manual": True}
    monkeypatch.setattr(cos, "_site_text_targets", lambda b: (list(TARGETS), state["manual"]))
    return store, refreshed, state


def _run(coro):
    return asyncio.run(coro)


def test_registered_classified_and_taught():
    assert cos.ACTION_HANDLERS["edit_site_text"] is cos.handle_edit_site_text
    assert cos.ACTION_HANDLERS["revert_site_text"] is cos.handle_revert_site_text
    assert action_registry.reversibility("edit_site_text") == "A"
    assert action_registry.reversibility("revert_site_text") == "A"
    src = chief_source()
    assert '"type":"edit_site_text","find"' in src      # the model is shown the shape
    assert '"type":"revert_site_text","target"' in src


def test_a_quoted_phrase_edits_exactly_one_spot_and_is_live_on_a_manual_site(wired):
    store, refreshed, _ = wired
    out = _run(cos.handle_edit_site_text(None, BIZ, {"find": "step out and build", "text": "Ready to build?"}))
    assert not out.get("failed"), out
    assert out["target_path"] == "home.cta.title"
    assert out["previous_text"] == "Ready to step out and build?"
    assert "Live now" in out["label"]
    assert store.upserts[0]["path"] == "home.cta.title"
    assert store.upserts[0]["value"] == "Ready to build?"
    assert store.upserts[0]["original"] == "Ready to step out and build?"
    assert store.upserts[0]["via"] == "chief_command"
    assert refreshed == []


def test_new_wording_is_stored_escaped_never_as_markup(wired):
    store, _, _ = wired
    out = _run(cos.handle_edit_site_text(None, BIZ, {"target": "home.hero.lead",
                                                     "text": "Clarity <b>first</b> & always"}))
    assert not out.get("failed")
    assert store.upserts[0]["value"] == "Clarity &lt;b&gt;first&lt;/b&gt; &amp; always"


def test_an_ambiguous_phrase_is_refused_and_the_candidates_are_named(wired):
    store, _, _ = wired
    out = _run(cos.handle_edit_site_text(None, BIZ, {"find": "no fee, no pitch", "text": "Free."}))
    assert out.get("failed")
    assert "more than one spot" in out["result"]
    assert "contact" in out["result"] and "services" in out["result"]
    assert store.upserts == []


def test_unknown_wording_and_missing_inputs_are_refused(wired):
    store, _, _ = wired
    assert _run(cos.handle_edit_site_text(None, BIZ, {"find": "not on the site", "text": "x"})).get("failed")
    assert _run(cos.handle_edit_site_text(None, BIZ, {"text": "x"})).get("failed")
    assert _run(cos.handle_edit_site_text(None, BIZ, {"find": "build"})).get("failed")
    assert _run(cos.handle_edit_site_text(None, BIZ, {"target": "home.hero.lead", "text": "y" * 601})).get("failed")
    assert store.upserts == []


def test_a_composed_site_gets_a_background_re_render(wired):
    store, refreshed, state = wired
    state["manual"] = False
    out = _run(cos.handle_edit_site_text(None, BIZ, {"target": "home.hero.lead", "text": "New lead."}))
    assert not out.get("failed")
    assert refreshed == ["biz-1"]
    assert "Re-rendering" in out["label"]


def test_revert_removes_the_override_and_carries_the_words_for_redo(wired):
    store, _, _ = wired
    _run(cos.handle_edit_site_text(None, BIZ, {"target": "home.hero.lead", "text": "New lead."}))
    out = _run(cos.handle_revert_site_text(None, BIZ, {"target": "home.hero.lead"}))
    assert not out.get("failed"), out
    assert store.deleted == ["home.hero.lead"]
    assert out["previous_text"] == "New lead."
    again = _run(cos.handle_revert_site_text(None, BIZ, {"target": "home.hero.lead"}))
    assert again.get("failed")


def test_the_two_verbs_invert_each_other_from_the_result():
    edit_result = {"target_path": "home.cta.title", "previous_text": "Ready to step out and build?"}
    inv = ai.build_inverse("edit_site_text", {"find": "step out"}, edit_result)
    assert inv == {"type": "revert_site_text", "target": "home.cta.title"}
    revert_result = {"target_path": "home.cta.title", "previous_text": "Ready to build?"}
    redo = ai.build_inverse("revert_site_text", {"target": "home.cta.title"}, revert_result)
    assert redo == {"type": "edit_site_text", "target": "home.cta.title", "text": "Ready to build?"}
    assert ai.build_inverse("edit_site_text", {"find": "x"}, {}) is None


def test_targets_are_read_from_home_and_every_generated_page(monkeypatch):
    import sb_clients
    row = {"html_content": '<p data-override-target="home.hero.lead">Old <b>lead</b></p>',
           "site_config": {"html_source": "manual",
                           "generated_pages": {"about": '<h1 data-override-target="about.h">About &amp; more</h1>'}}}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [row])
    from agents.override_system import override_resolver
    monkeypatch.setattr(override_resolver, "resolve_html_overrides",
                        lambda html, biz: html.replace("Old <b>lead</b>", "Edited lead"))
    targets, manual = cos._site_text_targets("biz-1")
    assert manual is True
    assert targets == [
        {"page": "home", "target_path": "home.hero.lead", "current": "Edited lead"},
        {"page": "about", "target_path": "about.h", "current": "About & more"},
    ]
