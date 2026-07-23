# agents/composer/drl/passes.py
# ═══════════════════════════════════════════════════════════════════════
# Design Rationale Layer — PR2: the two LLM passes + the deterministic
# distinctiveness check + persistence.
#
#   detect_signals()  — transcript/context → signals[] with verbatim
#                        evidence (taxonomy = signals.SIGNALS).
#   author_dro()      — signals + principles + 2 contrasting exemplars +
#                        recent-output signatures → a validated DRO; runs
#                        the distinctiveness check; one regeneration max.
#   produce_dro()     — orchestrator: detect → fetch recent → author →
#                        distinctiveness → persist (design_rationales) → return.
#
# Mirrors compose_hero's discipline: one Anthropic call per pass, code-fence
# strip, one retry on parse/validation failure, structured soft-fallback on
# any error (never raises into the caller). CONSUMED by the composer:
# site_composer.compose_site calls produce_dro() and threads the DRO into
# the design tokens (brand_dna.apply_dro_palette/style), the copy directive
# (_dro_directive), variant selection (symmetry + hero direction), and the
# Arc 4 quality gate; the stored rationale is served by GET
# /composer/rationale (frontend DesignRationalePanel). All DB access is
# service role.
# ═══════════════════════════════════════════════════════════════════════

import json
import os
import logging
import time
import difflib
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic

import sb_clients
import model_ladder
from agents.composer.hero_composer import _strip_code_fence
from agents.composer import drl
from agents.composer.drl import signals as sig

logger = logging.getLogger("drl.passes")

# Site Arc 12 — REASONING UPGRADE: the DRO is the creative brain of every
# compose (signal detection + rationale authoring), so this is the
# surgical place to spend Opus. Env-driven (DRL_MODEL) with the full
# model-ladder protecting it: an unavailable model 404/403/400s → ONE
# loud, breadcrumbed retry on model_ladder.FALLBACK_MODEL (Sonnet 4.5);
# a timeout → one same-model retry at -35% max_tokens → the sonnet rung
# → minimal mode. COST NOTE: Opus 4.8 is ~$5/$25 per MTok vs Sonnet
# $3/$15; a single compose is 1 signal pass + 1 DRO (~10k out) ≈ +$0.15,
# a directions run authors 3 candidate DROs on this model (~20k out)
# ≈ +$0.40 — Kevin ruled quality-first (2026-07).
# COST DIET (2026-07-22, Kevin's ruling): Sonnet 5 is the default brain
# — the DRO is structured reasoning Sonnet handles well at ~40% of Opus
# cost, and per-build spend had crept 4-6x past the return-point era.
# DRL_MODEL=claude-opus-4-8 remains the one-env premium override (the
# future Practice-tier lever).
DRL_MODEL_DEFAULT = "claude-sonnet-5"


def _drl_model() -> str:
    return (os.environ.get("DRL_MODEL") or "").strip() or DRL_MODEL_DEFAULT
# Arc 7 quality floor: 1800 truncated the signal JSON on rich intakes —
# a parse failure silently returned [] and the DRO authored blind while
# still reporting dro_status='applied'. Roomy cap + parse-retry below.
SIGNAL_MAX_TOKENS = 3200
SIGNAL_TEMPERATURE = 0.2                       # extraction — low/deterministic
# Arc 7: how much intake material the signal pass reads. The owner's
# freshest evidence leads the transcript (site_composer._assemble_intake_text
# puts it FIRST), so the tail — not the newest prefs — is what truncates.
SIGNAL_TRANSCRIPT_CAP = 12000
# Arc 7 same-business freshness: a recompose sharing >= this many of the
# 8 distinctiveness axes with the business's OWN last DRO gets one regen
# (the platform-wide _collides check only fires at >= 6 vs a mixed cohort,
# so a same-shell recompose could share 5/8 with itself and pass).
OWN_REPEAT_AXES_THRESHOLD = 5
# Arc 7 honest thin-brief status: a DRO driven by fewer consumable
# signals than this is 'applied_thin', not 'applied' (site_composer).
THIN_BRIEF_MIN_SIGNALS = 3
# Arc 6 grew the DRO (rule_break/tension/first_impression blocks, each with
# because + from_signals) — 3000 truncated the JSON mid-object, and a parse
# failure returned None with NO retry, killing all three direction stances
# identically ("0/3 succeeded"). Roomy cap + parse-retry in author_dro.
# Why-minimal hunt (2026-07-23): the interview bridge grew the consumed-
# signal set by 3-6 entries, and the output shape used to echo every
# signal WITH its evidence quotes — prime truncation suspect for the
# full DRO JSON dying at the old 6000 cap (every build since the bridge
# fell to minimal). Slimmer echo above + a taller cap below.
DRO_MAX_TOKENS = 9000
DRO_TEMPERATURE = 0.4                          # reasoning with creative latitude


# ─── LLM plumbing ──────────────────────────────────────────────────────
# Per-call ceilings now live in model_ladder.timeout_for(task, model):
# they scale with the model FAMILY (Opus streams ~2-3x slower than
# Sonnet — signals 120s / DRO 240s on Opus vs 75/120 on Sonnet). WITHOUT
# an explicit ceiling the SDK default is 600s/call with 2 retries, so
# one slow call could stall a build for 10+ minutes. The compose runs
# as a chief_jobs background job, so the long Opus ceilings are safe.
# _CLIENT_DEFAULT_TIMEOUT_S is only the constructor default — every real
# call passes its own timeout.
_CLIENT_DEFAULT_TIMEOUT_S = 120.0


def _client() -> Optional[Anthropic]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    return (Anthropic(api_key=key, timeout=_CLIENT_DEFAULT_TIMEOUT_S,
                      max_retries=1) if key else None)


def _set_fail(out: Optional[Dict[str, str]], stage: str, detail: str) -> None:
    """Record a machine-readable failure reason on the caller's mutable
    out-param (forensics: site_composer persists it as site_config.dro_failure
    so a fallback compose is never a mystery again). stage ∈
    signals|authoring|validation|exception."""
    if isinstance(out, dict):
        out["stage"] = stage
        out["detail"] = str(detail)[:300]


# task → the ladder's timeout family ('signals' streams less than a DRO).
_TASK_FAMILY = {"signals": "signals"}   # everything else = "dro"


def _call(client: Anthropic, system: str, user: str, *, max_tokens: int,
          temperature: float, business_id: str, task: str) -> str:
    """One DRL call under the model ladder (Site Arc 12): family-scaled
    timeout, loud+breadcrumbed sonnet fallback on a model-identity error,
    same-model reduced-tokens retry on a timeout. Raises only when every
    rung failed — the callers' attempt/parse-retry + minimal-mode
    machinery stays the outer safety net. NOTE: temperature is dropped
    automatically for model families that 400 on sampling params
    (Opus 4.7/4.8 / Sonnet 5 / Fable)."""
    family = _TASK_FAMILY.get(task, "dro")

    def _do(model: str, max_tokens: int, timeout: float):
        return client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
            timeout=timeout,
            **model_ladder.sampling_kwargs(model, temperature),
        )

    # Provider switch (2026-07-17): when the site pipeline runs on
    # Kimi (SITE_BUILDER_PROVIDER=moonshot), skip the Claude model
    # ladder — site_llm handles the call and fails open to Anthropic
    # (in which case the single-model path, not the ladder, applies).
    import site_llm
    # Stage routing (2026-07-21): the BRAIN defaults to Claude even when
    # the global builder is Kimi (site_llm.provider_for's brain rule) —
    # this branch now only fires when a stage map EXPLICITLY routes the
    # DRL to moonshot.
    if site_llm.provider_for(f"drl/{task}") == "moonshot":
        # Design-quality audit fix R3 (2026-07-18): this branch used
        # site_llm's default 120s timeout — the full DRO needs the
        # ladder's family-scaled ceiling (240s on slow models) plus
        # Kimi's reasoning headroom. Under 120s the call died on BOTH
        # attempts, every build fell to minimal mode, and the atelier
        # (which requires a full DRO) never ran: the flat-site cascade.
        # On ANY moonshot failure we now fall back to the FULL Claude
        # model ladder, not a single brittle call.
        try:
            msg = site_llm.create_message(
                model=_drl_model(), max_tokens=max_tokens,
                temperature=temperature, system=system, user_content=user,
                timeout=model_ladder.timeout_for(family, _drl_model()) + 120.0,
                task=f"drl/{task}")
            used_model = getattr(msg, "model", "moonshot")
        except Exception as _ms_err:
            logger.warning(f"[drl] moonshot path failed for {task} "
                           f"({type(_ms_err).__name__}) — full ladder fallback")
            msg, used_model = model_ladder.call_with_ladder(
                _do, model=_drl_model(), task=family,
                business_id=business_id, max_tokens=max_tokens)
    else:
        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_drl_model(), task=family,
            business_id=business_id, max_tokens=max_tokens)
    try:
        from api_usage_logger import log_api_usage_sync
        u = getattr(msg, "usage", None)
        log_api_usage_sync(
            endpoint=f"/composer/drl/{task}", model=used_model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            business_id=business_id, task_type="composer")
    except Exception:
        pass
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _parse_json(raw: str) -> Optional[Any]:
    try:
        return json.loads(_strip_code_fence(raw))
    except Exception:
        return None


# ─── Enums derived from the schema (validation target) ──────────────────
def _decision_enums() -> Dict[str, Dict[str, List[str]]]:
    """{decision: {field: [allowed]}} pulled from schema.json so validation
    tracks the schema automatically."""
    props = (drl.load_schema().get("properties", {})
             .get("decisions", {}).get("properties", {}))
    out: Dict[str, Dict[str, List[str]]] = {}
    for dec, dspec in props.items():
        fields = {}
        for fname, fspec in (dspec.get("properties") or {}).items():
            if isinstance(fspec, dict) and "enum" in fspec:
                fields[fname] = fspec["enum"]
        out[dec] = fields
    return out


REQUIRED_DECISIONS = ["palette", "typography", "layout", "motion",
                      "hero_concept", "whitespace", "voice_to_visual"]


# ─── Enum coercion (2026-07-20): an invented enum value must never kill a
# 95%-valid DRO again. The 07-20 KMJ build authored a well-aligned DRO whose
# hero_concept.direction='photographic_hero' was outside the schema enum;
# validation rejected the whole DRO twice and the build fell back to the
# minimal (bland) DRO. Now out-of-enum values are snapped to the nearest
# allowed value BEFORE validation: explicit alias → difflib close match →
# field removed (validation treats absent as unconstrained). Every snap is
# logged — coercions are breadcrumbs, never silent. ───
_ENUM_ALIASES: Dict[str, Dict[str, str]] = {
    "hero_concept.direction": {
        "photographic_hero": "portrait_presence",
        "photo_hero": "portrait_presence",
        "photography_led": "portrait_presence",
    },
    "typography.body_personality": {
        "grotesque_bold": "plain_grotesque",
        "warm_editorial_serif": "readable_serif",
    },
    "layout.hierarchy_approach": {
        "asymmetric_editorial": "editorial_columns",
    },
}


def _coerce_dro_enums(dro: Any) -> None:
    """Mutates dro in place, snapping out-of-enum decision values to the
    nearest allowed value. Called at the top of _validate_dro so every
    call site benefits; idempotent (a coerced DRO is valid on re-check)."""
    if not isinstance(dro, dict):
        return
    decisions = dro.get("decisions")
    if not isinstance(decisions, dict):
        return
    for dec, fields in _decision_enums().items():
        block = decisions.get(dec)
        if not isinstance(block, dict):
            continue
        for field, allowed in fields.items():
            val = block.get(field)
            if val is None or val in allowed:
                continue
            key = f"{dec}.{field}"
            norm = str(val).strip().lower()
            snap = _ENUM_ALIASES.get(key, {}).get(norm)
            if not snap:
                close = difflib.get_close_matches(
                    norm, [str(a) for a in allowed], n=1, cutoff=0.65)
                snap = close[0] if close else None
            if snap:
                logger.warning(f"[drl] enum coerced: decisions.{key} "
                               f"'{val}' -> '{snap}' (not in schema enum)")
                block[field] = snap
            else:
                logger.warning(f"[drl] enum value dropped: decisions.{key} "
                               f"'{val}' has no near match in {allowed}")
                block.pop(field, None)


def _validate_dro(dro: Any) -> List[str]:
    """Light structural validation → list of problems (empty = valid).
    Checks required decisions, because/from_signals on each, and enum
    membership for the fields the schema constrains. Coerces out-of-enum
    values in place first (see _coerce_dro_enums)."""
    _coerce_dro_enums(dro)
    problems: List[str] = []
    if not isinstance(dro, dict):
        return ["DRO is not an object"]
    decisions = dro.get("decisions")
    if not isinstance(decisions, dict):
        return ["decisions missing"]
    enums = _decision_enums()
    for dec in REQUIRED_DECISIONS:
        block = decisions.get(dec)
        if not isinstance(block, dict):
            problems.append(f"decisions.{dec} missing")
            continue
        if not block.get("because"):
            problems.append(f"decisions.{dec}.because missing")
        if not isinstance(block.get("from_signals"), list):
            problems.append(f"decisions.{dec}.from_signals missing")
        for field, allowed in enums.get(dec, {}).items():
            val = block.get(field)
            if val is not None and val not in allowed:
                problems.append(f"decisions.{dec}.{field}='{val}' not in {allowed}")
    return problems


# ─── Pass 1: signal detection ───────────────────────────────────────────
def _signal_system_prompt() -> str:
    lines = [
        "You detect DESIGN-RELEVANT signals from a practitioner's intake "
        "conversation. You do NOT design anything here — you observe.",
        "For each signal below, decide its value from the practitioner's own "
        "words. Quote them VERBATIM as evidence — those quotes are the audit "
        "trail. If a signal isn't evidenced, infer conservatively and mark "
        "source='inferred' with lower confidence; never fabricate quotes.",
        "",
        "SIGNALS:",
    ]
    for sid, meta in sig.SIGNALS.items():
        vals = meta.get("values")
        vals_str = vals if isinstance(vals, str) else " | ".join(vals)
        lines.append(f"- {sid} ({meta['name']}): {meta['definition']}")
        lines.append(f"    values: {vals_str}")
    lines += [
        "",
        "OUTPUT ONLY this JSON (no markdown):",
        '{"signals":[{"signal_id":"opening_posture","value":"problem_first",'
        '"confidence":0.0,"evidence":["verbatim quote"],"source":"intake|inferred"}]}',
        "One entry per signal_id above. confidence is 0..1. "
        "For communication_temperature, value is a 0.0(direct)..1.0(relational) "
        "number; for multi-select signals, value is an array.",
    ]
    return "\n".join(lines)


def detect_signals(business_id: str, transcript: str,
                   failure_out: Optional[Dict[str, str]] = None,
                   ) -> List[Dict[str, Any]]:
    """Transcript/context → signals[]. Soft-fails to [] (the authoring pass
    can still proceed conservatively). One clean retry on a call/parse
    failure — mirrors author_dro's discipline; previously a single
    truncated response silently starved the whole DRO of evidence.
    `failure_out` (forensics): mutable dict that receives {stage, detail}
    when BOTH attempts fail — the reason is never lost again."""
    client = _client()
    if not client:
        logger.warning(f"[drl] signal detection skipped for {business_id}: "
                       "no ANTHROPIC_API_KEY — DRL client unavailable")
        _set_fail(failure_out, "signals",
                  "no ANTHROPIC_API_KEY — DRL client unavailable")
        return []
    if not (transcript or "").strip():
        logger.warning(f"[drl] signal detection skipped for {business_id}: "
                       "empty intake transcript")
        _set_fail(failure_out, "signals", "empty intake transcript")
        return []
    system = _signal_system_prompt()
    user = (f"Practitioner intake material for business {business_id}:\n\n"
            f"{transcript.strip()[:SIGNAL_TRANSCRIPT_CAP]}")
    last: Dict[str, str] = {}

    def _attempt(extra: str = "") -> Optional[List[Any]]:
        t0 = time.monotonic()
        try:
            raw = _call(client, system, user + extra,
                        max_tokens=SIGNAL_MAX_TOKENS, temperature=SIGNAL_TEMPERATURE,
                        business_id=business_id, task="signals")
        except Exception as e:
            last["detail"] = (f"signal call failed after "
                              f"{time.monotonic() - t0:.0f}s "
                              f"({type(e).__name__}): {e}")
            logger.warning(f"[drl] signal detection call failed for "
                           f"{business_id}: {last['detail']}")
            return None
        parsed = _parse_json(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("signals"), list):
            # Diagnose, don't guess: truncation = long raw w/ no closing
            # brace in the tail; refusal/preamble shows in the head.
            r = raw or ""
            last["detail"] = (f"signal parse failed: len={len(r)} "
                              f"head={r[:60]!r} tail={r[-60:]!r}")
            logger.warning(f"[drl] signal parse failed for {business_id}: "
                           f"len={len(r)} head={r[:60]!r} tail={r[-60:]!r}")
            return None
        return parsed["signals"]

    out = _attempt()
    if out is None:
        out = _attempt(
            "\n\nYour previous response was not parseable JSON. Output ONLY "
            "the complete JSON object — no prose, no code fences — and make "
            "sure the JSON is fully closed.")
    if out is None:
        _set_fail(failure_out, "signals",
                  last.get("detail") or "both signal attempts failed")
        return []
    valid_ids = set(sig.signal_ids())
    return [s for s in out if isinstance(s, dict) and s.get("signal_id") in valid_ids]


# ─── Exemplar selection (1 similar + 1 contrasting, by signal overlap) ───
def _signal_value_map(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {s.get("signal_id"): s.get("value") for s in signals if isinstance(s, dict)}


def _select_exemplars(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One nearest (for the move) + one farthest (to stretch the space) by
    count of matching signal values."""
    want = _signal_value_map(signals)
    scored = []
    for ex in drl.load_exemplars():
        ex_vals = _signal_value_map(ex.get("signals", []))
        overlap = sum(1 for k, v in want.items() if k in ex_vals and ex_vals[k] == v)
        scored.append((overlap, ex))
    if not scored:
        return []
    scored.sort(key=lambda t: t[0])
    picks = [scored[-1][1]]                       # nearest
    if len(scored) > 1 and scored[0][1] is not scored[-1][1]:
        picks.append(scored[0][1])                # farthest
    return picks


def _exemplar_for_prompt(ex: Dict[str, Any]) -> Dict[str, Any]:
    """Trim an exemplar to what the authoring prompt needs."""
    return {"exemplar_id": ex.get("exemplar_id"), "narrative": ex.get("narrative"),
            "signals": ex.get("signals"), "decisions": ex.get("decisions")}


# ─── Distinctiveness check (deterministic, spec §5.2) ────────────────────
def distinctiveness_signature(dro: Dict[str, Any]) -> List[Any]:
    d = (dro or {}).get("decisions", {})

    def g(path: str) -> Any:
        dec, field = path.split(".")
        return (d.get(dec) or {}).get(field)

    return [g(axis) for axis in sig.DISTINCTIVENESS_AXES]


def _shared_axes(a: List[Any], b: List[Any],
                 exempt: Optional[set] = None) -> int:
    return sum(1 for i, (x, y) in enumerate(zip(a, b))
               if x is not None and x == y
               and not (exempt and i in exempt))


def run_distinctiveness(dro: Dict[str, Any],
                        recent: List[Dict[str, Any]],
                        exempt: Optional[set] = None) -> Dict[str, Any]:
    """Compare against recent DRO signatures; return the distinctiveness_check
    block. Verdict 'regenerated_once' is set by the caller after a regen.
    `exempt` (Interview v3, B4): axis indexes with owner-explicit direction
    evidence — cohort similarity there is allowed without justification and
    does not count toward the collision threshold."""
    mine = distinctiveness_signature(dro)
    worst = 0
    nearest_ids: List[str] = []
    for r in recent:
        shared = _shared_axes(mine, distinctiveness_signature(r), exempt=exempt)
        if shared > worst:
            worst = shared
            nearest_ids = [r.get("id") or r.get("exemplar_id") or "?"]
        elif shared == worst and worst:
            nearest_ids.append(r.get("id") or r.get("exemplar_id") or "?")
    verdict = "distinct" if worst < sig.DISTINCTIVENESS_COLLISION_THRESHOLD else "flagged"
    return {
        "compared_against": [r.get("id") or r.get("exemplar_id") for r in recent][:sig.DISTINCTIVENESS_COHORT_N],
        "axes_shared_with_nearest": worst,
        "verdict": verdict,
        "notes": f"nearest shares {worst}/8 axes" + (f" with {nearest_ids[0]}" if nearest_ids else "")
                 + (f" ({len(exempt)} owner-explicit axis/axes exempt)"
                    if exempt else ""),
    }


def _collides(dro: Dict[str, Any], recent: List[Dict[str, Any]],
              exempt: Optional[set] = None) -> bool:
    mine = distinctiveness_signature(dro)
    return any(_shared_axes(mine, distinctiveness_signature(r), exempt=exempt) >= sig.DISTINCTIVENESS_COLLISION_THRESHOLD
               for r in recent)


# ─── Owner-direction exemption (Interview v3, B4) ───────────────────────
# Anti-convergence pressure exists to stop AI-default convergence — but an
# axis the OWNER explicitly chose is not convergence, it's the brief. When
# the intake carries owner-supplied direction evidence, cohort similarity
# on those axes is allowed without justification (no re-roll there); every
# other axis keeps full pressure.
def owner_exempt_axes(site_prefs: Optional[Dict[str, Any]] = None,
                      reference_analysis: Optional[List[Dict[str, Any]]] = None,
                      fonts_pinned: bool = False) -> set:
    """Axis INDEXES into sig.DISTINCTIVENESS_AXES carrying owner-explicit
    direction evidence:
      type_personality or fonts_pinned  → typography.display_personality
      colors.love                       → palette base/accent/temperature
      inspiration_urls WITH a successful reference_analysis → palette.* +
        typography.display_personality + layout.density (the analyzer
        extracts exactly palette read / type class / density).
    """
    axes = sig.DISTINCTIVENESS_AXES
    exempt: set = set()
    prefs = site_prefs if isinstance(site_prefs, dict) else {}

    def _idx(name: str) -> int:
        return axes.index(name)

    if str(prefs.get("type_personality") or "").strip() or fonts_pinned:
        exempt.add(_idx("typography.display_personality"))
    colors = prefs.get("colors") if isinstance(prefs.get("colors"), dict) else {}
    if colors.get("love"):
        exempt.update(_idx(a) for a in ("palette.base", "palette.accent_strategy",
                                        "palette.temperature"))
    ok_ref = any(isinstance(r, dict) and r.get("ok")
                 for r in (reference_analysis or []))
    if (prefs.get("inspiration_urls") or []) and ok_ref:
        exempt.update(_idx(a) for a in ("palette.base", "palette.accent_strategy",
                                        "palette.temperature",
                                        "typography.display_personality",
                                        "layout.density"))
    return exempt


# ─── Pass 2: DRO authoring ───────────────────────────────────────────────
def _dro_system_prompt() -> str:
    # PROMPT DIET (2026-07-21 root-cause fix): the full DOCTRINE block
    # (~6KB of HTML-execution law) was wrapped around the DRO author in
    # Phase 1 — but the DRO writes REASONING, not HTML, and the forensic
    # record shows the design brain starving to 'applied_thin' since the
    # doctrine era: heavier prompts, more timeouts, more minimal-mode
    # fallbacks, flatter sites. The DRO keeps its own CREATIVE ENGINE
    # philosophy (below) + the short diversity clause; the doctrine
    # stays where HTML is authored (atelier / hero / canvas).
    from design_doctrine import DIVERSITY_LINE
    return (
        DIVERSITY_LINE + "\n\n" +
        "You are a lead designer authoring a Design Rationale Object (DRO) — "
        "the REASONING for a website's design, written BEFORE any HTML exists. "
        "You decide DIRECTION, never concrete assets: no hex codes, no font "
        "names (those resolve downstream). Use ONLY the enum values from the "
        "schema.\n\n"
        "Every decision MUST carry a one-line `because` and `from_signals` "
        "(the signal_ids that drove it) — that is the trust contract. When two "
        "principles collide, name the collision and the winner in `because`.\n\n"
        "=== THE CREATIVE ENGINE (Arc 6 — the design philosophy; non-negotiable) ===\n"
        "1. ONE ORGANIZING IDEA RULES EVERYTHING. hero_concept.concept_statement "
        "is the BOSS of every other decision: palette, typography, layout, motion "
        "and whitespace must each be defensible as serving THAT idea. If a "
        "decision can't argue from the concept, change the decision.\n"
        "2. EXACTLY ONE DELIBERATE RULE-BREAK. Author decisions.rule_break "
        "{what, where, because}: one — and only one — knowing violation of good "
        "manners, placed where it lands hardest. This is where the RESTRAINT "
        "BUDGET spends: the page gets ONE signature moment at full volume "
        "(either the rule-break or the motion signature move, never both loud), "
        "and everything else stays quiet to pay for it.\n"
        "3. CHARACTER IS TENSION BETWEEN TWO POLES. Author decisions.tension "
        "{pole_a, pole_b, expression}: name the two truths the business holds at "
        "once (e.g. heritage vs. electric) and say HOW the design holds both — "
        "which decisions carry which pole. A design with no tension has no "
        "character.\n"
        "4. DESIGN THE FIRST 3 SECONDS. Author decisions.first_impression "
        "{feel_in_3s, remember}: what a stranger feels before reading anything, "
        "and the one thing they should remember. Every hero-adjacent decision "
        "answers to this.\n"
        "5. MATERIAL TRUTH. Layout choices must be honest to the data the "
        "business actually has (the offering/testimonial counts and texture in "
        "the signals): never author a proof-heavy, gallery-led or stat-led "
        "direction the material can't fill. An honest sparse page beats a "
        "padded one.\n\n"
        "Apply the translation principles below as MOVES, not lookups. Avoid "
        "the banned defaults (generic display fonts, purple-gradient SaaS look, "
        "the centered-hero+3-cards+CTA skeleton, stock-photo cliches, decorative "
        "accent when accent_strategy=single_semantic). Vary from the recent "
        "signatures where signals permit — but signal-fit always beats variety.\n\n"
        "=== TRANSLATION PRINCIPLES ===\n" + drl.load_principles()
    )


def _reference_analysis_block(reference_analysis: Optional[List[Dict[str, Any]]]) -> str:
    """Arc 5 — deterministic study of the reference sites the owner named
    (reference_analyzer output, compacted). DIRECTION EVIDENCE only."""
    if not reference_analysis:
        return ""
    try:
        from reference_analyzer import compact_summary
        compact = compact_summary(reference_analysis)
    except Exception:
        compact = []
    if not compact:
        return ""
    return (
        "REFERENCE SITES THE OWNER ADMIRES (fetched + analyzed by the "
        "platform — treat as DIRECTION EVIDENCE for mood/ground/contrast/"
        "type-class/density; NEVER copy their content, branding or exact "
        f"colors):\n{json.dumps(compact, indent=2)}\n\n")


def _creative_brief_block(creative: Optional[Dict[str, Any]]) -> str:
    """Arc 6 — the owner's creative brief (design_prefs v3 `creative`),
    rendered VERBATIM as the highest-priority authoring evidence. The
    metaphor seeds concept_statement; loud_where constrains where the
    rule-break / signature move may spend the restraint budget."""
    c = creative if isinstance(creative, dict) else {}
    lines: List[str] = []
    if c.get("metaphor"):
        lines.append(f'- The business feels like: "{c["metaphor"]}" '
                     "<- SEED hero_concept.concept_statement from this metaphor.")
    if c.get("surprise"):
        lines.append(f'- What people would never guess: "{c["surprise"]}"')
    if c.get("remember"):
        lines.append(f'- Three seconds in, a stranger should remember: '
                     f'"{c["remember"]}" <- this IS first_impression.remember.')
    if c.get("loud_where"):
        lines.append(f"- The ONE loud moment lives in: {c['loud_where']} "
                     "<- the rule-break/signature move may spend the restraint "
                     "budget ONLY there; every other channel stays quiet.")
    tn = c.get("tension") if isinstance(c.get("tension"), dict) else {}
    if tn.get("pole_a") and tn.get("pole_b"):
        lean = tn.get("lean")
        lean_txt = (f" (lean {lean}/5 toward '{tn['pole_b']}')"
                    if isinstance(lean, int) else "")
        lines.append(f"- Tension to hold: '{tn['pole_a']}' vs '{tn['pole_b']}'"
                     f"{lean_txt} <- author decisions.tension from exactly these poles.")
    st = c.get("story") if isinstance(c.get("story"), dict) else {}
    _story_labels = (("origin", "How it started"),
                     ("craft", "What people never guess it takes"),
                     ("proof", "The work they are proudest of"),
                     ("voice", "What clients say"),
                     ("atmosphere", "What walking in feels like"))
    st_lines = [f'    {label}: "{str(st[k]).strip()}"'
                for k, label in _story_labels
                if str(st.get(k) or "").strip()]
    if st_lines:
        # Design audit P3: the story used to reach only the signal pass;
        # the author now reads it raw — mine it for the metaphor, the
        # palette's temperature, and WHERE the rule-break belongs.
        lines.append("- THE OWNER'S STORY (their own words — mine it for "
                     "the organizing metaphor, the palette's temperature, "
                     "and where the rule-break belongs):\n"
                     + "\n".join(st_lines))
    if not lines:
        return ""
    return ("OWNER'S CREATIVE BRIEF (verbatim, HIGHEST PRIORITY — outranks "
            "every other signal; the metaphor is the organizing idea unless "
            "it is unusable):\n" + "\n".join(lines) + "\n\n")


# Shared by the full authoring prompt AND the minimal-mode fallback —
# the output contract is identical in both modes.
_DRO_OUTPUT_SHAPE = (
    "OUTPUT ONLY the DRO as JSON: "
    '{"dro_version":1,"business_id":"...","signals":[{"signal_id":"...","value":"..."} for each consumed signal — IDs and values ONLY, never repeat evidence quotes],'
    '"decisions":{"palette":{...},"typography":{...},"layout":{...},"motion":{...},'
    '"hero_concept":{...},"whitespace":{...},"voice_to_visual":{...},'
    '"rule_break":{"what":"...","where":"...","because":"..."},'
    '"tension":{"pole_a":"...","pole_b":"...","expression":"how the design holds both","because":"..."},'
    '"first_impression":{"feel_in_3s":"...","remember":"...","because":"..."},'
    '"language":{"choice":"<a listed language key or none>","because":"argued from THIS business\'s evidence"}},'
    '"anti_convergence":{"distinctiveness_check":{}},'
    '"summary_for_practitioner":"plain-language why-your-site-looks-this-way",'
    '"exemplars_consulted":[{"exemplar_id":"..","borrowed":"the move, named"}]}'
)


def _language_sheets_block() -> str:
    """The design-language character sheets (design_languages registry) —
    lazy + fail-open so a registry error never blocks DRO authoring."""
    try:
        import design_languages
        if design_languages.enabled():
            return "\n\n" + design_languages.character_sheets()
    except Exception:
        pass
    return ""


def _dro_user_prompt(business_id: str, signals: List[Dict[str, Any]],
                     exemplars: List[Dict[str, Any]],
                     recent_signatures: List[List[Any]],
                     reference_analysis: Optional[List[Dict[str, Any]]] = None,
                     creative: Optional[Dict[str, Any]] = None,
                     stance: Optional[str] = None) -> str:
    consumable = [s for s in signals
                  if isinstance(s.get("confidence"), (int, float))
                  and sig.is_consumable(s["confidence"])]
    stance_block = (f"AUTHORING STANCE FOR THIS CANDIDATE (one of three "
                    f"directions being authored — commit to it fully):\n"
                    f"{stance}\n\n" if stance else "")
    return (
        f"BUSINESS: {business_id}\n\n"
        + _creative_brief_block(creative)
        + stance_block +
        f"DETECTED SIGNALS (only these drive design; confidence<{sig.CONSUME_THRESHOLD} "
        f"recorded but not consumed):\n{json.dumps(consumable, indent=2)}\n\n"
        + _reference_analysis_block(reference_analysis) +
        f"CONTRASTING EXEMPLARS (learn the MOVE, never copy the surface):\n"
        f"{json.dumps([_exemplar_for_prompt(e) for e in exemplars], indent=2)}\n\n"
        f"RECENTLY-USED 8-AXIS SIGNATURES (justify any repetition from signals; "
        f"axes order = {sig.DISTINCTIVENESS_AXES}):\n{json.dumps(recent_signatures, indent=2)}\n\n"
        + _DRO_OUTPUT_SHAPE + _language_sheets_block()
    )


# ─── Minimal-mode fallback (the resilience ladder's last rung) ──────────
# A bland-but-valid DRO beats NO DRO: a fallback compose loses the atelier,
# the ceremony seams, the anchored hero and every DRO-driven design lever
# at once. When the full prompt fails call+parse-retry+validation-retry,
# one stripped attempt runs: signals + a principles summary + the output
# schema ONLY — no exemplars, no reference analysis, no creative brief,
# no stance. Such DROs carry meta.authored_minimal=true and always report
# dro_status='applied_thin' (site_composer), regardless of signal count.
_MINIMAL_PRINCIPLES_CAP = 1500


def _minimal_dro_system_prompt() -> str:
    lines = [
        "You author a Design Rationale Object (DRO) — the reasoning for a "
        "website's design — as ONE JSON object. MINIMAL MODE: a plain, "
        "conservative, VALID DRO is the goal; no flourish required.",
        "You decide DIRECTION, never concrete assets: no hex codes, no "
        "font names.",
        "Every decision object MUST include `because` (one line) and "
        "`from_signals` (a list of signal_ids; [] when inferred).",
        f"decisions MUST include ALL of: {REQUIRED_DECISIONS} "
        "plus rule_break, tension and first_impression.",
        "",
        "For the fields below use ONLY these values:",
    ]
    for dec, fields in _decision_enums().items():
        for fname, allowed in fields.items():
            lines.append(f"- decisions.{dec}.{fname}: {allowed}")
    try:
        principles = str(drl.load_principles() or "")[:_MINIMAL_PRINCIPLES_CAP]
    except Exception:
        principles = ""
    if principles:
        lines += ["", "TRANSLATION PRINCIPLES (summary):", principles]
    # Audit fix: minimal mode is the emergency fallback that was carrying
    # EVERY build — it never had the doctrine. Now it does.
    try:
        from design_doctrine import DOCTRINE
        return DOCTRINE + "\n\n" + "\n".join(lines)
    except Exception:
        return "\n".join(lines)


def _author_dro_minimal(client: Anthropic, business_id: str,
                        signals: List[Dict[str, Any]],
                        recent: List[Dict[str, Any]],
                        failure_out: Optional[Dict[str, str]] = None,
                        ) -> Optional[Dict[str, Any]]:
    """The FINAL rung: stripped prompt, one attempt + one corrective retry.
    Returns a validated, minimal-tagged DRO or None (failure_out then
    carries the combined reason)."""
    consumable = [s for s in signals
                  if isinstance(s.get("confidence"), (int, float))
                  and sig.is_consumable(s["confidence"])]
    system = _minimal_dro_system_prompt()
    user = (f"BUSINESS: {business_id}\n\n"
            f"DETECTED SIGNALS (drive the decisions where they can):\n"
            f"{json.dumps(consumable, indent=2)}\n\n" + _DRO_OUTPUT_SHAPE)
    last: Dict[str, str] = {}

    def _attempt(extra: str = "") -> Optional[Dict[str, Any]]:
        t0 = time.monotonic()
        try:
            raw = _call(client, system, user + extra, max_tokens=DRO_MAX_TOKENS,
                        temperature=DRO_TEMPERATURE, business_id=business_id,
                        task="dro_minimal")
        except Exception as e:
            last["detail"] = (f"minimal call failed after "
                              f"{time.monotonic() - t0:.0f}s "
                              f"({type(e).__name__}): {e}")
            logger.warning(f"[drl] minimal-mode call failed for "
                           f"{business_id}: {last['detail']}")
            return None
        parsed = _parse_json(raw)
        if isinstance(parsed, dict):
            _pop_audit_fields(parsed, business_id)
        if not isinstance(parsed, dict):
            r = raw or ""
            last["detail"] = (f"minimal parse failed: len={len(r)} "
                              f"head={r[:60]!r} tail={r[-60:]!r}")
            logger.warning(f"[drl] minimal-mode parse failed for "
                           f"{business_id}: {last['detail']}")
            return None
        return parsed

    dro = _attempt()
    if dro is None:
        dro = _attempt(
            "\n\nYour previous response was not parseable JSON. Output ONLY "
            "the complete JSON object — no prose, no code fences — and make "
            "sure the JSON is fully closed.")
    if dro is not None:
        problems = _validate_dro(dro)
        if problems:
            last["detail"] = f"minimal validation problems: {problems}"
            dro = _attempt(
                f"\n\nYour previous DRO had these problems: {problems}. "
                "Fix them. Use only the allowed enum values; include because "
                "+ from_signals on every decision. Output ONLY the JSON.")
    if dro is None or _validate_dro(dro):
        prior = (failure_out or {}).get("detail") or ""
        _set_fail(failure_out,
                  (failure_out or {}).get("stage") or "authoring",
                  (prior + " | minimal-mode also failed: "
                   + (last.get("detail") or "invalid after retry")).strip(" |"))
        logger.warning(f"[drl] minimal-mode DRO failed for {business_id}: "
                       f"{last.get('detail') or 'invalid after retry'}")
        return None
    dro["dro_version"] = 1
    dro["business_id"] = business_id
    meta = dro.get("meta") if isinstance(dro.get("meta"), dict) else {}
    meta["authored_minimal"] = True
    # WHY-MINIMAL TELEMETRY (2026-07-23, the burning-money rule): the
    # FULL attempt's failure stage+detail rides the DRO so site_config
    # can say exactly why the brain fell back — one organic build
    # diagnoses what paid test builds were burning cash to guess at.
    if isinstance(failure_out, dict) and (failure_out.get("stage")
                                          or failure_out.get("detail")):
        meta["full_failure"] = {
            "stage": str(failure_out.get("stage") or "")[:40],
            "detail": str(failure_out.get("detail") or "")[:300]}
    dro["meta"] = meta
    # No collision regen at this rung (last resort) — but the check block
    # still records honestly how close to the cohort it landed.
    dro["anti_convergence"] = {"distinctiveness_check": run_distinctiveness(dro, recent)}
    logger.warning(f"[drl] minimal-mode DRO authored for {business_id} — "
                   "bland-but-valid fallback (dro_status will be applied_thin)")
    return dro


def _pop_audit_fields(parsed: dict, business_id: str) -> None:
    """Phase 1 (spec 3-D): lift inventions / echo_plan / exception_log out
    of the DRO before schema validation so they can never fail a build
    (enforcement is the Phase-2 judge's job). Logged as the
    exception-register feed. Never raises."""
    try:
        inv = parsed.pop("inventions", None)
        if isinstance(inv, list):
            for i, item in enumerate(inv[:6]):
                logger.info(f"[dro-audit] INVENTION {i + 1} "
                            f"({str(business_id)[:8]}): {str(item)[:220]}")
            # Phase 2: stash the count + the records for the loop's
            # invention check (A4 verifies count AND restatement).
            try:
                from design_register import note_inventions
                note_inventions(business_id, len(inv), texts=inv[:6])
            except Exception:
                pass
        echo = parsed.pop("echo_plan", None)
        if echo:
            logger.info(f"[dro-audit] ECHO_PLAN ({str(business_id)[:8]}): "
                        f"{str(echo)[:220]}")
        exc = parsed.pop("exception_log", None)
        if isinstance(exc, list):
            for item in exc[:6]:
                t = str(item).strip()
                if t and t.lower() != "none":
                    logger.warning(f"[dro-audit] EXCEPTION "
                                   f"({str(business_id)[:8]}): {t[:220]}")
                    # Phase 2: the exception register (vocabulary roadmap).
                    try:
                        from design_register import record_exception
                        record_exception(business_id, "dro", t)
                    except Exception:
                        pass
    except Exception:
        pass


def author_dro(business_id: str, signals: List[Dict[str, Any]],
               recent: List[Dict[str, Any]],
               reference_analysis: Optional[List[Dict[str, Any]]] = None,
               creative: Optional[Dict[str, Any]] = None,
               stance: Optional[str] = None,
               extra_instruction: Optional[str] = None,
               failure_out: Optional[Dict[str, str]] = None,
               owner_direction: Optional[Dict[str, Any]] = None,
               ) -> Optional[Dict[str, Any]]:
    """signals + principles + exemplars + recent signatures (+ Arc 5
    reference-site analysis, + Arc 6 owner creative brief / directions
    stance) → validated DRO. One retry on validation failure; one
    regeneration on distinctiveness collision. `recent` may include the
    sibling candidate DROs of a directions run — the same collision check
    then enforces distinctiveness ACROSS the three candidates.
    `extra_instruction` (Arc 7) appends a caller-supplied directive to the
    authoring prompt — used by the same-business freshness regen.
    `owner_direction` (Interview v3, B4): {"site_prefs": ..., "fonts_pinned":
    bool} — owner-supplied direction evidence; the axes it covers are EXEMPT
    from cohort pressure (no re-roll there, pressure stays on the rest).

    RESILIENCE LADDER: attempt → parse-retry → validation-retry → one
    MINIMAL-MODE attempt (stripped prompt; the result is tagged
    meta.authored_minimal). Returns None only when every rung failed —
    `failure_out` then carries {stage, detail} (never lose the reason).
    NOTE: failure_out may hold the FULL-mode failure even when minimal
    mode rescued the DRO — callers must key off the return value, not
    the presence of a reason."""
    client = _client()
    if not client:
        logger.warning(f"[drl] DRO authoring skipped for {business_id}: "
                       "no ANTHROPIC_API_KEY — DRL client unavailable")
        _set_fail(failure_out, "authoring",
                  "no ANTHROPIC_API_KEY — DRL client unavailable")
        return None
    exemplars = _select_exemplars(signals)
    recent_sigs = [distinctiveness_signature(r) for r in recent]
    # Interview v3 (B4) — axes the owner personally directed are exempt
    # from cohort pressure (computed once; feeds the prompt AND the gate).
    od = owner_direction if isinstance(owner_direction, dict) else {}
    exempt = owner_exempt_axes(
        site_prefs=od.get("site_prefs"),
        reference_analysis=reference_analysis,
        fonts_pinned=bool(od.get("fonts_pinned")))
    exempt_names = [sig.DISTINCTIVENESS_AXES[i] for i in sorted(exempt)]
    system = _dro_system_prompt()
    user = _dro_user_prompt(business_id, signals, exemplars, recent_sigs,
                            reference_analysis=reference_analysis,
                            creative=creative, stance=stance)
    if exempt:
        user += ("\n\nOWNER-EXPLICIT DIRECTION (anti-convergence exemption): "
                 "the owner personally supplied direction evidence on these "
                 f"axes: {', '.join(exempt_names)}. Matching a recent "
                 "signature on THOSE axes is allowed WITHOUT justification — "
                 "never vary them away from the owner's stated direction. "
                 "Anti-convergence pressure still applies to every other axis.")
    # Phase 1 (spec 4-C) — the audit-fields request rides the user turn.
    # The fields are POPPED before schema validation (never build-fatal).
    user += (
        "\n\nAfter the rationale, ALSO include these top-level fields: "
        '"inventions" (list of >=3 objects {addition, builds_on, where} - design '
        "decisions NOT present in the brief; an invention that merely restates "
        'the brief is a failure), "echo_plan" (which accent gets an atmospheric '
        'echo, and where - per the doctrine echo rule), "exception_log" (list of '
        "anything you wanted that the schema cannot express; may be empty but "
        "must be present). If you cannot name three genuine additions, you have "
        "not finished designing."
    )
    if extra_instruction:
        user += "\n\n" + str(extra_instruction)
    last: Dict[str, str] = {}

    def _attempt(extra: str = "") -> Optional[Dict[str, Any]]:
        t0 = time.monotonic()
        try:
            raw = _call(client, system, user + extra, max_tokens=DRO_MAX_TOKENS,
                        temperature=DRO_TEMPERATURE, business_id=business_id,
                        task="dro")
        except Exception as e:
            last["detail"] = (f"DRO call failed after "
                              f"{time.monotonic() - t0:.0f}s "
                              f"({type(e).__name__}): {e}")
            logger.warning(f"[drl] DRO authoring call failed for "
                           f"{business_id}: {last['detail']}")
            return None
        parsed = _parse_json(raw)
        if isinstance(parsed, dict):
            _pop_audit_fields(parsed, business_id)
        if not isinstance(parsed, dict):
            # Diagnose, don't guess: truncation = long raw w/ no closing
            # brace in the tail; refusal/preamble shows in the head.
            r = raw or ""
            last["detail"] = (f"DRO parse failed: len={len(r)} "
                              f"head={r[:60]!r} tail={r[-60:]!r}")
            logger.warning(f"[drl] DRO parse failed for {business_id}: "
                           f"len={len(r)} head={r[:60]!r} tail={r[-60:]!r}")
            return None
        return parsed

    dro = _attempt()
    if dro is None:
        # Parse/call failures get one clean retry too — previously only
        # VALIDATION problems retried, so a single truncated or fenced
        # response hard-failed the whole authoring.
        dro = _attempt(
            "\n\nYour previous response was not parseable JSON. Output ONLY "
            "the complete JSON object — no prose, no code fences — and make "
            "sure the JSON is fully closed.")
    if dro is not None:
        problems = _validate_dro(dro)
        if problems:
            last["detail"] = f"validation problems: {problems}"
            dro = _attempt(
                f"\n\nYour previous DRO had these problems: {problems}. "
                "Fix them. Use only schema enum values; include because + "
                "from_signals on every decision. Output ONLY the JSON.")
    final_problems = _validate_dro(dro) if dro is not None else None
    if dro is None or final_problems:
        if dro is None:
            _set_fail(failure_out, "authoring",
                      last.get("detail") or "call/parse failed on both attempts")
        else:
            _set_fail(failure_out, "validation",
                      f"invalid after retry: {final_problems}")
        logger.warning(
            f"[drl] DRO invalid after retry for {business_id} "
            f"({(failure_out or last).get('detail', 'unknown')}) — "
            "attempting minimal mode")
        return _author_dro_minimal(client, business_id, signals, recent,
                                   failure_out=failure_out)

    # Stamp identity + run distinctiveness; regenerate once on collision.
    dro["dro_version"] = 1
    dro["business_id"] = business_id
    if recent and _collides(dro, recent, exempt=exempt):
        regen = _attempt(
            "\n\nYour DRO shares too many of the 8 distinctiveness axes with a "
            "recent site. Vary at least 2 axes (palette base/accent/temperature, "
            "display personality, layout symmetry/density, motion, hero direction) "
            "ONLY where the signals still support it."
            + (f" Axes {', '.join(exempt_names)} are owner-explicit direction — "
               "do NOT move those."
               if exempt else "")
            + " Output ONLY the JSON.")
        if regen is not None and not _validate_dro(regen):
            regen["dro_version"] = 1
            regen["business_id"] = business_id
            regen["anti_convergence"] = {"distinctiveness_check": {
                **run_distinctiveness(regen, recent, exempt=exempt),
                "verdict": "regenerated_once"}}
            return regen
        # Collision-regen chain: NOT fatal (the valid original ships), but
        # the forensics must show the chain was attempted and why it bent.
        logger.warning(
            f"[drl] collision regen failed for {business_id} "
            f"({last.get('detail') or 'invalid regen'}) — keeping the "
            "original (collision-flagged) DRO")

    dro["anti_convergence"] = {"distinctiveness_check": run_distinctiveness(dro, recent, exempt=exempt)}
    return dro


# ─── Persistence (service role) ──────────────────────────────────────────
def fetch_recent_dros(business_id: str, n: int = sig.DISTINCTIVENESS_COHORT_N) -> List[Dict[str, Any]]:
    """Last-N DROs platform-wide, this business first (per-business double
    weight, spec fork F4). Returns the stored `dro` blobs with id stamped."""
    out: List[Dict[str, Any]] = []
    try:
        mine = sb_clients.sb_get_as_service(
            f"/design_rationales?business_id=eq.{business_id}"
            f"&select=id,dro&order=created_at.desc&limit={n}") or []
        recent = sb_clients.sb_get_as_service(
            f"/design_rationales?select=id,dro&order=created_at.desc&limit={n}") or []
    except Exception as e:
        logger.warning(f"[drl] fetch_recent_dros failed for {business_id}: {e}")
        return []
    seen = set()
    for row in list(mine) + list(recent):          # mine first = double weight
        rid = row.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        blob = row.get("dro") or {}
        if isinstance(blob, dict):
            blob.setdefault("id", rid)
            out.append(blob)
        if len(out) >= n:
            break
    return out


def fetch_own_last_dro(business_id: str) -> Optional[Dict[str, Any]]:
    """The business's OWN most recent stored DRO (the design behind its
    current live site), or None. Arc 7 same-business freshness reads this
    directly — fetch_recent_dros mixes in the platform cohort, which lets
    a recompose share 5/8 axes with ITSELF and still pass _collides."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/design_rationales?business_id=eq.{business_id}"
            "&select=id,dro&order=created_at.desc&limit=1") or []
    except Exception as e:
        logger.warning(f"[drl] fetch_own_last_dro failed for {business_id}: {e}")
        return None
    blob = rows[0].get("dro") if rows else None
    return blob if isinstance(blob, dict) else None


def persist_dro(business_id: str, dro: Dict[str, Any]) -> Optional[str]:
    """Insert into design_rationales; return the new row id."""
    try:
        rows = sb_clients.sb_post_as_service(
            "/design_rationales", {"business_id": business_id, "dro": dro})
        if isinstance(rows, list) and rows:
            return rows[0].get("id")
    except Exception as e:
        logger.warning(f"[drl] persist_dro failed for {business_id}: {e}")
    return None


# ─── Orchestrator ────────────────────────────────────────────────────────
def produce_dro(business_id: str, transcript: str,
                reference_analysis: Optional[List[Dict[str, Any]]] = None,
                creative: Optional[Dict[str, Any]] = None,
                owner_direction: Optional[Dict[str, Any]] = None,
                ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    """Full pass: detect signals → fetch recent → author DRO (with
    distinctiveness) → persist. Returns (dro, failure): the DRO (with `id`
    stamped) and None, or None and {"stage": "signals|authoring|validation|
    exception", "detail": str} — failure forensics so a fallback compose is
    never a mystery (site_composer persists it as site_config.dro_failure).
    Best-effort: never raises into the caller (PR3 wires this ahead of compose).
    `reference_analysis` (Arc 5) = reference_analyzer results for the sites
    the owner admires — rides into the authoring prompt as direction evidence.
    `creative` (Arc 6) = sanitized design_prefs.creative — the owner's
    creative brief, quoted verbatim at highest priority in the authoring
    prompt. (The directions engine calls detect_signals/author_dro directly
    so it can share one signal pass across three candidates and defer
    persistence to the choose step.)

    Arc 7 additions (single-compose path only — directions bypass this):
      - same-business freshness: the fresh DRO is compared against the
        business's OWN last DRO on the 8 distinctiveness axes; >= 5 shared
        triggers ONE regen naming the repeated axes (accept whatever comes
        back — no loop).
      - the returned DRO carries `consumable_signal_count` (runtime-only,
        stamped AFTER persist) so compose_site can report 'applied_thin'
        when the rationale ran on a thin brief."""
    try:
        # Site Arc 12 — startup model probe (once per process): a
        # misconfigured DRL/atelier model shows up in the logs as
        # '[model-probe] … unreachable' before the first silent fallback.
        try:
            import atelier as _atelier_mod
            model_ladder.probe_models_once(
                [_drl_model(), _atelier_mod._model()])
        except Exception:
            model_ladder.probe_models_once([_drl_model()])

        sig_fail: Dict[str, str] = {}
        auth_fail: Dict[str, str] = {}
        signals = detect_signals(business_id, transcript, failure_out=sig_fail)
        # THE INTERVIEW BRIDGE (2026-07-22): the owner's interview answers
        # become practitioner_set signals — the transcript detector alone
        # left interview-driven builds starved to applied_thin forever.
        # Detected signals keep priority per id; the bridge fills gaps.
        try:
            _prefs = ((owner_direction or {}).get("site_prefs")
                      if isinstance(owner_direction, dict) else None) or {}
            _have = {s.get("signal_id") for s in signals}
            _bridged = [s for s in sig.signals_from_prefs(_prefs)
                        if s["signal_id"] not in _have]
            if _bridged:
                signals = signals + _bridged
                logger.info(f"[drl] interview bridge added "
                            f"{len(_bridged)} practitioner_set signals")
        except Exception as _be:
            logger.warning(f"[drl] interview bridge failed open: {_be}")
        consumable_n = sum(
            1 for s in signals
            if isinstance(s.get("confidence"), (int, float))
            and sig.is_consumable(s["confidence"]))
        recent = fetch_recent_dros(business_id)
        dro = author_dro(business_id, signals, recent,
                         reference_analysis=reference_analysis,
                         creative=creative, failure_out=auth_fail,
                         owner_direction=owner_direction)
        if dro is None:
            failure = {
                "stage": auth_fail.get("stage") or "authoring",
                "detail": (auth_fail.get("detail")
                           or "author_dro returned None")}
            if sig_fail.get("detail"):
                # Signal failure alone never causes fallback (authoring
                # proceeds on []), but it belongs in the forensics.
                failure["detail"] = (f"signals: {sig_fail['detail']} | "
                                     f"{failure['detail']}")[:300]
            logger.warning(f"[drl] produce_dro fallback for {business_id}: "
                           f"stage={failure['stage']} {failure['detail']}")
            return None, failure

        # Same-business freshness (runs BEFORE persist, so own-last is
        # genuinely the previous compose). Deterministic palette/ground/
        # font pins make the shell identical when the axes repeat — this
        # is the "recompose looks exactly the same" guard.
        own_last = fetch_own_last_dro(business_id)
        if own_last is not None:
            mine = distinctiveness_signature(dro)
            prev = distinctiveness_signature(own_last)
            repeated = [axis for axis, m, p in
                        zip(sig.DISTINCTIVENESS_AXES, mine, prev)
                        if m is not None and m == p]
            if len(repeated) >= OWN_REPEAT_AXES_THRESHOLD:
                logger.info(
                    f"[drl] same-business repeat for {business_id}: new DRO "
                    f"shares {len(repeated)}/8 axes with own last "
                    f"({repeated}) — regenerating once")
                regen = author_dro(
                    business_id, signals, recent,
                    reference_analysis=reference_analysis, creative=creative,
                    owner_direction=owner_direction,
                    extra_instruction=(
                        "IMPORTANT — FRESHNESS: this design repeats the "
                        f"business's CURRENT live site on {len(repeated)} of "
                        f"the 8 distinctiveness axes ({', '.join(repeated)}). "
                        "Vary at least 2 of those axes while honoring the "
                        "signals and the owner's stated constraints. "
                        "Output ONLY the JSON."))
                if regen is not None:
                    now_shared = sum(
                        1 for m, p in zip(distinctiveness_signature(regen), prev)
                        if m is not None and m == p)
                    logger.info(
                        f"[drl] same-business regen accepted for {business_id}: "
                        f"now shares {now_shared}/8 axes with own last "
                        f"(was {len(repeated)}/8)")
                    dro = regen
                else:
                    logger.info(
                        f"[drl] same-business regen failed for {business_id} — "
                        f"keeping the original DRO ({len(repeated)}/8 shared)")

        dro_id = persist_dro(business_id, dro)
        if dro_id:
            dro["id"] = dro_id
        # Runtime-only metadata (never persisted): feeds the honest
        # thin-brief status in compose_site.
        dro["consumable_signal_count"] = consumable_n
        return dro, None
    except Exception as e:
        logger.warning(f"[drl] produce_dro failed for {business_id}: "
                       f"({type(e).__name__}) {e}")
        return None, {"stage": "exception",
                      "detail": f"{type(e).__name__}: {e}"[:300]}
