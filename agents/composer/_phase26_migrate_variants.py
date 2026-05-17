"""Spike-only one-shot migration. Run once to wire Phase 2.6 depth
treatments into every variant. Idempotent — safe to re-run; just
checks for the depth-bg stack and skips if already present.

Three transformations per variant:
  1. Replace the section-root `background: var(--brand-warm-neutral)`
     line with the five-property depth bg stack.
  2. Inject IMAGE_DEPTH_STYLE into <img> inline styles (image-using
     variants only).
  3. Insert render_satellite_diamonds(...) before </section>.

Adds the required import to each variant file. Skips full_bleed_overlay's
section bg (image dominates so depth bg is moot — but full_bleed_overlay
DOES get image treatment + satellites).

Run: railway run python -m agents.composer._phase26_migrate_variants
or:  python -m agents.composer._phase26_migrate_variants   (no Supabase needed)
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

VARIANTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "design_modules", "cinematic_authority",
    "hero", "variants",
)

# All 11 variants.
ALL_VARIANTS = [
    "manifesto_center",
    "asymmetric_left",
    "asymmetric_right",
    "full_bleed_overlay",
    "split_stacked",
    "layered_diamond",
    "quote_anchor",
    "tabular_authority",
    "vertical_manifesto",
    "annotated_hero",
    "cinematic_caption",
]

# Image-using variants get IMAGE_DEPTH_STYLE on their <img> tags.
IMAGE_USING = {
    "asymmetric_left",
    "asymmetric_right",
    "full_bleed_overlay",
    "split_stacked",
    "cinematic_caption",
}

# Variants whose section bg is brand-warm-neutral (default). 10 of 11.
# full_bleed_overlay uses brand-authority — handled separately.
WARM_NEUTRAL_BG_VARIANTS = set(ALL_VARIANTS) - {"full_bleed_overlay"}

# The depth-bg stack — replaces the single shorthand `background:` line.
DEPTH_BG_STACK = (
    "background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1));\n"
    "    background-image: var(--ca-bg-image, none);\n"
    "    background-size: var(--ca-bg-size, auto);\n"
    "    background-repeat: var(--ca-bg-repeat, no-repeat);\n"
    "    background-position: center center;\n"
    "    background-blend-mode: var(--ca-bg-blend, normal);"
)

# Image inline-style suffix.
IMAGE_DEPTH_STYLE = (
    "filter: var(--ca-image-filter, none); "
    "-webkit-mask-image: var(--ca-image-mask, none); "
    "mask-image: var(--ca-image-mask, none); "
)


def _has_depth_bg(src: str) -> bool:
    return "--ca-bg-color" in src


def _has_satellite_call(src: str) -> bool:
    # Look for the CALL form, not just the name (which also matches
    # the helper import we add earlier in the same migration pass).
    return "render_satellite_diamonds(" in src


def _has_image_depth(src: str) -> bool:
    return "--ca-image-filter" in src


def _add_helpers_import(src: str) -> str:
    """Ensure `from ._depth_helpers import render_satellite_diamonds`
    sits below the existing primitives import."""
    if "from ._depth_helpers import" in src:
        return src
    # Anchor on the primitives import block.
    pattern = re.compile(
        r"(from \.\.primitives import \([^\)]+\))",
        re.DOTALL,
    )
    m = pattern.search(src)
    if not m:
        # Fallback: anchor on any existing variant import.
        pattern = re.compile(r"(from \.\.primitives import [^\n]+\n)")
        m = pattern.search(src)
        if not m:
            return src
        insertion = m.end()
        helper_import = "from ._depth_helpers import render_satellite_diamonds\n"
        return src[:insertion] + helper_import + src[insertion:]
    insertion = m.end()
    helper_import = "\nfrom ._depth_helpers import render_satellite_diamonds"
    return src[:insertion] + helper_import + src[insertion:]


def _swap_warm_neutral_bg(src: str) -> Tuple[str, bool]:
    """Replace the section-root warm-neutral shorthand with depth bg stack."""
    target = "background: var(--brand-warm-neutral, #F8F6F1);"
    if target not in src:
        return src, False
    # Replace the FIRST occurrence only (section-root). Other elements
    # may also reference warm-neutral but those aren't the section bg.
    return src.replace(target, DEPTH_BG_STACK, 1), True


def _swap_authority_bg_for_full_bleed(src: str) -> Tuple[str, bool]:
    """Full_bleed_overlay's section bg is brand-authority. Layer the
    depth bg on top (the image still covers the section so bg shows
    only at edges / before image loads). Keeps the dark backstop."""
    # In full_bleed_overlay the very first `background: var(--brand-authority...)`
    # is the section bg (later instances are overlay layers). We don't
    # touch them; we add depth bg AFTER the existing bg line.
    target = "background: var(--brand-authority, #0A1628);"
    if target not in src:
        return src, False
    replacement = (
        "background: var(--brand-authority, #0A1628);\n"
        "    " + DEPTH_BG_STACK
    )
    # Replace first occurrence only.
    return src.replace(target, replacement, 1), True


def _inject_image_depth(src: str) -> Tuple[str, int]:
    """Append IMAGE_DEPTH_STYLE to every <img> style="..." inline style
    that doesn't already include the filter var. Variants emit img tags
    with `style="width: 100%; ..."` — we find and patch them."""
    count = 0
    # Match <img ... style="X" ... > — multiline (DOTALL) because img
    # opens with newlines per variant.
    img_re = re.compile(r'(<img\b[^>]*?\bstyle=")([^"]*?)("[^>]*?>)', re.DOTALL)

    def _patch(m: re.Match) -> str:
        nonlocal count
        prefix, style_inner, suffix = m.group(1), m.group(2), m.group(3)
        if "--ca-image-filter" in style_inner:
            return m.group(0)
        # Trim trailing semicolon/whitespace then append depth style.
        cleaned = style_inner.rstrip().rstrip(";").rstrip()
        new_style = cleaned + "; " + IMAGE_DEPTH_STYLE.rstrip()
        count += 1
        return f"{prefix}{new_style}{suffix}"

    return img_re.sub(_patch, src), count


def _inject_satellite_call(src: str, variant_id: str) -> Tuple[str, bool]:
    """Insert {render_satellite_diamonds(...)} just before </section>."""
    if _has_satellite_call(src):
        return src, False
    # Each variant ends its f-string with "</section>" — inject before it.
    target = "</section>"
    if target not in src:
        return src, False
    call = (
        "{render_satellite_diamonds(treatments.ornament, "
        f"'{variant_id}')}}"
        "\n"
    )
    return src.replace(target, call + target, 1), True


def migrate_one(variant_id: str) -> dict:
    path = os.path.join(VARIANTS_DIR, f"{variant_id}.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    report = {
        "variant": variant_id,
        "bg_swapped": False,
        "img_patched": 0,
        "satellite_added": False,
        "import_added": False,
    }

    if _has_depth_bg(src) and _has_satellite_call(src):
        report["status"] = "already-migrated"
        return report

    # 1. Import.
    new_src = _add_helpers_import(src)
    if new_src != src:
        report["import_added"] = True
        src = new_src

    # 2. Section bg.
    if not _has_depth_bg(src):
        if variant_id == "full_bleed_overlay":
            src, ok = _swap_authority_bg_for_full_bleed(src)
        else:
            src, ok = _swap_warm_neutral_bg(src)
        report["bg_swapped"] = ok

    # 3. Image depth (image-using only).
    if variant_id in IMAGE_USING and not _has_image_depth(src):
        src, n = _inject_image_depth(src)
        report["img_patched"] = n

    # 4. Satellite diamonds (all variants).
    if not _has_satellite_call(src):
        src, ok = _inject_satellite_call(src, variant_id)
        report["satellite_added"] = ok

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    report["status"] = "migrated"
    return report


def main() -> int:
    print("=== Phase 2.6 variant migration ===")
    reports: List[dict] = []
    for v in ALL_VARIANTS:
        reports.append(migrate_one(v))
    for r in reports:
        print(
            f"  {r['variant']:22} | bg={r['bg_swapped']} "
            f"| img={r['img_patched']} | sat={r['satellite_added']} "
            f"| import={r['import_added']} | {r.get('status')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
