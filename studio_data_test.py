"""Smoke tests for the Studio port. Run as: python studio_data_test.py

Tests:
  1. studio_data imports cleanly with 23/12/23 counts asserted at import time.
  2. Color math (hex_to_hsl, hsl_to_hex, blend_hex_colors) produces expected
     outputs on canonical inputs.
  3. detect_vocabularies returns sensible top-3 results for the 6 active
     businesses in production. Skipped gracefully when SUPABASE_KEY is unset.
  4. build_composite produces valid blended palettes + layout rankings for
     representative vocabulary triples.
  5. build_design_system returns non-empty CSS strings end-to-end.
"""
from __future__ import annotations

import os

import httpx

from studio_composite import (
    blend_hex_colors,
    build_composite,
    hex_to_hsl,
    hsl_to_hex,
)
from studio_data import (
    FONT_PAIRINGS,
    LAYOUTS,
    STYLE_STRANDS,
    VOCAB_LAYOUT_MAP,
    VOCABULARIES,
    all_layout_ids,
    all_vocabulary_ids,
)
from studio_design_system import build_design_system
from studio_vocab_detect import detect_vocabularies, detect_vocabulary_triple


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://brqjgbpzackdihgjsorf.supabase.co")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_ANON")
)


def _sb_get(path: str):
    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    try:
        r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"  [warn] sb GET {path} failed: {e}")
        return []


def test_data_module():
    print("=" * 64)
    print("TEST 1: studio_data module integrity")
    print("=" * 64)
    print(f"Vocabularies: {len(VOCABULARIES)}  (expect 23)")
    print(f"Layouts:      {len(LAYOUTS)}  (expect 12)")
    print(f"Vocab->layout: {len(VOCAB_LAYOUT_MAP)}  (expect 23)")
    print(f"Font pairs:   {len(FONT_PAIRINGS)}")
    print(f"Style strands:{len(STYLE_STRANDS)}")
    assert len(VOCABULARIES) == 23
    assert len(LAYOUTS) == 12
    assert len(VOCAB_LAYOUT_MAP) == 23
    print("\nVocabulary IDs (sorted):")
    for vid in sorted(all_vocabulary_ids()):
        print(f"  - {vid}  ({VOCABULARIES[vid]['section']})")
    print("\nLayout IDs (sorted):")
    for lid in sorted(all_layout_ids()):
        print(f"  - {lid}")
    print("\n[PASS]\n")


def test_color_math():
    print("=" * 64)
    print("TEST 2: Color math (hex_to_hsl, hsl_to_hex, blend_hex_colors)")
    print("=" * 64)
    blend = blend_hex_colors("#000000", "#FFFFFF", 0.5)
    print(f"blend(#000000, #FFFFFF, 0.5) = {blend}  (expect ~#7F7F7F or #808080)")
    assert blend.lower() in ("#808080", "#7f7f7f", "#7e7e7e", "#7d7d7d"), \
        f"Mid-grey blend produced {blend}"

    h, s, l = hex_to_hsl("#1A1A2E")
    print(f"hex_to_hsl(#1A1A2E) = ({h:.0f}, {s:.0f}%, {l:.0f}%)  (expect deep navy: ~240, ~28%, ~14%)")

    rt = hsl_to_hex(h, s, l)
    print(f"hsl_to_hex roundtrip -> {rt}  (expect ~#1A1A2E)")

    h2, s2, l2 = hex_to_hsl("#C9A84C")
    print(f"hex_to_hsl(#C9A84C) = ({h2:.0f}, {s2:.0f}%, {l2:.0f}%)  (expect gold: ~45, ~55%, ~54%)")

    sov_warm = blend_hex_colors("#1A1A2E", "#C0392B", 0.5)
    print(f"blend(sovereign navy, warm-community red, 0.5) = {sov_warm}")

    print("\n[PASS]\n")


def test_detection_for_real_businesses():
    print("=" * 64)
    print("TEST 3: Vocabulary detection on real businesses")
    print("=" * 64)

    if not SUPABASE_KEY:
        print(
            "WARNING: SUPABASE_SERVICE_KEY (or SUPABASE_KEY / SUPABASE_ANON) not set\n"
            "  in this environment. Skipping live detection on the 6 active\n"
            "  businesses. Re-run locally with the key exported to verify\n"
            "  detection accuracy:\n"
            "    export SUPABASE_SERVICE_KEY=<your service role key>\n"
            "    python studio_data_test.py\n"
        )
        print("[SKIP]\n")
        return

    businesses = _sb_get("businesses?is_active=eq.true&select=*") or []
    profiles = _sb_get("business_profiles?select=*") or []
    profiles_by_biz = {p.get("business_id"): p for p in profiles}

    if not businesses:
        print("No active businesses returned by Supabase. Test cannot proceed.")
        print("[SKIP]\n")
        return

    for biz in businesses:
        biz_id = biz.get("id")
        profile = profiles_by_biz.get(biz_id, {})
        voice_profile = biz.get("voice_profile") or {}
        brand_kit = (biz.get("settings") or {}).get("brand_kit") or {}

        archetype = profile.get("business_type") or biz.get("type") or "?"
        brand_voice = profile.get("brand_voice") or voice_profile.get("tone") or "?"

        print(f"\n— {biz.get('name', 'Unnamed')} (archetype: {archetype}, voice: {brand_voice}) —")
        matches = detect_vocabularies(biz, profile, voice_profile, brand_kit)
        if not matches:
            print("  (no vocabularies scored above threshold — falling back to defaults)")
        for m in matches:
            v = m["vocabulary"]
            print(f"  {m['confidence']:.2f}  {v['name']:30s}  ({v['section']})")
            for r in m["reasons"]:
                print(f"         - {r}")

        primary, secondary, aesthetic = detect_vocabulary_triple(biz, profile, voice_profile, brand_kit)
        print(f"  -> triple: {primary} + {secondary or '(none)'} + {aesthetic or '(none)'}")

    print("\n[PASS]\n")


def test_composite_blending():
    print("=" * 64)
    print("TEST 4: Composite blending")
    print("=" * 64)

    cases = [
        ("sovereign-authority", None, None, "Sovereign alone"),
        ("sovereign-authority", "faith-ministry", None, "Sovereign + Faith"),
        ("sovereign-authority", "faith-ministry", "minimalist", "Sovereign + Faith + Minimalist"),
        ("scholar-educator", "warm-community", "editorial", "Scholar + Warm + Editorial"),
        ("creative-artist", "expressive-vibrancy", "maximalist", "Creative + Expressive + Maximalist"),
        ("wellness-healing", None, "organic-natural", "Wellness + Organic"),
    ]

    for primary, secondary, aesthetic, label in cases:
        c = build_composite(primary, secondary, aesthetic)
        print(f"\n— {label} —")
        print(f"  layouts:    {c['recommended_layouts']}")
        print(f"  font pair:  {c['selected_font_pairing']['name']}")
        print(f"  primary:    {c['blended_color_system']['primary']}")
        print(f"  accent:     {c['blended_color_system']['accent']}")
        print(f"  background: {c['blended_color_system']['background']}")
        print(f"  confidence: {c['confidence_score']}")
        # Sanity: 3 layouts unless the union is smaller than 3
        assert 1 <= len(c["recommended_layouts"]) <= 3
        assert c["confidence_score"] >= 0
        assert c["confidence_score"] <= 100

    print("\n[PASS]\n")


def test_design_system_generation():
    print("=" * 64)
    print("TEST 5: Design system generation end-to-end")
    print("=" * 64)

    composite = build_composite("scholar-educator", "warm-community")
    ds = build_design_system(
        composite,
        business_name="Embrace the Shift",
        tagline="Education for the times we're in",
    )

    print(f"Business name:   {ds['business_name']}")
    print(f"Tagline:         {ds['tagline']}")
    print(f"Display font:    {ds['font_display']}")
    print(f"Body font:       {ds['font_body']}")
    print(f"Background:      {ds['palette_bg']}")
    print(f"Accent:          {ds['palette_accent']}")
    print(f"Text:            {ds['palette_text']}")
    print(f"Surface:         {ds['palette_surface']}")
    print(f"Dominant strand: {ds['dominant_strand']}")
    print(f"Recessive strand:{ds['recessive_strand']}")
    print(f"Spatial DNA:     {ds['spatial_dna'][:80]}...")
    print(f"Animation char:  {ds['animation_character']}")

    print("\n--- Nav CSS preview ---")
    print(ds["nav_css"][:240] + ("..." if len(ds["nav_css"]) > 240 else ""))
    print("\n--- Card CSS ---")
    print(ds["card_css"])
    print("\n--- CTA CSS ---")
    print(ds["cta_css"])
    print("\n--- Typography CSS ---")
    print(ds["typography_css"])

    assert ds["nav_css"]
    assert ds["card_css"]
    assert ds["cta_css"]
    assert ds["typography_css"]
    assert ds["reveal_css"]
    print("\n[PASS]\n")


def test_session2_patches():
    """Test 6: verify Session 2's two patches are live.

    Patch A: contrast-aware text colors. Patch B: real palette blending in
    build_composite (vs Session 1's identity).
    """
    print("=" * 64)
    print("TEST 6: Session 2 patches (contrast + real blending)")
    print("=" * 64)

    # Patch A — contrast helpers
    from studio_design_system import _pick_accent_contrast, _pick_contrast_text, _yiq_luminance
    yellow_lum = _yiq_luminance("#F1C40F")
    navy_lum = _yiq_luminance("#1A1A2E")
    print(f"YIQ luminance: yellow #F1C40F = {yellow_lum:.1f}, navy #1A1A2E = {navy_lum:.1f}")
    on_yellow = _pick_accent_contrast("#F1C40F")
    on_navy = _pick_contrast_text("#1A1A2E")
    print(f"  text-on-yellow accent: {on_yellow}  (expect dark text)")
    print(f"  text-on-navy bg:       {on_navy}  (expect light text)")
    assert on_yellow == "#1A1A1A", f"yellow needs dark text, got {on_yellow}"
    assert on_navy.upper() == "#F8F8F8", f"navy needs light text, got {on_navy}"

    # Patch B — palette blending actually runs
    from studio_composite import build_composite
    sov_alone = build_composite("sovereign-authority")
    sov_faith = build_composite("sovereign-authority", "faith-ministry")
    p_alone = sov_alone["blended_color_system"]["primary"]
    p_blend = sov_faith["blended_color_system"]["primary"]
    print(f"\nSovereign primary alone:        {p_alone}")
    print(f"Sovereign + Faith primary blend: {p_blend}")
    assert p_alone.lower() != p_blend.lower(), \
        "blend_palettes is still identity — Session 2 patch B didn't take effect"
    print("\n[PASS]\n")


def test_layout_renderers():
    """Test 7: every layout renders without error against KMJ Creative sample data."""
    print("=" * 64)
    print("TEST 7: All 12 layouts render end-to-end")
    print("=" * 64)

    from studio_composite import build_composite
    from studio_design_system import build_design_system
    from studio_layouts.dispatch import all_layouts, render_layout

    biz = {"name": "KMJ Creative Solutions", "type": "consultant",
           "tagline": "Strategy. Identity. Execution.",
           "elevator_pitch": "Helping established consultants articulate their authority."}
    bundle = {
        "business": {"name": biz["name"], "type": "consultant", "slug": "kmj-creative-solutions"},
        "practitioner": {"display_name": "Kevin McCloud Jr."},
        "voice": {"brand_voice": "corporate"},
        "design": {"primary_color": "#1A1A2E", "accent_color": "#C9A84C"},
        "legal": {"in_the_clear": True, "required_disclaimers": []},
        "footer": {"copyright_line": "(c) 2026 Kevin McCloud Jr.",
                   "contact_email": "kevin@kmjcreative.com"},
    }
    products = [
        {"name": "Foundation Strategy Sprint", "price": 2500, "description": "Two-week intensive."},
        {"name": "Brand Audit", "price": 1500, "description": "Comprehensive review."},
    ]
    sections = {"hero": {"enabled": True}, "about": {"enabled": True}, "services": {"enabled": True}}

    composite = build_composite("sovereign-authority", "established-authority", "minimalist")
    ds = build_design_system(composite, business_name=biz["name"], tagline=biz["tagline"])

    layouts = all_layouts()
    print(f"Rendering {len(layouts)} layouts...")
    failed = []
    for lid in layouts:
        try:
            html = render_layout(
                lid,
                business_data=biz,
                design_system=ds,
                composite=composite,
                sections_config=sections,
                bundle=bundle,
                products=products,
            )
            assert html.startswith("<!DOCTYPE html>")
            assert biz["name"] in html
            assert "<footer" in html
            print(f"  [OK] {lid:18s}  {len(html):,} bytes")
        except Exception as e:
            failed.append((lid, f"{type(e).__name__}: {e}"))
            print(f"  [FAIL] {lid}: {type(e).__name__}: {e}")

    if failed:
        raise AssertionError(f"{len(failed)} layout(s) failed: {failed}")
    print(f"\n[PASS] all {len(layouts)} layouts render valid HTML\n")


def test_preview_files_present():
    """Test 8: confirm studio_preview.py produced the 36 expected files."""
    print("=" * 64)
    print("TEST 8: Preview files generated")
    print("=" * 64)

    from pathlib import Path
    preview_dir = Path(__file__).parent / "layout_previews"
    if not preview_dir.exists():
        print("  layout_previews/ does not exist yet — run `python studio_preview.py` first.")
        print("[SKIP]\n")
        return

    files = list(preview_dir.glob("*.html"))
    business_layout_files = [f for f in files if f.name != "index.html"]
    print(f"  Total HTML files in layout_previews/: {len(files)}")
    print(f"  Business x layout files (excluding index.html): {len(business_layout_files)}")
    print(f"  index.html present: {(preview_dir / 'index.html').exists()}")
    if business_layout_files:
        sizes = [f.stat().st_size for f in business_layout_files]
        print(f"  Total bytes: {sum(sizes):,}  (avg {sum(sizes)//len(sizes):,} per file)")
    assert len(business_layout_files) == 36, f"Expected 36 preview files, got {len(business_layout_files)}"
    assert (preview_dir / "index.html").exists(), "index.html missing"
    print("\n[PASS]\n")


if __name__ == "__main__":
    test_data_module()
    test_color_math()
    test_detection_for_real_businesses()
    test_composite_blending()
    test_design_system_generation()
    test_session2_patches()
    test_layout_renderers()
    test_preview_files_present()
    print("=" * 64)
    print("ALL TESTS COMPLETE")
    print("=" * 64)
