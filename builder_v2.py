# builder_v2.py
# ─────────────────────────────────────────────────────────────────────
# REVAMP PHASE 2 — BUILDER V2 (docs/REVAMP_TARGET.md Layer 4, signed).
#
# ONE mind, ONE call, the whole page — the claude.ai/Emergent mechanism
# proven in the local renders — executing the APPROVED SPEC as law.
# The contract armor runs AFTER authorship, never fighting it:
#
#   MECHANICAL (deterministic, zero model calls — Amendment 1):
#     - THE ANNOTATOR: a real DOM walk injects any missing
#       data-override-target stamps so Edit Mode always works.
#       Editability is the platform's guarantee, not the model's job.
#     - JS ARMOR: scripts scanned against the banned list; a bad
#       script is dropped, never fatal.
#     - EXTERNAL-REQUEST ARMOR: only Google-Fonts links and https
#       images survive; everything else is stripped.
#   AUTHORSHIP (repair-worthy — truth + coverage):
#     - TRUTH: every digit-run in visible text must trace to the data.
#     - COVERAGE: every inventory image present by url; nav, contact
#       form (posting to the real endpoint), and footer present.
#     - ONE surgical repair call carrying the exact violations with a
#       minimal-edit command; repair fails again → fallback (None) and
#       the old path takes over, wearing the spec's tokens via the
#       bridge. One repair, ever.
#
# Gated on SITE_BUILDER_V2=on (default OFF). The v2 document joins
# render_and_persist at the same seam the canvas uses (_canvas_html),
# so slot population, overrides, the token bridge, the easel step and
# the judge all apply unchanged. Model-portable by construction: the
# prompt carries no model-specific syntax; model/limits live in env
# (BUILDER_V2_MODEL / BUILDER_V2_MAX_TOKENS) and every call rides the
# model_ladder.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("builder_v2")

V2_MAX_TOKENS_DEFAULT = 28000
V2_TEMPERATURE = 0.8
DOC_MAX_BYTES = 300 * 1024

_ALLOWED_LINK_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
_DIGIT_RUN_RE = re.compile(r"\d{2,}")     # 2+ digit runs must trace
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

_JS_BANNED = (
    "eval(", "new Function", "fetch(", "XMLHttpRequest", "import(",
    "WebSocket", "document.write", "localStorage", "sessionStorage",
)


def enabled() -> bool:
    return (os.environ.get("SITE_BUILDER_V2") or "").strip().lower() in (
        "on", "1", "true", "yes")


def _model() -> str:
    m = (os.environ.get("BUILDER_V2_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


def _max_tokens() -> int:
    try:
        return max(8000, int(os.environ.get("BUILDER_V2_MAX_TOKENS")
                             or V2_MAX_TOKENS_DEFAULT))
    except ValueError:
        return V2_MAX_TOKENS_DEFAULT


# ─── the prompt (model-portable: plain instructions, no syntax) ──────

_SYSTEM = """You are a master web designer-craftsperson building ONE complete production web page in a single pass. You hold the whole page in mind at once — every decision coherent with every other. You were chosen because one sighted mind beats a pipeline of blind stages.

THE LAW OF THE PAGE is the approved design specification the owner has read and signed. Execute it exactly: its sections, its written copy, its named signature move, its color and font roles. Where the spec is silent, decide with craft in the spec's spirit — never retreat to a generic median.

HARD RULES (a validator checks each; violations cost a repair round):
1. Output ONE complete HTML document: <!DOCTYPE html> through </html>. Inline <style>. At most one <script> (a single IIFE, DOM-only: class toggles, listeners on elements you rendered; the page must stay fully coherent with JS disabled).
2. TRUTH: every fact, number, price, and claim on the page appears in the REAL DATA below. Nothing invented — a stat the data doesn't prove renders as a clearly-marked editable placeholder, never a made-up figure.
3. COVERAGE: every listed image appears (exact url in src); a fixed navigation; a working contact form posting to the given endpoint (method="POST", the given action url, name/email fields at minimum); a footer. Every real service/offering has a home.
4. EXTERNAL REQUESTS: Google Fonts stylesheet links and the provided https image urls ONLY. No other external scripts, styles, frames, or calls.
5. EDITABILITY: stamp data-override-target="v2/f1", "v2/f2", … on headings, paragraphs, and captions as you write them (a platform pass guarantees any you miss — stamping well keeps the labels meaningful).
6. MOBILE: a real responsive pass in the same document — media queries so every section holds at 390px. What breaks on a phone fails the whole page.
7. The spec's color hexes and font names are law — write them directly in your CSS (:root custom properties named as the spec names them, then var() references).

CRAFT FLOOR: generous, complete pages beat austere concepts; restraint disciplines color and motion, never content. Light the stage (glow, texture, gradient depth) — never a flat rectangle. One signature moment, executed exactly as the spec draws it.

OUTPUT: the HTML document only. No commentary, no code fences."""


def build_user_prompt(spec_text: str, real_data: str,
                      violations: Optional[List[str]] = None,
                      prior_doc: str = "") -> str:
    """Pure prompt assembly (testable). With violations + prior_doc it
    becomes the ONE surgical repair prompt (Amendment 1: minimal edits,
    never a fresh re-roll)."""
    if violations:
        return "\n".join([
            "SURGICAL REPAIR — your page failed validation on these exact "
            "points. Fix ONLY what each violation requires; every other "
            "byte of the document stays as you wrote it. Do not redesign, "
            "do not rewrite unaffected sections.",
            "",
            "VIOLATIONS:",
            *[f"- {v}" for v in violations[:12]],
            "",
            "THE REAL DATA (the only source of facts):",
            real_data.strip()[:12000],
            "",
            "YOUR DOCUMENT:",
            prior_doc,
            "",
            "Output the corrected complete HTML document only.",
        ])
    return "\n".join([
        "== THE APPROVED SPEC (the law of the page — the owner read and "
        "approved this document) ==",
        spec_text.strip(),
        "",
        "== THE REAL DATA (the only facts you may render; every image url "
        "listed here must appear on the page) ==",
        real_data.strip()[:16000],
        "",
        "Build the complete page now.",
    ])


# ─── real data assembly ──────────────────────────────────────────────

def assemble_real_data(ctx: Dict[str, Any], business_id: str) -> str:
    """Everything true, in one block: business facts, offerings,
    testimonials, contact endpoint + channels, every image url, the
    discovery dossier digest."""
    parts: List[str] = []
    biz = ctx.get("business") or {}
    parts.append(f"BUSINESS: {biz.get('name') or ''} — type: "
                 f"{biz.get('type') or ''}")
    contact = ctx.get("contact") if isinstance(ctx.get("contact"), dict) else {}
    ch = {k: v for k, v in contact.items()
          if isinstance(v, str) and v.strip()}
    if ch:
        parts.append("CONTACT CHANNELS: " + json.dumps(ch, ensure_ascii=False))
    parts.append("CONTACT FORM ENDPOINT (the form's action): "
                 f"https://kmj-intake-server-production.up.railway.app"
                 f"/sites/{business_id}/contact-submit")
    try:
        import atelier
        for mid in ("offerings", "testimonials", "statband", "faq", "store"):
            try:
                data = atelier._section_data(mid, {}, ctx)
            except Exception:
                continue
            if data:
                parts.append(f"[{mid}]\n"
                             + json.dumps(data, ensure_ascii=False)[:3000])
    except Exception as e:
        logger.info(f"[v2] section data skipped: {e}")
    # every image, by url
    imgs: List[str] = []
    slots = (((ctx.get("site") or {}).get("site_config") or {})
             .get("slots") or {})
    for name, rec in sorted(slots.items()):
        if isinstance(rec, dict) and not rec.get("removed") \
                and (rec.get("custom_url") or "").strip():
            imgs.append(f"- {rec['custom_url'].strip()} (owner upload: {name})")
    for g in (ctx.get("gallery") or []):
        if isinstance(g, dict) and (g.get("url") or "").strip():
            note = g.get("alt") or g.get("caption") or ""
            imgs.append(f"- {g['url'].strip()}"
                        + (f" ({note})" if note else ""))
    if imgs:
        parts.append("IMAGES (every one appears on the page, exact urls):\n"
                     + "\n".join(dict.fromkeys(imgs)))
    try:
        import discovery
        dd = (((ctx.get("site") or {}).get("site_config") or {})
              .get("discovery_dossier"))
        digest = discovery.dossier_digest(dd)
        if digest:
            parts.append("DISCOVERY DOSSIER (the owner's confirmed answers):\n"
                         + digest)
    except Exception:
        pass
    return "\n\n".join(parts)


# ─── mechanical armor (deterministic, zero model calls) ─────────────

def annotate_editability(html: str) -> Tuple[str, int]:
    """THE ANNOTATOR (Amendment 1): guarantee data-override-target on
    every text-bearing element the model missed. Returns (html, added)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        n = 0
        existing = {el.get("data-override-target")
                    for el in soup.find_all(attrs={"data-override-target": True})}
        counter = 0
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li",
                                   "blockquote", "figcaption"]):
            if tag.get("data-override-target"):
                continue
            text = tag.get_text(strip=True)
            if not text or len(text) < 2:
                continue
            counter += 1
            target = f"v2/auto_{counter}"
            while target in existing:
                counter += 1
                target = f"v2/auto_{counter}"
            tag["data-override-target"] = target
            existing.add(target)
            n += 1
        return str(soup), n
    except Exception as e:
        logger.warning(f"[v2] annotator skipped: {e}")
        return html, 0


def armor_scripts(html: str) -> Tuple[str, List[str]]:
    """Drop any <script> containing a banned call; report what fell."""
    dropped: List[str] = []

    def _check(m: re.Match) -> str:
        body = m.group(1) or ""
        for ban in _JS_BANNED:
            if ban in body:
                dropped.append(ban)
                return ""
        return m.group(0)

    out = re.sub(r"<script[^>]*>(.*?)</script>", _check, html,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, dropped


def armor_external(html: str) -> Tuple[str, List[str]]:
    """Strip non-whitelisted external <link>/<iframe>/external <script
    src>. Google Fonts links survive; https images are untouched (img
    tags aren't requests we initiate logic through)."""
    stripped: List[str] = []

    def _link(m: re.Match) -> str:
        tag = m.group(0)
        href = (re.search(r'href\s*=\s*["\']([^"\']+)', tag) or [None, ""])[1]
        if any(h in href for h in _ALLOWED_LINK_HOSTS) or href.startswith("#") \
                or not href.startswith("http"):
            return tag
        stripped.append(href[:80])
        return ""

    out = re.sub(r"<link\b[^>]*>", _link, html, flags=re.IGNORECASE)

    def _script_src(m: re.Match) -> str:
        stripped.append("external script")
        return ""
    out = re.sub(r"<script\b[^>]*\bsrc\s*=[^>]*>\s*</script>", _script_src,
                 out, flags=re.IGNORECASE)

    def _iframe(m: re.Match) -> str:
        stripped.append("iframe")
        return ""
    out = re.sub(r"<iframe\b.*?</iframe>", _iframe, out,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, stripped


# ─── authorship checks (truth + coverage) ────────────────────────────

def _visible_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
               flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", t)


def check_truth(html: str, real_data: str) -> List[str]:
    """Every 2+ digit run in visible text must appear in the data (the
    canvas fact-trace, page-wide). Years-as-copy ('24/7') ride only if
    the data holds them too — real or removed."""
    data_runs = set(_DIGIT_RUN_RE.findall(real_data))
    problems: List[str] = []
    for run in dict.fromkeys(_DIGIT_RUN_RE.findall(_visible_text(html))):
        if run not in data_runs:
            problems.append(f"number '{run}' on the page but not in the "
                            f"REAL DATA — real or removed")
        if len(problems) >= 6:
            break
    return problems


def check_coverage(html: str, real_data: str) -> List[str]:
    problems: List[str] = []
    for m in re.finditer(r"^- (https://\S+)", real_data, re.MULTILINE):
        url = m.group(1)
        if url not in html:
            problems.append(f"required image missing: {url}")
    if not re.search(r"<nav\b", html, re.IGNORECASE):
        problems.append("no <nav> — a fixed navigation is required")
    endpoint = re.search(r"CONTACT FORM ENDPOINT[^\n]*:\s*(\S+)", real_data)
    if endpoint and endpoint.group(1) not in html:
        problems.append(f"contact form must post to {endpoint.group(1)}")
    if not re.search(r"<form\b", html, re.IGNORECASE):
        problems.append("no <form> — the working inquiry form is required")
    if not re.search(r"<footer\b", html, re.IGNORECASE):
        problems.append("no <footer>")
    return problems[:12]


def _parse_doc(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    if i < 0:
        return None
    j = text.lower().rfind("</html>")
    if j < 0:
        return None
    doc = text[i:j + len("</html>")]
    return doc if len(doc.encode()) <= DOC_MAX_BYTES else None


# ─── the run ─────────────────────────────────────────────────────────

def _call(system: str, user: str, business_id: str) -> Optional[str]:
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        # Flight one lesson: the full-page pass is ONE giant generation;
        # a tight timeout forced the ladder's reduced-tokens retry and
        # shipped a SQUEEZED page ("headline feels compressed"). Give
        # the first attempt real room — a slow masterpiece beats a fast
        # miniature.
        client = Anthropic(api_key=key, timeout=900.0, max_retries=1)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                timeout=max(timeout, 900.0),
                **model_ladder.sampling_kwargs(model, V2_TEMPERATURE))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="builder_v2",
            business_id=business_id, max_tokens=_max_tokens())
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/builder-v2", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="builder_v2")
        except Exception:
            pass
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.error(f"[v2] build call failed on every rung: "
                     f"{type(e).__name__}: {e}")
        return None


def run_builder_v2(spec_text: str, ctx: Dict[str, Any], business_id: str,
                   progress_cb=None) -> Dict[str, Any]:
    """ONE call → armor → (one scoped repair) → document or None.
    None = the old path takes over (and still wears the spec's tokens
    via the bridge). The report always returns — loud failures."""
    report: Dict[str, Any] = {"engine": "builder_v2", "model": _model(),
                              "mechanical": {}, "violations": [],
                              "repaired": False, "fallbacks": []}

    def _progress(pct: int, stage: str):
        try:
            if progress_cb:
                progress_cb(pct, stage)
        except Exception:
            pass

    real_data = assemble_real_data(ctx, business_id)
    _progress(48, "One mind builds the whole page")
    raw = _call(_SYSTEM, build_user_prompt(spec_text, real_data), business_id)
    doc = _parse_doc(raw or "")
    if not doc:
        report["fallbacks"].append({"stage": "author",
                                    "detail": "no parseable document"})
        return {"html": None, "report": report}

    def _mechanical(d: str) -> str:
        d, dropped = armor_scripts(d)
        d, stripped = armor_external(d)
        d, added = annotate_editability(d)
        report["mechanical"] = {"scripts_dropped": dropped,
                                "externals_stripped": stripped,
                                "override_targets_added": added}
        return d

    doc = _mechanical(doc)
    violations = check_truth(doc, real_data) + check_coverage(doc, real_data)
    if violations:
        report["violations"] = violations
        _progress(56, "Surgical repair")
        raw2 = _call(_SYSTEM,
                     build_user_prompt(spec_text, real_data,
                                       violations=violations, prior_doc=doc),
                     business_id)
        doc2 = _parse_doc(raw2 or "")
        if doc2:
            doc2 = _mechanical(doc2)
            v2 = check_truth(doc2, real_data) + check_coverage(doc2, real_data)
            if not v2:
                report["repaired"] = True
                return {"html": doc2, "report": report}
            report["fallbacks"].append({
                "stage": "repair",
                "detail": "still failing after one repair: "
                          + "; ".join(v2[:4])})
        else:
            report["fallbacks"].append({"stage": "repair",
                                        "detail": "repair unparseable"})
        return {"html": None, "report": report}
    return {"html": doc, "report": report}
