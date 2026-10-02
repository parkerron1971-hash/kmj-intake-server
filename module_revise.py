"""
module_revise.py — the builder acts on the designer's verdict.

module_check looks at a module and says what would make it excellent:
a hero stat, a milestone label, a warmer tone, an empty line that says
something. This is the hand that makes the change. It may touch ONLY
the two things the practitioner never typed and the surface renders
deterministically — `presentation` (empty_line, reached_line,
milestone_labels, tone) and `archetype_params` (which fields feed the
hero, the stages, the blocks on a dashboard). Never the fields, never
the rows. A revision is validated through the same ModuleSpec model a
new proposal goes through, applied, looked at again, and KEPT only if
the score went up — otherwise put back exactly as it was.

One model call, one re-look. The loop closes here.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("module_revise")

REVISE_BELOW = 4            # a 4/5 or better is left alone
MAX_CHANGES = 6

# What the reviser may change, per surface — in its own words, so the
# model reasons about a real lever instead of inventing a field.
_LEVERS = {
    "work_pipeline": (
        "archetype_params: value_field (the currency/number field that becomes the "
        "'$X in play' hero and the card price), title_field, contact_field, date_field, "
        "location_field, item_noun, stages[{id,label,done}] (labels and order only — never "
        "drop a stage that rows use)."),
    "progress_tracker": (
        "archetype_params: milestones (numbers between start and target), target, unit, "
        "item_noun, subject_noun, direction. presentation.milestone_labels ('620': 'Fair'), "
        "presentation.reached_line."),
    "composed_dashboard": (
        "archetype_params.blocks — reorder, relabel, add or drop blocks (kinds: stat, series, "
        "breakdown, progress, recent, upcoming, notes, list, board, calendar; 2 to 8 blocks; the "
        "first block is the hero — make it the one number they check first), block.label, "
        "block.window, block.target, block.where; title_field, date_field, item_noun."),
    "event_roster": "archetype_params: roles[] labels and needed counts, item_noun; presentation.empty_line.",
    "agreement_ledger": "archetype_params: item_noun, the field roles; presentation.empty_line.",
    "booking_calendar": "presentation.empty_line, presentation.tone; archetype_params.item_noun only.",
    "fallback_generic": "presentation.empty_line and presentation.tone only — the generic surface has no levers; say so in why.",
}

_SYSTEM = """You are revising ONE module surface in a small-business app after a designer
reviewed screenshots of it. You get the module as built (its fields, its
archetype and parameters, its presentation), the designer's verdict (score,
first impression, findings, next moves) and the levers you are allowed to
pull. Make the smallest set of changes that answers the next moves.

HARD RULES
- Change only `presentation` and `archetype_params`. Never invent a field:
  every *_field value and every block.field must be a field NAME from the
  module's schema (given). Never remove a stage or a block that rows depend
  on. Keep every value that already works.
- Presentation lines are for the practitioner, in their trade's words, one
  sentence, no software words. tone is one of: calm, bold, warm, precise.
  milestone_labels and reached_line belong to progress_tracker ONLY (keys are
  the milestone NUMBERS as strings); every other surface has empty_line and tone.
- Return the COMPLETE archetype_params and COMPLETE presentation objects
  (not a diff), plus `why` (one sentence) and `changes` (a short list of
  what you changed, in plain words). If nothing you may change would help,
  return {"unchanged": true, "why": "..."}.

Output STRICT JSON only:
{"archetype_params": {...}, "presentation": {...}, "why": "...", "changes": ["..."]}
"""


def _fields_block(module: Dict[str, Any]) -> str:
    out = []
    for f in ((module.get("schema") or {}).get("fields") or []):
        if not isinstance(f, dict) or not f.get("name"):
            continue
        extra = ""
        if f.get("options"):
            extra = " options=" + "/".join(str(o) for o in f["options"][:8])
        out.append(f"  - {f['name']} ({f.get('type', 'text')}){extra}  label='{f.get('label', '')}'")
    return "\n".join(out) or "  (no fields)"


def _user(module: Dict[str, Any], report: Dict[str, Any]) -> str:
    arch = module.get("archetype") or "fallback_generic"
    findings = "\n".join(
        f"  - [{f.get('severity')}] {f.get('what')} ({f.get('where')}, {f.get('width')}px)"
        for f in (report.get("findings") or [])[:8]) or "  (none)"
    nxt = "\n".join(f"  - {n}" for n in (report.get("next") or [])) or "  (none)"
    return (
        f"MODULE: {module.get('name')} (archetype {arch})\n"
        f"FIELDS:\n{_fields_block(module)}\n"
        f"CURRENT archetype_params: {json.dumps(module.get('archetype_params') or {}, ensure_ascii=False)}\n"
        f"CURRENT presentation: {json.dumps(module.get('presentation') or {}, ensure_ascii=False)}\n\n"
        f"DESIGNER'S VERDICT: design {report.get('design_score')}/5\n"
        f"First impression: {report.get('first_impression') or '(none)'}\n"
        f"Findings:\n{findings}\n"
        f"Next moves:\n{nxt}\n\n"
        f"LEVERS YOU MAY PULL for {arch}: {_LEVERS.get(arch, _LEVERS['fallback_generic'])}\n\n"
        f"Return the JSON now."
    )


def validate(module: Dict[str, Any], params: Dict[str, Any],
             presentation: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any], Dict[str, Any]]:
    """Run the revision through the same ModuleSpec model a new proposal
    passes: field refs, stage shapes, block kinds, presentation lines.
    Returns (ok, error, normalized_params, normalized_presentation)."""
    import module_spec_generator as msg
    try:
        spec = msg.ModuleSpec(
            slug=str(module.get("slug") or "module"), name=str(module.get("name") or "Module"),
            description=str(module.get("description") or "revised"), intake_excerpt="module_revise",
            schema=module.get("schema") or {"fields": []}, reasoning="module_revise",
            archetype=str(module.get("archetype") or "fallback_generic"),
            archetype_params=params or {}, presentation=presentation or {},
            archetype_fallback_reason=module.get("archetype_fallback_reason") or (
                "kept" if (module.get("archetype") or "fallback_generic") == "fallback_generic" else None),
        )
    except Exception as e:
        return False, str(e)[:300], {}, {}
    pres = spec.presentation.model_dump(exclude_none=True)
    if not pres.get("milestone_labels"):
        pres.pop("milestone_labels", None)          # the model's empty default is not a change
    return True, "", spec.archetype_params, pres


# Presentation keys that only one surface draws. A reviser that writes
# milestone labels for a pipeline (first live loop: stage names as keys)
# has misread the lever, not broken a rule — the key is dropped, not the
# whole revision.
_TRACKER_ONLY = ("milestone_labels", "reached_line")


def _is_number(k: Any) -> bool:
    try:
        float(str(k))
        return True
    except ValueError:
        return False


def sanitize_presentation(archetype: str, pres: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in (pres or {}).items()
           if k in ("empty_line", "reached_line", "milestone_labels", "tone")}
    if archetype != "progress_tracker":
        for k in _TRACKER_ONLY:
            out.pop(k, None)
    if isinstance(out.get("milestone_labels"), dict):
        out["milestone_labels"] = {k: v for k, v in out["milestone_labels"].items() if _is_number(k)}
    return out


def _ask(client, model: str, user: str) -> Dict[str, Any]:
    import module_spec_generator as msg
    m = client.messages.create(model=model, max_tokens=4000, system=_SYSTEM,
                               messages=[{"role": "user", "content": user}])
    raw = "".join(b.text for b in m.content if getattr(b, "type", None) == "text")
    data = json.loads(msg._strip_code_fence(raw))
    if not isinstance(data, dict):
        raise ValueError("reviser returned no object")
    return data


def propose(module: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    """One model call (two if the first was refused) → a validated
    revision, or an honest no."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
    arch = str(module.get("archetype") or "fallback_generic")
    try:
        import llm_call
        import module_spec_generator as msg
        client = llm_call.sdk_client(key=key)
        user = _user(module, report)
        data = _ask(client, msg.GENERATOR_MODEL, user)
    except Exception as e:
        return {"ok": False, "error": f"reviser_failed: {type(e).__name__}: {str(e)[:160]}"}
    if data.get("unchanged"):
        return {"ok": True, "unchanged": True, "why": str(data.get("why") or "")[:200]}
    params = data.get("archetype_params")
    pres = data.get("presentation")
    if not isinstance(params, dict) or not isinstance(pres, dict):
        return {"ok": False, "error": "reviser returned no params/presentation"}
    ok, err, nparams, npres = validate(module, params, sanitize_presentation(arch, pres))
    if not ok:
        # One more try, with the validator's reason in front of it.
        try:
            data = _ask(client, msg.GENERATOR_MODEL,
                        user + f"\n\nYOUR PREVIOUS ANSWER WAS REFUSED: {err}\nFix exactly that and return the JSON again.")
        except Exception as e:
            return {"ok": False, "error": f"revision_invalid: {err} (retry failed: {type(e).__name__})"}
        if data.get("unchanged"):
            return {"ok": True, "unchanged": True, "why": str(data.get("why") or "")[:200]}
        params = data.get("archetype_params")
        pres = data.get("presentation")
        if not isinstance(params, dict) or not isinstance(pres, dict):
            return {"ok": False, "error": f"revision_invalid: {err}"}
        ok, err, nparams, npres = validate(module, params, sanitize_presentation(arch, pres))
        if not ok:
            return {"ok": False, "error": f"revision_invalid: {err}"}
    before = {"archetype_params": module.get("archetype_params") or {},
              "presentation": module.get("presentation") or {}}
    if nparams == before["archetype_params"] and npres == before["presentation"]:
        return {"ok": True, "unchanged": True, "why": "nothing to change"}
    return {"ok": True, "unchanged": False, "archetype_params": nparams, "presentation": npres,
            "why": str(data.get("why") or "")[:200],
            "changes": [str(c)[:120] for c in (data.get("changes") or [])][:MAX_CHANGES],
            "before": before}


def apply(module_id: str, params: Dict[str, Any], presentation: Dict[str, Any]) -> bool:
    import sb_clients
    row = sb_clients.sb_patch_as_service(
        f"/custom_modules?id=eq.{module_id}",
        {"archetype_params": params, "presentation": presentation})
    return bool(row)
