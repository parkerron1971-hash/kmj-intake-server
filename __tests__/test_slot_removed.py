"""
test_slot_removed.py — the practitioner "Remove image" flag.

Pure-function coverage of the resolution layer (no IO):
  - resolve_slot_url: removed wins over custom AND default; the flag
    rides the record, not the URL fields, so nothing is destroyed.
  - resolve_html_slots: a removed slot's <img> is stripped entirely —
    no placeholder box on a live public page — while other slots in
    the same document keep resolving normally.
"""
from agents.slot_system.slot_resolver import (
    resolve_html_slots,
    resolve_slot_url,
)


def _record(**overrides):
    base = {
        "default_url": "https://img.example/default.jpg",
        "default_source": "unsplash",
        "default_credit": {"name": "Ada", "url": "https://u", "username": "ada"},
        "custom_url": None,
        "removed": False,
    }
    base.update(overrides)
    return base


# ─── resolve_slot_url ────────────────────────────────────────────────

def test_removed_wins_over_custom_and_default():
    resolved = resolve_slot_url(
        _record(custom_url="https://img.example/mine.jpg", removed=True),
        "hero_main",
    )
    assert resolved["source"] == "removed"
    assert resolved["url"] is None
    assert resolved["removed"] is True
    # Not a placeholder: the renderer must strip, not draw an
    # "add your photo" box.
    assert resolved["is_placeholder"] is False


def test_not_removed_resolves_normally():
    resolved = resolve_slot_url(_record(), "hero_main")
    assert resolved["source"] == "default"
    assert resolved["url"] == "https://img.example/default.jpg"

    resolved = resolve_slot_url(
        _record(custom_url="https://img.example/mine.jpg"), "hero_main"
    )
    assert resolved["source"] == "custom"


def test_legacy_record_without_flag_is_unaffected():
    legacy = _record()
    del legacy["removed"]
    resolved = resolve_slot_url(legacy, "hero_main")
    assert resolved["source"] == "default"


# ─── resolve_html_slots ──────────────────────────────────────────────

_HTML = (
    "<html><body>"
    '<img data-slot="hero_main" src="" alt="hero" class="hero">'
    '<img data-slot="about_subject" src="" alt="about">'
    "</body></html>"
)


def test_removed_slot_img_is_stripped_others_resolve():
    slots = {
        "hero_main": _record(removed=True),
        "about_subject": _record(),
    }
    out, credits, found = resolve_html_slots(_HTML, slots, slot_definitions={})
    assert "hero_main" not in out            # tag gone entirely
    assert "slot-placeholder" not in out     # and no placeholder box
    assert 'data-slot="about_subject"' in out
    assert "https://img.example/default.jpg" in out
    assert sorted(found) == ["about_subject", "hero_main"]
    # A stripped slot contributes no photographer credit.
    assert len(credits) == 1


def test_removed_slot_with_custom_upload_still_stripped():
    slots = {
        "hero_main": _record(
            custom_url="https://img.example/mine.jpg", removed=True
        ),
        "about_subject": _record(),
    }
    out, _credits, _found = resolve_html_slots(_HTML, slots, slot_definitions={})
    assert "mine.jpg" not in out
    assert "hero_main" not in out
