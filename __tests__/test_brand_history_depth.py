"""
test_brand_history_depth.py — how far back Restore can reach.

The cap was 2, set when nothing could SEE the history: the Brand Room
offered "Restore most recent" and "the one before", so two was as much
as the interface could use. It now lists every stored version with its
date, primary colour, heading face and tagline — so the cap became the
limit rather than the UI.

A full kit measures ~2.1KB, so ten is ~21KB on a business row.

What these pin is the ORDER and the TRIM, because getting either wrong
is silent: a reversed list hands back the oldest version when the owner
asked for the newest, and an off-by-one trim throws away a version the
list is still offering.
"""
import brand_engine


def _saved(monkeypatch, prior_kit, prior_history, new_kit):
    captured = {}

    def fake_one(table, col, val):
        return {"id": "biz-1", "name": "KMJ", "owner_id": "o1",
                "settings": {"brand_kit": prior_kit},
                "brand_kit_history": prior_history}

    monkeypatch.setattr(brand_engine, "_safe_get_one", fake_one)
    monkeypatch.setattr(brand_engine, "_sb_patch",
                        lambda path, payload: captured.update(payload) or [{"id": "biz-1"}])
    monkeypatch.setattr(brand_engine, "invalidate_bundle_cache", lambda *a, **k: None)
    monkeypatch.setattr(brand_engine, "get_bundle", lambda *a, **k: {})
    brand_engine.save_brand_kit("biz-1", new_kit)
    return captured.get("brand_kit_history") or []


def _hist(n):
    """n prior snapshots, newest first — the order save_brand_kit keeps."""
    return [{"kit": {"tagline": f"v{i}"}, "saved_at": f"2026-08-{10 - i:02d}T00:00:00Z"}
            for i in range(n)]


def test_it_keeps_ten_not_two(monkeypatch):
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(9), {"tagline": "new"})
    assert len(out) == 10


def test_the_newest_is_first(monkeypatch):
    """idx 0 is what the room labels 'most recent' and what
    restore_snapshot(0) returns. A reversed list would hand back the
    oldest kit while the row said otherwise."""
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(3), {"tagline": "new"})
    assert out[0]["kit"]["tagline"] == "current", \
        "the kit being replaced must land at the front"
    assert out[1]["kit"]["tagline"] == "v0"


def test_the_eleventh_pushes_out_the_oldest(monkeypatch):
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(10), {"tagline": "new"})
    assert len(out) == 10
    assert out[0]["kit"]["tagline"] == "current"
    assert out[-1]["kit"]["tagline"] == "v8", "v9 was the oldest and should be gone"


def test_an_over_long_history_is_trimmed_back(monkeypatch):
    """A row written before the cap changed, or by hand."""
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(40), {"tagline": "new"})
    assert len(out) == 10


def test_existing_rows_are_not_backfilled(monkeypatch):
    """Depth accumulates from the next save. Nobody gets history
    retroactively, and claiming otherwise in the UI would be a lie."""
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(2), {"tagline": "new"})
    assert len(out) == 3


def test_no_current_kit_writes_no_snapshot(monkeypatch):
    """A first-ever save has nothing to preserve."""
    out = _saved(monkeypatch, None, [], {"tagline": "first"})
    assert out == []


def test_every_snapshot_carries_a_timestamp(monkeypatch):
    """The room prints these. A snapshot without one renders 'date
    unknown', which is the row nobody dares click."""
    out = _saved(monkeypatch, {"tagline": "current"}, _hist(3), {"tagline": "new"})
    assert out[0]["saved_at"].endswith("Z"), "Z form, never isoformat +00:00"
    assert all(s.get("saved_at") for s in out)
