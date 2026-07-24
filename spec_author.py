# spec_author.py
# ─────────────────────────────────────────────────────────────────────
# THE SPEC AUTHOR (Director's Cut arc 3).
#
# Kevin's finding (2026-07-24): a hand-written design SPEC — every
# decision already made: which word is gold, what the stats say, what
# the button does — produced the same excellent page from five
# different models. The prompt did the designing; the models did the
# rendering. Vague briefs get filled with the median of the internet;
# a fully-decided spec leaves no gaps for generic to leak in.
#
# This module authors that document from everything the system knows
# (the canvas dossier: facts, brand, section plan, owner's words,
# judge lessons, language + bar) — one CHEAP text-only call. The
# practitioner reads and revises the spec for pennies; only an
# APPROVED spec is worth a paid build, where it leads the canvas
# brief as the law of the page.
#
# Persistence: business_sites.site_config.design_spec =
#   {"text", "status": "draft"|"approved", "authored_at", "model",
#    "revision": int}
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("spec_author")

SPEC_MAX_TOKENS = 4000
SPEC_TEMPERATURE = 0.7
# The spec leads the canvas brief — cap what rides downstream so the
# builder's context stays sane even if a model over-writes.
SPEC_MAX_CHARS = 12000


def _model() -> str:
    m = (os.environ.get("SPEC_AUTHOR_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


# ─── The taught anatomy ──────────────────────────────────────────────
# The format is taught as a RUBRIC (the shape of decidedness), never a
# lookup table of content — the standing generalization rule.

_SYSTEM = """You are the DIRECTOR — a senior creative director writing the complete design specification for one business's website. A builder (another craftsperson) will execute your document exactly as written, so the quality of the final page equals the decidedness of your spec.

THE STANDARD OF DECIDEDNESS — the entire point of this document:
A vague brief gets filled with the median of the internet. Your spec leaves NO decision to the builder's defaults. That means:
- Write the ACTUAL words: every headline verbatim, every eyebrow, every stat with its real number and label, every button label. Never "a strong headline about X" — write the headline.
- Name every color BY ROLE AND HEX and say exactly which words/elements carry an accent color. Never "use accents tastefully."
- Name the fonts and which one owns display / body / editorial-accent duty.
- Decide every section's composition in one or two sentences a builder can execute ("two-column: portrait left in a hairline frame; bio right, 2 paragraphs, second one shorter").
- Decide the interactions: what moves, when, and what every hover/click does. One signature interaction maximum; name it.
- Decide the mobile behavior in one line per non-obvious section.

STRUCTURE — output the document in exactly this anatomy, plain text with section rules (=====) and numbered sections:
1. OVERVIEW — what this site is, one paragraph. The page's single memorable move, named.
2. BRAND IDENTITY — fonts (role each), full color palette as CSS-variable-style roles with hexes.
3. LAYOUT & SECTIONS (top to bottom) — every section numbered, each with: composition decided, the REAL copy written out, which words carry accents, what imagery goes where (only real provided images or clearly-labeled slots).
4. INTERACTIONS & ANIMATIONS — the definitive list.
5. DESIGN RULES (do / don't) — the taste laws for THIS page, including every learned ban from the judge's notes.

TRUTH LAW (absolute): every fact, price, service, testimonial, stat and claim in your spec must come from the DOSSIER below. Real or removed — if the dossier doesn't provide a number, do not invent one. Real portfolio images are listed; reference them by their given names/urls only.

TASTE: commit. The safe generic version of this page is a failure. One move a visitor describes to a friend tomorrow — designed, decided, and named in section 1. Honor the owner's words above everything except truth. If judge lessons are present, every one of them is a ban you design around. Do not reuse the same accent treatment the lessons criticize (no default gold-underline crutch).

OUTPUT: the document only. No preamble, no commentary, no code."""


def _digest_plan(spec_plan: List[Dict[str, Any]]) -> str:
    """The composed section plan as a one-line-per-section digest —
    the Director decides content AROUND this structure (data sections
    render from real rows; creative sections are fully authorable)."""
    if not spec_plan:
        return "(no composed plan yet — propose a section list yourself, 6-9 sections)"
    lines = []
    for i, s in enumerate(spec_plan, 1):
        mid = str(s.get("module") or "?")
        var = str(s.get("variant") or "")
        keys = ", ".join(sorted((s.get("content") or {}).keys())) or "-"
        lines.append(f"{i}. {mid}{f' ({var})' if var else ''} — content fields: {keys}")
    return "\n".join(lines)


def build_user_prompt(dossier: str, spec_plan: List[Dict[str, Any]],
                      prior_spec: str = "", feedback: str = "") -> str:
    """Pure prompt assembly (testable, no IO). `dossier` is the canvas
    brief — everything the system knows, already compiled."""
    parts = [
        "== THE DOSSIER (everything known about this business — the only "
        "source of facts) ==",
        dossier.strip(),
        "",
        "== THE CURRENT SECTION PLAN (the page's chapters, in order) ==",
        _digest_plan(spec_plan),
        "",
    ]
    if prior_spec.strip():
        parts += [
            "== THE PRIOR SPEC (you are REVISING, not restarting — keep "
            "every decision the owner didn't question) ==",
            prior_spec.strip()[:SPEC_MAX_CHARS],
            "",
        ]
    if feedback.strip():
        parts += [
            "== THE OWNER'S REVISION NOTES (address every one, precisely) ==",
            feedback.strip()[:1200],
            "",
        ]
    parts.append("Write the complete design specification now.")
    return "\n".join(parts)


def _call_llm(system: str, user: str, business_id: str) -> Optional[str]:
    """Anthropic call, usage metered under its own endpoint so spec
    authoring cost is visible separately from builds."""
    try:
        from anthropic import Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        client = Anthropic(api_key=key)
        msg = client.messages.create(
            model=_model(), max_tokens=SPEC_MAX_TOKENS,
            temperature=SPEC_TEMPERATURE, system=system,
            messages=[{"role": "user", "content": user}], timeout=120.0)
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/spec", model=getattr(msg, "model", "") or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="spec_author")
        except Exception:
            pass
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.warning(f"[spec] author call failed: {type(e).__name__}: {e}")
        return None


def author_spec(business_id: str, ctx: Dict[str, Any],
                dro: Optional[Dict[str, Any]],
                spec_plan: List[Dict[str, Any]],
                prior_spec: str = "", feedback: str = "") -> Optional[str]:
    """One text-only call → the full design document, or None (caller
    surfaces the failure; nothing is persisted here)."""
    try:
        import canvas_brief
        dossier = canvas_brief.compile_canvas_brief(ctx, dro, spec_plan)
    except Exception as e:
        logger.warning(f"[spec] dossier compile failed ({e}) — minimal dossier")
        dossier = "Follow the design rationale. Real data only; never invent facts."
    user = build_user_prompt(dossier, spec_plan, prior_spec, feedback)
    text = (_call_llm(_SYSTEM, user, business_id) or "").strip()
    if not text:
        return None
    return text[:SPEC_MAX_CHARS]


# ─── Persistence ─────────────────────────────────────────────────────

def _site_row(business_id: str):
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1") or []
    return rows[0] if rows else None


def get_spec(business_id: str) -> Optional[Dict[str, Any]]:
    row = _site_row(business_id)
    if not row:
        return None
    spec = (row.get("site_config") or {}).get("design_spec")
    return spec if isinstance(spec, dict) and spec.get("text") else None


def save_spec(business_id: str, text: str,
              status: str = "draft") -> Optional[Dict[str, Any]]:
    """Persist the spec document. Bumps revision when one exists."""
    import sb_clients
    row = _site_row(business_id)
    if not row:
        return None
    cfg = dict(row.get("site_config") or {})
    prior = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else {}
    spec = {
        "text": text[:SPEC_MAX_CHARS],
        "status": status,
        "authored_at": datetime.now(timezone.utc).isoformat(),
        "model": _model(),
        "revision": int(prior.get("revision") or 0) + 1,
    }
    cfg["design_spec"] = spec
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    return spec


def set_status(business_id: str, status: str) -> Optional[Dict[str, Any]]:
    import sb_clients
    row = _site_row(business_id)
    if not row:
        return None
    cfg = dict(row.get("site_config") or {})
    spec = cfg.get("design_spec")
    if not isinstance(spec, dict) or not spec.get("text"):
        return None
    spec = dict(spec)
    spec["status"] = status
    cfg["design_spec"] = spec
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    return spec


def approved_spec_text(business_id: str) -> str:
    """The approved document, or '' — compose_site's one-line read."""
    spec = get_spec(business_id)
    if spec and spec.get("status") == "approved":
        return str(spec.get("text") or "")
    return ""
