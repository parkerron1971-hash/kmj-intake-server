# craft_laws.py
# ─────────────────────────────────────────────────────────────────────
# THE CRAFT FLOOR, IN CODE (2026-10-01, the concept-layer plan, step 2).
#
# Kevin sent liaisongraphics.com as the standard for "very high attention
# to detail". Its concept carried it; its craft did not: typos in
# headline text ("SEMSESTER", "AVALIABLE"), ten H1s on one page, a phone
# layout that hid the headline and shrank the class schedule to text
# about six pixels tall, paragraphs centered for eight lines, buttons in
# the browser's default font. Nothing in builder_v2 checked any of it.
#
# Every check here is a QUALITY defect, never a lie, so it rides the
# soft tier beside the stand-in law: it earns the surgical repair round
# and never sends a build to the fallback engine. Three layers:
#
#   1. check_html: read from the document (headings, alt text, how many
#      type families load, likely typos).
#   2. typographer: a mechanical pass, no model call, that fixes what a
#      person would mark with a pen (straight quotes, apostrophes,
#      ranges, ellipses) in place rather than rejecting the page.
#   3. RENDER_JS + render_findings: read from the page the eyes already
#      render at 390 and 1440 (running text under 14px on a phone, any
#      text under 11px, centered paragraphs over three lines, controls in
#      the system font, a headline that never reaches the first screen).
#
# The 11px floor for any text is deliberate: tracked micro-caps at 11px
# are a real editorial voice (the atelier language uses them); six
# pixels is not.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("craft_laws")

MAX_FINDINGS = 8


def _strip_code(html: str) -> str:
    return re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html or "",
                  flags=re.DOTALL | re.IGNORECASE)


# ─── 1. read from the document ───────────────────────────────────────

_HEADING_RE = re.compile(r"<h([1-6])\b", re.IGNORECASE)


def check_headings(html: str) -> List[str]:
    """One h1, and headings that never skip a level going deeper."""
    levels = [int(m.group(1)) for m in _HEADING_RE.finditer(_strip_code(html))]
    problems: List[str] = []
    h1s = levels.count(1)
    if h1s == 0:
        problems.append("HEADINGS: the page has no <h1>. The hero headline is "
                        "the one h1.")
    elif h1s > 1:
        problems.append(f"HEADINGS: the page has {h1s} <h1> elements. Keep one "
                        "(the hero headline) and make the rest h2, so search "
                        "engines and screen readers get one outline.")
    jumps: List[str] = []
    for prev, cur in zip(levels, levels[1:]):
        if cur > prev + 1:
            jump = f"h{prev} to h{cur}"
            if jump not in jumps:
                jumps.append(jump)
    if jumps:
        problems.append("HEADINGS: the outline skips levels ("
                        + ", ".join(jumps[:3]) + "). Step down one level at "
                        "a time; style the size with CSS, not the tag.")
    return problems


_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def check_alt(html: str) -> List[str]:
    missing = 0
    for m in _IMG_RE.finditer(html or ""):
        tag = m.group(0)
        if not re.search(r"\balt\s*=", tag, re.IGNORECASE):
            missing += 1
    if not missing:
        return []
    return [f"ALT TEXT: {missing} image(s) have no alt attribute. Say what each "
            "one shows (alt=\"\" only for pure decoration)."]


_FONT_LINK_RE = re.compile(
    r"<link\b[^>]*href\s*=\s*[\"']([^\"']*fonts\.googleapis\.com[^\"']*)",
    re.IGNORECASE)
_NOT_TYPE = re.compile(r"icon|symbol|emoji", re.IGNORECASE)


def font_families(html: str) -> List[str]:
    fams: List[str] = []
    for m in _FONT_LINK_RE.finditer(html or ""):
        href = m.group(1).replace("&amp;", "&")
        for fam in re.findall(r"family=([^&:]+)", href):
            name = fam.replace("+", " ").strip()
            if name and not _NOT_TYPE.search(name) and name not in fams:
                fams.append(name)
    return fams


def check_families(html: str) -> List[str]:
    fams = font_families(html)
    if len(fams) <= 3:
        return []
    return [f"TYPE FAMILIES: {len(fams)} families load ({', '.join(fams)}). "
            "Keep two, three with a utility face; let weight and size do "
            "the rest."]


# Typos: only where a close real word exists, never for the business's
# own words. ALL-CAPS words are checked (headlines are where a typo
# shouts); a Capitalized word inside a sentence is treated as a name.
_COPY_RE = re.compile(
    r"<(h[1-6]|p|li|blockquote|figcaption|button|a|span|dt|dd|td|th|label)"
    r"(?:\s[^>]*)?>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_WORD_RE = re.compile(r"(?<![\w'’-])([A-Za-z]{5,})(?![\w'’-])")
_SPELL = None
_SPELL_TRIED = False


def _speller():
    global _SPELL, _SPELL_TRIED
    if not _SPELL_TRIED:
        _SPELL_TRIED = True
        try:
            from spellchecker import SpellChecker
            _SPELL = SpellChecker(distance=2)
        except Exception as e:
            logger.info(f"[craft] spelling check unavailable: {e}")
            _SPELL = None
    return _SPELL


def _data_words(real_data: str) -> Set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", real_data or "")}


def check_spelling(html: str, real_data: str = "") -> List[str]:
    sp = _speller()
    if sp is None:
        return []
    known = _data_words(real_data)
    words: List[str] = []
    for m in _COPY_RE.finditer(_strip_code(html)):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"&[a-z#0-9]+;", " ", text)
        for i, w in enumerate(_WORD_RE.findall(text)):
            if w.isupper():
                pass                                   # a shouted word is checked
            elif w[0].isupper() and w[1:].islower():
                continue                               # a name, a brand, a place
            elif not w.islower():
                continue                               # camelCase, product names
            lw = w.lower()
            if lw in known or lw in words:
                continue
            words.append(lw)
    found: List[str] = []
    try:
        for w in sorted(sp.unknown(words)):
            fix = sp.correction(w)
            if fix and fix != w and fix in sp:
                found.append(f"'{w}' ({fix}?)")
            if len(found) >= 6:
                break
    except Exception as e:
        logger.info(f"[craft] spelling pass skipped: {e}")
        return []
    if not found:
        return []
    return ["POSSIBLE TYPOS in the page copy: " + ", ".join(found)
            + ". Fix the spelling; leave any that are deliberate names or "
              "coined words."]


def check_html(html: str, real_data: str = "") -> List[str]:
    """Every document-level craft check, in order of damage."""
    out = (check_headings(html) + check_spelling(html, real_data)
           + check_alt(html) + check_families(html))
    return out[:MAX_FINDINGS]


# ─── 2. the typographer (mechanical, in place) ──────────────────────

_SKIP_TAGS = {"script", "style", "code", "pre", "textarea", "svg", "noscript"}
_TAG_RE = re.compile(r"(<[^>]+>)")
_TAG_NAME_RE = re.compile(r"^<\s*(/)?\s*([a-zA-Z0-9]+)")
_OPENERS = set(" \t\n\r([{\u2014\u2013-/\u00a0")

_YEAR_RANGE = re.compile(r"\b((?:19|20)\d{2})\s?-\s?((?:19|20)\d{2})\b")
_TIME = r"\d{1,2}(?::\d{2})?\s?(?:am|pm|AM|PM|a\.m\.|p\.m\.)"
_TIME_RANGE = re.compile(r"\b(\d{1,2}(?::\d{2})?(?:\s?(?:am|pm|AM|PM))?)\s?-\s?(" + _TIME + r")")
_MONEY_RANGE = re.compile(r"(\$\d[\d,]*(?:\.\d{2})?)\s?-\s?(\$\d[\d,]*(?:\.\d{2})?)")


def _curl(text: str, before: str) -> Tuple[str, int]:
    out: List[str] = []
    n = 0
    prev = before
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == '"':
            ch = "\u201c" if (prev == "" or prev in _OPENERS) else "\u201d"
            n += 1
        elif ch == "'":
            if prev and (prev.isalnum() or prev in ".,!?\u201d"):
                ch = "\u2019"
            elif nxt.isalnum() and (prev == "" or prev in _OPENERS):
                ch = "\u2018"
            else:
                ch = "\u2019"
            n += 1
        out.append(ch)
        prev = ch
    return "".join(out), n


def typographer(html: str) -> Tuple[str, int]:
    """Straight quotes and apostrophes become typographic ones, numeric
    ranges get an en dash, three dots become an ellipsis. Only visible
    text inside <body> is touched: never a tag, an attribute, a script,
    a style or code. Returns (html, changes). Fail-open."""
    try:
        m = re.search(r"<body\b[^>]*>", html or "", re.IGNORECASE)
        if not m:
            return html, 0
        head, body = html[:m.end()], html[m.end():]
        parts = _TAG_RE.split(body)
        skip = 0
        changes = 0
        last_char = ""
        for i, part in enumerate(parts):
            if not part:
                continue
            if part.startswith("<"):
                tm = _TAG_NAME_RE.match(part)
                if tm:
                    name = tm.group(2).lower()
                    if name in _SKIP_TAGS and not part.rstrip().endswith("/>"):
                        skip = max(0, skip - 1) if tm.group(1) else skip + 1
                    if name in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                                "div", "section", "br", "td", "th", "dt", "dd",
                                "figcaption", "blockquote", "button", "header",
                                "footer", "nav", "article", "aside", "main"):
                        last_char = ""                 # a block edge resets context
                continue
            if skip:
                continue
            text = (part.replace("&quot;", '"').replace("&#34;", '"')
                    .replace("&#39;", "'").replace("&apos;", "'"))
            before = text
            text = _YEAR_RANGE.sub("\\1\u2013\\2", text)
            text = _TIME_RANGE.sub("\\1\u2013\\2", text)
            text = _MONEY_RANGE.sub("\\1\u2013\\2", text)
            text = re.sub(r"(?<!\.)\.\.\.(?!\.)", "\u2026", text)
            changes += sum(1 for a, b in zip(before, text) if a != b) \
                + abs(len(before) - len(text))
            text, n = _curl(text, last_char)
            changes += n
            if text != part:
                parts[i] = text
            last_char = text[-1] if text else last_char
        return head + "".join(parts), changes
    except Exception as e:
        logger.warning(f"[craft] typographer skipped: {e}")
        return html, 0


# ─── 3. read from the render ─────────────────────────────────────────

RENDER_JS = r"""
() => {
  const vh = window.innerHeight, vw = window.innerWidth;
  const out = { width: vw, small_text: [], tiny_text: [], centered_long: [],
                control_font: null, h1: null };
  const label = el => el.tagName.toLowerCase()
    + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : '')
    + ' "' + (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
  const visible = el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const skip = el => el.closest('[aria-hidden="true"],.sx-drop,noscript,svg,[data-craft-ok]');
  const own = el => Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const sel = 'p,li,blockquote,dd,dt,td,th,figcaption,label,a,span,small,em,strong,b,i,h1,h2,h3,h4,h5,h6,button,div,cite,time';
  for (const el of document.body.querySelectorAll(sel)) {
    if (skip(el) || !visible(el)) continue;
    const t = own(el);
    if (t.length < 2) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (t.length >= 40 && fs < 14 && vw <= 480) {
      if (out.small_text.length < 6) out.small_text.push({ label: label(el), px: fs });
    } else if (fs < 11) {
      if (out.tiny_text.length < 6) out.tiny_text.push({ label: label(el), px: fs });
    }
  }
  for (const el of document.body.querySelectorAll('p,blockquote,li')) {
    if (skip(el) || !visible(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.textAlign !== 'center') continue;
    let lh = parseFloat(cs.lineHeight);
    if (isNaN(lh)) lh = parseFloat(cs.fontSize) * 1.2;
    const lines = Math.round(el.getBoundingClientRect().height / lh);
    if (lines > 3 && out.centered_long.length < 4) out.centered_long.push({ label: label(el), lines });
  }
  const fam = el => (getComputedStyle(el).fontFamily || '').split(',')[0].replace(/["']/g, '').trim().toLowerCase();
  const pageFams = new Set([fam(document.body)]);
  for (const el of Array.from(document.querySelectorAll('h1,h2,h3,p,a,li')).slice(0, 60)) pageFams.add(fam(el));
  const ctl = Array.from(document.querySelectorAll('button,input[type=submit],input[type=text],input[type=email],textarea,select')).find(visible);
  if (ctl && !pageFams.has(fam(ctl))) out.control_font = { control: label(ctl), family: fam(ctl) };
  const h1 = document.querySelector('h1');
  if (h1) {
    const r = h1.getBoundingClientRect();
    out.h1 = { visible: visible(h1), top: Math.round(r.top + window.scrollY), vh: vh };
  }
  return out;
}
"""


def render_findings(measures: Optional[Dict[str, Any]]) -> List[str]:
    """The craft keys of the eyes' measurements, in the builder's words."""
    out: List[str] = []
    control_said = False
    for width, m in sorted((measures or {}).items(), key=lambda kv: int(kv[0])):
        if not isinstance(m, dict):
            continue
        small = m.get("small_text") or []
        if small:
            ex = "; ".join(f"{s.get('label')} at {s.get('px')}px" for s in small[:3])
            out.append(f"at {width}px running text is under 14px ({ex}). Body "
                       "copy on a phone is 16px, never under 14px.")
        tiny = m.get("tiny_text") or []
        if tiny:
            ex = "; ".join(f"{s.get('label')} at {s.get('px')}px" for s in tiny[:3])
            out.append(f"at {width}px text renders under 11px ({ex}). Nothing a "
                       "visitor should read is smaller than 11px.")
        cent = m.get("centered_long") or []
        if cent:
            ex = "; ".join(f"{c.get('label')} ({c.get('lines')} lines)" for c in cent[:2])
            out.append(f"at {width}px long paragraphs are centered ({ex}). Center "
                       "three lines at most; set longer copy flush left.")
        ctl = m.get("control_font")
        if ctl and not control_said:
            control_said = True
            out.append(f"form controls fall back to the system font "
                       f"({ctl.get('control')} renders in {ctl.get('family')}). "
                       "Give buttons and inputs font: inherit.")
        h1 = m.get("h1")
        if int(width) <= 480 and isinstance(h1, dict):
            if not h1.get("visible"):
                out.append(f"at {width}px the h1 headline is not visible on "
                           "load. The headline must read on a phone.")
            elif h1.get("vh") and h1.get("top", 0) > 1.5 * h1["vh"]:
                out.append(f"at {width}px the h1 headline starts {h1.get('top')}px "
                           "down, past the first screen and a half. Bring it "
                           "into the first screen on a phone.")
    return out[:6]
