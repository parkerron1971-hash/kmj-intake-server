"""Pass 4.0b.5 — Render-time slot resolution.

Pure functions — no IO, no Supabase, no HTTP. Two surfaces:

  resolve_slot_url(slot_data, slot_name)
    Given a slot's persisted state dict, decides what URL the renderer
    should emit and how to label attribution.

  resolve_html_slots(html, slots, slot_definitions)
    PART 4 addition — finds every <img data-slot="X" src="..."> in
    rendered HTML and either substitutes the resolved URL or replaces
    the entire <img> with a styled placeholder div. Also collects
    Unsplash credits from the slots that resolved to defaults and
    emits a credit footer block injected before </footer> or </body>.

Precedence (resolve_slot_url):
  1. custom_url present  → render the practitioner's upload (no credit)
  2. default_url present → render the suggested image (Unsplash credit
                           or DALL-E generation marker)
  3. nothing present     → render the placeholder slot UI
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, List, Optional, Tuple


def resolve_slot_url(
    slot_data: Optional[Dict[str, Any]],
    slot_name: str,
) -> Dict[str, Any]:
    """Decide what to render for a given slot.

    Returns:
      {
        "url": str | None,        # None → render placeholder
        "source": "custom" | "default" | "placeholder",
        "credit": dict | None,    # attribution payload when default
                                  # came from Unsplash; None otherwise
        "is_placeholder": bool,   # convenience flag for the renderer
      }

    `slot_name` is included in the output for callers that fan out and
    need to keep slot identity attached to the resolved record.
    """
    base = {"slot_name": slot_name}

    if not slot_data:
        return {
            **base,
            "url": None,
            "source": "placeholder",
            "credit": None,
            "is_placeholder": True,
        }

    custom_url = slot_data.get("custom_url")
    if custom_url:
        return {
            **base,
            "url": custom_url,
            "source": "custom",
            "credit": None,
            "is_placeholder": False,
        }

    default_url = slot_data.get("default_url")
    if default_url:
        return {
            **base,
            "url": default_url,
            "source": "default",
            "credit": slot_data.get("default_credit"),
            "is_placeholder": False,
        }

    return {
        **base,
        "url": None,
        "source": "placeholder",
        "credit": None,
        "is_placeholder": True,
    }


# ─── HTML transformation (PART 4) ────────────────────────────────────

# Match <img ... data-slot="<name>" ... > including any other attrs in
# any order. Captures the FULL match so the replacer can swap it whole.
# Permissive: tolerates single quotes, no quotes, attribute reordering.
_IMG_SLOT_RE = re.compile(
    r"""<img\b[^>]*?\bdata-slot\s*=\s*["']?([a-z_0-9]+)["']?[^>]*?>""",
    re.IGNORECASE | re.DOTALL,
)

# After the data-slot attr is found, this isolates the alt for the
# placeholder caption and src for resolved-URL substitution.
_ALT_RE = re.compile(r'\balt\s*=\s*"([^"]*)"', re.IGNORECASE)
_SRC_RE = re.compile(r'\bsrc\s*=\s*"[^"]*"', re.IGNORECASE)


def _aspect_ratio_css(aspect_ratio: Optional[str]) -> str:
    """Convert '16:9' → '16 / 9' for the CSS aspect-ratio property.
    Falls back to '4 / 3' for unknown / malformed input."""
    if not aspect_ratio or ":" not in aspect_ratio:
        return "4 / 3"
    try:
        w, h = aspect_ratio.split(":", 1)
        return f"{int(w)} / {int(h)}"
    except (ValueError, AttributeError):
        return "4 / 3"


def render_placeholder_html(
    slot_name: str,
    slot_definition: Optional[Dict[str, Any]],
) -> str:
    """Render an inline styled placeholder div for an unresolved slot.
    Used for profile slots (default strategy: placeholder) and for any
    slot whose default failed to populate (e.g. budget cap rejected
    a DALL-E generation, Unsplash returned nothing).

    Style is Cinematic-Authority-flavored but uses fallback CSS values
    so it renders sensibly on any strand. The placeholder carries the
    data-slot attribute so the Slot Management UI (PART 5) can target
    it for the upload affordance."""
    aspect = "4 / 3"
    description = "Add your photo"
    if slot_definition:
        aspect = _aspect_ratio_css(slot_definition.get("aspect_ratio"))
        desc = slot_definition.get("description")
        if desc:
            description = f"{desc} · click to add"
    safe_desc = html_lib.escape(description)
    return (
        f'<div class="slot-placeholder" data-slot="{slot_name}" '
        f'style="'
        f'aspect-ratio: {aspect}; '
        f'border: 2px dashed var(--gold, #c6952f); '
        f'display: flex; align-items: center; justify-content: center; '
        f'background: var(--navy-mid, #15151f); '
        f'color: var(--gold, #c6952f); '
        f'font-style: italic; '
        f"font-family: var(--serif, Georgia, 'Times New Roman', serif); "
        f'font-size: 16px; letter-spacing: 1px; '
        f'padding: 24px; text-align: center; '
        f'box-sizing: border-box;'
        f'">'
        f'<span>{safe_desc}</span>'
        f'</div>'
    )


def _render_credit_footer(credits: List[Dict[str, Any]]) -> str:
    """Build the Unsplash attribution footer that gets injected before
    </footer> or </body>. One link per photographer; deduplicated by
    username. Empty string when no credits."""
    if not credits:
        return ""
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for c in credits:
        if not isinstance(c, dict):
            continue
        username = c.get("username") or c.get("name") or ""
        key = username.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)
    if not deduped:
        return ""
    parts: List[str] = []
    for c in deduped:
        name = html_lib.escape(c.get("name") or c.get("username") or "Photographer")
        url = html_lib.escape(c.get("url") or "")
        if url:
            parts.append(f'<a href="{url}" rel="noopener" target="_blank" style="color: inherit;">{name}</a>')
        else:
            parts.append(name)
    unsplash_link = (
        '<a href="https://unsplash.com/?utm_source=solutionist_studio&amp;utm_medium=referral" '
        'rel="noopener" target="_blank" style="color: inherit;">Unsplash</a>'
    )
    photog_list = ", ".join(parts)
    return (
        '<aside class="slot-credits" data-slot-credits '
        'style="font-size: 11px; '
        'font-family: system-ui, -apple-system, sans-serif; '
        'color: rgba(255, 255, 255, 0.4); '
        'padding: 24px 32px; '
        'text-align: center; '
        'letter-spacing: 0.5px; '
        'mix-blend-mode: difference;">'
        f'Photography: {photog_list} on {unsplash_link}'
        '</aside>'
    )


def _inject_credits(html: str, credits_block: str) -> str:
    """Insert credits block before </footer> if present, else before
    </body>. Returns html unchanged when both absent (rare)."""
    if not credits_block:
        return html
    # Prefer </footer> placement so credits live in the footer DOM
    # naturally; fall back to body close for sites without an explicit
    # <footer> tag. Both lookups are case-insensitive.
    for closing in (r"</footer>", r"</body>"):
        m = re.search(closing, html, re.IGNORECASE)
        if m:
            return html[: m.start()] + credits_block + html[m.start():]
    return html


def resolve_html_slots(
    html: str,
    slots: Optional[Dict[str, Dict[str, Any]]],
    slot_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Replace every <img data-slot="X" src="..."> tag with either a
    populated <img src="<resolved url>" ...> or a styled placeholder
    div. Inject the photographer credit footer before </footer>.

    Args:
      html: persisted Builder HTML containing data-slot tags.
      slots: site_config["slots"] — dict keyed by slot_name with
             persisted records ({default_url, custom_url, ...}).
      slot_definitions: SLOT_DEFINITIONS (optional, defaults imported
             lazily). Drives placeholder aspect-ratio + label.

    Returns:
      (resolved_html, credits, slot_names_found)

    `credits` is the deduplicated list of attribution dicts that ended
    up rendered in the footer; `slot_names_found` is every slot the
    HTML referenced (including duplicates, useful for diagnostics).
    """
    if not html or not isinstance(html, str):
        return html or "", [], []

    if slot_definitions is None:
        try:
            from agents.slot_system.slot_definitions import SLOT_DEFINITIONS
            slot_definitions = SLOT_DEFINITIONS
        except Exception:
            slot_definitions = {}

    slots = slots or {}
    credits: List[Dict[str, Any]] = []
    found: List[str] = []

    def _swap(match: re.Match) -> str:
        full = match.group(0)
        slot_name = match.group(1)
        found.append(slot_name)

        record = slots.get(slot_name)
        resolved = resolve_slot_url(record, slot_name)
        defn = slot_definitions.get(slot_name)

        if resolved["is_placeholder"]:
            return render_placeholder_html(slot_name, defn)

        # Resolved URL — substitute into the original src attribute.
        # Preserve all the Builder's existing attributes (alt, class,
        # loading, etc.) so the design's intent stays intact.
        url = resolved["url"]
        # If the original tag had src="", replace it; otherwise insert
        # src="..." right before the closing >.
        if _SRC_RE.search(full):
            new_tag = _SRC_RE.sub(f'src="{html_lib.escape(url, quote=True)}"', full, count=1)
        else:
            new_tag = full[:-1] + f' src="{html_lib.escape(url, quote=True)}">'

        # Collect credit if Unsplash-sourced. DALL-E and custom uploads
        # have no credit.
        credit = resolved.get("credit")
        if credit and isinstance(credit, dict) and credit.get("name"):
            credits.append({**credit, "slot_name": slot_name})
        return new_tag

    resolved_html = _IMG_SLOT_RE.sub(_swap, html)
    credits_block = _render_credit_footer(credits)
    final_html = _inject_credits(resolved_html, credits_block)

    # Dedupe credits the same way the footer renderer does, so the
    # caller's manifest matches what landed on the page.
    seen: set = set()
    final_credits: List[Dict[str, Any]] = []
    for c in credits:
        key = (c.get("username") or c.get("name") or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            final_credits.append(c)

    return final_html, final_credits, found
