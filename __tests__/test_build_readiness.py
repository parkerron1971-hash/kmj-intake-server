"""
test_build_readiness.py — the "before you approve" pass (2026-08-28).
"""
import build_readiness as br


def _ctx(**over):
    base = {"gallery": [], "offerings": [], "testimonials": [],
            "settings": {"brand_kit": {}},
            "site": {"site_config": {"discovery_dossier": {
                "gaps": ["brand_mark_missing", "work_missing"],
                "meta": {}}}},
            "store": {"enabled": False, "items": []}}
    base.update(over)
    return base


def test_macnificent_shaped_context_names_every_gap_in_plain_words():
    """Zero photos, no mark, two services, no testimonials, an empty
    shop, an unfinished session — the exact shape that shipped."""
    r = br.spec_readiness(_ctx(offerings=[{"name": "Box braids"},
                                          {"name": "Kids"}]))
    assert r["photos"] == 0 and r["brand_mark"] is False
    assert r["offerings"] == 2 and r["session_done"] is False
    joined = " ".join(r["notes"])
    assert "No photos" in joined and "typographic" in joined
    assert "No logo" in joined and "wordmark" in joined
    assert "2 offerings on file" in joined
    assert "No testimonials" in joined
    assert "Nothing in the shop" in joined
    assert "Design Session was not finished" in joined
    assert len(r["notes"]) <= 6 and 1 <= len(r["chips"]) <= 4
    assert any("typographic" in c for c in r["chips"])


def test_a_kmj_shaped_context_is_mostly_quiet():
    r = br.spec_readiness(_ctx(
        gallery=[{"url": f"https://x/{i}.jpg"} for i in range(7)],
        offerings=[{"name": f"o{i}"} for i in range(8)],
        testimonials=[{"quote": "great"}],
        settings={"brand_kit": {"logo_url": "https://x/mark.png"}},
        site={"site_config": {"discovery_dossier": {
            "gaps": [], "meta": {"coach_session_completed": {"value": True}}}}},
        store={"enabled": True, "items": [{"name": "tee"}]}))
    assert r["photos"] == 7 and r["brand_mark"] and r["session_done"]
    assert r["chips"] == []
    assert r["notes"] == ["7 photos on file — the gallery will be real.",
                          "8 offerings on file."]


def test_readiness_never_raises_on_a_bare_context():
    r = br.spec_readiness({})
    assert r["photos"] == 0 and r["notes"] and r["gaps"] == []
    assert br.spec_readiness(None)["offerings"] == 0


# ─── PHOTOS FIRST (2026-11-08) ───────────────────────────────────

def _church(photos=0, **over):
    base = {"business": {"name": "Grace Chapel", "type": "church"},
            "gallery": [{"url": f"https://x/{i}.jpg"} for i in range(photos)],
            "offerings": [], "testimonials": [], "settings": {}, "site": {"site_config": {}}}
    base.update(over)
    return base


def test_the_photo_stop_waits_for_its_switch(monkeypatch):
    monkeypatch.delenv("SITE_PHOTOS_FIRST", raising=False)
    assert br.spec_readiness(_church())["photo_stop"] is None


def test_a_church_short_of_photos_gets_the_stop(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    assert br.spec_readiness(_church())["photo_stop"] == {"have": 0, "want": 6}
    assert br.spec_readiness(_church(5))["photo_stop"] == {"have": 5, "want": 6}
    assert br.spec_readiness(_church(6))["photo_stop"] is None


def test_a_salon_gets_the_stop_and_a_law_firm_never_does(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    salon = _church(business={"name": "Fade", "type": "hair salon"})
    assert br.spec_readiness(salon)["photo_stop"] == {"have": 0, "want": 6}
    law = _church(business={"name": "Whitlock Law", "type": "law firm"})
    assert br.spec_readiness(law)["photo_stop"] is None


def test_a_trade_whose_proof_is_not_a_picture_gets_no_stop(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    coach = _church(business={"name": "Vertical", "type": "career coach"})
    assert br.spec_readiness(coach)["photo_stop"] is None


def test_an_owner_who_chose_plain_gets_no_stop(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    ctx = _church(site={"site_config": {"discovery_dossier": {"taste": {"concept": {"value": "plain"}}}}})
    assert br.spec_readiness(ctx)["photo_stop"] is None


def test_a_bad_read_never_blocks_the_card(monkeypatch):
    import site_concept
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")

    def boom(ctx):
        raise ValueError("no")
    monkeypatch.setattr(site_concept, "resolve", boom)
    assert br.spec_readiness(_church())["photo_stop"] is None


def test_a_failed_site_read_cannot_hide_a_plain_choice(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    assert br.spec_readiness(_church(site={}))["photo_stop"] is None
    assert br.spec_readiness(_church(site=None))["photo_stop"] is None


def test_with_the_concept_layer_off_everything_is_plain(monkeypatch):
    monkeypatch.setenv("SITE_PHOTOS_FIRST", "on")
    monkeypatch.setenv("SITE_CONCEPT", "off")
    assert br.spec_readiness(_church())["photo_stop"] is None
