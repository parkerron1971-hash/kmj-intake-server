"""site_adopt.py — a hand-built site becomes the system's own.

Kevin (2026-09-05): "we had built my website and connected the website
inside the system but Chief and the system doesn't know anything about
the website at all. is it a way to wire this in as though Chief and the
system built this?"

A site under sites/<dir>/ is installed by site_sync as
site_config.html_source == "manual". It serves, its text edits work, the
visual check looks at it — but everything that TALKS about the site was
still reading the composed page it replaced: Chief's site block said an
address and a status, site_health reported the old build's quality gate,
the Blueprint on file described the old design, and a "rebuild my site"
would have composed over the pages (and been reinstalled on the next
deploy). This module is the missing half:

  * page_text()           the words on each page, tokens and markup gone
  * adopt()               ONE model call writes the design record (the
                          Blueprint) FROM the live pages, in the same
                          anatomy the Director writes before a build, and
                          stamps site_config.adopted so it happens once
                          per change of the words (a CSS-only deploy costs
                          nothing)
  * schedule()            site_sync's hook: a daemon thread, fail-soft
  * describe_for_chief()  the lines Chief's PRACTITIONER SITE block gains
  * health_lines()        what site_health says instead of the stale gates
  * hand_built_block()    the sentence that refuses a builder job

Fail-soft everywhere: no key, no row, no browser — it says so and never
raises into a boot or a chat turn. SITE_ADOPT=off disables the automatic
pass (the verb-free kind: nothing here is reachable from a prompt).
"""
from __future__ import annotations

import hashlib
import html as _html
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("site_adopt")

EDITION = "hand-built"
PAGE_TEXT_CAP = 6000          # characters of copy per page that ride the call
ADOPT_MAX_CHARS = 60000

_TOKEN_RE = re.compile(r"\{\{[A-Z_]+\}\}")
_DROP_RE = re.compile(r"<(script|style|noscript|svg|template)\b.*?</\1\s*>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_BLOCK_END_RE = re.compile(
    r"</(p|h[1-6]|li|div|section|article|header|footer|nav|blockquote|"
    r"figcaption|dt|dd|tr|th|td|summary|label|a|button)\s*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
_GFONT_RE = re.compile(r"family=([A-Za-z+ ]+?)(?:[:&\"']|$)")


def enabled() -> bool:
    return (os.environ.get("SITE_ADOPT") or "on").strip().lower() not in ("off", "0", "false", "no")


def is_hand_built(site_config: Any) -> bool:
    return isinstance(site_config, dict) and site_config.get("html_source") == "manual"


# ─── the words on the page ────────────────────────────────────────────

def page_text(html: str, cap: int = PAGE_TEXT_CAP) -> str:
    """The copy a visitor reads, one line per block, tokens and markup
    gone. Deterministic and cheap: this is what the model sees, and what
    decides whether the record needs rewriting."""
    if not html:
        return ""
    s = _COMMENT_RE.sub(" ", str(html))
    s = _DROP_RE.sub(" ", s)
    s = _TOKEN_RE.sub(" ", s)
    s = _BLOCK_END_RE.sub("\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _TAG_RE.sub(" ", s)
    s = _html.unescape(s)
    lines: List[str] = []
    for raw in s.split("\n"):
        line = " ".join(raw.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    out = "\n".join(lines)
    return out[:cap]


def pages_of(row: Dict[str, Any]) -> Dict[str, str]:
    """{page_id: html} in site order — home first, then the secondary
    pages the row actually carries."""
    cfg = row.get("site_config") if isinstance(row.get("site_config"), dict) else {}
    pages: Dict[str, str] = {}
    home = row.get("html_content") or ""
    if home:
        pages["home"] = home
    gp = cfg.get("generated_pages") if isinstance(cfg.get("generated_pages"), dict) else {}
    order = [p for p in (cfg.get("site_pages") or []) if isinstance(p, str)]
    for pid in order + sorted(k for k in gp if k not in order):
        if pid == "home":
            continue
        html = gp.get(pid)
        if isinstance(html, str) and html.strip():
            pages[pid] = html
    return pages


def style_facts(pages: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """(fonts, hexes) actually present in the pages' markup — the record
    names the palette and type the site USES, never an imagined one."""
    fonts: List[str] = []
    hexes: Counter = Counter()
    for html in pages.values():
        for m in _GFONT_RE.finditer(html or ""):
            name = m.group(1).replace("+", " ").strip()
            if name and name not in fonts:
                fonts.append(name)
        for m in _FONT_RE.finditer(html or ""):
            first = m.group(1).split(",")[0].strip().strip("'\"")
            if first and first.lower() not in ("inherit", "system-ui", "sans-serif", "serif",
                                              "monospace", "var(--font-display)",
                                              "var(--font-body)") \
                    and not first.startswith("var(") and first not in fonts:
                fonts.append(first)
        for m in _HEX_RE.finditer(html or ""):
            hexes[m.group(0).lower()] += 1
    return fonts[:8], [h for h, _ in hexes.most_common(12)]


def text_digest(pages: Dict[str, str]) -> str:
    h = hashlib.sha256()
    for pid in sorted(pages):
        h.update(pid.encode())
        h.update(b"\0")
        h.update(page_text(pages[pid]).encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def is_current(site_config: Any, pages: Optional[Dict[str, str]] = None) -> bool:
    """True when the record on file was written from these exact words."""
    if not is_hand_built(site_config):
        return False
    adopted = site_config.get("adopted") if isinstance(site_config.get("adopted"), dict) else None
    if not adopted or not adopted.get("text_hash"):
        return False
    if pages is None:
        # Without the pages we can only compare the install hash — a
        # CSS-only deploy will look stale here and be found current by
        # adopt() itself once it has the words.
        return adopted.get("hash") == site_config.get("manual_hash")
    return adopted.get("text_hash") == text_digest(pages)


# ─── the record ───────────────────────────────────────────────────────

_SYSTEM = """You are the DIRECTOR of the Solutionist System, writing the design record of a website that already exists. The pages were built by hand by the system's own craftsmen; your document is the specification they would have executed to produce EXACTLY these pages. Write it as if you had authored it before the build: decided, complete, in the past tense of a decision already made ("The hero carries...", "The palette is...").

You are given the copy of every page, in order, and the fonts and colors present in the markup. Nothing else exists. THE TRUTH LAW is absolute: every headline, sentence, price, name, number and link in your document comes from the pages verbatim; the fonts and hexes you name come from the STYLE FACTS block. You do not improve the copy, propose alternatives, or invent sections, imagery, stats or doors the pages do not carry. Where the pages are silent (an interaction you cannot see in copy), say "not recorded" rather than guessing.

STRUCTURE — plain text with section rules (=====) and numbered sections, the same anatomy every design record in this system uses:
1. OVERVIEW — what this site is, one paragraph; the page's single memorable move if the copy makes one plain, else the site's voice in one sentence.
2. BRAND IDENTITY — the fonts by role (display / body / accent, from STYLE FACTS) and the palette as CSS-variable-style roles with the hexes present, most used first. Begin this section with 2-4 lines starting "OBSERVED ON THE SITE:" describing the voice and density the copy shows.
3. LAYOUT & SECTIONS (top to bottom), page by page — every page a heading ("PAGE /about"), every section numbered with its REAL copy written out verbatim: headlines, eyebrows, body, buttons, captions.
4. INTERACTIONS & ANIMATIONS — only what the copy states (form confirmations, button labels); otherwise "not recorded".
5. DESIGN RULES (do / don't) — the taste laws these pages evidently keep: what the copy never does, what recurs.

THE COPY GRAMMAR: never splice a sentence with a dash in prose you author; quoted site copy stays exactly as written.

OUTPUT: the document only. No preamble, no commentary, no code."""


def build_user_prompt(business: Dict[str, Any], row: Dict[str, Any],
                      pages: Dict[str, str]) -> str:
    cfg = row.get("site_config") if isinstance(row.get("site_config"), dict) else {}
    name = str(business.get("name") or "the business")
    slug = str(row.get("slug") or "")
    custom = str(cfg.get("custom_domain") or "").strip().lower()
    address = f"https://{custom}" if custom else (f"https://{slug}.mysolutionist.app" if slug else "")
    fonts, hexes = style_facts(pages)
    parts = [f"BUSINESS: {name}",
             f"LIVE ADDRESS: {address or 'not recorded'}",
             f"INSTALLED: {str(cfg.get('manual_installed_at') or '')[:10] or 'not recorded'}",
             f"PAGES: {', '.join('/' if p == 'home' else '/' + p for p in pages)}",
             "",
             "STYLE FACTS (present in the markup):",
             f"  fonts: {', '.join(fonts) if fonts else 'not recorded'}",
             f"  colors: {', '.join(hexes) if hexes else 'not recorded'}",
             ""]
    for pid, html in pages.items():
        parts.append(f"===== PAGE {'/' if pid == 'home' else '/' + pid} =====")
        parts.append(page_text(html) or "(no copy)")
        parts.append("")
    return "\n".join(parts)


def _read_row(business_id: str) -> Optional[Dict[str, Any]]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,business_id,slug,html_content,site_config&limit=1") or []
    return rows[0] if rows else None


def _read_business(business_id: str) -> Dict[str, Any]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1") or []
    return rows[0] if rows else {"id": business_id}


def adopt(business_id: str, *, row: Optional[Dict[str, Any]] = None,
          force: bool = False) -> Dict[str, Any]:
    """Write the design record for a hand-built site from its live pages.
    Returns {ok, status: current|adopted, ...} or {ok: False, error}.
    Never raises."""
    try:
        row = row or _read_row(business_id)
        if not row:
            return {"ok": False, "error": "no_site"}
        cfg = dict(row.get("site_config") or {}) if isinstance(row.get("site_config"), dict) else {}
        if not is_hand_built(cfg):
            return {"ok": False, "error": "not_hand_built"}
        pages = pages_of(row)
        if not pages:
            return {"ok": False, "error": "no_pages"}
        digest = text_digest(pages)
        if not force and is_current(cfg, pages):
            return {"ok": True, "status": "current", "text_hash": digest}

        business = _read_business(business_id)
        import spec_author
        user = build_user_prompt(business, row, pages)
        text = (spec_author._call_llm(_SYSTEM, user, business_id) or "").strip()
        if not text:
            return {"ok": False, "error": "author_unavailable"}
        text = text[:ADOPT_MAX_CHARS]

        # Persist against a FRESH read: the words above took a while and
        # a site_check may have landed on the row in the meantime.
        fresh = _read_row(business_id) or row
        cfg = dict(fresh.get("site_config") or {}) if isinstance(fresh.get("site_config"), dict) else cfg
        prior = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else {}
        now = datetime.now(timezone.utc).isoformat()
        revision = int(prior.get("revision") or 0) + 1
        model = ""
        try:
            model = spec_author._model()
        except Exception:
            pass
        cfg["design_spec"] = {
            "text": text, "status": "approved", "authored_at": now,
            "model": model, "revision": revision,
            "source": "adopted", "edition": EDITION,
        }
        cfg["adopted"] = {
            "at": now, "edition": EDITION,
            "hash": cfg.get("manual_hash"), "text_hash": digest,
            "pages": list(pages.keys()), "spec_revision": revision, "model": model,
        }
        # The path's "Built <date>" reads this; the truthful date is the
        # install, not the moment the record was written.
        cfg["html_generated_at"] = cfg.get("manual_installed_at") or cfg.get("html_generated_at") or now
        try:
            spec_author._patch_site_config(str(fresh.get("id")), cfg, f"adopt rev {revision}")
        except Exception as e:
            logger.warning(f"[site-adopt] {business_id[:8]}: record written but not saved: {e}")
            return {"ok": False, "error": "save_failed"}
        logger.info(f"[site-adopt] {business_id[:8]}: design record rev {revision} "
                    f"written from {len(pages)} live pages ({len(text)} chars)")
        return {"ok": True, "status": "adopted", "revision": revision,
                "pages": list(pages.keys()), "text_hash": digest}
    except Exception as e:
        logger.warning(f"[site-adopt] {str(business_id)[:8]}: failed (non-fatal): {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def schedule(business_id: str, site_config: Any = None, delay: float = 5.0) -> bool:
    """site_sync's hook. True when a pass was queued. A site whose record
    is current by install hash is skipped without a thread."""
    if not enabled():
        return False
    if site_config is not None and is_current(site_config):
        return False
    try:
        t = threading.Timer(delay, lambda: adopt(business_id))
        t.daemon = True
        t.name = f"site-adopt-{str(business_id)[:8]}"
        t.start()
        return True
    except Exception as e:  # pragma: no cover
        logger.info(f"[site-adopt] not scheduled: {e}")
        return False


# ─── what the rest of the system says about it ────────────────────────

def _date(s: Any) -> str:
    return str(s or "")[:10]


def describe_for_chief(site: Dict[str, Any]) -> List[str]:
    """Lines for Chief's PRACTITIONER SITE block. [] when the site is
    not hand-built (the caller keeps its usual lines)."""
    cfg = site.get("site_config") if isinstance(site.get("site_config"), dict) else {}
    if not is_hand_built(cfg):
        return []
    lines: List[str] = []
    installed = _date(cfg.get("manual_installed_at"))
    lines.append(f"  Built by: the Solutionist System, {EDITION} edition"
                 + (f" (installed {installed})" if installed else "")
                 + " — the pages are kept as code in the system; no builder job touches them")
    pages = [p for p in (cfg.get("site_pages") or []) if isinstance(p, str)] or ["home"]
    lines.append("  Pages: " + ", ".join(pages))
    adopted = cfg.get("adopted") if isinstance(cfg.get("adopted"), dict) else None
    spec = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else {}
    if adopted and spec.get("source") == "adopted":
        lines.append(f"  Design record: Blueprint rev {spec.get('revision')} on file, written from "
                     f"the live pages (adopted {_date(adopted.get('at'))})")
    else:
        lines.append("  Design record: not written yet — it is authored automatically after the next deploy")
    lines.append("  Changing it: copy edits go live at once through edit_site_text; NEVER offer "
                 "rebuild_site or a refine — a compose would be overwritten by the next deploy. "
                 "For a design change, say it goes into the site's code")
    last = cfg.get("last_site_check") if isinstance(cfg.get("last_site_check"), dict) else None
    if last:
        try:
            import site_check
            looked = site_check.describe(last, limit=3)
        except Exception:
            looked = ""
        if looked:
            lines.append("  " + looked.replace("\n", "\n  "))
    return lines


def health_lines(site_config: Any) -> Tuple[List[str], List[str]]:
    """(healthy, issues) for site_health on a hand-built site — replaces
    the composer-only gates, which describe the page this one replaced."""
    cfg = site_config if isinstance(site_config, dict) else {}
    healthy: List[str] = []
    issues: List[str] = []
    installed = _date(cfg.get("manual_installed_at"))
    healthy.append(f"{EDITION} edition" + (f" installed {installed}" if installed else "")
                   + "; copy edits go live through edit_site_text")
    adopted = cfg.get("adopted") if isinstance(cfg.get("adopted"), dict) else None
    spec = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else {}
    if adopted and spec.get("source") == "adopted":
        healthy.append(f"design record on file (Blueprint rev {spec.get('revision')}, "
                       f"from the live pages)")
    else:
        issues.append("design record not written yet — fix: it is authored automatically "
                      "after the next deploy; nothing to do")
    return healthy, issues


def hand_built_block(site_config: Any) -> Optional[str]:
    """The sentence that refuses a builder job on a hand-built site, or
    None when the job may run."""
    if not is_hand_built(site_config):
        return None
    return ("this site is the hand-built edition: its pages are kept as code in the "
            "system, and a builder job would be overwritten by the next deploy. Copy "
            "changes go live through a text edit; a design change goes into the site's code")


def hand_built_block_for(business_id: str) -> Optional[str]:
    """Same, from a fresh read. Sync; call in a thread. None on any failure
    (a read problem must never block a build for everyone else)."""
    try:
        row = _read_row(business_id)
        return hand_built_block((row or {}).get("site_config"))
    except Exception:
        return None
