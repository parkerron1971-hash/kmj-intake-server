"""Pass 4.0d PART 1 — Render-time override resolver.

Pure-function HTML transform. Runs AFTER the slot resolver in
smart_sites.py so slot images are already substituted by the time
overrides apply.

Three override surfaces (only `text` is implemented in PART 1; the
others lay groundwork for later passes):

  text       — find `<elt ... data-override-target="<path>">...</elt>`
               and replace the element's text content with the
               override's override_value. Preserves tag, attributes,
               and nested non-text children (e.g. an inline <strong>
               inside the element stays put with its own text replaced
               only when the element itself carries the data attr).
               Pragmatic implementation: replace the entire innerHTML
               with HTML-escaped override_value, so any inner markup
               gets flattened. Users edit visible text, not structure.

  color_role — implemented in PART 3 (Brand Kit color linking). The
               resolver currently NO-OPs color_role overrides; the
               actual injection of :root { --brand-<role>: ...; } is
               part of PART 3's brand-kit→site pipeline rewrite.

  slot_image — site_config.slots remains the authoritative store for
               images in 4.0d PART 1. slot_image overrides are
               NO-OP here.

Public entry: resolve_html_overrides(html, business_id) -> str
  Catches all exceptions internally and returns the input HTML
  unchanged on failure — same soft-fail discipline as resolve_html_slots.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Match any element opening tag that carries data-override-target="<path>",
# the element's inner content (lazy match), then its closing tag of the
# same name. Captures: 1=tag-name, 2=full-opening-tag, 3=target_path,
# 4=inner-content, 5=closing-tag.
#
# Limitations:
#   - Does not handle self-closing tags (they have no inner content
#     anyway, so text-replacement is N/A).
#   - Does not handle nested same-tag elements with the same data attr;
#     practical edge case for normal site copy.
_OVERRIDE_TARGET_RE = re.compile(
    r"""
    (<                              # opening <
      ([a-zA-Z][a-zA-Z0-9]*)        # group 2: tag name
      \b
      [^>]*?                        # other attrs (lazy)
      \bdata-override-target\s*=\s*
      ["']([^"']+)["']              # group 3: target_path
      [^>]*?                        # any further attrs
    >)                              # group 1 ends at closing >
    (.*?)                           # group 4: inner content (lazy)
    (</\2>)                         # group 5: matching closing tag
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


def _apply_text_overrides(
    html: str,
    text_overrides_by_path: Dict[str, str],
) -> tuple[str, List[str]]:
    """Replace innerHTML of every <... data-override-target="path"> ... </...>
    element whose path appears in `text_overrides_by_path`. Returns
    (new_html, list_of_paths_applied)."""
    if not text_overrides_by_path:
        return html, []
    applied: List[str] = []

    def _swap(m: re.Match) -> str:
        opening = m.group(1)
        target_path = m.group(3)
        closing = m.group(5)
        replacement = text_overrides_by_path.get(target_path)
        if replacement is None:
            # No override for this path — leave the element untouched.
            return m.group(0)
        applied.append(target_path)
        # HTML-escape the practitioner's override so they can't inject
        # arbitrary markup. Practitioner-supplied edits arrive via
        # the /chief/override endpoint with no sanitization upstream.
        return f"{opening}{html_lib.escape(replacement)}{closing}"

    new_html = _OVERRIDE_TARGET_RE.sub(_swap, html)
    return new_html, applied


def resolve_html_overrides(
    html: str,
    business_id: str,
) -> str:
    """Apply all persisted text overrides for `business_id` to the given
    HTML, returning the transformed string. Soft-fails to the input
    HTML on any error (lookup failure, regex issue, etc.) so an
    override bug never breaks the site render.

    color_role overrides are recognized at the storage layer but NOT
    applied here — that's PART 3's render-pipeline rewrite. slot_image
    overrides are NO-OPs (existing slot system is authoritative).
    """
    if not html or not isinstance(html, str) or not business_id:
        return html or ""
    try:
        from agents.override_system.override_storage import overrides_as_lookup
        text_overrides_raw = overrides_as_lookup(business_id, "text")
    except Exception as e:
        logger.warning(
            f"[override_resolver] storage lookup failed for {business_id}: {e}"
        )
        return html

    if not text_overrides_raw:
        return html

    text_by_path = {
        path: row.get("override_value", "")
        for path, row in text_overrides_raw.items()
        if row.get("override_value") is not None
    }
    try:
        new_html, applied = _apply_text_overrides(html, text_by_path)
        if applied:
            logger.info(
                f"[override_resolver] applied {len(applied)} text override(s) "
                f"for {business_id}: {applied}"
            )
        return new_html
    except Exception as e:
        logger.warning(
            f"[override_resolver] apply failed for {business_id}, "
            f"returning HTML unchanged: {e}"
        )
        return html


# ─── Diagnostic helpers (used by router /chief/override/_diag) ──────

def find_override_targets(html: str) -> List[Dict[str, Any]]:
    """Return every data-override-target element in the HTML with its
    target_path and current inner content. Used by the Studio UI to
    enumerate editable fields without re-parsing on the frontend."""
    if not html or not isinstance(html, str):
        return []
    out: List[Dict[str, Any]] = []
    for m in _OVERRIDE_TARGET_RE.finditer(html):
        out.append(
            {
                "tag": m.group(2).lower(),
                "target_path": m.group(3),
                "current_value": m.group(4),
            }
        )
    return out
