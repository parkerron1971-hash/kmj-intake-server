"""Pass 4.0d PART 3 — Brand-kit-driven CSS variable injection at render time.

Composes a per-business CSS variable map from `businesses.settings.brand_kit`
and injects it as a `:root { --brand-X: ...; }` block into the served HTML.
The Builder Agent (Pass 4.0d PART 3 prompt update) emits `var(--brand-X)`
instead of raw hex, so when the brand_kit changes the site re-themes WITHOUT
a rebuild.

Pipeline position (in smart_sites._try_serve_builder_html):
  Builder HTML → motion injection → brand_kit_vars injection → slot resolve → override resolve

Three pure-function surfaces:

  compose_brand_kit_vars(brand_kit, color_role_overrides=None)
    Maps brand_kit's nested `colors.{primary,secondary,accent,background,text}`
    object (canonical shape per Pass 2.5a brand-engine-migration) into a
    dict keyed by CSS variable name. Applies any color_role overrides
    from site_content_overrides on top (PART 1 deferred its color_role
    resolution to PART 3 — this is that resolution). Falls back to the
    Cinematic Authority default palette when a role is missing.

  derive_text_on(role_hex)
    Returns "#0F172A" (dark) or "#FFFFFF" (light) based on the role
    color's perceived luminance. Used to auto-fill the
    --brand-text-on-authority / --brand-text-on-signal pair so the
    Builder doesn't have to think about contrast.

  inject_brand_kit_vars(html, css_vars)
    Inserts a `<style id="brand-kit-vars">:root { ... }</style>` block
    just inside `<head>` (or just before `</head>` if `<head>` isn't
    found). Soft-fails to the input HTML on any error.

Role mapping (Cinematic Authority — same shape future modules should adopt):
  --brand-authority         ← brand_kit.colors.primary
  --brand-signal            ← brand_kit.colors.accent
  --brand-warm-neutral      ← brand_kit.colors.background
  --brand-deep-secondary    ← brand_kit.colors.secondary
  --brand-text-primary      ← brand_kit.colors.text
  --brand-text-on-authority ← derived (contrast vs --brand-authority)
  --brand-text-on-signal    ← derived (contrast vs --brand-signal)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Cinematic Authority defaults — used when brand_kit.colors.<role> is
# missing. These match the module document's "Primary Palette" section
# (navy / gold / cream / dark text on warm white).
_DEFAULT_AUTHORITY = "#0A1628"
_DEFAULT_SIGNAL = "#C6952F"
_DEFAULT_WARM_NEUTRAL = "#F8F6F1"
_DEFAULT_DEEP_SECONDARY = "#122040"
_DEFAULT_TEXT_PRIMARY = "#0A1628"

# Role → brand_kit.colors.<key> mapping. The Builder Agent reads these
# CSS variable names; the renderer fills them from brand_kit. Keeping the
# mapping in one place makes it the canonical reference for adding
# new modules that reuse the same role vocabulary.
_ROLE_TO_BRAND_KIT_KEY = {
    "authority": "primary",
    "signal": "accent",
    "warm_neutral": "background",
    "deep_secondary": "secondary",
    "text_primary": "text",
}

_ROLE_DEFAULTS = {
    "authority": _DEFAULT_AUTHORITY,
    "signal": _DEFAULT_SIGNAL,
    "warm_neutral": _DEFAULT_WARM_NEUTRAL,
    "deep_secondary": _DEFAULT_DEEP_SECONDARY,
    "text_primary": _DEFAULT_TEXT_PRIMARY,
}


# ─── Color math (contrast) ─────────────────────────────────────────

def _hex_to_rgb(hex_str: str) -> Optional[tuple]:
    """Parse #RRGGBB / #RGB / RRGGBB into (r, g, b) ints 0-255.
    Returns None for unparseable input."""
    if not isinstance(hex_str, str):
        return None
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _luminance(hex_str: str) -> float:
    """Perceived luminance per WCAG 2.x. Returns 0.0 (black) to 1.0 (white).
    Returns 0.5 if input can't be parsed so the contrast picker doesn't
    crash on a malformed brand_kit color."""
    rgb = _hex_to_rgb(hex_str)
    if rgb is None:
        return 0.5

    def _channel(c: int) -> float:
        cs = c / 255.0
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4

    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def derive_text_on(role_hex: str) -> str:
    """Pick contrasting text color for the given background.
    Returns "#FFFFFF" or "#0F172A" — whichever scores higher WCAG
    contrast against the background. A pure luminance threshold gets
    amber/gold wrong (luminance ~0.44 reads as "dark enough for white
    text" but black text actually scores 9.8:1 vs 2.1:1 for white)."""
    bg_l = _luminance(role_hex)
    # WCAG contrast: (Llighter + 0.05) / (Ldarker + 0.05)
    contrast_vs_white = (1.0 + 0.05) / (bg_l + 0.05)
    # 0x0F = 15 → linearized ~0.005; close enough to 0 for the picker.
    near_black_l = 0.005
    contrast_vs_dark = (bg_l + 0.05) / (near_black_l + 0.05)
    return "#FFFFFF" if contrast_vs_white >= contrast_vs_dark else "#0F172A"


# ─── Composition ───────────────────────────────────────────────────

def compose_brand_kit_vars(
    brand_kit: Optional[Dict[str, Any]],
    color_role_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build the CSS variable dict for a business.

    Resolution order per role (matches Pass 4.0d's override priority spec
    custom_url > override_value > generated_value > placeholder):

      1. color_role override (from site_content_overrides type='color_role')
      2. brand_kit.colors.<key>
      3. brand_kit.<flat_key>            (legacy alias)
      4. module default

    color_role_overrides is the dict shape produced by
    override_storage.overrides_as_lookup(business_id, 'color_role') —
    keyed by target_path (which is the role name without the --brand- prefix).

    Returns a dict keyed by CSS variable name (no leading --), values
    are hex strings or whatever the brand_kit had (which should be hex
    but might be rgb() / named colors for legacy rows; passed through
    verbatim).
    """
    brand_kit = brand_kit or {}
    colors = brand_kit.get("colors") or {}
    overrides = color_role_overrides or {}
    out: Dict[str, str] = {}

    for role, default in _ROLE_DEFAULTS.items():
        # 1. override row
        override_row = overrides.get(role)
        if isinstance(override_row, dict):
            v = override_row.get("override_value")
            if v:
                out[role] = str(v)
                continue
        # 2. nested
        bk_key = _ROLE_TO_BRAND_KIT_KEY[role]
        nested_val = colors.get(bk_key)
        if nested_val:
            out[role] = str(nested_val)
            continue
        # 3. flat legacy alias
        flat_key = f"{bk_key}_color" if bk_key != "text" else "text_color"
        flat_val = brand_kit.get(flat_key)
        if flat_val:
            out[role] = str(flat_val)
            continue
        # 4. module default
        out[role] = default

    # Derived contrast text colors. These cannot be overridden — they
    # follow from authority + signal mechanically. If a future practitioner
    # wants a third option (e.g., gold text on navy instead of white),
    # that's a content_edit on a specific element via PART 1, not a
    # palette role override.
    out["text_on_authority"] = derive_text_on(out["authority"])
    out["text_on_signal"] = derive_text_on(out["signal"])

    return out


# ─── Injection ─────────────────────────────────────────────────────

# Match the opening <head> tag (with any attributes). Used to find the
# spot just after <head> where the brand-kit-vars style block goes.
_HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
# Strip any prior brand-kit-vars block so re-renders don't accumulate.
_PRIOR_BLOCK_RE = re.compile(
    r'<style\s+id="brand-kit-vars">.*?</style>',
    re.IGNORECASE | re.DOTALL,
)


def _format_css_block(css_vars: Dict[str, str]) -> str:
    """Render the `:root { --brand-X: value; }` block. Sorted keys so
    diffs across renders are clean."""
    lines = ["<style id=\"brand-kit-vars\">", ":root {"]
    for key in sorted(css_vars.keys()):
        lines.append(f"  --brand-{key.replace('_', '-')}: {css_vars[key]};")
    lines.append("}")
    lines.append("</style>")
    return "\n".join(lines)


def inject_brand_kit_vars(html: str, css_vars: Dict[str, str]) -> str:
    """Insert the brand-kit-vars `<style>` block just after `<head>` in
    `html`. If a previous brand-kit-vars block exists (e.g. the renderer
    is re-running on cached HTML), strip it first so values don't stack.

    Soft-fails to the input HTML unchanged if `<head>` is missing.
    """
    if not html or not isinstance(html, str) or not css_vars:
        return html or ""

    block = _format_css_block(css_vars)

    # Strip any prior block (idempotency).
    html = _PRIOR_BLOCK_RE.sub("", html)

    m = _HEAD_OPEN_RE.search(html)
    if not m:
        # No <head> tag — try injecting at the very top so the variables
        # are at least in scope. Fully-headless HTML is rare but the
        # builder occasionally trims <head> when prompted aggressively.
        return block + "\n" + html

    insert_at = m.end()
    return html[:insert_at] + "\n" + block + html[insert_at:]


# ─── Pass 4.0e PART 3 — per-element color overrides ────────────────

# Strip any prior per-element color block on re-render so values don't
# stack. Tag block via the same data-attribute pattern used elsewhere.
_PRIOR_PER_ELEMENT_RE = re.compile(
    r'<style[^>]*data-per-element-colors="1"[^>]*>.*?</style>',
    re.IGNORECASE | re.DOTALL,
)


def _is_role_target_path(target_path: str) -> bool:
    """A color_role override row whose target_path matches one of the 5
    palette role names re-themes the :root variable globally (handled by
    compose_brand_kit_vars). Anything else is a per-element override
    (e.g. 'hero.accent_line') and gets applied via attribute-selector
    CSS rules in apply_per_element_color_overrides."""
    return target_path in _ROLE_DEFAULTS


def _escape_css_attr_value(value: str) -> str:
    """Escape an attribute value for use inside a CSS [attr="..."] selector.
    Replace " and \\ with their CSS-escape equivalents. target_paths are
    practitioner-controlled so we don't trust them implicitly."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_per_element_color_block(overrides_by_path: Dict[str, str]) -> str:
    """Render CSS rules for per-element color overrides. Each rule uses
    an attribute selector targeting the element by its
    data-override-target. !important wins over the inline
    `background: var(--brand-signal)` the Builder emits.

    Both background and color are set so the override applies to the
    element regardless of whether it's a filled shape (accent line,
    diamond, full-bleed band — uses background) or a colored character
    target (would use color). For accent-line + diamond patterns —
    most common — background is the right hit."""
    lines = ['<style data-per-element-colors="1">']
    for path in sorted(overrides_by_path.keys()):
        hex_val = overrides_by_path[path]
        safe = _escape_css_attr_value(path)
        lines.append(
            f'[data-override-target="{safe}"][data-override-type="color"] '
            f'{{ background: {hex_val} !important; color: {hex_val} !important; }}'
        )
        # SVG-children color (for icon-style targets). Cheap and matches
        # nothing for non-SVG accent-line/diamond patterns.
        lines.append(
            f'[data-override-target="{safe}"][data-override-type="color"] svg '
            f'{{ fill: {hex_val} !important; stroke: {hex_val} !important; }}'
        )
    lines.append('</style>')
    return "\n".join(lines)


def inject_per_element_color_overrides(
    html: str,
    overrides_by_path: Dict[str, str],
) -> str:
    """Insert a per-element color overrides <style> block after the
    brand-kit-vars block. Idempotent: prior block stripped first.

    overrides_by_path maps target_path → hex value. Empty dict → no-op
    (caller filters role names out before passing)."""
    if not html or not isinstance(html, str):
        return html or ""
    # Strip prior block (idempotency).
    html = _PRIOR_PER_ELEMENT_RE.sub("", html)
    if not overrides_by_path:
        return html
    block = _format_per_element_color_block(overrides_by_path)
    m = _HEAD_OPEN_RE.search(html)
    if not m:
        return block + "\n" + html
    insert_at = m.end()
    return html[:insert_at] + "\n" + block + html[insert_at:]


# ─── Public entrypoint ─────────────────────────────────────────────

def render_with_brand_kit(
    html: str,
    business_id: str,
    site_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Pure-ish entrypoint used by smart_sites render. Looks up the
    business's brand_kit + any color_role overrides, composes the
    variable map, injects.

    Soft-fails to the input HTML on any error (lookup failure, etc.)
    so a brand-kit issue can never break a site render. Failure cause
    is logged at WARN, same discipline as resolve_html_slots /
    resolve_html_overrides.
    """
    if not html or not isinstance(html, str) or not business_id:
        return html or ""

    # Fetch brand_kit. Lazy import keeps this module testable.
    brand_kit: Dict[str, Any] = {}
    try:
        from brand_engine import _sb_get as be_get
        rows = be_get(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1"
        ) or []
        if rows:
            brand_kit = (rows[0].get("settings") or {}).get("brand_kit") or {}
    except Exception as e:
        logger.warning(
            f"[brand_kit_renderer] brand_kit fetch failed for {business_id}: {e}"
        )

    # Fetch color_role overrides (PART 1's site_content_overrides table).
    color_overrides: Dict[str, Dict[str, Any]] = {}
    try:
        from agents.override_system.override_storage import overrides_as_lookup
        color_overrides = overrides_as_lookup(business_id, "color_role")
    except Exception as e:
        logger.warning(
            f"[brand_kit_renderer] color_role override lookup failed "
            f"for {business_id}: {e}"
        )

    try:
        # Role-level overrides (target_path matches one of the 5 role
        # names) update :root --brand-* vars and re-theme globally.
        css_vars = compose_brand_kit_vars(brand_kit, color_overrides)
        new_html = inject_brand_kit_vars(html, css_vars)

        # Pass 4.0e PART 3 — per-element overrides (target_path = e.g.
        # 'hero.accent_line'). Generate attribute-selector CSS rules so
        # each tagged element re-themes independently. The inline edit
        # mode picker writes these.
        per_element = {
            path: row.get("override_value")
            for path, row in color_overrides.items()
            if path and not _is_role_target_path(path) and row.get("override_value")
        }
        new_html = inject_per_element_color_overrides(new_html, per_element)

        if color_overrides:
            role_count = len(color_overrides) - len(per_element)
            logger.info(
                f"[brand_kit_renderer] {business_id}: "
                f"{role_count} role-level, {len(per_element)} per-element "
                f"color override(s) applied"
            )
        return new_html
    except Exception as e:
        logger.warning(
            f"[brand_kit_renderer] injection failed for {business_id}, "
            f"serving HTML unchanged: {e}"
        )
        return html
