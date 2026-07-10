"""
atelier_validator.py — Arc 8 — deterministic inspection of bespoke
fragments (the spirit of studio_solutionist_quality, ported to the
Atelier's hard output contract).

Pure functions, no LLM, no network. stdlib html.parser + regex only
(bs4 is a dep but the checks here are contract checks, not DOM
queries — the parser tracks structure, the regexes police the CSS).

validate_fragment(html, css, ...) -> (ok, problems)

Rules enforced (each maps to a numbered clause of the prompt's HARD
OUTPUT CONTRACT):
  1. exactly one root <section> whose class list contains atl-{uid};
     nothing but whitespace/comments outside it; balanced tags
  2. CSS scoping — every selector starts with .atl-{uid}; @media only
     at-rule allowed besides @keyframes whose names start with
     atl-{uid}; no #id selectors
  3. color discipline — var(--sx-*)/transparent/currentColor only;
     the two neutral rgba() forms allowed; hex/rgb()/hsl() banned
  4. fonts — every font-family references var(--sx-font-*)
  5. imagery — <img> only with data-slot from the allowed list (each
     at most once), src empty, alt non-empty
  6. copy paths — one data-override-target="{kind}/{field}" per
     provided copy field; ADDITIONAL display text the author invents
     must carry {kind}/custom_N (Site Arc 11 total editability — the
     module's own declared fields are also accepted)
  7. links — #anchors or the explicitly allowed hrefs; no external
     URLs / @import / url() anywhere
  8. no <script>/<style>/<iframe>/inline handlers/position:fixed
  9. responsive — a max-width media query <= 900px present
 10. reduced motion — any animation requires prefers-reduced-motion
 11. size caps — html <= 14KB, css <= 10KB
 12. DATA FIDELITY — every digit-run in the rendered text appears in
     the provided data JSON (prices/numbers can never be invented)
 13. a11y floor — at least one heading present
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple

HTML_MAX_BYTES = 14 * 1024
CSS_MAX_BYTES = 10 * 1024

_VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr",
              "area", "base", "col", "embed", "track"}
_BANNED_TAGS = {"script", "style", "iframe", "object", "embed", "link",
                "meta", "base", "form"}
_HEADING_TAGS = {"h1", "h2", "h3"}

_ALLOWED_RGBA_RE = re.compile(
    r"rgba\(\s*(?:0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)\s*,\s*[0-9.]+\s*\)",
    re.IGNORECASE)
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_HSL_RE = re.compile(r"\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)\(",
                         re.IGNORECASE)
_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)")
_FONT_FAMILY_RE = re.compile(r"font(?:-family)?\s*:\s*([^;}{]+)", re.IGNORECASE)
_EXTERNAL_RE = re.compile(r"https?://|(?<!:)//(?![*/])|url\s*\(|@import|data:",
                          re.IGNORECASE)
_MEDIA_MAXW_RE = re.compile(r"max-width\s*:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)
_DIGIT_RUN_RE = re.compile(r"\d+")
# Site Arc 11 — invented-display-text override targets: {kind}/custom_1,
# custom_2, … (sequential numbering is the prompt's ask; the validator
# only requires the FORM so a re-numbered repair never fails on it).
_CUSTOM_TARGET_RE = re.compile(r"custom_\d+$")


class _FragmentParser(HTMLParser):
    """Structure walk: root elements, banned tags, imgs, anchors,
    inline handlers, style attrs, override targets, visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.roots: List[Tuple[str, Dict[str, Optional[str]]]] = []
        self.banned: List[str] = []
        self.imgs: List[Dict[str, Optional[str]]] = []
        self.anchors: List[Dict[str, Optional[str]]] = []
        self.handlers: List[str] = []
        self.style_attrs: List[str] = []
        self.targets: List[str] = []
        self.headings = 0
        self.text_parts: List[str] = []
        self.stray_text: List[str] = []
        self.unbalanced = False

    def _record(self, tag: str, attrs_list) -> Dict[str, Optional[str]]:
        attrs = {k.lower(): v for k, v in attrs_list}
        if tag in _BANNED_TAGS:
            self.banned.append(tag)
        for k in attrs:
            if k.startswith("on"):
                self.handlers.append(f"{tag}@{k}")
        if attrs.get("style"):
            self.style_attrs.append(attrs["style"] or "")
        if attrs.get("data-override-target"):
            self.targets.append(attrs["data-override-target"] or "")
        if tag == "img":
            self.imgs.append(attrs)
        if tag == "a":
            self.anchors.append(attrs)
        if tag in _HEADING_TAGS:
            self.headings += 1
        return attrs

    def handle_starttag(self, tag, attrs):
        attrs_d = self._record(tag, attrs)
        if tag in _VOID_TAGS:
            if self.depth == 0:
                self.roots.append((tag, attrs_d))
            return
        if self.depth == 0:
            self.roots.append((tag, attrs_d))
        self.depth += 1

    def handle_startendtag(self, tag, attrs):
        attrs_d = self._record(tag, attrs)
        if self.depth == 0:
            self.roots.append((tag, attrs_d))

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        self.depth -= 1
        if self.depth < 0:
            self.unbalanced = True
            self.depth = 0

    def handle_data(self, data):
        if data.strip():
            self.text_parts.append(data)
            if self.depth == 0:
                self.stray_text.append(data.strip()[:40])


def _check_css_scoping(css: str, uid: str, problems: List[str]) -> None:
    """Brace-walking selector check: every rule selector starts with
    .atl-{uid}; @media is the only allowed conditional at-rule;
    @keyframes names must start with atl-{uid} (their frame selectors
    are exempt); no #id selectors."""
    prefix = f".atl-{uid}"
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    stack: List[str] = []
    buf: List[str] = []
    for ch in body:
        if ch == "{":
            prelude = "".join(buf).strip()
            buf = []
            low = prelude.lower()
            if low.startswith("@media"):
                stack.append("media")
            elif low.startswith(("@keyframes", "@-webkit-keyframes")):
                name = prelude.split(None, 1)[1].strip() if " " in prelude else ""
                if not name.startswith(f"atl-{uid}"):
                    problems.append(
                        f"@keyframes name '{name or '(missing)'}' must start "
                        f"with atl-{uid}")
                stack.append("keyframes")
            elif low.startswith("@"):
                problems.append(f"at-rule not allowed: '{prelude[:40]}'")
                stack.append("atrule")
            elif "keyframes" in stack:
                stack.append("frame")     # from/to/% — exempt
            else:
                for sel in prelude.split(","):
                    s = sel.strip()
                    if not s:
                        continue
                    if "#" in s:
                        problems.append(f"id selector banned: '{s[:60]}'")
                    if not s.startswith(prefix):
                        problems.append(
                            f"unscoped selector (must start with {prefix}): "
                            f"'{s[:60]}'")
                stack.append("rule")
        elif ch == "}":
            if stack:
                stack.pop()
            else:
                problems.append("unbalanced braces in CSS (extra '}')")
            buf = []
        else:
            buf.append(ch)
    if stack:
        problems.append("unbalanced braces in CSS (unclosed block)")


def _check_colors(css: str, style_attrs: Sequence[str],
                  problems: List[str]) -> None:
    surfaces = [("css", css)] + [("style attribute", s) for s in style_attrs]
    for label, text in surfaces:
        for m in _HEX_RE.finditer(text):
            problems.append(f"hex color literal in {label}: '{m.group(0)}'")
        # Neutralize the two allowed rgba() forms, then any remaining
        # rgb(/rgba(/hsl( call is a violation.
        cleaned = _ALLOWED_RGBA_RE.sub("OKRGBA", text)
        for m in re.finditer(r"\brgba\(", cleaned, re.IGNORECASE):
            problems.append(
                f"rgba() in {label} outside the allowed neutrals "
                "rgba(0,0,0,x)/rgba(255,255,255,x)")
        for m in _RGB_HSL_RE.finditer(cleaned):
            problems.append(f"color function banned in {label}: "
                            f"'{m.group(0)}…'")


def _check_tokens_and_fonts(css: str, style_attrs: Sequence[str],
                            problems: List[str]) -> None:
    for m in _VAR_RE.finditer(css + " " + " ".join(style_attrs)):
        if not m.group(1).startswith("--sx-"):
            problems.append(f"unknown token '{m.group(1)}' — only --sx-* "
                            "variables exist")
    for m in _FONT_FAMILY_RE.finditer(css):
        decl = m.group(0)
        # `font:` shorthand or `font-family:` — either way the family
        # must come from the token contract.
        if "font-family" in decl.lower() or decl.lower().lstrip().startswith("font"):
            if "var(--sx-font-" not in m.group(1).replace(" ", ""):
                problems.append(
                    f"font-family must use var(--sx-font-*): '{decl[:60]}'")


def _visible_digit_runs(text_parts: Sequence[str]) -> List[str]:
    return _DIGIT_RUN_RE.findall(" ".join(text_parts))


def validate_fragment(html: str, css: str, *, uid: str, kind: str,
                      data: Dict[str, Any],
                      allowed_slots: Sequence[str] = (),
                      required_targets: Sequence[str] = (),
                      allowed_hrefs: Sequence[str] = (),
                      allowed_fields: Sequence[str] = (),
                      ) -> Tuple[bool, List[str]]:
    """Full contract inspection. Returns (ok, problems); problems are
    written to be pasted straight into the repair prompt."""
    problems: List[str] = []
    html = str(html or "")
    css = str(css or "")

    # 11 — size caps first (cheap, and oversized output isn't worth parsing)
    if len(html.encode("utf-8")) > HTML_MAX_BYTES:
        problems.append(f"HTML exceeds {HTML_MAX_BYTES // 1024}KB")
    if len(css.encode("utf-8")) > CSS_MAX_BYTES:
        problems.append(f"CSS exceeds {CSS_MAX_BYTES // 1024}KB")

    # 1 — structure
    p = _FragmentParser()
    try:
        p.feed(html)
        p.close()
    except Exception as e:
        return False, problems + [f"HTML failed to parse: {e}"]
    if p.unbalanced or p.depth != 0:
        problems.append("unbalanced HTML tags")
    real_roots = [(t, a) for t, a in p.roots]
    if len(real_roots) != 1 or real_roots[0][0] != "section":
        problems.append(
            f"exactly one root <section> required (found "
            f"{[t for t, _ in real_roots] or 'none'})")
    else:
        classes = (real_roots[0][1].get("class") or "").split()
        if f"atl-{uid}" not in classes:
            problems.append(f'root <section> class must include "atl-{uid}"')
    if p.stray_text:
        problems.append(f"text outside the root section: {p.stray_text[:2]}")

    # 8 — banned tags / handlers / fixed positioning
    for t in p.banned:
        problems.append(f"banned tag <{t}>")
    for h in p.handlers:
        problems.append(f"inline event handler banned: {h}")
    if re.search(r"position\s*:\s*fixed", css + " ".join(p.style_attrs),
                 re.IGNORECASE):
        problems.append("position:fixed banned")

    # 7 — external references (checked over both surfaces; data: URIs are
    # platform-only, never bespoke). The explicitly-allowed hrefs (e.g.
    # the booking URL handed in as data) are the only http exemption.
    for label, text in (("HTML", html), ("CSS", css)):
        for m in _EXTERNAL_RE.finditer(text):
            if m.group(0).lower().startswith("http") and any(
                    h and text[m.start():m.start() + len(h)] == h
                    for h in allowed_hrefs):
                continue
            problems.append(
                f"external reference banned in {label}: "
                f"'{text[m.start():m.start() + 40]}…'")
            break
    for a in p.anchors:
        href = (a.get("href") or "").strip()
        if not href:
            problems.append("anchor with empty href (dead link)")
        elif not href.startswith("#") and href not in allowed_hrefs:
            problems.append(f"href not allowed: '{href[:80]}' "
                            f"(use #anchors or: {list(allowed_hrefs) or 'none'})")

    # 5 — imagery + a11y alt
    seen_slots: List[str] = []
    for img in p.imgs:
        slot = (img.get("data-slot") or "").strip()
        if not slot:
            problems.append("every <img> must carry data-slot")
        elif slot not in allowed_slots:
            problems.append(f'data-slot "{slot}" not allowed for {kind} '
                            f"(allowed: {list(allowed_slots) or 'none'})")
        elif slot in seen_slots:
            problems.append(f'data-slot "{slot}" used more than once')
        else:
            seen_slots.append(slot)
        if str(img.get("src") or "").strip():
            problems.append("img src must be empty — the platform fills it")
        if not str(img.get("alt") or "").strip():
            problems.append(f'img (slot "{slot or "?"}") missing alt text')

    # 6 — copy override paths
    for field in required_targets:
        want = f"{kind}/{field}"
        n = p.targets.count(want)
        if n == 0:
            problems.append(f'missing data-override-target="{want}" for the '
                            f"provided copy field '{field}'")
        elif n > 1:
            problems.append(f'data-override-target="{want}" appears {n} times '
                            "(must be unique)")
    # Site Arc 11 (total editability): every target lives under {kind}/;
    # the field half must be a provided copy field, one of the module's
    # declared fields (allowed_fields), or custom_N — the path the author
    # gives any ADDITIONAL display text it invents.
    known_fields = set(required_targets) | set(allowed_fields)
    for t in p.targets:
        if not t.startswith(f"{kind}/"):
            problems.append(f'override target "{t}" must live under "{kind}/"')
            continue
        field = t[len(kind) + 1:]
        if field in known_fields or _CUSTOM_TARGET_RE.fullmatch(field):
            continue
        problems.append(
            f'override target "{t}" not recognized — invented display text '
            f'must use data-override-target="{kind}/custom_N" (N = 1, 2, …)')

    # 2 — CSS scoping
    _check_css_scoping(css, uid, problems)

    # 3/4 — color + token + font discipline
    _check_colors(css, p.style_attrs, problems)
    _check_tokens_and_fonts(css, p.style_attrs, problems)

    # 9 — responsive (only @media PRELUDES count — a max-width property
    # on a column is layout, not responsiveness)
    preludes = re.findall(r"@media[^{]*", css, re.IGNORECASE)
    widths = [float(w) for pre in preludes
              for w in _MEDIA_MAXW_RE.findall(pre)]
    if not any(w <= 900 for w in widths):
        problems.append("no mobile @media (max-width: <=760px) block found")

    # 10 — reduced motion
    if re.search(r"animation|@keyframes", css, re.IGNORECASE) and \
            "prefers-reduced-motion" not in css:
        problems.append("animation present without a "
                        "prefers-reduced-motion guard")

    # 13 — a11y floor
    if p.headings < 1:
        problems.append("no heading (h1-h3) in the section")

    # 12 — DATA FIDELITY: every rendered digit-run must exist in the data.
    # Site Arc 9 DATA DIGNITY note: the rule is one-directional (rendered
    # digits ⊆ data), so the literal string "Free" standing in for a
    # data price of 0 is PERMITTED by construction — "Free" carries no
    # digit run, and prompt clause DATA DIGNITY requires it. Do not
    # tighten this into a bidirectional check without exempting
    # Free-for-0.
    data_digits = set(_DIGIT_RUN_RE.findall(
        json.dumps(data or {}, ensure_ascii=False)))
    for run in _visible_digit_runs(p.text_parts):
        if run not in data_digits:
            problems.append(
                f"number '{run}' rendered but not present in the provided "
                "data — never invent prices/figures")

    # 14 — HEADLINE PLAIN-TEXT INTEGRITY (2026-07-10, the morph-headline
    # bug): a live hero shipped an h1 whose tag-stripped text read "From
    # tangled launched tangled to launched." — a word-morph split across
    # aria-hidden spans plus an sr echo. Pixels looked fine mid-animation;
    # the TEXT (screen readers, search indexing, copy-paste) was garbled,
    # and the reduced-motion fallback dropped the subject entirely.
    # Rule: no aria-hidden subtree inside an h1/h2 may carry words, and
    # a heading's words must not repeat as duplicated spans.
    for hm in re.finditer(r"<h[12][^>]*>([\s\S]*?)</h[12]>", html, re.IGNORECASE):
        inner = hm.group(1)
        hidden_words = []
        for ah in re.finditer(
                r"<[^>]+aria-hidden=[\"']true[\"'][^>]*>([\s\S]*?)</[^>]+>",
                inner, re.IGNORECASE):
            hidden_words += re.findall(r"[A-Za-z']{2,}",
                                       re.sub(r"<[^>]+>", " ", ah.group(1)))
        if hidden_words:
            problems.append(
                "headline contains aria-hidden WORDS "
                f"({', '.join(hidden_words[:4])}) — headings must read as "
                "clean plain text with CSS off; never split/morph/echo "
                "headline words across hidden spans (HEADLINE INTEGRITY)")
            break

    # 15 — STYLESHEET PURITY (2026-07-10, the junk-in-CSS bug): the CSS
    # part of the response runs to end-of-output, and a live page shipped
    # with a stray '</section>' and a leaked '</invoke>' inside the
    # stylesheet. CSS error recovery discards such junk PLUS the entire
    # next rule — which in the assembled page was the next fragment's
    # base rule (positioning/overflow gone, decorations painting over
    # the whole page). '</' is never valid CSS; '<' alone stays legal
    # (modern range media queries use it).
    css_body = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    jm = re.search(r"</[^\n]{0,30}", css_body)
    if jm:
        problems.append(
            f"markup junk inside CSS: '{jm.group(0)}' — after the final "
            "closing brace output nothing; no closing tags ever belong "
            "in the stylesheet")

    # 16 — SCOPE CLASS DISCIPLINE (2026-07-10, the stamped-children bug):
    # a live hero carried atl-{uid} on EVERY element, so the root base
    # rule (min-height:88vh, display:flex, section padding) cascaded onto
    # each child — the h1 became a viewport-tall flex box and the layout
    # detonated. The scope class belongs to the root <section> alone;
    # descendant selectors work without repeating it.
    stamps = len(re.findall(rf"\batl-{re.escape(uid)}\b", html))
    if stamps > 1:
        problems.append(
            f"the scope class atl-{uid} appears on {stamps} elements — it "
            "belongs ONLY on the root <section>; child elements use plain "
            "role classes targeted via descendant selectors "
            f"(.atl-{uid} .crest)")

    return (not problems), problems
