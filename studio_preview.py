"""Static HTML preview generator. Run as: python studio_preview.py

Generates one HTML file per layout × sample-business combination in
layout_previews/, using sample data based on KMJ Creative + ETS +
Kingdom Expressions to demonstrate the range of vocabularies + archetypes.

Total expected output:
  3 sample businesses × 12 layouts = 36 HTML files + 1 index.html
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from studio_composite import build_composite
from studio_design_system import build_design_system
from studio_layouts.dispatch import all_layouts, render_layout


PREVIEW_DIR = Path(__file__).parent / "layout_previews"


# ─── Sample bundles representing different archetype combinations ─────

SAMPLE_BUSINESSES: Dict[str, Dict[str, Any]] = {
    "kmj_consultant": {
        "label": "KMJ Creative Solutions",
        "business_data": {
            "name": "KMJ Creative Solutions",
            "type": "consultant",
            "tagline": "Strategy. Identity. Execution.",
            "elevator_pitch": "Helping established consultants articulate their authority and convert at premium rates.",
        },
        "vocabulary_triple": ("sovereign-authority", "established-authority", "minimalist"),
        "bundle": {
            "business": {
                "name": "KMJ Creative Solutions",
                "type": "consultant",
                "slug": "kmj-creative-solutions",
                "tagline": "Strategy. Identity. Execution.",
                "elevator_pitch": "Helping established consultants articulate their authority.",
            },
            "practitioner": {"display_name": "Kevin McCloud Jr."},
            "voice": {"brand_voice": "corporate", "personality": "Composed, authoritative, premium"},
            "design": {"primary_color": "#1A1A2E", "accent_color": "#C9A84C"},
            "legal": {"in_the_clear": True, "required_disclaimers": []},
            "footer": {
                "copyright_line": "© 2026 Kevin McCloud Jr.",
                "contact_email": "kevin@kmjcreative.com",
            },
        },
        "products": [
            {"name": "Foundation Strategy Sprint", "price": 2500,
             "description": "Two-week intensive on positioning and pricing."},
            {"name": "Brand Audit & Recommendations", "price": 1500,
             "description": "Comprehensive review with prioritized recommendations."},
            {"name": "Quarterly Advisor", "price": 5000,
             "description": "Ongoing strategic partnership."},
        ],
    },
    "ets_financial_educator": {
        "label": "Embrace the Shift",
        "business_data": {
            "name": "Embrace the Shift",
            "type": "financial_educator",
            "tagline": "Education for the times we're in",
            "elevator_pitch": "Teaching everyday people how to navigate macro shifts in money, markets, and meaning.",
        },
        "vocabulary_triple": ("scholar-educator", "warm-community", "editorial"),
        "bundle": {
            "business": {
                "name": "Embrace the Shift",
                "type": "financial_educator",
                "slug": "embrace-the-shift",
                "tagline": "Education for the times we're in",
                "elevator_pitch": "Teaching everyday people how to navigate macro shifts.",
            },
            "practitioner": {"display_name": "Kevin McCloud Jr."},
            "voice": {"brand_voice": "warm", "personality": "Credible, deep, transformative"},
            "design": {"primary_color": "#1B3A6B", "accent_color": "#F1C40F"},
            "legal": {
                "in_the_clear": False,
                "required_disclaimers": [
                    "sec_education_only",
                    "not_financial_advice",
                    "no_fiduciary",
                    "past_results_disclaimer",
                ],
            },
            "footer": {
                "copyright_line": "© 2026 Kevin McCloud Jr.",
                "contact_email": "hello@embracetheshift.com",
            },
        },
        "products": [
            {"name": "Workshop", "price": 297,
             "description": "Two-day weekend workshop on macro economics for everyday people."},
            {"name": "Group Bootcamp", "price": 997,
             "description": "Six-week cohort with weekly live sessions."},
            {"name": "1-on-1 Mentorship", "price": 4500,
             "description": "90-day Legacy Builder Plan."},
        ],
    },
    "kingdom_ministry": {
        "label": "Kingdom Expressions",
        "business_data": {
            "name": "Kingdom Expressions",
            "type": "custom",
            "tagline": "Where the kingdom comes alive",
            "elevator_pitch": "Pastoral teaching and discipleship for the Black church.",
        },
        "vocabulary_triple": ("faith-ministry", "warm-community", "organic-natural"),
        "bundle": {
            "business": {
                "name": "Kingdom Expressions",
                "type": "custom",
                "slug": "kingdom-expressions",
                "tagline": "Where the kingdom comes alive",
                "elevator_pitch": "Pastoral teaching and discipleship for the Black church.",
            },
            "practitioner": {"display_name": "Pastor Kevin McCloud Jr."},
            "voice": {"brand_voice": "ministry", "personality": "Trustworthy, inspiring, communal"},
            "design": {"primary_color": "#4A2D5C", "accent_color": "#D4AF37"},
            "legal": {"in_the_clear": False, "required_disclaimers": []},
            "footer": {
                "copyright_line": "© 2026 Kingdom Expressions",
                "contact_email": "pastor@kingdomexpressions.com",
            },
        },
        "products": [
            {"name": "The Foundation Track",
             "description": "8-week introduction to discipleship."},
            {"name": "The Formation Track",
             "description": "Deeper formation for committed disciples."},
            {"name": "The Function Track",
             "description": "Equipping for ministry calling."},
        ],
    },
}


SAMPLE_SECTIONS_CONFIG: Dict[str, Any] = {
    "hero": {
        "enabled": True,
        "headline": None,
        "subheadline": None,
        "cta_label": None,
        "cta_link": None,
    },
    "about": {"enabled": True, "text": None},
    "services": {"enabled": True},
    "testimonials": {"enabled": False},
    "gallery": {"enabled": False},
    "resources": {"enabled": False},
    "footer_extra_text": None,
}


# ─── Generation ────────────────────────────────────────────────────────


def generate_all() -> Tuple[List[Tuple[str, str, str, int]], List[Tuple[str, str, str]]]:
    """Generate every sample business × every layout. Returns (successes, errors).

    successes: list of (biz_label, layout_id, filename, byte_count)
    errors:    list of (biz_key, layout_id, error_message)
    """
    PREVIEW_DIR.mkdir(exist_ok=True)
    layouts = all_layouts()
    successes: List[Tuple[str, str, str, int]] = []
    errors: List[Tuple[str, str, str]] = []

    for biz_key, sample in SAMPLE_BUSINESSES.items():
        primary, secondary, aesthetic = sample["vocabulary_triple"]
        try:
            composite = build_composite(primary, secondary, aesthetic)
            design_system = build_design_system(
                composite,
                business_name=sample["business_data"]["name"],
                tagline=sample["business_data"].get("tagline"),
            )
        except Exception as e:
            print(f"  [FATAL] {biz_key} composite/design system build failed: {type(e).__name__}: {e}")
            for layout_id in layouts:
                errors.append((biz_key, layout_id, f"composite-build: {e}"))
            continue

        for layout_id in layouts:
            try:
                html = render_layout(
                    layout_id,
                    business_data=sample["business_data"],
                    design_system=design_system,
                    composite=composite,
                    sections_config=SAMPLE_SECTIONS_CONFIG,
                    bundle=sample["bundle"],
                    products=sample["products"],
                )
                filename = f"{biz_key}__{layout_id}.html"
                filepath = PREVIEW_DIR / filename
                filepath.write_text(html, encoding="utf-8")
                successes.append((sample["label"], layout_id, filename, len(html)))
                print(f"  [OK] {filename} ({len(html):,} bytes)")
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                errors.append((biz_key, layout_id, msg))
                print(f"  [FAIL] {biz_key} x {layout_id}: {msg}")

    return successes, errors


def generate_index(successes: List[Tuple[str, str, str, int]]) -> Path:
    """Write a navigable index.html that groups previews by business."""
    by_biz: Dict[str, List[Tuple[str, str, int]]] = {}
    for label, layout_id, filename, size in successes:
        by_biz.setdefault(label, []).append((layout_id, filename, size))

    parts: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Studio Layout Previews — Pass 3.5 Session 2</title>",
        "<style>",
        "  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "max-width: 1080px; margin: 48px auto; padding: 0 24px; color: #1a1a1a; line-height: 1.5; }",
        "  h1 { font-size: 2rem; margin: 0 0 8px; font-weight: 700; }",
        "  .subtitle { color: #666; margin-bottom: 32px; }",
        "  h2 { margin-top: 48px; font-size: 1.3rem; padding-bottom: 8px; border-bottom: 1px solid #e0e0e0; }",
        "  .layouts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; margin-top: 16px; }",
        "  .layouts a { padding: 14px 16px; background: #f5f5f5; border-radius: 8px; "
        "text-decoration: none; color: #1a1a1a; transition: background 0.15s ease; "
        "display: flex; justify-content: space-between; align-items: center; gap: 8px; }",
        "  .layouts a:hover { background: #e8e8e8; }",
        "  .layouts .name { font-weight: 600; }",
        "  .layouts .size { color: #888; font-size: 0.8rem; font-variant-numeric: tabular-nums; }",
        "</style>",
        "</head><body>",
        "<h1>Studio Layout Previews</h1>",
        f'<div class="subtitle">Pass 3.5 Session 2 — {len(successes)} preview files across '
        f'{len(by_biz)} sample businesses × 12 layouts. Click any layout to view.</div>',
    ]

    for label, items in by_biz.items():
        parts.append(f"<h2>{label}</h2>")
        parts.append('<div class="layouts">')
        for layout_id, filename, size in sorted(items, key=lambda x: x[0]):
            parts.append(
                f'<a href="{filename}">'
                f'<span class="name">{layout_id}</span>'
                f'<span class="size">{size:,}</span></a>'
            )
        parts.append("</div>")

    parts.append("</body></html>")

    index_path = PREVIEW_DIR / "index.html"
    index_path.write_text("\n".join(parts), encoding="utf-8")
    return index_path


def main() -> int:
    layouts = all_layouts()
    print("=" * 70)
    print(f"Studio Layout Previews — generating {len(SAMPLE_BUSINESSES)} businesses x "
          f"{len(layouts)} layouts = {len(SAMPLE_BUSINESSES) * len(layouts)} files")
    print(f"Output dir: {PREVIEW_DIR}")
    print("=" * 70)

    successes, errors = generate_all()

    print()
    print("=" * 70)
    print(f"SUCCESS: {len(successes)} files written")
    print(f"ERRORS:  {len(errors)}")
    if errors:
        print("\nFailed combinations:")
        for biz_key, layout_id, msg in errors:
            print(f"  - {biz_key} x {layout_id}: {msg}")

    total_bytes = sum(size for _, _, _, size in successes)
    print(f"\nTotal bytes written: {total_bytes:,}")

    if successes:
        index_path = generate_index(successes)
        print(f"\nIndex: {index_path}")
        # Print absolute file:// URL for easy browser opening
        abs_path = index_path.resolve()
        # Windows file:// URLs need three slashes after file:
        url = abs_path.as_uri()
        print(f"\nOpen in browser:\n  {url}")

    print("=" * 70)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
