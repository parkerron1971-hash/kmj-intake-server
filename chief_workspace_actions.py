"""
chief_workspace_actions.py — Chief's verbs for the workspace composer.

Phase one gives Chief exactly one decision: read the intake answers and pick
which of five hand-authored workspaces this business gets. It does not
compose layouts, it does not author blocks, and it cannot invent a sixth
archetype — `workspace_layouts.ARCHETYPES` is a closed set and every path
here goes through it.

Three verbs:

  choose_workspace     classify from the intake answers, persist, and say
                       what it chose AND why
  switch_workspace     the override. One tap, always available, and it
                       keeps every terminology row the practitioner set
  rename_term          set a term and stamp it `user_override`, which makes
                       it permanent against every automatic write after it

Practitioner-facing wording, per the Chief doctrine: no archetype slugs, no
primitive names, no talk of schemas, presets or validators. The practitioner
asked for a workspace that fits their business; they are not being handed a
configuration screen.

Every handler returns both `result` and `label` — a missing `result` blanks
the app on a toLowerCase call.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sb_clients
import workspace_archetypes
import workspace_layout_validator as validator
import workspace_layouts

logger = logging.getLogger("chief_workspace_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    logger.info(f"Action {action_type} failed: {msg}")
    return {
        "type": action_type,
        "result": msg,
        "label": action_type,
        "nav": None,
        "failed": True,
    }


def _nav_workspace() -> Dict[str, Any]:
    return {"tab": "home"}


def _profile(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/business_profiles?business_id=eq.{business_id}"
        f"&select=business_id,workspace_archetype,workspace_terminology&limit=1"
    ) or []
    if rows:
        return rows[0]
    created = sb_clients.sb_post_as_service(
        "/business_profiles", {"business_id": business_id}
    )
    if isinstance(created, list) and created:
        return created[0]
    return {"business_id": business_id}


def _persist(business_id: str, archetype: str, stored_terms: Dict[str, Any]
             ) -> Dict[str, Any]:
    """Build the layout, then hand the WRITE to the composer's `_persist`,
    which validates, writes, and proves the write actually landed.

    This function used to duplicate that logic line for line, and the
    duplicate is exactly how the silent-write bug survived as long as it
    did: the archetype CHECK rejected `therapist` and `nonprofit`,
    `sb_clients` swallowed the 4xx and returned None, and BOTH copies
    ignored it. Fixing one would have left this one — the copy Chief
    actually calls — still telling practitioners their choice was saved
    when it was not.

    One write path now. There is no second place to forget.

    Chief catches whatever a handler raises and turns it into a visible
    failure line, so raising here is the right move: the practitioner
    learns their choice did not stick, instead of being quietly asked to
    choose again on every load.
    """
    import workspace_composer_router as composer

    layout = composer.build_layout(archetype, stored_terms)
    try:
        composer._persist(business_id, archetype, layout)
    except HTTPException as exc:
        # Re-worded because Chief renders this straight to the
        # practitioner, and "500:" is not a sentence anyone should read.
        raise RuntimeError(
            "I could not save that workspace, so nothing was changed. "
            "This has been logged — I would rather tell you than let you "
            "think it worked."
        ) from exc
    return layout


def _shape_line(layout: Dict[str, Any]) -> str:
    """One sentence describing what the practitioner is about to see, in
    their language rather than the registry's."""
    lead = next((s for s in layout.get("surfaces") or []
                 if s.get("role") == "lead"), None)
    if not lead:
        return ""
    others = [s["title"] for s in layout.get("surfaces") or []
              if s.get("role") != "lead" and s.get("title")]
    line = f"Your home screen opens on {lead.get('title', 'your work')}"
    if others:
        line += f", with {' and '.join(others)} underneath"
    return line + "."


# ─── choose ──────────────────────────────────────────────────────────

async def handle_choose_workspace(client, biz, action) -> Dict[str, Any]:
    """Classify this business from what it told us at intake, and build the
    workspace that fits.

    action: {answers?: {...}} — anything the intake collected. The business
    type is always folded in from the record, so the caller cannot claim to
    be a different kind of business than it is.
    """
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("choose_workspace", "no business on record")

    answers = action.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    answers = dict(answers)
    answers.setdefault("vertical", biz.get("type"))
    # Whatever the practitioner wrote about themselves at signup is the
    # best free-text evidence we have; the classifier reads these keys.
    for src, dst in (("description", "description"), ("summary", "summary")):
        if biz.get(src) and not answers.get(dst):
            answers[dst] = biz[src]

    decision = workspace_archetypes.classify(answers)
    profile = _profile(business_id)
    stored_terms = profile.get("workspace_terminology") or {}

    try:
        layout = _persist(business_id, decision["archetype"], stored_terms)
    except validator.LayoutValidationError as e:
        logger.error("preset failed validation: %s", e.errors)
        return _fail("choose_workspace",
                     "I couldn't set that workspace up just now — try again in a moment.")

    parts: List[str] = [workspace_archetypes.narrate(decision)]
    shape = _shape_line(layout)
    if shape:
        parts.append(shape)

    return {
        "type": "choose_workspace",
        "result": "\n\n".join(parts),
        "label": f"Set up as {decision['label']}",
        "nav": _nav_workspace(),
        "archetype": decision["archetype"],
        "confidence": decision["confidence"],
        "alternatives": [
            {"archetype": a["archetype"], "label": a["label"]}
            for a in decision["alternatives"]
            if a["archetype"] != decision["archetype"]
        ],
    }


# ─── override ────────────────────────────────────────────────────────

# What the practitioner is likely to say, mapped to the closed set. Chief
# never asks them to learn the slug.
_SPOKEN = {
    "salon": "salon", "barber": "salon", "barbershop": "salon",
    "hair": "salon", "spa": "salon", "chair": "salon", "chairs": "salon",
    "law": "law_firm", "law firm": "law_firm", "lawyer": "law_firm",
    "attorney": "law_firm", "legal": "law_firm", "docket": "law_firm",
    "matters": "law_firm",
    "church": "ministry", "ministry": "ministry", "congregation": "ministry",
    "parish": "ministry", "nonprofit": "ministry",
    "consultant": "consultant", "consulting": "consultant",
    "coach": "consultant", "coaching": "consultant", "advisory": "consultant",
    "engagements": "consultant",
    "trades": "trades", "contractor": "trades", "contracting": "trades",
    "crew": "trades", "crews": "trades", "jobs": "trades",
    "home services": "trades",
}


def _resolve_spoken(raw: str) -> Optional[str]:
    key = (raw or "").strip().lower()
    if not key:
        return None
    if key in workspace_layouts.ARCHETYPES:
        return key
    if key in _SPOKEN:
        return _SPOKEN[key]
    # Longest-match containment, so "we're more of a barber shop really"
    # still lands. Longest first, or "law" inside "lawyer" wins by accident.
    for phrase in sorted(_SPOKEN, key=len, reverse=True):
        if phrase in key:
            return _SPOKEN[phrase]
    return None


async def handle_switch_workspace(client, biz, action) -> Dict[str, Any]:
    """The override, spoken. "Actually we're more like a barbershop" has to
    work as well as tapping the picker does.

    action: {archetype: str} — a slug or whatever the practitioner called it.
    """
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("switch_workspace", "no business on record")

    raw = (action.get("archetype") or action.get("to")
           or action.get("workspace") or "")
    archetype = _resolve_spoken(str(raw))
    if not archetype:
        options = ", ".join(
            a["label"] for a in workspace_layouts.summaries()
        )
        return _fail(
            "switch_workspace",
            f"I'm not sure which setup you mean. I can build any of these: {options}.",
        )

    profile = _profile(business_id)
    previous = profile.get("workspace_archetype")
    stored_terms = profile.get("workspace_terminology") or {}

    if previous == archetype:
        preset = workspace_layouts.get_preset(archetype)
        return {
            "type": "switch_workspace",
            "result": f"You're already set up as a {preset['label']}, so nothing changed.",
            "label": f"Already a {preset['label']}",
            "nav": _nav_workspace(),
            "archetype": archetype,
        }

    try:
        layout = _persist(business_id, archetype, stored_terms)
    except validator.LayoutValidationError as e:
        logger.error("preset failed validation: %s", e.errors)
        return _fail("switch_workspace",
                     "I couldn't rebuild that workspace just now — try again in a moment.")

    kept = [k for k, v in (layout.get("terminology") or {}).items()
            if v.get("origin") == "user_override"]

    parts = [f"Rebuilt as a {layout['label']}.", layout["rationale"]]
    shape = _shape_line(layout)
    if shape:
        parts.append(shape)
    if kept:
        words = ", ".join(sorted({v["value"] for k, v in
                                  (layout.get("terminology") or {}).items()
                                  if v.get("origin") == "user_override"}))
        parts.append(f"I kept the words you chose — {words}.")

    return {
        "type": "switch_workspace",
        "result": "\n\n".join(parts),
        "label": f"Switched to {layout['label']}",
        "nav": _nav_workspace(),
        "archetype": archetype,
        "previous_archetype": previous,
        "kept_overrides": kept,
    }


# ─── terminology ─────────────────────────────────────────────────────

async def handle_rename_term(client, biz, action) -> Dict[str, Any]:
    """Rename what something is called, permanently.

    Once the practitioner has said what they call a thing, nothing
    overwrites it — not a re-classification, not switching archetype, not a
    preset refresh. That is the point of the verb, and it is why the row is
    stamped rather than merged.

    action: {term: "project", value: "Case"} or {terms: {...}}
    """
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("rename_term", "no business on record")

    updates: Dict[str, Any] = {}
    if isinstance(action.get("terms"), dict):
        updates.update(action["terms"])
    single = (action.get("term") or action.get("key") or "").strip()
    if single:
        updates[single] = action.get("value") or action.get("to")

    updates = {k.strip().lower(): v for k, v in updates.items() if (k or "").strip()}
    if not updates:
        return _fail("rename_term", "tell me which word you want to change, and to what")

    profile = _profile(business_id)
    archetype = profile.get("workspace_archetype")
    if archetype not in workspace_layouts.ARCHETYPES:
        return _fail(
            "rename_term",
            "I need to set your workspace up first — ask me to build it and "
            "then we can rename anything in it.",
        )

    stored = dict(profile.get("workspace_terminology") or {})
    changed: List[str] = []
    cleared: List[str] = []
    for key, value in updates.items():
        if value is None or not str(value).strip():
            if stored.pop(key, None) is not None:
                cleared.append(key)
        else:
            stored[key] = {"value": str(value).strip(), "origin": "user_override"}
            changed.append(f"{key} → {str(value).strip()}")

    try:
        layout = _persist(business_id, archetype, stored)
    except validator.LayoutValidationError as e:
        logger.error("terminology write failed validation: %s", e.errors)
        return _fail("rename_term",
                     "I couldn't save that just now — try again in a moment.")

    bits: List[str] = []
    if changed:
        bits.append("Done — " + ", ".join(changed) + ".")
        bits.append("That's yours now. I won't change it back, even if we "
                    "rebuild the workspace later.")
    if cleared:
        bits.append("Put back to the default: " + ", ".join(cleared) + ".")

    return {
        "type": "rename_term",
        "result": " ".join(bits) or "Nothing to change.",
        "label": "Renamed" if changed else "Reset wording",
        "nav": _nav_workspace(),
        "changed": changed,
        "cleared": cleared,
        "terminology": layout.get("terminology") or {},
    }
