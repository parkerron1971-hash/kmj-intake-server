"""
test_brand_draft.py — Brand Studio's draft: edits that survive leaving
the page, and a Publish that makes them live.

What must hold:
  • A draft is written ALONE — its own two columns, never `settings`.
    save_brand_kit rewrites the whole settings object; a draft that
    autosaves every few seconds into settings would race every other
    settings writer (assistant name, theme, site brief).
  • A write that did not land is an ERROR, not a quiet success. PostgREST
    answers a request that failed with None and a row RLS filtered out
    with [] — both are failures here.
  • Publish = save_brand_kit (which snapshots the live kit into history)
    then clear the draft; the page's kit wins over the stored draft.
"""
import pytest

import brand_engine


@pytest.fixture
def patched(monkeypatch):
    calls = []
    state = {"patch_result": [{"id": "biz-1"}], "row": {}}

    def fake_patch(path, payload):
        calls.append((path, payload))
        return state["patch_result"]

    def fake_get(path):
        return [state["row"]]

    monkeypatch.setattr(brand_engine, "_sb_patch", fake_patch)
    monkeypatch.setattr(brand_engine, "_sb_get", fake_get)
    return calls, state


def test_a_draft_writes_only_its_own_columns(patched):
    calls, _ = patched
    out = brand_engine.save_brand_draft("biz-1", {"tagline": "New line"})
    path, payload = calls[-1]
    assert set(payload) == {"brand_kit_draft", "brand_kit_draft_at"}, \
        "a draft must never write settings — that races every other settings writer"
    assert payload["brand_kit_draft"] == {"tagline": "New line"}
    assert out["draft_at"] == payload["brand_kit_draft_at"]
    assert path.startswith("/businesses?id=eq.biz-1")


def test_a_failed_write_is_an_error_not_a_success(patched):
    _, state = patched
    for failed in (None, []):     # request failed / RLS filtered the row
        state["patch_result"] = failed
        with pytest.raises(brand_engine.BrandDraftError) as e:
            brand_engine.save_brand_draft("biz-1", {"tagline": "x"})
        assert e.value.status == 502


def test_bad_input_is_a_400(patched):
    with pytest.raises(brand_engine.BrandDraftError) as e:
        brand_engine.save_brand_draft("biz-1", ["not", "a", "kit"])  # type: ignore[arg-type]
    assert e.value.status == 400
    with pytest.raises(brand_engine.BrandDraftError) as e:
        brand_engine.save_brand_draft("biz-1", {"tagline": "x" * (brand_engine.BRAND_DRAFT_MAX_BYTES + 1)})
    assert e.value.status == 400


def test_reading_an_empty_draft_says_none(patched):
    _, state = patched
    state["row"] = {"brand_kit_draft": None, "brand_kit_draft_at": None}
    assert brand_engine.get_brand_draft("biz-1") == {"draft": None, "draft_at": None}
    state["row"] = {"brand_kit_draft": {}, "brand_kit_draft_at": "2026-09-28T00:00:00Z"}
    assert brand_engine.get_brand_draft("biz-1")["draft"] is None, "an empty object is no draft"


def test_publish_saves_the_pages_kit_then_clears(patched, monkeypatch):
    calls, state = patched
    state["row"] = {"brand_kit_draft": {"tagline": "stored"}, "brand_kit_draft_at": "t"}
    saved = {}
    monkeypatch.setattr(brand_engine, "save_brand_kit",
                        lambda biz, kit: saved.setdefault("kit", kit) and {"ok": "bundle"})
    out = brand_engine.publish_brand_draft("biz-1", {"tagline": "on screen"})
    assert saved["kit"] == {"tagline": "on screen"}, "the page's kit wins over the stored draft"
    assert out == {"ok": "bundle"}
    assert calls[-1][1] == {"brand_kit_draft": None, "brand_kit_draft_at": None}


def test_publish_without_a_kit_uses_the_stored_draft(patched, monkeypatch):
    _, state = patched
    state["row"] = {"brand_kit_draft": {"tagline": "stored"}, "brand_kit_draft_at": "t"}
    saved = {}
    monkeypatch.setattr(brand_engine, "save_brand_kit",
                        lambda biz, kit: saved.setdefault("kit", kit) and {})
    brand_engine.publish_brand_draft("biz-1")
    assert saved["kit"] == {"tagline": "stored"}


def test_nothing_to_publish_is_a_400(patched):
    _, state = patched
    state["row"] = {"brand_kit_draft": None}
    with pytest.raises(brand_engine.BrandDraftError) as e:
        brand_engine.publish_brand_draft("biz-1")
    assert e.value.status == 400


def test_a_draft_that_will_not_clear_does_not_undo_the_publish(patched, monkeypatch):
    """Published is what the owner asked for. A lingering draft equals the
    live kit, which the studio reads as no changes — log it, don't fail."""
    _, state = patched
    monkeypatch.setattr(brand_engine, "save_brand_kit", lambda biz, kit: {"live": True})
    state["patch_result"] = None
    assert brand_engine.publish_brand_draft("biz-1", {"tagline": "x"}) == {"live": True}


# ─── Publish carries the brand onto the website, and says so ───────

import sys
import types


@pytest.fixture
def site(monkeypatch):
    started = []
    fake = types.ModuleType("site_composer")
    fake.refresh_if_composed_async = lambda biz: started.append(biz)
    monkeypatch.setitem(sys.modules, "site_composer", fake)
    rows = {"value": []}
    monkeypatch.setattr(brand_engine.sb_clients, "sb_get_as_service", lambda path: rows["value"])
    return started, rows


@pytest.mark.parametrize("source", ["module-composer", "canvas"])
def test_a_composed_site_is_refreshed(site, source):
    started, rows = site
    rows["value"] = [{"html_source": source}]
    assert brand_engine.refresh_site_after_publish("biz-1") == "refreshing"
    assert started == ["biz-1"]


def test_a_site_the_refresh_cannot_touch_is_not_claimed(site):
    """A manual or legacy site would be a no-op refresh — the sheet must not
    say 'your website is updating' for it."""
    started, rows = site
    rows["value"] = [{"html_source": "manual"}]
    assert brand_engine.refresh_site_after_publish("biz-1") == "not_composed"
    assert started == []


def test_no_site_says_so(site):
    started, rows = site
    rows["value"] = []
    assert brand_engine.refresh_site_after_publish("biz-1") == "no_site"
    assert started == []
