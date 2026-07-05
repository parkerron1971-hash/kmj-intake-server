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

    # Arc 4 "Trust & Polish": overrides marked stale by the recompose
    # reconciliation (composer wrote new text at the path, or the path no
    # longer exists) are NEVER applied — they'd silently mask fresh
    # composer copy. Rows predating the status column (key absent) are
    # treated as active.
    text_by_path = {
        path: row.get("override_value", "")
        for path, row in text_overrides_raw.items()
        if row.get("override_value") is not None
        and (row.get("status") or "active") != "stale"
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


# ─── Arc 4 "Trust & Polish" — recompose reconciliation ──────────────

_RECON_TAG_RE = re.compile(r"<[^>]+>")


def _norm_text(fragment: str) -> str:
    """Comparison normal form: tags stripped (composer copy may carry
    accent <em>/<span> fragments), entities unescaped, whitespace
    collapsed. original_value was captured as innerHTML at edit time, so
    both sides normalize identically."""
    return " ".join(
        html_lib.unescape(_RECON_TAG_RE.sub(" ", str(fragment or ""))).split())


def reconcile_text_overrides(business_id: str, fresh_html: str) -> Dict[str, Any]:
    """Diff every stored TEXT override against a freshly-composed document
    (BEFORE overrides are applied) and mark rows stale/active:

      - path missing from the fresh doc               → stale (orphaned)
      - composer wrote NEW text at the path (fresh ≠
        the override's original_value)                → stale (rewrote)
      - fresh text still matches original_value       → active (applies)
      - legacy row without original_value             → active (unknown
        provenance; staling it would visibly revert a real edit)

    Stale rows are never deleted — GET /composer/spec exposes them so a
    future UI can offer re-apply. Status writes are best-effort: if the
    status column migration isn't applied yet, marking soft-fails (logged)
    and behavior degrades to the pre-Arc-4 apply-everything.

    Returns {"applied": n, "stale": n, "unknown_kept": n, "stale_paths": [...]}."""
    from agents.override_system import override_storage

    result: Dict[str, Any] = {"applied": 0, "stale": 0,
                              "unknown_kept": 0, "stale_paths": []}
    rows = override_storage.list_overrides(business_id, "text")
    if not rows:
        return result

    fresh_by_path: Dict[str, str] = {}
    for t in find_override_targets(fresh_html):
        fresh_by_path.setdefault(t["target_path"], t.get("current_value") or "")

    to_stale: List[str] = []
    to_activate: List[str] = []
    for row in rows:
        path = row.get("target_path")
        prev_status = (row.get("status") or "active")
        if path not in fresh_by_path:
            new_status = "stale"          # orphaned — path left the document
        else:
            original = row.get("original_value")
            if original is None or not str(original).strip():
                new_status = "active"     # legacy row — provenance unknown
                result["unknown_kept"] += 1
            elif _norm_text(fresh_by_path[path]) != _norm_text(original):
                new_status = "stale"      # composer produced NEW copy here
            else:
                new_status = "active"     # composer copy unchanged — apply
        if new_status == "stale":
            result["stale"] += 1
            result["stale_paths"].append(path)
            if prev_status != "stale" and row.get("id"):
                to_stale.append(str(row["id"]))
        else:
            result["applied"] += 1
            if prev_status == "stale" and row.get("id"):
                to_activate.append(str(row["id"]))

    if to_stale:
        override_storage.mark_overrides_status(to_stale, "stale")
    if to_activate:
        override_storage.mark_overrides_status(to_activate, "active")
    return result


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
