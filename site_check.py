"""site_check.py — the system looks at the live site the way a person does.

Kevin's ask (2026-09-04): "you know how you check the website to make
sure everything was good — can the system do that?" The builder already
had a vision grader, but it only ever looked at a page it had just
composed, as a ship gate. This looks at the LIVE site, on demand or
after a deploy, and says in plain words what is off.

Two layers, cheapest first:

  1. Geometry (free). Headless Chromium loads each public page at a
     phone width and a desktop width, lets the animations settle, and
     measures: content wider than the screen, images that failed to
     load, headings with no text, leftover {{tokens}}, and pairs of
     visible elements that overlap each other (the class of thing a
     misplaced photo or a card sliding under a headline produces).
     Intentional layering opts out with data-overlap-ok.
  2. Vision (a few cents). One call per page with the phone + desktop
     screenshots and an alignment-first rubric, returning findings the
     way a designer would phrase them. Skipped when vision=False (the
     post-edit check) or VISION_GRADER=off.

The report is written to site_config.last_site_check on the business's
site row, the screenshots go to the private hand bucket under the
business, and a site_check_completed event lands on the spine. Chief
reads the report through site_health. Fail-soft throughout: a check
that cannot run says so; it never touches the site.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("site_check")

WIDTHS: Tuple[int, ...] = (390, 1440)
PAGE_PATHS: Tuple[str, ...] = ("/", "/about", "/services", "/contact")
PLATFORM_DOMAIN = "mysolutionist.app"
MAX_FINDINGS = 12

# Elements worth measuring against each other. Layout wrappers are left
# out on purpose: a section legitimately contains its children, and the
# audit only compares elements that are not ancestor/descendant.
_AUDIT_JS = r"""
() => {
  const vw = window.innerWidth;
  const doc = document.documentElement;
  const out = { overflow_x: doc.scrollWidth > vw + 2, scroll_width: doc.scrollWidth,
                broken_images: [], empty_headings: 0, leftover_tokens: [], overlaps: [] };
  for (const img of document.images) {
    if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) {
      out.broken_images.push((img.getAttribute('src') || '').slice(0, 120));
    }
  }
  for (const h of document.querySelectorAll('h1,h2,h3')) {
    if (!h.textContent.trim()) out.empty_headings += 1;
  }
  const m = (document.body.innerText || '').match(/\{\{[A-Z_]+\}\}/g);
  if (m) out.leftover_tokens = Array.from(new Set(m)).slice(0, 6);
  const sel = 'h1,h2,h3,p,li,img,blockquote,a.btn,button,figure,.card,.nameplate,.win,.art,form,input,textarea';
  const els = Array.from(document.querySelectorAll(sel)).filter(el => {
    if (el.closest('[data-overlap-ok]')) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return false;
    const r = el.getBoundingClientRect();
    return r.width > 24 && r.height > 12;
  });
  const rects = els.map(el => { const r = el.getBoundingClientRect(); return {el, l: r.left, t: r.top + window.scrollY, r: r.right, b: r.bottom + window.scrollY}; });
  const label = el => (el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : '')) + ' "' + (el.textContent || el.getAttribute('alt') || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
      const h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      if (w <= 4 || h <= 4) continue;
      const inter = w * h;
      const small = Math.min((a.r - a.l) * (a.b - a.t), (b.r - b.l) * (b.b - b.t));
      if (small > 0 && inter / small > 0.35) {
        out.overlaps.push({ a: label(a.el), b: label(b.el), y: Math.round(Math.max(a.t, b.t)) });
        if (out.overlaps.length >= 12) return out;
      }
    }
  }
  return out;
}
"""

_SETTLE_CSS = ("*,*::before,*::after{animation-delay:0s !important;"
               "animation-duration:0.01s !important;transition-duration:0.01s !important;"
               "transition-delay:0s !important;}")

_VISION_RUBRIC = """You are reviewing screenshots of a live business website, one page at a
time, at a phone width and a desktop width. You are the second pair of
eyes before the owner shows it to clients. Look ONLY for things that are
actually wrong on the screen, in this order of importance:

1. Alignment: an element that sits visibly higher or lower than the thing
   it belongs beside; a photo or card that hangs below its section; text
   whose left edge does not line up with its neighbours in the same block.
2. Overlap and crowding: anything covering something else, text touching
   an edge, elements colliding.
3. Broken or empty: missing images, blank areas where content should be,
   a heading with nothing under it, placeholder text like {{TOKEN}}.
4. Tilted or off-axis imagery that reads as a mistake rather than a style.
5. Text that is cut off, wraps into a single orphaned word, or is unreadable
   against its background.

Do not comment on taste, copy, colour choices, or what you would design
differently. Do not invent problems to fill the list; an empty list is a
good answer. Return JSON only:
{"findings":[{"severity":"high|medium|low","width":390|1440,
  "what":"one sentence a business owner understands",
  "where":"section or element, briefly"}],
 "summary":"one sentence"}"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled() -> bool:
    return (os.environ.get("SITE_CHECK") or "on").strip().lower() not in ("off", "0", "false", "no")


def _vision_enabled() -> bool:
    return (os.environ.get("VISION_GRADER") or "on").strip().lower() not in ("off", "0", "false")


# ─── what to look at ──────────────────────────────────────────────────

def site_pages(business_id: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """The site row and the public URLs to check (home always; a
    secondary page only when the site actually has it)."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,slug,site_config,html_content&order=updated_at.desc&limit=1") or []
    if not rows or not rows[0].get("html_content"):
        return (rows[0] if rows else None), []
    row = rows[0]
    cfg = row.get("site_config") if isinstance(row.get("site_config"), dict) else {}
    custom = str(cfg.get("custom_domain") or "").strip().lower()
    origin = f"https://{custom}" if custom else f"https://{row.get('slug')}.{PLATFORM_DOMAIN}"
    pages = cfg.get("generated_pages") if isinstance(cfg.get("generated_pages"), dict) else {}
    urls = [origin + "/"]
    for p in PAGE_PATHS[1:]:
        if str(pages.get(p.strip("/")) or "").strip():
            urls.append(origin + p)
    return row, urls


# ─── layer 1: geometry ────────────────────────────────────────────────

def inspect_pages(urls: List[str], widths: Tuple[int, ...] = WIDTHS,
                  screenshots: bool = True) -> Optional[List[Dict[str, Any]]]:
    """Load every url at every width in headless Chromium and measure it.
    Returns per-page results, or None when no browser is available."""
    try:
        from playwright.sync_api import sync_playwright  # lazy — optional dep
    except Exception:
        logger.info("[site-check] playwright not installed — check skipped")
        return None
    results: List[Dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for url in urls:
                    entry: Dict[str, Any] = {"url": url, "widths": {}, "shots": {},
                                             "console_errors": [], "failed_requests": []}
                    for width in widths:
                        page = browser.new_page(viewport={"width": width, "height": 900})
                        page.on("console", lambda msg, e=entry: (
                            e["console_errors"].append(str(msg.text)[:160])
                            if msg.type == "error" and len(e["console_errors"]) < 8 else None))
                        page.on("response", lambda resp, e=entry: (
                            e["failed_requests"].append(f"{resp.status} {resp.url[:120]}")
                            if resp.status >= 400 and len(e["failed_requests"]) < 8 else None))
                        try:
                            page.goto(url, wait_until="networkidle", timeout=30000)
                        except Exception as ex:
                            entry["widths"][str(width)] = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
                            page.close()
                            continue
                        try:
                            page.add_style_tag(content=_SETTLE_CSS)
                            # let scroll-reveal and lazy images settle
                            page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight); }")
                            page.wait_for_timeout(500)
                            page.evaluate("() => { window.scrollTo(0, 0); }")
                            page.wait_for_timeout(300)
                        except Exception:
                            pass
                        try:
                            audit = page.evaluate(_AUDIT_JS)
                        except Exception as ex:
                            audit = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
                        entry["widths"][str(width)] = audit
                        if screenshots:
                            try:
                                entry["shots"][str(width)] = page.screenshot(
                                    type="jpeg", quality=55, full_page=True)
                            except Exception as ex:
                                logger.info(f"[site-check] screenshot failed {url}@{width}: {ex}")
                        page.close()
                    results.append(entry)
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[site-check] browser pass failed: {type(e).__name__}: {e}")
        return None
    return results


def findings_from_geometry(page: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn one page's measurements into plain-language findings."""
    out: List[Dict[str, Any]] = []
    path = _path_of(page.get("url", ""))
    for width, audit in (page.get("widths") or {}).items():
        w = int(width)
        where = f"{path} at {w}px"
        if audit.get("error"):
            out.append({"severity": "high", "width": w, "source": "geometry",
                        "what": "The page did not load for the check.", "where": where,
                        "detail": audit["error"]})
            continue
        if audit.get("overflow_x"):
            out.append({"severity": "high", "width": w, "source": "geometry",
                        "what": "Something is wider than the screen, so the page scrolls sideways.",
                        "where": where, "detail": f"content {audit.get('scroll_width')}px wide"})
        for src in audit.get("broken_images") or []:
            out.append({"severity": "high", "width": w, "source": "geometry",
                        "what": "An image did not load.", "where": where, "detail": src})
        if audit.get("empty_headings"):
            out.append({"severity": "medium", "width": w, "source": "geometry",
                        "what": "A heading has no text in it.", "where": where})
        for tok in audit.get("leftover_tokens") or []:
            out.append({"severity": "high", "width": w, "source": "geometry",
                        "what": "Placeholder text is showing instead of real content.",
                        "where": where, "detail": tok})
        for ov in audit.get("overlaps") or []:
            out.append({"severity": "medium", "width": w, "source": "geometry",
                        "what": "Two things are sitting on top of each other.",
                        "where": where, "detail": f"{ov.get('a')} over {ov.get('b')}"})
    for req in page.get("failed_requests") or []:
        out.append({"severity": "medium", "width": 0, "source": "geometry",
                    "what": "Something the page asked for came back missing.",
                    "where": path, "detail": req})
    return out


def _path_of(url: str) -> str:
    m = re.match(r"https?://[^/]+(/.*)?$", url or "")
    p = (m.group(1) if m else "") or "/"
    return p


# ─── layer 2: vision ──────────────────────────────────────────────────

def vision_findings(page: Dict[str, Any], business_id: str) -> List[Dict[str, Any]]:
    """One vision call for one page (phone + desktop shots). [] on any
    failure; the geometry findings stand on their own."""
    shots = page.get("shots") or {}
    if not shots or not _vision_enabled():
        return []
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []
    try:
        import llm_call
        content: List[Dict[str, Any]] = [{"type": "text", "text": f"Page: {_path_of(page.get('url', ''))}"}]
        for width, jpeg in shots.items():
            content.append({"type": "text", "text": f"Width {width}px:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg).decode()}})
        content.append({"type": "text", "text": "Review per the rubric. JSON only."})
        client = llm_call.sdk_client(key=key)
        msg = client.messages.create(
            model=(os.environ.get("VISION_JUDGE_MODEL") or "claude-sonnet-4-5-20250929").strip(),
            max_tokens=900, system=_VISION_RUBRIC,
            messages=[{"role": "user", "content": content}], timeout=90.0)
        try:
            from vision_grader import _meter
            _meter(business_id, getattr(msg, "model", "") or "",
                   getattr(getattr(msg, "usage", None), "input_tokens", 0) or 0,
                   getattr(getattr(msg, "usage", None), "output_tokens", 0) or 0)
        except Exception:
            pass
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return parse_vision(text, _path_of(page.get("url", "")))
    except Exception as e:
        logger.warning(f"[site-check] vision skipped for {page.get('url')}: {type(e).__name__}: {e}")
        return []


def parse_vision(text: str, path: str) -> List[Dict[str, Any]]:
    """The judge's JSON → findings. Tolerates prose around the JSON and
    drops anything not shaped like a finding."""
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for f in (data.get("findings") or []):
        if not isinstance(f, dict) or not str(f.get("what") or "").strip():
            continue
        sev = str(f.get("severity") or "medium").lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        try:
            width = int(f.get("width") or 0)
        except Exception:
            width = 0
        out.append({"severity": sev, "width": width, "source": "vision",
                    "what": str(f["what"]).strip()[:200],
                    "where": (f"{path}: " + str(f.get("where") or "").strip()[:80]).rstrip(": ")})
    return out


# ─── the run ──────────────────────────────────────────────────────────

def _store_shots(business_id: str, run_id: str, pages: List[Dict[str, Any]]) -> List[str]:
    paths: List[str] = []
    try:
        import browser_hand
    except Exception:
        return paths
    n = 0
    for page in pages:
        for width, jpeg in (page.get("shots") or {}).items():
            p = browser_hand._store_frame(business_id, f"check-{run_id}", n, jpeg)
            if p:
                paths.append(p)
                page.setdefault("shot_paths", {})[width] = p
            n += 1
    return paths


def _persist(row: Optional[Dict[str, Any]], report: Dict[str, Any]) -> None:
    if not row or not row.get("id"):
        return
    try:
        import sb_clients
        cfg = dict(row.get("site_config") or {}) if isinstance(row.get("site_config"), dict) else {}
        cfg["last_site_check"] = report
        sb_clients.sb_patch_as_service(f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    except Exception as e:
        logger.warning(f"[site-check] report not saved: {e}")


def _rank(f: Dict[str, Any]) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(f.get("severity"), 3)


def run(business_id: str, *, reason: str = "manual", vision: bool = True,
        progress_cb=None) -> Dict[str, Any]:
    """Check the business's live site. Returns the report (also saved on
    the site row). Never raises."""
    started = time.time()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    report: Dict[str, Any] = {"ok": False, "reason": reason, "checked_at": _now(),
                              "pages": [], "findings": [], "summary": "", "screenshots": []}
    try:
        if not enabled():
            report["summary"] = "Site checks are switched off."
            report["error"] = "disabled"
            return report
        row, urls = site_pages(business_id)
        if not urls:
            report["summary"] = "There is no published site to check yet."
            report["error"] = "no_site"
            _persist(row, report)
            return report
        if progress_cb:
            progress_cb(10, "opening the site")
        pages = inspect_pages(urls, screenshots=True)
        if pages is None:
            report["summary"] = "The check could not open a browser on the server."
            report["error"] = "no_browser"
            _persist(row, report)
            return report
        findings: List[Dict[str, Any]] = []
        for i, page in enumerate(pages):
            findings.extend(findings_from_geometry(page))
            if progress_cb:
                progress_cb(20 + int(60 * (i + 1) / max(1, len(pages))), f"measuring {_path_of(page['url'])}")
        if vision:
            for page in pages:
                findings.extend(vision_findings(page, business_id))
        if progress_cb:
            progress_cb(90, "filing the report")
        report["screenshots"] = _store_shots(business_id, run_id, pages)
        findings.sort(key=_rank)
        seen = set()
        deduped = []
        for f in findings:
            k = (f.get("what"), f.get("where"))
            if k in seen:
                continue
            seen.add(k)
            deduped.append(f)
        report["findings"] = deduped[:MAX_FINDINGS]
        report["pages"] = [{"url": p["url"], "shot_paths": p.get("shot_paths") or {},
                            "console_errors": p.get("console_errors") or []} for p in pages]
        report["vision"] = bool(vision and _vision_enabled())
        high = sum(1 for f in report["findings"] if f["severity"] == "high")
        n = len(report["findings"])
        report["summary"] = ("All clear — nothing out of place on "
                             f"{len(pages)} page{'s' if len(pages) != 1 else ''}."
                             if n == 0 else
                             f"{n} thing{'s' if n != 1 else ''} to look at"
                             + (f", {high} that matter{'s' if high == 1 else ''}" if high else "")
                             + f", across {len(pages)} page{'s' if len(pages) != 1 else ''}.")
        report["ok"] = True
        report["seconds"] = round(time.time() - started, 1)
        _persist(row, report)
        try:
            import event_spine
            event_spine.emit("site_check_completed", business_id, data={
                "reason": reason, "findings": n, "high": high,
                "pages": len(pages), "summary": report["summary"]}, source="site_check")
        except Exception:
            pass
        logger.info(f"[site-check] {business_id[:8]} ({reason}): {report['summary']}")
        return report
    except Exception as e:
        logger.warning(f"[site-check] failed (non-fatal): {type(e).__name__}: {e}")
        report["summary"] = "The check hit a problem and stopped."
        report["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return report


def run_in_background(business_id: str, *, reason: str, vision: bool = True) -> None:
    """Fire-and-forget (deploy, post-edit). Never blocks the caller."""
    if not enabled():
        return
    threading.Thread(target=lambda: run(business_id, reason=reason, vision=vision),
                     name=f"site-check-{business_id[:8]}", daemon=True).start()


def describe(report: Optional[Dict[str, Any]], limit: int = 5) -> str:
    """One paragraph Chief can say about the last check."""
    if not report:
        return "No site check has run yet."
    when = str(report.get("checked_at") or "")[:16].replace("T", " ")
    head = f"Last site check ({when}): {report.get('summary') or 'no summary'}"
    lines = []
    for f in (report.get("findings") or [])[:limit]:
        lines.append(f"• {f.get('what')} ({f.get('where')})")
    return head + ("\n" + "\n".join(lines) if lines else "")
