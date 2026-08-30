# directions_judge.py
# ═══════════════════════════════════════════════════════════════════════
# TWO DIRECTIONS + A JUDGE (2026-08-29 — the builder bench, step 5).
#
# Taste is chosen, not described — but the Arc-6 directions gallery asks
# the OWNER to choose between three rendered drafts on the old composer,
# and the one-mind builder never sees it. This is the cheap version for
# every build: the DRL authors TWO candidate rationales with opposite
# stances (the concept-literal default, and the stance the owner's own
# energy argues for), and a small judge scores both against the
# acceptance test the DRO already lives by — the first-five-seconds
# feeling, the signals, the facts on file, the owner's stated direction,
# one organizing idea — and picks. The winner is the ONE rationale the
# $3 build runs on; the loser and the verdict ride the DRO's meta for
# audit. Cost: one extra DRO on the DRL model + one short judge call —
# cents, not a second build.
#
# Off by default (DRO_DIRECTIONS=on to switch it on, like BUILDER_V2_LOOP).
# Fail-open everywhere: no second candidate → candidate A; judge cannot
# run / cannot parse → candidate A ("today's default") with the reason on
# the record. Never raises into produce_dro.
# ═══════════════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

JUDGE_MAX_TOKENS = 1200
JUDGE_TEMPERATURE = 0.2
FACTS_CAP = 1800
DEFAULT_STANCE = "concept-literal"


def enabled() -> bool:
    return (os.environ.get("DRO_DIRECTIONS") or "off").strip().lower() \
        in ("on", "1", "true", "yes")


# The three Arc-6 stances live on site_composer.DIRECTION_STANCES (the
# gallery's source of truth). Read lazily so this module never imports
# site_composer at load time; the copies below are the fail-open floor.
_STANCES: Dict[str, str] = {
    "concept-literal": (
        "CONCEPT-LITERAL — design the metaphor as literally as craft "
        "allows. The organizing idea must be VISIBLE in the decisions, not "
        "just described in copy. Spend the rule-break where the metaphor "
        "lands hardest."),
    "tension-led": (
        "TENSION-LED — let the two poles fight visibly. decisions.tension "
        "is MANDATORY: pick decisions that hold both poles at once and "
        "place the ONE rule-break exactly at their collision point."),
    "quiet-editorial": (
        "QUIET-EDITORIAL — maximum restraint; whitespace is the luxury. "
        "Airy density, quiet scale contrast, motion none or subtle. "
        "Exactly ONE perfect loud moment (the rule-break)."),
}


def stances() -> Dict[str, str]:
    try:
        from site_composer import DIRECTION_STANCES
        if isinstance(DIRECTION_STANCES, dict) and DIRECTION_STANCES:
            return dict(DIRECTION_STANCES)
    except Exception:
        pass
    return dict(_STANCES)


def pick_pair(signals: List[Dict[str, Any]],
              owner_direction: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Candidate A is always the concept-literal default (so 'off' and
    'on but the judge failed' are the same design). Candidate B is the
    stance the owner's own energy argues for: a quiet/deliberate owner
    gets the quiet-editorial reading, a bold one gets tension-led — the
    judge then decides whether the concept or the energy wins."""
    prefs = ((owner_direction or {}).get("site_prefs")
             if isinstance(owner_direction, dict) else None) or {}
    boldness = str(prefs.get("boldness") or "").strip().lower()
    energy = next((s.get("value") for s in (signals or [])
                   if isinstance(s, dict) and s.get("signal_id") == "energy_signature"), None)
    quiet = boldness in ("quiet", "calm") or (
        not boldness and energy in ("deliberate", "warm_steady"))
    return DEFAULT_STANCE, ("quiet-editorial" if quiet else "tension-led")


# ─── The judge ───────────────────────────────────────────────────────────
_SYSTEM = (
    "You are the design director choosing between TWO candidate design "
    "rationales (DROs) for the same business. You do not design; you judge. "
    "The acceptance test, in order of weight:\n"
    "1. FIRST FIVE SECONDS — which candidate better produces the feeling the "
    "owner asked a stranger to have before reading anything?\n"
    "2. SIGNALS HONOURED — each decision must argue from the detected signals; "
    "name any decision that contradicts one.\n"
    "3. MATERIAL TRUTH — check each candidate against THE FACTS on file: a "
    "gallery-led or proof-led direction the material cannot fill (two photos, "
    "no testimonials) FAILS this test regardless of its beauty.\n"
    "4. THE OWNER'S DIRECTION — boldness, type voice, colour direction, and "
    "'never like' are the owner's words; a candidate that overrides them loses.\n"
    "5. ONE ORGANIZING IDEA — every decision defensible from the concept.\n"
    "6. DISTINCT FROM THE COHORT — fewer shared signature axes with recent "
    "sites is better; a tiebreaker only.\n"
    "Beauty in the abstract is not a criterion. Output ONLY JSON: "
    '{"winner":"A"|"B","because":"one paragraph naming the deciding criterion '
    'and the specific decision that won it","loser_weakness":"one sentence"}'
)


def _axis_signature(dro: Dict[str, Any]) -> List[Any]:
    from agents.composer.drl import passes
    return passes.distinctiveness_signature(dro)


def _shared_with_cohort(dro: Dict[str, Any],
                        recent_signatures: Optional[List[List[Any]]]) -> int:
    from agents.composer.drl import passes
    mine = _axis_signature(dro)
    return max((passes._shared_axes(mine, r) for r in (recent_signatures or [])),
               default=0)


def _trim(dro: Dict[str, Any]) -> Dict[str, Any]:
    """What the judge needs to read — the decisions and their arguments,
    never the evidence quotes (the signals are shown once, separately)."""
    d = dro.get("decisions") or {}

    def blk(name: str, *fields: str) -> Dict[str, Any]:
        b = d.get(name) or {}
        out = {f: b.get(f) for f in fields if b.get(f) is not None}
        if b.get("because"):
            out["because"] = b["because"]
        return out

    return {
        "hero_concept": blk("hero_concept", "direction", "concept_statement"),
        "first_impression": blk("first_impression", "feel_in_3s", "remember"),
        "palette": blk("palette", "base", "accent_strategy", "temperature"),
        "typography": blk("typography", "display_personality", "scale_contrast"),
        "layout": blk("layout", "symmetry", "density", "hierarchy_approach"),
        "motion": blk("motion", "temperature", "signature_move"),
        "whitespace": blk("whitespace", "philosophy"),
        "rule_break": blk("rule_break", "what", "where"),
        "tension": blk("tension", "pole_a", "pole_b"),
        "language": blk("language", "choice"),
        "summary_for_practitioner": str(dro.get("summary_for_practitioner") or "")[:600],
    }


def _owner_words(owner_direction: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    prefs = ((owner_direction or {}).get("site_prefs")
             if isinstance(owner_direction, dict) else None) or {}
    colors = prefs.get("colors") if isinstance(prefs.get("colors"), dict) else {}
    out = {k: prefs.get(k) for k in ("boldness", "type_personality", "feel_words",
                                     "avoid", "hero_verbs", "audience") if prefs.get(k)}
    if colors.get("direction"):
        out["colour_direction"] = colors["direction"]
    return out


def build_user_prompt(business_id: str, signals: List[Dict[str, Any]],
                      candidates: List[Tuple[str, Dict[str, Any]]], *,
                      facts_text: str = "",
                      owner_direction: Optional[Dict[str, Any]] = None,
                      recent_signatures: Optional[List[List[Any]]] = None) -> str:
    from agents.composer.drl import signals as sig
    consumable = [{"signal_id": s.get("signal_id"), "value": s.get("value")}
                  for s in (signals or [])
                  if isinstance(s, dict) and isinstance(s.get("confidence"), (int, float))
                  and sig.is_consumable(s["confidence"])]
    letters = "AB"
    blocks = []
    for i, (stance_key, dro) in enumerate(candidates[:2]):
        blocks.append(
            f"CANDIDATE {letters[i]} (stance: {stance_key}; shares "
            f"{_shared_with_cohort(dro, recent_signatures)}/8 signature axes with the "
            f"nearest recent site):\n{json.dumps(_trim(dro), indent=1)}")
    facts = (facts_text or "").strip()
    return (
        f"BUSINESS: {business_id}\n\n"
        f"THE OWNER'S OWN DIRECTION (their words; criterion 4):\n"
        f"{json.dumps(_owner_words(owner_direction), indent=1)}\n\n"
        f"DETECTED SIGNALS (criterion 1 and 2; first_five_seconds is the acceptance test):\n"
        f"{json.dumps(consumable, indent=1)}\n\n"
        + (f"THE FACTS ON FILE (criterion 3 — what the page can honestly fill):\n"
           f"{facts[:FACTS_CAP]}\n\n" if facts else
           "THE FACTS ON FILE: not available for this judgment — weigh criterion 3 "
           "from the offering/testimonial texture in the signals only.\n\n")
        + "\n\n".join(blocks)
        + "\n\nChoose. Output ONLY the JSON."
    )


def judge(business_id: str, signals: List[Dict[str, Any]],
          candidates: List[Tuple[str, Dict[str, Any]]], *,
          facts_text: str = "",
          owner_direction: Optional[Dict[str, Any]] = None,
          recent_signatures: Optional[List[List[Any]]] = None) -> Dict[str, Any]:
    """→ {"winner": 0|1, "because": str, "by": "judge"|"default",
    "loser_weakness": str, "detail": str}. Never raises; on any failure the
    concept-literal candidate (index 0 — today's design) is kept and the
    reason is on the record."""
    default: Dict[str, Any] = {
        "winner": 0, "by": "default", "loser_weakness": "",
        "because": "judge unavailable — the concept-literal candidate kept "
                   "(the same rationale a single-direction build would run on)",
        "detail": ""}
    if len(candidates) < 2:
        default["detail"] = "fewer than two candidates"
        return default
    from agents.composer.drl import passes
    client = passes._client()
    if not client:
        default["detail"] = "no ANTHROPIC_API_KEY — DRL client unavailable"
        return default
    user = build_user_prompt(business_id, signals, candidates, facts_text=facts_text,
                             owner_direction=owner_direction,
                             recent_signatures=recent_signatures)
    try:
        raw = passes._call(client, _SYSTEM, user, max_tokens=JUDGE_MAX_TOKENS,
                           temperature=JUDGE_TEMPERATURE, business_id=business_id,
                           task="judge", prefill='{"winner"')
    except Exception as e:
        default["detail"] = f"judge call failed ({type(e).__name__}): {e}"[:300]
        logger.warning(f"[directions] judge call failed for {business_id[:8]}: "
                       f"{default['detail']}")
        return default
    parsed = passes._parse_json(raw)
    letter = str((parsed or {}).get("winner") or "").strip().upper() \
        if isinstance(parsed, dict) else ""
    if letter not in ("A", "B"):
        default["detail"] = (f"judge output unparseable: head={str(raw)[:80]!r}")
        logger.warning(f"[directions] {default['detail']}")
        return default
    return {"winner": 0 if letter == "A" else 1, "by": "judge",
            "because": str(parsed.get("because") or "")[:900],
            "loser_weakness": str(parsed.get("loser_weakness") or "")[:300],
            "detail": ""}


def record(winner: Dict[str, Any], loser: Dict[str, Any],
           winner_key: str, loser_key: str, verdict: Dict[str, Any]) -> None:
    """Stamp the audit block on the winning DRO's meta (persisted with it)."""
    def _card(key: str, dro: Dict[str, Any]) -> Dict[str, Any]:
        d = dro.get("decisions") or {}
        return {"stance": key,
                "signature": _axis_signature(dro),
                "language": ((d.get("language") or {}).get("choice")),
                "concept": str(((d.get("hero_concept") or {}).get("concept_statement")) or "")[:240]}
    meta = winner.get("meta") if isinstance(winner.get("meta"), dict) else {}
    meta["directions"] = {
        "candidates": [_card(winner_key, winner), _card(loser_key, loser)],
        "judge": {"winner": winner_key, "by": verdict.get("by"),
                  "because": verdict.get("because"),
                  "loser_weakness": verdict.get("loser_weakness"),
                  "detail": verdict.get("detail")},
        "loser_summary": str(loser.get("summary_for_practitioner") or "")[:400],
    }
    winner["meta"] = meta
