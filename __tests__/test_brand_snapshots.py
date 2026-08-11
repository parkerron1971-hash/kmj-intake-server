"""
test_brand_snapshots.py — Restore must stop being a coin flip.

THE DEFECT (2026-08-10 Brand Studio audit): the bundle carried only
`snapshot_count`, so the Brand Room could offer "Restore most recent"
and "Restore the one before" and nothing else. The practitioner had no
way to know which design they were about to get back or how old it was.

`saved_at` was written on every snapshot from the very first version of
save_brand_kit and simply never left the server.

The trap this pins: snapshots are stored kits, and kits exist in TWO
shapes. `_normalize_brand_kit` writes nested and flat together now, but
rows written by older code carry only one. A summary that read just one
shape would render a blank, unlabelled row for those — which is worse
than showing no list at all, because a blank row still looks clickable.
"""
import brand_engine


LOGO = "https://cdn.example.com/brand/primary.png"


def _bundle(monkeypatch, brand_kit, history):
    def fake_one(table, col, val):
        if table == "businesses":
            return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                    "settings": {"brand_kit": brand_kit},
                    "brand_kit_history": history}
        return {}
    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    return brand_engine.get_bundle("biz-1", use_cache=False)


NESTED = {
    "kit": {
        "tagline": "Systems that run your business.",
        "colors": {"primary": "#2E7DFF"},
        "font_pair": {"heading": "Inter Tight"},
    },
    "saved_at": "2026-08-09T14:03:00Z",
}

# What older code left behind: flat keys only, no nested mirror.
FLAT_ONLY = {
    "kit": {
        "tagline": "The old line.",
        "primary_color": "#1A365D",
        "font_heading": "Cormorant Garamond",
    },
    "saved_at": "2026-08-01T09:15:00Z",
}


def test_the_bundle_says_what_each_version_was(monkeypatch):
    b = _bundle(monkeypatch, {"tagline": "now"}, [NESTED])
    snaps = b["snapshots"]
    assert len(snaps) == 1
    s = snaps[0]
    assert s["idx"] == 0, "the index is what restore_snapshot takes"
    assert s["saved_at"] == "2026-08-09T14:03:00Z"
    assert s["primary_color"] == "#2E7DFF"
    assert s["font_heading"] == "Inter Tight"
    assert s["tagline"] == "Systems that run your business."


def test_a_flat_shaped_snapshot_is_not_a_blank_row(monkeypatch):
    """The whole reason the summary reads both shapes."""
    b = _bundle(monkeypatch, {"tagline": "now"}, [FLAT_ONLY])
    s = b["snapshots"][0]
    assert s["primary_color"] == "#1A365D"
    assert s["font_heading"] == "Cormorant Garamond"
    assert s["tagline"] == "The old line."


def test_indexes_line_up_with_restore(monkeypatch):
    """idx N in the list must be the same version restore_snapshot(N)
    returns, or the room offers one design and hands back another."""
    b = _bundle(monkeypatch, {"tagline": "now"}, [NESTED, FLAT_ONLY])
    snaps = b["snapshots"]
    assert [s["idx"] for s in snaps] == [0, 1]
    assert snaps[0]["primary_color"] == "#2E7DFF"
    assert snaps[1]["primary_color"] == "#1A365D"
    assert b["snapshot_count"] == 2, "the old field still ships for existing readers"


def test_a_partial_snapshot_reports_none_rather_than_guessing(monkeypatch):
    b = _bundle(monkeypatch, {"tagline": "now"}, [{"kit": {}, "saved_at": None}])
    s = b["snapshots"][0]
    assert s["tagline"] is None
    assert s["primary_color"] is None
    assert s["font_heading"] is None
    assert s["saved_at"] is None


def test_no_history_is_an_empty_list_not_a_missing_key(monkeypatch):
    """A consumer must never have to guess whether the key exists."""
    b = _bundle(monkeypatch, {"tagline": "now"}, [])
    assert b["snapshots"] == []
    assert b["snapshot_count"] == 0


def test_the_empty_bundle_carries_the_key_too(monkeypatch):
    def none_one(table, col, val):
        return None
    monkeypatch.setattr(brand_engine, "_safe_get_one", none_one)
    b = brand_engine.get_bundle("nope", use_cache=False)
    assert b["snapshots"] == []
