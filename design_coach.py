# design_coach.py
# ─────────────────────────────────────────────────────────────────────
# THE DESIGN COACH (2026-07-25, Kevin's ruling: "turn this into a
# design coach experience... like the strategy coach... the full
# experience").
#
# The discovery system's CONVERSATIONAL door. The compressed form
# collected facts; the coach extracts taste, story, and conviction the
# way a senior creative director does — one question at a time, real
# follow-ups, their words mirrored back — and every learned detail
# lands in the SAME discovery dossier with provenance 'asked' (the
# strongest material the Director can receive).
#
# Architecture rulings:
#   - NOT a chief_chat mode. A dedicated /composer/coach/* door means
#     no injector gating to leak (#153's class is structurally
#     impossible here), no action-tag parsing, and a strict JSON turn
#     contract validated server-side.
#   - STATELESS turns: the frontend carries the transcript; the
#     backend carries the truth (dossier + business facts). Every turn
#     re-reads what is KNOWN so the coach never re-asks (Kevin's
#     standing rule; the prefill-signals discipline).
#   - Salvaged from the Style Interview (now retired): the creative
#     spark (metaphor / surprise / remember / tension) and the story
#     walkthrough (origin / craft / proof / voice / atmosphere) — the
#     best questions it had, asked as dialogue instead of form steps.
#   - Every save rides discovery.apply_practitioner_patch — one
#     dossier, one provenance vocabulary, zero new storage.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("design_coach")

COACH_MAX_TOKENS = 1400
COACH_TEMPERATURE = 0.7
MAX_TURNS = 60          # transcript cap (user+coach messages)
MAX_MSG_CHARS = 1200    # per-message cap before the prompt

# The session's territory — the coach walks these stations in spirit,
# not as a rigid script. The frontend renders them as the thread.
STATIONS = ("welcome", "world", "story", "taste", "signature",
            "truth", "brief")

_SYSTEM = """You are THE DESIGN COACH inside the Solutionist System — a warm, sharp senior creative director sitting down with a business owner to draw out everything a designer needs to make their site unmistakably THEIRS. You are having a real conversation, not administering a form.

HOW YOU TALK (the coaching craft):
- ONE question at a time. Never a list of questions. Short messages — two or three sentences, then the question.
- FOLLOW UP on what they actually said. Mirror their exact words back ("you said 'it should feel like a homecoming' — tell me more about that"). The second question on a topic is where the gold is.
- Ask about their WORLD, never about design. "Walk me into your shop — what do I see first? what's playing?" beats "what's your aesthetic?" They answer in materials, light, and sound; the designer translates.
- Hunt STORIES and REACTIONS: what clients say when they walk in, the work they're proudest of, the site that made them jealous, what would make them cringe. Stories become copy; cringes become bans.
- Plain language always. Never say motif, palette, typography, hierarchy. Say "the one thing people should screenshot", "the colors that feel like you", "how loud should it read".
- Warm, direct, a little playful. Celebrate specific answers ("THAT — 'installed once, worn for years' — that's a headline"). Push politely past vague ones ("'professional' tells me nothing about YOU — what would your best client say?").

THE TERRITORY (walk it naturally; skip what's already known; follow heat when they light up):
1. world — their physical trade: the room, materials, light, sounds, tools. This is where their real palette and texture live.
2. story — origin (how it started), craft (what nobody guesses it takes), proof (proudest win), voice (what customers say walking away), atmosphere (the place it feels like).
3. taste — reactions, not vocabulary: this-or-that pairs (use the "pair" field), the one site/brand they admire and WHY in their words, what they'd never want ("cringe" answers — save these as bans).
4. signature — "if a visitor screenshots ONE moment on your page, what is it?" Push until it's concrete.
5. truth — real numbers they're proud of (years, clients, reviews) WITH where each comes from; the one action a visitor should take.
6. brief — when the territory is covered (or they're done), reflect the whole session back as a short vivid summary they can confirm.

NEVER RE-ASK what the KNOWN CONTEXT below already contains — reference it instead ("I know you work with coaches and barbers — who's the one client you'd clone?"). If the context shows brand colors or images, react to them like a director would.

SAVING (the whole point — capture as you go):
Every turn, extract anything learned into "saves". Use these dossier sections/fields:
- identity: one_liner, primary_action, brand_persona (list of up to 3 words), first_3s_feel
- world: room, materials, light, sounds (free text, their words)
- story: origin, craft, proof, voice, atmosphere
- taste: each answered pair saved as its OWN field (field is one of ground/density/carrier/edges/era/tone/motion, value is the chosen word); plus admired (what and why, one string) and bans (the cringe answers, one string or list)
- signature: moment (their words), sharpened (your one-line phrasing of it)
- truth: proven_stats (value is a list of {label, value, proof} objects)
Save the practitioner's OWN PHRASING in values — verbatim quotes are design material. Only save what THIS turn established. Empty saves list is fine.

OUTPUT — STRICT JSON, nothing else:
{
  "reply": "your next message to them (plain text, no markdown headers)",
  "chips": ["up to 4 short tap-to-answer suggestions", "..."],        // optional
  "pair": {"key": "ground", "a": "Dark and moody", "b": "Light and airy"},  // optional, when asking a this-or-that
  "saves": [{"section": "story", "field": "voice", "value": "..."}],
  "stage": "world|story|taste|signature|truth|brief",
  "done": false,
  "reflect_back": ["6-10 short vivid lines summarizing the session"]   // ONLY with stage "brief"
}
Rules: chips are answers THEY might tap, not questions. Use "pair" at most every third turn. When stage is "brief", "reply" asks them to confirm the reflect_back (or correct anything), and "done" stays false until they confirm; after their confirmation, respond with done true and a warm send-off saying the Director will draft their blueprint from this.
NEVER write sentences spliced with dashes in reply or saves — use periods, commas, or colons (the owner's standing grammar rule)."""


# ─── context assembly (what is already KNOWN — never re-ask) ─────────

def _known_context(business_id: str) -> str:
    parts: List[str] = []
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            "&select=name,business_type,settings&limit=1") or []
        if rows:
            b = rows[0]
            parts.append(f"BUSINESS: {b.get('name')} "
                         f"({b.get('business_type') or 'business'})")
            st = b.get("settings") or {}
            bk = st.get("brand_kit") or {}
            cols = bk.get("colors") or {}
            if cols:
                parts.append("BRAND COLORS ON FILE: "
                             + json.dumps(cols)[:200])
            prefs = st.get("site_prefs") or {}
            if prefs:
                parts.append("EARLIER STYLE ANSWERS (do not re-ask; "
                             "build on them): "
                             + json.dumps(prefs, ensure_ascii=False)[:900])
    except Exception as e:
        logger.info(f"[coach] business context skipped: {e}")
    try:
        import discovery
        d = discovery.get_dossier(business_id)
        digest = discovery.dossier_digest(d) if d else ""
        if digest:
            parts.append("THE DOSSIER SO FAR (already known — reference, "
                         "never re-ask):\n" + digest[:2400])
    except Exception as e:
        logger.info(f"[coach] dossier context skipped: {e}")
    return "\n\n".join(parts) or "(nothing known yet — a fresh start)"


def build_turn_prompt(business_id: str,
                      messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """The transcript as ladder messages: KNOWN CONTEXT rides the first
    user message so caching-friendly system stays constant."""
    trimmed = [
        {"role": ("assistant" if m.get("role") == "assistant" else "user"),
         "content": str(m.get("content") or "")[:MAX_MSG_CHARS]}
        for m in (messages or [])[-MAX_TURNS:]
        if str(m.get("content") or "").strip()
    ]
    known = _known_context(business_id)
    lead = ("KNOWN CONTEXT (the platform already knows this — never "
            "re-ask any of it):\n" + known
            + "\n\nBegin (or continue) the session. JSON only.")
    if not trimmed:
        return [{"role": "user", "content": lead}]
    # prepend the known-context to the FIRST user message
    out: List[Dict[str, str]] = []
    injected = False
    for m in trimmed:
        if not injected and m["role"] == "user":
            out.append({"role": "user",
                        "content": lead + "\n\nTHEY SAY: " + m["content"]})
            injected = True
        else:
            out.append(m)
    if not injected:
        out.insert(0, {"role": "user", "content": lead})
    # anthropic requires user-first
    if out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": lead})
    return out


# ─── the turn contract ───────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
_ALLOWED_SECTIONS = {"identity", "world", "story", "taste", "signature",
                     "truth"}


def parse_turn(raw: str) -> Optional[Dict[str, Any]]:
    """Tolerant strict-JSON parse of a coach turn. None = unusable."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        out = json.loads(text[i:j + 1])
    except Exception:
        return None
    if not isinstance(out, dict) or not str(out.get("reply") or "").strip():
        return None
    out["reply"] = str(out["reply"]).strip()
    out["stage"] = out.get("stage") if out.get("stage") in STATIONS else "world"
    out["done"] = bool(out.get("done"))
    chips = out.get("chips")
    out["chips"] = [str(c)[:80] for c in chips[:4]] \
        if isinstance(chips, list) else []
    pair = out.get("pair")
    out["pair"] = pair if (isinstance(pair, dict) and pair.get("a")
                           and pair.get("b")) else None
    rb = out.get("reflect_back")
    out["reflect_back"] = [str(x)[:200] for x in rb[:12]] \
        if isinstance(rb, list) else []
    saves = out.get("saves")
    clean: List[Dict[str, Any]] = []
    for s in (saves if isinstance(saves, list) else []):
        if not isinstance(s, dict):
            continue
        sec = str(s.get("section") or "").strip()
        fld = str(s.get("field") or "").strip()
        if sec in _ALLOWED_SECTIONS and fld and s.get("value") not in (None, ""):
            clean.append({"section": sec, "field": fld, "value": s["value"]})
    out["saves"] = clean[:10]
    return out


def apply_saves(business_id: str, saves: List[Dict[str, Any]]) -> int:
    """Every save lands in THE dossier with provenance 'asked'. Returns
    how many applied. apply_practitioner_patch is pure — read, merge,
    persist here. proven_stats ride the truth door's list shape."""
    if not saves:
        return 0
    try:
        import discovery
    except Exception as e:
        logger.warning(f"[coach] discovery unavailable, saves lost: {e}")
        return 0
    patch: Dict[str, Any] = {}
    n = 0
    for s in saves:
        if s["section"] == "truth" and s["field"] == "proven_stats":
            stats = s["value"] if isinstance(s["value"], list) else [s["value"]]
            patch.setdefault("truth", {})["proven_stats"] = [
                st for st in stats if isinstance(st, dict)]
        else:
            patch.setdefault(s["section"], {})[s["field"]] = {
                "value": s["value"], "source": "asked"}
        n += 1
    try:
        # discovery.answer is the write engine: load → merge (pure
        # apply_practitioner_patch) → persist.
        if discovery.answer(business_id, patch) is None:
            logger.warning("[coach] dossier patch found no site row")
            return 0
    except Exception as e:
        logger.warning(f"[coach] dossier patch failed: {e}")
        return 0
    return n


# ─── the calls ───────────────────────────────────────────────────────

def _model() -> str:
    m = (os.environ.get("DESIGN_COACH_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


def run_turn(business_id: str,
             messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """One coach turn: transcript in → {reply, chips, pair, saves_applied,
    stage, done, reflect_back} out. Loud failures — the frontend shows a
    retry, never a blank."""
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"error": "coach unavailable (no key)"}
        client = Anthropic(api_key=key, timeout=120.0, max_retries=1)
        turn_msgs = build_turn_prompt(business_id, messages)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=_SYSTEM,
                messages=turn_msgs, timeout=max(timeout, 120.0),
                **model_ladder.sampling_kwargs(model, COACH_TEMPERATURE))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="design_coach",
            business_id=business_id, max_tokens=COACH_MAX_TOKENS)
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/coach/turn", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="design_coach")
        except Exception:
            pass
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", None) == "text")
        turn = parse_turn(raw)
        if not turn:
            return {"error": "the coach lost the thread — try again"}
        applied = apply_saves(business_id, turn.pop("saves", []))
        turn["saves_applied"] = applied
        return turn
    except Exception as e:
        logger.error(f"[coach] turn failed: {type(e).__name__}: {e}")
        return {"error": "the coach is unavailable right now — try again"}


def finish_session(business_id: str) -> Dict[str, Any]:
    """The session's close: derive the taste profile from everything
    gathered, stamp the session complete, and return the digest the
    Blueprint panel opens with."""
    out: Dict[str, Any] = {"ok": True}
    try:
        import discovery
        try:
            derived = discovery.derive_taste(business_id)
            out["derived"] = bool(derived)
        except Exception as e:
            logger.info(f"[coach] derive skipped: {e}")
            out["derived"] = False
        try:
            discovery.answer(business_id, {
                "meta": {"coach_session_completed": {
                    "value": True, "source": "asked"}}})
        except Exception:
            pass
        d = discovery.get_dossier(business_id)
        out["digest"] = discovery.dossier_digest(d) if d else ""
    except Exception as e:
        logger.warning(f"[coach] finish degraded: {e}")
        out["digest"] = ""
    return out
