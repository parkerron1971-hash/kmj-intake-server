"""
workspace_composer_router.py — the practitioner-facing surface of the
workspace composer.

Chief classifies at onboarding, the practitioner overrides in one tap, and
the layout is validated before it is ever persisted or rendered. Nothing
here trusts the caller for whose business it is: every endpoint is
`require_user` + `_require_owner`, service-role read of `businesses.owner_id`
against the verified JWT, independent of RLS (see docs/RLS_MODEL.md).

Endpoints
  GET   /workspace/registry
        The primitive registry, field catalog and the five preset summaries.
        Read-only reference the renderer and the override picker both read.

  GET   /workspace/layout?business_id=...
        The business's live layout, resolved terminology, and archetype.
        Falls back to the classified preset if nothing is persisted yet.

  POST  /workspace/classify
        Body: { business_id, answers?, persist? }
        Runs the classifier over the intake answers and returns the pick
        plus Chief's narration. `persist: true` writes it.

  PUT   /workspace/layout
        Body: { business_id, archetype }
        The override. Switches archetype, rebuilds from the preset, and
        carries every `user_override` terminology row across untouched.

  PATCH /workspace/terminology
        Body: { business_id, terms: { key: value } }
        Sets a term and stamps `origin: user_override`. Nothing overwrites
        that row again — not a re-classification, not an archetype switch.

Layout state lives on `business_profiles` (workspace_archetype,
workspace_layout, workspace_terminology) — see
supabase/APPLY-2026-08-26-workspace-composer.sql.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
import workspace_archetypes
import workspace_layout_picker
import workspace_field_catalog as field_catalog
import workspace_layout_validator as validator
import workspace_layouts
import workspace_primitives as registry
import workspace_resolver
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("workspace_composer_router")

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Same pattern as contacts_router: service-role read of the owner id,
    compared to the verified JWT subject. App-layer, not RLS-dependent."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,type&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _get_or_create_profile(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/business_profiles?business_id=eq.{business_id}"
        f"&select=business_id,workspace_archetype,workspace_layout,"
        f"workspace_layout_variant,workspace_layout_variant_origin,"
        f"workspace_terminology&limit=1"
    ) or []
    if rows:
        return rows[0]
    created = sb_clients.sb_post_as_service("/business_profiles", {
        "business_id": business_id,
    })
    if isinstance(created, list) and created:
        return created[0]
    # Surface nothing; the caller reads the empty defaults and the next
    # write retries the insert.
    return {"business_id": business_id}


# ─── terminology merge ───────────────────────────────────────────────

def merge_terminology(
    preset_terms: Dict[str, Any],
    stored_terms: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Preset rows, with every `user_override` row from storage kept.

    This is the whole rule from the brief, in one function: a row the
    practitioner set is never overwritten again. An archetype switch
    rebuilds everything else from the new preset and leaves those rows
    exactly where they were — including rows the new preset has no opinion
    about, which is why we start from the stored overrides rather than
    intersecting with the preset's keys.
    """
    merged: Dict[str, Any] = {}
    for key, row in (preset_terms or {}).items():
        merged[key] = {"value": row["value"], "origin": "preset"}

    for key, row in (stored_terms or {}).items():
        if not isinstance(row, dict):
            continue
        if row.get("origin") == "user_override" and str(row.get("value") or "").strip():
            merged[key] = {"value": row["value"], "origin": "user_override"}
    return merged


def build_layout(archetype: str, stored_terms: Optional[Dict[str, Any]] = None,
                 variant: Optional[str] = None,
                 ) -> Dict[str, Any]:
    """A preset with the practitioner's terminology carried across.

    `variant` selects which layout of that archetype. Unknown falls back
    to the default inside get_preset rather than raising — a stale
    variant on a row must never be able to blank a home screen.
    """
    layout = workspace_layouts.get_preset(archetype, variant=variant)
    layout["terminology"] = merge_terminology(layout.get("terminology"), stored_terms)
    return layout


def _persist(business_id: str, archetype: str, layout: Dict[str, Any]) -> None:
    """Validate, THEN write, THEN prove the write landed.

    Validate before writing, never after — a layout that cannot render
    must not be able to reach the column the renderer reads.

    The read-back is not belt-and-braces. `sb_clients._sync_request` logs
    a warning and returns None on any 4xx, and None is also what a
    successful PATCH returns when there is no representation body, so the
    return value cannot tell the two apart. That ambiguity already cost
    us: the archetype CHECK allowed five values while seven presets
    shipped, so a therapist choosing their workspace was rejected by
    Postgres with 23514, told nothing, and asked to choose again on the
    next load — forever. A write that cannot fail out loud is not a
    write; it is a hope.
    """
    validator.assert_valid(layout, business_id=business_id)
    _get_or_create_profile(business_id)
    sb_clients.sb_patch_as_service(
        f"/business_profiles?business_id=eq.{business_id}",
        {
            "workspace_archetype": archetype,
            "workspace_layout": layout,
            "workspace_terminology": layout.get("terminology") or {},
        },
    )

    rows = sb_clients.sb_get_as_service(
        f"/business_profiles?business_id=eq.{business_id}"
        f"&select=workspace_archetype&limit=1"
    ) or []
    saved = (rows[0] or {}).get("workspace_archetype") if rows else None
    if saved != archetype:
        logger.error(
            "workspace layout did not persist for %s: asked for %r, row holds %r",
            business_id, archetype, saved,
        )
        raise HTTPException(
            500,
            "the workspace could not be saved — nothing was changed. "
            "This has been logged.",
        )


# ─── read ────────────────────────────────────────────────────────────

@router.get("/registry")
def get_registry(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Reference data. Not business-scoped — it is the same six primitives
    for everyone — but still behind auth, because it describes the shape of
    every tenant's data surface."""
    return {
        "ok": True,
        "primitives": registry.describe(),
        "roles": list(registry.ROLES),
        "surface_budget": registry.SURFACE_BUDGET,
        "sources": field_catalog.describe(),
        "derivations": {
            name: {"from": list(spec["from"]), "to": spec["to"],
                   "label": spec["label"]}
            for name, spec in field_catalog.DERIVATIONS.items()
        },
        "archetypes": workspace_layouts.summaries(),
        "checks": list(validator.CHECKS),
    }


@router.get("/layout")
def get_layout(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    profile = _get_or_create_profile(business_id)

    archetype = profile.get("workspace_archetype")
    stored_terms = profile.get("workspace_terminology") or {}

    if archetype and archetype in workspace_layouts.ARCHETYPES:
        layout = build_layout(archetype, stored_terms)
        provisional = False
    else:
        # Nothing chosen yet. Classify from what we know — the business type
        # is usually all we have at this point — and return it WITHOUT
        # persisting. A layout the practitioner has not seen should not
        # become the record.
        decision = workspace_archetypes.classify({"vertical": biz.get("type")})
        archetype = decision["archetype"]
        layout = build_layout(archetype, stored_terms)
        provisional = True

    return {
        "ok": True,
        "business_id": business_id,
        "archetype": archetype,
        "provisional": provisional,
        "layout": layout,
        "terminology": layout.get("terminology") or {},
        "alternatives": workspace_layouts.summaries(),
    }


@router.get("/home")
def get_home(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """The composed workspace, layout AND data, ready to render.

    This is the endpoint the app's Home screen calls. `/workspace/layout`
    returns the schema alone and is for tooling; this one executes it.

    The resolver holds the service-role key, so the owner check above is
    the boundary — and the resolver re-asserts the tenant pin itself
    rather than trusting that this ran.

    `provisional` says Chief has proposed an archetype but nobody has
    accepted it yet. The client should render the workspace and show the
    override prominently: a practitioner who has never been asked should
    not silently inherit a decision.
    """
    biz = _require_owner(business_id, user)
    profile = _get_or_create_profile(business_id)

    archetype = profile.get("workspace_archetype")
    stored_terms = profile.get("workspace_terminology") or {}
    provisional = archetype not in workspace_layouts.ARCHETYPES

    if provisional:
        decision = workspace_archetypes.classify({"vertical": biz.get("type")})
        archetype = decision["archetype"]

    # WHICH DESK, within that room. The archetype says a firm is a firm;
    # it cannot say whether this firm is drowning in filings or has not
    # been paid since June. That comes from its own benchmark values.
    #
    # A user_override is honoured here and never silently replaced — the
    # pick still reports what it WOULD have chosen so the surface can
    # offer the way back, which is the whole difference between an
    # assistant and a thing that moves your furniture overnight.
    pick = workspace_layout_picker.pick_for_business(
        business_id, archetype, biz.get("type"),
        stored={"variant": profile.get("workspace_layout_variant"),
                "origin": profile.get("workspace_layout_variant_origin")},
    )

    layout = build_layout(archetype, stored_terms, variant=pick["variant"])

    # Validated before execution, every time. The row could have been
    # written by an older build, or by hand.
    validator.assert_valid(layout, business_id=business_id)

    try:
        data = workspace_resolver.resolve(layout, business_id)
    except workspace_resolver.ResolveError as e:
        # A cross-tenant attempt is the only thing resolve() re-raises.
        logger.error("resolve refused for %s: %s", business_id, e)
        raise HTTPException(500, "workspace could not be assembled")

    return {
        "ok": True,
        "business_id": business_id,
        "archetype": archetype,
        # WHICH desk, and why. `variant_reason` is written for the
        # practitioner and Chief renders it above the workspace: a
        # layout that changes without saying why is a product that
        # moved somebody's furniture overnight.
        "variant": pick["variant"],
        "variant_origin": pick["origin"],
        "variant_reason": pick["reason"],
        "would_have_picked": pick["would_have_picked"],
        "variants": pick["candidates"],
        "provisional": provisional,
        "layout": layout,
        "data": data,
        "terminology": layout.get("terminology") or {},
        "alternatives": workspace_layouts.summaries(),
    }


@router.get("/benchmarks")
def get_benchmarks(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """The bands this business is measured against, and the one finding.

    Deliberately NOT part of /workspace/home. The vertical desks already
    own the home screen and have done since before this arc — they know
    things this composer did not, like the fact that no named staff exist
    anywhere in the product. Shipping a second home screen would be a
    duplicate; shipping the layer the desks lack is the contribution.

    So this is a standalone read a desk panel can call on its own:
      rows      one per band, value joined to the published average,
                target, floor, plain-language reading and citation
      finding   the single band furthest short of its target, which is
                the whole reason Chief sits in front of this data — a
                dashboard shows four numbers and leaves you to work out
                which one matters
      measured  false when nothing has been computed yet, so the panel
                can say "not measured" rather than draw four empty bars

    A business type with no published bands gets an empty list. Measuring
    a business against numbers from a different industry is worse than
    not measuring it.
    """
    import workspace_benchmarks

    biz = _require_owner(business_id, user)
    vertical = biz.get("type")
    panel = workspace_benchmarks.panel_for(business_id, vertical)

    return {
        "ok": True,
        "business_id": business_id,
        "vertical": vertical,
        "rows": panel["rows"],
        "finding": panel["finding"],
        "measured": panel["measured"],
    }


# ─── classify ────────────────────────────────────────────────────────

class ClassifyBody(BaseModel):
    business_id: str
    answers: Optional[Dict[str, Any]] = None
    persist: bool = False


@router.post("/classify")
def classify(
    body: ClassifyBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _require_owner(body.business_id, user)

    answers = dict(body.answers or {})
    # The picker's business type is a signal the caller shouldn't have to
    # remember to send, and shouldn't be able to lie about either.
    answers.setdefault("vertical", biz.get("type"))

    decision = workspace_archetypes.classify(answers)
    profile = _get_or_create_profile(body.business_id)
    stored_terms = profile.get("workspace_terminology") or {}
    layout = build_layout(decision["archetype"], stored_terms)

    if body.persist:
        _persist(body.business_id, decision["archetype"], layout)

    return {
        "ok": True,
        "business_id": body.business_id,
        "archetype": decision["archetype"],
        "label": decision["label"],
        "confidence": decision["confidence"],
        "evidence": decision["evidence"],
        "rationale": decision["rationale"],
        "runner_up": decision["runner_up"],
        "narration": workspace_archetypes.narrate(decision),
        "persisted": bool(body.persist),
        "layout": layout,
        "alternatives": decision["alternatives"],
    }


# ─── override ────────────────────────────────────────────────────────

class SetArchetypeBody(BaseModel):
    business_id: str
    archetype: str


@router.put("/layout")
def set_archetype(
    body: SetArchetypeBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """The override. One call, always available — the practitioner is never
    stuck with Chief's guess."""
    _require_owner(body.business_id, user)

    archetype = (body.archetype or "").strip().lower()
    if archetype not in workspace_layouts.ARCHETYPES:
        raise HTTPException(
            400,
            f"unknown archetype {body.archetype!r}; known: "
            f"{', '.join(workspace_layouts.ARCHETYPES)}",
        )

    profile = _get_or_create_profile(body.business_id)
    stored_terms = profile.get("workspace_terminology") or {}
    previous = profile.get("workspace_archetype")

    layout = build_layout(archetype, stored_terms)
    _persist(body.business_id, archetype, layout)

    kept = [k for k, v in (layout.get("terminology") or {}).items()
            if v.get("origin") == "user_override"]

    return {
        "ok": True,
        "business_id": body.business_id,
        "archetype": archetype,
        "previous_archetype": previous,
        "layout": layout,
        "terminology": layout.get("terminology") or {},
        "kept_overrides": kept,
    }


# ─── terminology override ────────────────────────────────────────────

class TerminologyBody(BaseModel):
    business_id: str
    terms: Dict[str, Optional[str]]


@router.patch("/terminology")
def patch_terminology(
    body: TerminologyBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Set a term. The row is stamped `user_override` and is then permanent
    against every automatic write — a re-classification, an archetype
    switch, a preset refresh. Setting a term to null clears the override and
    the row falls back to whatever the preset says.
    """
    _require_owner(body.business_id, user)

    profile = _get_or_create_profile(body.business_id)
    archetype = profile.get("workspace_archetype")
    if archetype not in workspace_layouts.ARCHETYPES:
        raise HTTPException(
            409,
            "no workspace archetype chosen yet; classify or set one first",
        )

    stored = dict(profile.get("workspace_terminology") or {})
    cleared: List[str] = []
    set_keys: List[str] = []

    for key, value in (body.terms or {}).items():
        key = (key or "").strip()
        if not key:
            continue
        if value is None or not str(value).strip():
            stored.pop(key, None)
            cleared.append(key)
        else:
            stored[key] = {"value": str(value).strip(), "origin": "user_override"}
            set_keys.append(key)

    layout = build_layout(archetype, stored)
    _persist(body.business_id, archetype, layout)

    return {
        "ok": True,
        "business_id": body.business_id,
        "archetype": archetype,
        "set": set_keys,
        "cleared": cleared,
        "terminology": layout.get("terminology") or {},
    }


# ─── validate (no persist) ───────────────────────────────────────────

class ValidateBody(BaseModel):
    business_id: str
    layout: Dict[str, Any]


@router.post("/validate")
def validate_layout(
    body: ValidateBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Run the seven checks without persisting anything.

    Phase two needs this — a composed layout gets checked before it is
    offered to the practitioner, not after. It exists now so the contract
    is fixed before there is a caller depending on it.
    """
    _require_owner(body.business_id, user)
    result = validator.validate_layout(body.layout, business_id=body.business_id)
    return {"ok": result.ok, "errors": result.errors}
