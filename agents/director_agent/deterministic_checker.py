"""Pass 4.0b — Layer 1 deterministic rule checkers.

Parses HTML/CSS, runs each rule's `check_spec`, returns violation
dicts with `fix_hint`s the Builder Agent can regenerate against.

Design philosophy:
  - Strict but fair. False positives waste a Builder regen, so the
    checks accept reasonable variations (px / rem / clamp() / vars).
  - Each check returns None on pass, dict on fail. The dict shape
    matches what `critique.py` and the punch-list formatter expect.
  - When in doubt, abstain (return None) rather than flag a borderline
    case as a violation. Layer 2 LLM judges catch the qualitative gaps.
  - Conditional rules (`condition: enriched_brief.brand_metaphor IS NOT NULL`)
    are skipped when the condition is unmet — same as not flagging.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ─── Public API ──────────────────────────────────────────────────────


def check_all_deterministic(
    rubric: Dict,
    html: str,
    css: str = "",
    enriched_brief: Optional[Dict] = None,
) -> List[Dict]:
    """Run every Layer 1 rule against the rendered HTML+CSS.

    Returns a list of violation dicts (may be empty). The combined CSS
    used for property checks is the union of `<style>` blocks parsed
    out of `html` plus any caller-supplied `css` string.
    """
    if not rubric:
        return []

    soup = _parse_html(html)
    combined_css = _extract_style_blocks(html) + "\n" + (css or "")
    css_rules = _parse_css_rules(combined_css)
    root_vars = _root_vars(css_rules)

    accent_color = _resolve_accent_color(enriched_brief, root_vars)

    ctx = _CheckContext(
        soup=soup,
        css_rules=css_rules,
        root_vars=root_vars,
        accent_color=accent_color,
        enriched_brief=enriched_brief or {},
        raw_html=html,
        raw_css=combined_css,
    )

    violations: List[Dict] = []
    for rule in rubric.get("layer_1_deterministic", []):
        try:
            v = check_rule(rule, ctx)
            if v:
                violations.append(v)
        except Exception as e:  # one bad rule never tanks the whole critique
            logger.warning(
                f"[director.deterministic] rule {rule.get('id')} raised: "
                f"{type(e).__name__}: {e}"
            )
    return violations


def check_rule(rule: Dict, ctx: "_CheckContext") -> Optional[Dict]:
    """Dispatch a single rule to its check_type handler."""
    spec = rule.get("check_spec", {}) or {}
    condition = spec.get("condition")
    if condition and not _evaluate_condition(condition, ctx.enriched_brief):
        return None  # rule doesn't apply to this brief

    check_type = rule.get("check_type")
    if check_type == "css_property":
        return _check_css_property(rule, ctx)
    if check_type == "html_structure":
        return _check_html_structure(rule, ctx)
    if check_type == "text_pattern":
        return _check_text_pattern(rule, ctx)
    if check_type == "global_pattern":
        return _check_global_pattern(rule, ctx)

    logger.warning(
        f"[director.deterministic] unknown check_type {check_type!r} on rule "
        f"{rule.get('id')}; skipping"
    )
    return None


# ─── Context object passed through every check ──────────────────────


class _CheckContext:
    """Bundles the parsed HTML + CSS + brief so each check function
    receives a single ctx argument instead of N keyword arguments."""

    def __init__(
        self,
        soup: BeautifulSoup,
        css_rules: List[Tuple[List[str], Dict[str, str]]],
        root_vars: Dict[str, str],
        accent_color: Optional[str],
        enriched_brief: Dict,
        raw_html: str,
        raw_css: str,
    ):
        self.soup = soup
        self.css_rules = css_rules
        self.root_vars = root_vars
        self.accent_color = accent_color
        self.enriched_brief = enriched_brief
        self.raw_html = raw_html
        self.raw_css = raw_css


# ─── Parsing helpers ────────────────────────────────────────────────


def _parse_html(html: str) -> BeautifulSoup:
    """Parse with the stdlib html.parser to avoid a hard dep on lxml."""
    return BeautifulSoup(html or "", "html.parser")


def _extract_style_blocks(html: str) -> str:
    """Concatenate all <style> block contents from the HTML."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return "\n".join(
        (tag.string or "")
        for tag in soup.find_all("style")
    )


# Match a CSS rule: SELECTOR_LIST { BODY }. Naive but works for the
# Builder Agent's output (no @media / @keyframes nesting in the rules
# we care about — those are tested by `global_pattern` substring matches).
_CSS_RULE_RE = re.compile(
    r"([^{}@][^{}]*)\{\s*([^{}]*)\s*\}",
    re.MULTILINE | re.DOTALL,
)


def _parse_css_rules(css: str) -> List[Tuple[List[str], Dict[str, str]]]:
    """Parse CSS into [(selector_list, props_dict), ...] tuples.

    `selector_list` is the CSS selector list split on commas and
    normalized (lowercased, whitespace collapsed). `props_dict` is
    `{property: value}` for each declaration in the rule body. !important
    suffix is stripped from values; we don't need it for thresholds.
    """
    out: List[Tuple[List[str], Dict[str, str]]] = []
    if not css:
        return out

    # Strip /* ... */ comments first
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    for match in _CSS_RULE_RE.finditer(css):
        selector_blob = match.group(1).strip()
        body = match.group(2).strip()
        if not selector_blob or not body:
            continue
        selectors = [
            re.sub(r"\s+", " ", s.strip().lower())
            for s in selector_blob.split(",")
            if s.strip()
        ]
        if not selectors:
            continue
        props: Dict[str, str] = {}
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            key, _, value = decl.partition(":")
            key = key.strip().lower()
            value = value.strip().rstrip(";").replace("!important", "").strip()
            if key:
                props[key] = value
        if props:
            out.append((selectors, props))
    return out


def _root_vars(
    css_rules: List[Tuple[List[str], Dict[str, str]]],
) -> Dict[str, str]:
    """Collect every --var declaration on `:root` (or `html`) into a flat
    dict so callers can resolve `var(--foo)` references."""
    out: Dict[str, str] = {}
    for selectors, props in css_rules:
        if any(s in (":root", "html", ":root, html") for s in selectors):
            for k, v in props.items():
                if k.startswith("--"):
                    out[k] = v
    return out


def _resolve_var(value: str, root_vars: Dict[str, str]) -> str:
    """Resolve a single var(--foo[, fallback]) reference. Recursive only
    one level — that's all the Builder Agent generates."""
    if not value:
        return value
    m = re.match(r"\s*var\(\s*(--[\w-]+)(?:\s*,\s*([^)]+))?\s*\)\s*", value)
    if not m:
        return value
    var_name = m.group(1)
    fallback = (m.group(2) or "").strip()
    return root_vars.get(var_name, fallback or value)


# ─── Selector matching ──────────────────────────────────────────────


def _split_rule_selectors(rule_selector: str) -> List[str]:
    """Normalize a rule's selector string into a list of lowercase,
    whitespace-collapsed selectors."""
    return [
        re.sub(r"\s+", " ", s.strip().lower())
        for s in rule_selector.split(",")
        if s.strip()
    ]


def _find_matching_props(
    rule_selector: str,
    css_rules: List[Tuple[List[str], Dict[str, str]]],
    root_vars: Dict[str, str],
    property_name: str,
) -> List[str]:
    """Return resolved values of `property_name` from CSS rules whose
    selector list intersects the rule's selectors. Order preserved
    (first declared wins per CSS, but we collect all so callers can
    pick the strictest match)."""
    targets = set(_split_rule_selectors(rule_selector))
    out: List[str] = []
    for selectors, props in css_rules:
        if not (set(selectors) & targets):
            continue
        if property_name in props:
            out.append(_resolve_var(props[property_name], root_vars))
    return out


# ─── Value parsing helpers ──────────────────────────────────────────


_REM_TO_PX = 16.0  # default Vite/React + browser default


def _parse_size_to_px(value: str) -> Optional[float]:
    """Parse a CSS size to px.

    Handles `Npx`, `Nrem`, `Nem`, and `clamp(min, _, max)` (returns the
    minimum — what we threshold against). Returns None if the value
    can't be parsed deterministically (e.g. a calc() with var()s)."""
    if not value:
        return None
    value = value.strip().lower()

    # clamp(min, preferred, max)  — use the first arg as the floor
    m = re.match(r"clamp\s*\(\s*([^,]+)\s*,", value)
    if m:
        return _parse_size_to_px(m.group(1))

    # min(...) — use the smallest of the inner args (lower bound on output)
    m = re.match(r"min\s*\(([^)]+)\)", value)
    if m:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        parsed = [_parse_size_to_px(p) for p in parts]
        parsed = [x for x in parsed if x is not None]
        return min(parsed) if parsed else None

    # max(...) — use the largest of the inner args (lower bound on output)
    m = re.match(r"max\s*\(([^)]+)\)", value)
    if m:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        parsed = [_parse_size_to_px(p) for p in parts]
        parsed = [x for x in parsed if x is not None]
        return max(parsed) if parsed else None

    m = re.match(r"(-?\d+(?:\.\d+)?)\s*px$", value)
    if m:
        return float(m.group(1))
    m = re.match(r"(-?\d+(?:\.\d+)?)\s*rem$", value)
    if m:
        return float(m.group(1)) * _REM_TO_PX
    m = re.match(r"(-?\d+(?:\.\d+)?)\s*em$", value)
    if m:
        return float(m.group(1)) * _REM_TO_PX
    if value == "0":
        return 0.0
    return None


def _parse_clamp_min_rem(value: str) -> Optional[float]:
    """If value is a clamp(), return the min argument in rem. Else None."""
    if not value:
        return None
    m = re.match(r"clamp\s*\(\s*([^,]+)\s*,", value.strip().lower())
    if not m:
        return None
    inner = m.group(1).strip()
    rm = re.match(r"(-?\d+(?:\.\d+)?)\s*rem$", inner)
    if rm:
        return float(rm.group(1))
    px = re.match(r"(-?\d+(?:\.\d+)?)\s*px$", inner)
    if px:
        return float(px.group(1)) / _REM_TO_PX
    return None


def _parse_padding_y(value: str) -> Optional[float]:
    """Extract the top (== bottom for shorthand) padding in px from a
    padding/padding-top/padding-bottom value. Handles 1-4 part shorthand."""
    if not value:
        return None
    parts = [p.strip() for p in value.split() if p.strip()]
    if not parts:
        return None
    # padding: top right bottom left  (or 1/2/3 part shorthand)
    # First part = top, which is what we threshold for vertical padding.
    return _parse_size_to_px(parts[0])


# ─── Color parsing ──────────────────────────────────────────────────

_HEX_RE = re.compile(r"#([0-9a-f]{3,8})", re.IGNORECASE)


def _normalize_hex(value: str) -> Optional[str]:
    """Pull the first hex color out of a CSS value and lowercase it."""
    if not value:
        return None
    m = _HEX_RE.search(value)
    if not m:
        return None
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return f"#{h[:6]}"  # drop alpha if present, we compare base hex only


def _hex_lightness(hex6: str) -> Optional[float]:
    """Return the HSL lightness (0..1) of a #RRGGBB color."""
    m = re.match(r"#([0-9a-f]{6})", hex6 or "", re.IGNORECASE)
    if not m:
        return None
    h = m.group(1).lower()
    r, g, b = (int(h[i: i + 2], 16) / 255.0 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    return (mx + mn) / 2.0


def _resolve_accent_color(
    enriched_brief: Optional[Dict],
    root_vars: Dict[str, str],
) -> Optional[str]:
    """Best-effort 'what is the brand accent color?' resolution.

    Order:
      1. enriched_brief.palette_roles.accent (hex)
      2. CSS --accent / --gold / --gold-light variable
      3. None (callers fall back to color-name matching where useful)
    """
    if enriched_brief:
        pal = (enriched_brief.get("palette_roles") or {})
        for key in ("accent", "cta_color", "warm_secondary"):
            v = pal.get(key)
            hex6 = _normalize_hex(v) if v else None
            if hex6:
                return hex6
    for var_name in ("--accent", "--gold", "--gold-light"):
        if var_name in root_vars:
            hex6 = _normalize_hex(root_vars[var_name])
            if hex6:
                return hex6
    return None


# ─── Condition evaluation ────────────────────────────────────────────


def _evaluate_condition(condition: str, enriched_brief: Optional[Dict]) -> bool:
    """Tiny DSL: 'enriched_brief.PATH IS NOT NULL'.

    Anything else evaluates to True (don't accidentally suppress rules
    we don't recognize)."""
    if not condition or not isinstance(condition, str):
        return True
    m = re.match(
        r"\s*enriched_brief\.([\w.]+)\s+IS\s+NOT\s+NULL\s*$",
        condition,
        re.IGNORECASE,
    )
    if not m:
        return True
    path = m.group(1).split(".")
    cur: Any = enriched_brief or {}
    for part in path:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return False
    return cur is not None


# ─── Violation helper ────────────────────────────────────────────────


def _violation(rule: Dict, evidence: str, fix_hint_override: str = "") -> Dict:
    return {
        "rule_id": rule.get("id"),
        "severity": rule.get("severity", "MEDIUM"),
        "description": rule.get("description", ""),
        "evidence": evidence,
        "fix_hint": fix_hint_override or rule.get("fix_hint", ""),
    }


# ─── css_property checks ─────────────────────────────────────────────


def _check_css_property(rule: Dict, ctx: _CheckContext) -> Optional[Dict]:
    spec = rule.get("check_spec", {}) or {}
    selector = spec.get("selector", "")
    prop = spec.get("property", "")
    if not selector or not prop:
        return None

    values = _find_matching_props(selector, ctx.css_rules, ctx.root_vars, prop)
    if not values:
        # Property not declared at all on the matching selector — that's
        # a real gap for HIGH/MEDIUM rules where the property is required.
        return _violation(
            rule,
            evidence=f"No `{prop}` declared on selector `{selector}`.",
        )

    # min_value_px / max_value_px (numeric thresholds, handles clamp())
    min_px = spec.get("min_value_px")
    max_px = spec.get("max_value_px")
    accept_clamp_min_rem = spec.get("accept_clamp_min_rem")
    allowed_values = spec.get("allowed_values")
    min_y = spec.get("min_value_px_y")
    axis = spec.get("axis")

    # Most-permissive evaluation: if ANY declared value passes the rule,
    # the rule passes. (Builder may declare a desktop value via @media
    # we don't parse; we only care that the floor exists somewhere.)
    parsed_values: List[Tuple[str, Optional[float]]] = []
    for v in values:
        if axis == "y":
            parsed_values.append((v, _parse_padding_y(v)))
        else:
            parsed_values.append((v, _parse_size_to_px(v)))

    # allowed_values exact-match (font-weight, etc.)
    if allowed_values:
        normalized = [v.strip() for v, _ in parsed_values]
        if any(v in allowed_values for v in normalized):
            return None
        return _violation(
            rule,
            evidence=(
                f"`{prop}` on `{selector}` is `{', '.join(normalized)}`; "
                f"expected one of {allowed_values}."
            ),
        )

    # min threshold (with optional clamp() rem floor)
    if min_px is not None or accept_clamp_min_rem is not None:
        for raw, parsed_px in parsed_values:
            if parsed_px is not None and min_px is not None and parsed_px >= min_px:
                return None
            if accept_clamp_min_rem is not None:
                clamp_rem = _parse_clamp_min_rem(raw)
                if clamp_rem is not None and clamp_rem >= accept_clamp_min_rem:
                    return None
        first_raw = parsed_values[0][0]
        return _violation(
            rule,
            evidence=(
                f"`{prop}` on `{selector}` resolves to `{first_raw}` — "
                f"need >= {min_px}px"
                + (
                    f" or clamp(>= {accept_clamp_min_rem}rem, ...)"
                    if accept_clamp_min_rem is not None
                    else ""
                )
                + "."
            ),
        )

    # max threshold (used only by hero_h1_letter_spacing — value must be
    # AT MOST max (which is negative), AT LEAST min. So both checks here.)
    if max_px is not None:
        floor = spec.get("min_value_px")
        ok = False
        for _, parsed_px in parsed_values:
            if parsed_px is None:
                continue
            if parsed_px <= max_px and (floor is None or parsed_px >= floor):
                ok = True
                break
        if ok:
            return None
        first_raw = parsed_values[0][0]
        bound_descr = f"<= {max_px}px"
        if floor is not None:
            bound_descr += f" and >= {floor}px"
        return _violation(
            rule,
            evidence=f"`{prop}` on `{selector}` is `{first_raw}` — need {bound_descr}.",
        )

    # min_value_px_y — handled by axis branch above. If it remains here
    # without a min_value_px, treat as min_y.
    if min_y is not None:
        for _, parsed_px in parsed_values:
            if parsed_px is not None and parsed_px >= min_y:
                return None
        first_raw = parsed_values[0][0]
        return _violation(
            rule,
            evidence=(
                f"`{prop}` (y-axis) on `{selector}` is `{first_raw}` — "
                f"need top/bottom >= {min_y}px."
            ),
        )

    return None


# ─── html_structure checks ──────────────────────────────────────────


def _select_tolerant(soup: BeautifulSoup, selector: str) -> List[Any]:
    """Run a CSS selector with bs4, return [] if the selector is too
    exotic for bs4's CSS engine instead of raising."""
    try:
        return soup.select(selector)
    except Exception:
        return []


def _check_html_structure(rule: Dict, ctx: _CheckContext) -> Optional[Dict]:
    spec = rule.get("check_spec", {}) or {}
    selector = spec.get("selector", "")
    if not selector:
        return None

    elements = _select_tolerant(ctx.soup, selector)
    if not elements:
        return _violation(
            rule,
            evidence=f"No elements matched selector `{selector}`.",
        )

    must_contain = spec.get("must_contain_child_matching")
    must_descend = spec.get("must_contain_descendant_matching")
    min_match_ratio = spec.get("min_match_ratio", 1.0)
    require_accent = spec.get("child_should_use_accent_color", False)

    # Combine the two "must contain" axes — the rubric uses one or the
    # other. The check is "this element contains a descendant matching
    # any of the listed selectors." For child-only rules we still walk
    # descendants — bs4's `select()` is descendant-by-default which is
    # what we want for the rubric semantics.
    target_selectors: List[str] = []
    if isinstance(must_contain, list):
        target_selectors.extend(must_contain)
    if isinstance(must_descend, list):
        target_selectors.extend(must_descend)

    if not target_selectors:
        return None

    matched = 0
    accent_failures: List[str] = []
    for el in elements:
        found = None
        for child_sel in target_selectors:
            try:
                hits = el.select(child_sel)
            except Exception:
                hits = []
            if hits:
                found = hits[0]
                break
        if found is None:
            continue
        if require_accent:
            child_color = _normalize_hex(
                found.get("style", "") if hasattr(found, "get") else ""
            )
            # Also accept inline style with var(--accent), or a class that
            # looks accent-related (bs4 can't resolve external CSS without
            # a full CSS engine — we accept "looks accent-y" as a soft pass).
            classes = " ".join(found.get("class") or []) if hasattr(found, "get") else ""
            inline_style = found.get("style", "") if hasattr(found, "get") else ""
            looks_accent = any(
                kw in (classes + " " + inline_style).lower()
                for kw in ("accent", "gold", "primary")
            )
            if ctx.accent_color and child_color and child_color == ctx.accent_color:
                pass  # explicit hex match
            elif looks_accent or "var(--accent" in inline_style or "var(--gold" in inline_style:
                pass  # CSS-var/class match
            else:
                accent_failures.append(
                    f"<{found.name}> child of <{el.name}> doesn't appear to use accent color"
                )
                continue
        matched += 1

    if matched < len(elements) * min_match_ratio:
        ratio_msg = (
            f"{matched}/{len(elements)} elements matched "
            f"`{selector}` contained one of {target_selectors} "
            f"(need >= {int(min_match_ratio * 100)}%)"
        )
        if accent_failures:
            ratio_msg += f"; accent color issues: {accent_failures[:2]}"
        return _violation(rule, evidence=ratio_msg)

    return None


# ─── text_pattern checks ────────────────────────────────────────────


def _check_text_pattern(rule: Dict, ctx: _CheckContext) -> Optional[Dict]:
    spec = rule.get("check_spec", {}) or {}
    selector = spec.get("selector", "")
    forbidden = spec.get("forbidden_phrases_ci") or spec.get("forbidden_phrases") or []
    if not selector or not forbidden:
        return None

    elements = _select_tolerant(ctx.soup, selector)
    if not elements:
        return None  # nothing to test; not a violation by itself

    forbidden_lc = [p.lower() for p in forbidden]
    hits: List[str] = []
    for el in elements:
        text = (el.get_text() or "").strip()
        if not text:
            continue
        lc = text.lower()
        for phrase in forbidden_lc:
            if phrase in lc:
                hits.append(text[:80])
                break

    if not hits:
        return None

    # `soft: true` rubric flag downgrades the violation to LOW so the
    # punch list doesn't insist on a regen for a borderline case.
    soft = bool(spec.get("soft"))
    sev_override = "LOW" if soft else rule.get("severity", "MEDIUM")
    return {
        "rule_id": rule.get("id"),
        "severity": sev_override,
        "description": rule.get("description", ""),
        "evidence": (
            f"Forbidden phrases on `{selector}`: "
            + ", ".join(repr(h) for h in hits[:5])
        ),
        "fix_hint": rule.get("fix_hint", ""),
    }


# ─── global_pattern checks ──────────────────────────────────────────


def _check_global_pattern(rule: Dict, ctx: _CheckContext) -> Optional[Dict]:
    spec = rule.get("check_spec", {}) or {}
    pattern = spec.get("pattern", "")

    if pattern == "alternating_section_backgrounds":
        return _check_alternating_section_backgrounds(rule, ctx, spec)
    if pattern == "full_bleed_accent_band":
        return _check_full_bleed_accent_band(rule, ctx, spec)
    if pattern == "film_grain_overlay":
        return _check_film_grain_overlay(rule, ctx, spec)
    if pattern == "css_contains_substring":
        return _check_css_contains_substring(rule, ctx, spec)
    if pattern == "no_pure_white_section_bg":
        return _check_no_pure_white_section_bg(rule, ctx, spec)

    logger.warning(
        f"[director.deterministic] unknown global_pattern {pattern!r}; skipping"
    )
    return None


def _section_bg(el: Any, ctx: _CheckContext) -> Optional[str]:
    """Best-effort 'what's the background color of this section?' —
    inline style first, then matching CSS rule for tag/class/id."""
    if not hasattr(el, "get"):
        return None

    # Inline style
    inline = el.get("style", "") or ""
    for prop in ("background", "background-color"):
        m = re.search(prop + r"\s*:\s*([^;]+)", inline, re.IGNORECASE)
        if m:
            v = _resolve_var(m.group(1).strip(), ctx.root_vars)
            hex6 = _normalize_hex(v)
            if hex6:
                return hex6
            v_lc = v.lower().strip()
            if v_lc == "white":
                return "#ffffff"
            if v_lc == "black":
                return "#000000"

    # Matching CSS rules — try tag, class, id
    candidates: List[str] = [el.name or ""]
    classes = el.get("class") or []
    candidates.extend(f".{c}" for c in classes)
    eid = el.get("id")
    if eid:
        candidates.append(f"#{eid}")

    for sel in candidates:
        for selectors, props in ctx.css_rules:
            if sel in selectors:
                for prop in ("background", "background-color"):
                    if prop in props:
                        v = _resolve_var(props[prop], ctx.root_vars)
                        hex6 = _normalize_hex(v)
                        if hex6:
                            return hex6
    return None


def _check_alternating_section_backgrounds(
    rule: Dict, ctx: _CheckContext, spec: Dict
) -> Optional[Dict]:
    sections = ctx.soup.find_all(["section"]) + ctx.soup.select("[class*=section]")
    # Dedupe while preserving order (bs4 nodes are equal-by-identity)
    seen: List[Any] = []
    for s in sections:
        if s not in seen:
            seen.append(s)
    if len(seen) < 2:
        return _violation(
            rule,
            evidence=f"Found only {len(seen)} sections; need at least 2 to alternate.",
        )

    dark_thresh = spec.get("dark_threshold_lightness", 0.25)
    light_thresh = spec.get("light_threshold_lightness", 0.85)
    min_alt = spec.get("min_alternations", 2)

    classified: List[str] = []  # 'dark' | 'light' | 'unknown'
    for s in seen:
        bg = _section_bg(s, ctx)
        if not bg:
            classified.append("unknown")
            continue
        L = _hex_lightness(bg)
        if L is None:
            classified.append("unknown")
        elif L <= dark_thresh:
            classified.append("dark")
        elif L >= light_thresh:
            classified.append("light")
        else:
            classified.append("unknown")

    # Count alternations in the dark/light subsequence (skipping unknowns)
    skipped = [c for c in classified if c != "unknown"]
    alternations = sum(
        1 for a, b in zip(skipped, skipped[1:]) if a != b
    )
    if alternations < min_alt:
        return _violation(
            rule,
            evidence=(
                f"Section bg classifications: {classified}. "
                f"Alternations: {alternations} (need >= {min_alt})."
            ),
        )
    return None


def _check_full_bleed_accent_band(
    rule: Dict, ctx: _CheckContext, spec: Dict
) -> Optional[Dict]:
    accent = ctx.accent_color
    needles = ["linear-gradient", "background"]

    sections = ctx.soup.find_all(["section", "div"])
    band_count = 0
    for s in sections:
        inline = (s.get("style", "") or "").lower() if hasattr(s, "get") else ""
        has_gradient = "linear-gradient" in inline
        bg = _section_bg(s, ctx)
        is_accent_bg = (
            (accent and bg and bg == accent)
            or any(
                kw in inline
                for kw in ("var(--gold", "var(--accent", "linear-gradient(135deg, var(--gold")
            )
        )
        if has_gradient and is_accent_bg:
            band_count += 1
            continue
        # Section-level CSS rule path (no inline style)
        if bg and accent and bg == accent:
            band_count += 1
            continue
        # Last-resort heuristic: a section's CSS class block contains
        # "linear-gradient" + a known accent var name
        classes = " ".join(s.get("class") or []) if hasattr(s, "get") else ""
        for cls in classes.split():
            for selectors, props in ctx.css_rules:
                if f".{cls.lower()}" not in selectors:
                    continue
                bg_decl = (props.get("background") or props.get("background-color") or "").lower()
                if "linear-gradient" in bg_decl and (
                    "gold" in bg_decl or "accent" in bg_decl or (accent and accent in bg_decl)
                ):
                    band_count += 1
                    break

    min_count = spec.get("min_count", 1)
    if band_count < min_count:
        return _violation(
            rule,
            evidence=f"Found {band_count} full-bleed accent band(s); need >= {min_count}.",
        )
    return None


def _check_film_grain_overlay(
    rule: Dict, ctx: _CheckContext, spec: Dict
) -> Optional[Dict]:
    needles = spec.get("must_match_one_of", [])
    haystack = (ctx.raw_html + "\n" + ctx.raw_css).lower()
    if any(n.lower() in haystack for n in needles):
        return None
    return _violation(rule, evidence="No film grain overlay markers found in HTML or CSS.")


def _check_css_contains_substring(
    rule: Dict, ctx: _CheckContext, spec: Dict
) -> Optional[Dict]:
    needles = spec.get("needles", [])
    min_count = spec.get("min_count", 1)
    haystack = ctx.raw_css.lower()
    found = sum(1 for n in needles if n.lower() in haystack)
    if found >= min_count:
        return None
    return _violation(
        rule,
        evidence=f"CSS doesn't contain any of {needles} (found {found}, need >= {min_count}).",
    )


def _check_no_pure_white_section_bg(
    rule: Dict, ctx: _CheckContext, spec: Dict
) -> Optional[Dict]:
    forbidden = [v.lower() for v in (spec.get("forbidden_values_ci") or [])]
    selectors = spec.get("selectors", ["section"])
    if not forbidden:
        return None

    offenders: List[str] = []
    for sel in selectors:
        for el in _select_tolerant(ctx.soup, sel):
            inline = (el.get("style", "") or "").lower() if hasattr(el, "get") else ""
            for prop in ("background", "background-color"):
                m = re.search(prop + r"\s*:\s*([^;]+)", inline)
                if m and any(f in m.group(1).strip().lower() for f in forbidden):
                    offenders.append(
                        f"<{el.name}> inline {prop}: {m.group(1).strip()}"
                    )

    # Also scan CSS rules for section/light selectors with pure white bg
    for selectors_list, props in ctx.css_rules:
        if not any(s in ("section", "body", ".section") for s in selectors_list):
            continue
        for prop in ("background", "background-color"):
            v = (props.get(prop) or "").lower()
            if any(f in v for f in forbidden):
                offenders.append(f"{selectors_list} CSS {prop}: {v}")

    if offenders:
        return _violation(
            rule,
            evidence=f"Pure white backgrounds: {offenders[:3]}",
        )
    return None
