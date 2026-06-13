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
# any error (never raises into the caller). NOT consumed by the composer yet
# — PR3 wires the DRO into compose. All DB access is service role.
# ═══════════════════════════════════════════════════════════════════════

import json
import os
import logging
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

import sb_clients
from agents.composer.hero_composer import _strip_code_fence
from agents.composer import drl
from agents.composer.drl import signals as sig

logger = logging.getLogger("drl.passes")

DRL_MODEL = "claude-sonnet-4-5-20250929"     # same tier as the composer
SIGNAL_MAX_TOKENS = 1800
SIGNAL_TEMPERATURE = 0.2                       # extraction — low/deterministic
DRO_MAX_TOKENS = 3000
DRO_TEMPERATURE = 0.4                          # reasoning with creative latitude


# ─── LLM plumbing ──────────────────────────────────────────────────────
def _client() -> Optional[Anthropic]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    return Anthropic(api_key=key) if key else None


def _call(client: Anthropic, system: str, user: str, *, max_tokens: int,
          temperature: float, business_id: str, task: str) -> str:
    msg = client.messages.create(
        model=DRL_MODEL, max_tokens=max_tokens, temperature=temperature,
        system=system, messages=[{"role": "user", "content": user}],
    )
    try:
        from api_usage_logger import log_api_usage_sync
        u = getattr(msg, "usage", None)
        log_api_usage_sync(
            endpoint=f"/composer/drl/{task}", model=DRL_MODEL,
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


def _validate_dro(dro: Any) -> List[str]:
    """Light structural validation → list of problems (empty = valid).
    Checks required decisions, because/from_signals on each, and enum
    membership for the fields the schema constrains."""
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


def detect_signals(business_id: str, transcript: str) -> List[Dict[str, Any]]:
    """Transcript/context → signals[]. Soft-fails to [] (the authoring pass
    can still proceed conservatively)."""
    client = _client()
    if not client or not (transcript or "").strip():
        return []
    user = f"Practitioner intake material for business {business_id}:\n\n{transcript.strip()[:8000]}"
    try:
        raw = _call(client, _signal_system_prompt(), user,
                    max_tokens=SIGNAL_MAX_TOKENS, temperature=SIGNAL_TEMPERATURE,
                    business_id=business_id, task="signals")
    except Exception as e:
        logger.warning(f"[drl] signal detection call failed for {business_id}: {e}")
        return []
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return []
    out = parsed.get("signals")
    if not isinstance(out, list):
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


def _shared_axes(a: List[Any], b: List[Any]) -> int:
    return sum(1 for x, y in zip(a, b) if x is not None and x == y)


def run_distinctiveness(dro: Dict[str, Any],
                        recent: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare against recent DRO signatures; return the distinctiveness_check
    block. Verdict 'regenerated_once' is set by the caller after a regen."""
    mine = distinctiveness_signature(dro)
    worst = 0
    nearest_ids: List[str] = []
    for r in recent:
        shared = _shared_axes(mine, distinctiveness_signature(r))
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
        "notes": f"nearest shares {worst}/8 axes" + (f" with {nearest_ids[0]}" if nearest_ids else ""),
    }


def _collides(dro: Dict[str, Any], recent: List[Dict[str, Any]]) -> bool:
    mine = distinctiveness_signature(dro)
    return any(_shared_axes(mine, distinctiveness_signature(r)) >= sig.DISTINCTIVENESS_COLLISION_THRESHOLD
               for r in recent)


# ─── Pass 2: DRO authoring ───────────────────────────────────────────────
def _dro_system_prompt() -> str:
    return (
        "You are a lead designer authoring a Design Rationale Object (DRO) — "
        "the REASONING for a website's design, written BEFORE any HTML exists. "
        "You decide DIRECTION, never concrete assets: no hex codes, no font "
        "names (those resolve downstream). Use ONLY the enum values from the "
        "schema.\n\n"
        "Every decision MUST carry a one-line `because` and `from_signals` "
        "(the signal_ids that drove it) — that is the trust contract. When two "
        "principles collide, name the collision and the winner in `because`.\n\n"
        "Apply the translation principles below as MOVES, not lookups. Avoid "
        "the banned defaults (generic display fonts, purple-gradient SaaS look, "
        "the centered-hero+3-cards+CTA skeleton, stock-photo cliches, decorative "
        "accent when accent_strategy=single_semantic). Vary from the recent "
        "signatures where signals permit — but signal-fit always beats variety.\n\n"
        "=== TRANSLATION PRINCIPLES ===\n" + drl.load_principles()
    )


def _dro_user_prompt(business_id: str, signals: List[Dict[str, Any]],
                     exemplars: List[Dict[str, Any]],
                     recent_signatures: List[List[Any]]) -> str:
    consumable = [s for s in signals
                  if isinstance(s.get("confidence"), (int, float))
                  and sig.is_consumable(s["confidence"])]
    return (
        f"BUSINESS: {business_id}\n\n"
        f"DETECTED SIGNALS (only these drive design; confidence<{sig.CONSUME_THRESHOLD} "
        f"recorded but not consumed):\n{json.dumps(consumable, indent=2)}\n\n"
        f"CONTRASTING EXEMPLARS (learn the MOVE, never copy the surface):\n"
        f"{json.dumps([_exemplar_for_prompt(e) for e in exemplars], indent=2)}\n\n"
        f"RECENTLY-USED 8-AXIS SIGNATURES (justify any repetition from signals; "
        f"axes order = {sig.DISTINCTIVENESS_AXES}):\n{json.dumps(recent_signatures, indent=2)}\n\n"
        "OUTPUT ONLY the DRO as JSON: "
        '{"dro_version":1,"business_id":"...","signals":[...echo the consumed signals...],'
        '"decisions":{"palette":{...},"typography":{...},"layout":{...},"motion":{...},'
        '"hero_concept":{...},"whitespace":{...},"voice_to_visual":{...}},'
        '"anti_convergence":{"distinctiveness_check":{}},'
        '"summary_for_practitioner":"plain-language why-your-site-looks-this-way",'
        '"exemplars_consulted":[{"exemplar_id":"..","borrowed":"the move, named"}]}'
    )


def author_dro(business_id: str, signals: List[Dict[str, Any]],
               recent: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """signals + principles + exemplars + recent signatures → validated DRO.
    One retry on validation failure; one regeneration on distinctiveness
    collision. Returns None on hard failure (caller decides fallback)."""
    client = _client()
    if not client:
        return None
    exemplars = _select_exemplars(signals)
    recent_sigs = [distinctiveness_signature(r) for r in recent]
    system = _dro_system_prompt()
    user = _dro_user_prompt(business_id, signals, exemplars, recent_sigs)

    def _attempt(extra: str = "") -> Optional[Dict[str, Any]]:
        try:
            raw = _call(client, system, user + extra, max_tokens=DRO_MAX_TOKENS,
                        temperature=DRO_TEMPERATURE, business_id=business_id, task="dro")
        except Exception as e:
            logger.warning(f"[drl] DRO authoring call failed for {business_id}: {e}")
            return None
        parsed = _parse_json(raw)
        return parsed if isinstance(parsed, dict) else None

    dro = _attempt()
    if dro is not None:
        problems = _validate_dro(dro)
        if problems:
            dro = _attempt(
                f"\n\nYour previous DRO had these problems: {problems}. "
                "Fix them. Use only schema enum values; include because + "
                "from_signals on every decision. Output ONLY the JSON.")
    if dro is None or _validate_dro(dro):
        logger.warning(f"[drl] DRO invalid after retry for {business_id}")
        return None

    # Stamp identity + run distinctiveness; regenerate once on collision.
    dro["dro_version"] = 1
    dro["business_id"] = business_id
    if recent and _collides(dro, recent):
        regen = _attempt(
            "\n\nYour DRO shares too many of the 8 distinctiveness axes with a "
            "recent site. Vary at least 2 axes (palette base/accent/temperature, "
            "display personality, layout symmetry/density, motion, hero direction) "
            "ONLY where the signals still support it. Output ONLY the JSON.")
        if regen is not None and not _validate_dro(regen):
            regen["dro_version"] = 1
            regen["business_id"] = business_id
            regen["anti_convergence"] = {"distinctiveness_check": {
                **run_distinctiveness(regen, recent), "verdict": "regenerated_once"}}
            return regen

    dro["anti_convergence"] = {"distinctiveness_check": run_distinctiveness(dro, recent)}
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
def produce_dro(business_id: str, transcript: str) -> Optional[Dict[str, Any]]:
    """Full pass: detect signals → fetch recent → author DRO (with
    distinctiveness) → persist. Returns the DRO (with `id` stamped) or None.
    Best-effort: never raises into the caller (PR3 wires this ahead of compose)."""
    try:
        signals = detect_signals(business_id, transcript)
        recent = fetch_recent_dros(business_id)
        dro = author_dro(business_id, signals, recent)
        if dro is None:
            return None
        dro_id = persist_dro(business_id, dro)
        if dro_id:
            dro["id"] = dro_id
        return dro
    except Exception as e:
        logger.warning(f"[drl] produce_dro failed for {business_id}: {e}")
        return None
