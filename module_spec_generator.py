"""
module_spec_generator.py — Phase A Light spike.

The Chief turns a free-text intake answer into a structured ModuleSpec
(Pydantic model, post-validated), stores it as a `module_specs` draft,
and on `accept` materializes it into a `custom_modules` row that the
existing DynamicModule renderer picks up unchanged.

Mirrors the Composer pattern: LLM fills a structured model + post-validation
catches drift. The runtime shape (custom_modules.schema) is preserved — the
spec layer sits *above* it. workflows[] and public_display in the spec are
captured but NOT materialized in this spike (Phase B / Phase C work).

Ruled forks honored:
  G2  Schema DSL + component library hybrid — the spec has the slots; we
      materialize only what custom_modules supports today.
  G3  module_specs is the source; custom_modules.schema is the runtime.
  G6  Booking + Loyalty are the canonical test verticals.
  G7  Pydantic + post-validation.
  G9  Materialization happens on practitioner accept (not auto).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError, model_validator

import sb_clients

logger = logging.getLogger("module_spec_generator")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] spec_gen: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────────────
# ModuleSpec — what the LLM fills + what materializes
# ──────────────────────────────────────────────────────────────
# Field types mirror useCustomModules.FieldType exactly — drift would mean
# DynamicModule rejects the schema.

FieldType = Literal["text", "textarea", "select", "date", "number",
                    "checkbox", "contact_link", "url", "email"]
ViewKind = Literal["list", "board"]
TriggerKind = Literal["new_entry", "overdue", "field_change"]


class ModuleField(BaseModel):
    name: str = Field(..., description="snake_case field key")
    type: FieldType
    label: str
    required: bool = False
    options: Optional[List[str]] = None       # select-only
    placeholder: Optional[str] = None


class ModuleSchema(BaseModel):
    fields: List[ModuleField]
    default_sort: Optional[str] = None
    default_view: ViewKind = "list"
    views: List[ViewKind] = Field(default_factory=lambda: ["list"])
    board_column: Optional[str] = None        # which field drives kanban columns


class ModuleTrigger(BaseModel):
    type: TriggerKind
    field: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    action: str
    template: Optional[str] = None

    model_config = {"populate_by_name": True}


class ModuleAgentConfig(BaseModel):
    enabled: bool = True
    triggers: List[ModuleTrigger] = Field(default_factory=list)
    closed_statuses: List[str] = Field(default_factory=list)
    check_schedule: Optional[str] = None


# Phase B — workflow rules MATERIALIZED on accept (alongside custom_modules).
# Phase C — public_display still a captured slot only.

class WorkflowTrigger(BaseModel):
    """Event type + shallow-equality conditions matched by workflow_engine
    on_event. event_type values used so far:
      module_entry.created     fires after a row is added
      module_entry.updated     fires after a row is changed
      schedule.daily           cron-fired daily (drained on tick)
    conditions are matched shallowly against the event payload (same as
    workflow_engine._conditions_match)."""
    event_type: str
    conditions: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    """One step in the workflow. action keys MUST be a workflow_engine
    STEP_HANDLERS key (log / update_context / emit_event / create_module_entry
    / create_milestone) OR a 'connector.<verb>' (Phase C). requires_confirmation
    triggers the engine's Fork 17 confirmation gate."""
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False


class WorkflowSpec(BaseModel):
    """A rule that ships with the module. Materialized to workflow_definitions
    on accept; the existing workflow_engine drains + executes."""
    name: Optional[str] = None                 # default from slug if omitted
    slug: str                                  # kebab-case, unique per business
    trigger: WorkflowTrigger
    steps: List[WorkflowStep] = Field(default_factory=list)
    enabled: bool = True

    def humanized_name(self) -> str:
        if self.name:
            return self.name
        return self.slug.replace("-", " ").replace("_", " ").title()


class PublicDisplaySlot(BaseModel):
    """Widget hint (Phase C). Whether/how this module surfaces customer-side."""
    component: Optional[str] = None        # 'BookingCalendar' / 'RewardProgressCard'
    visibility: Literal["internal_only", "customer_visible"] = "internal_only"


# ──────────────────────────────────────────────────────────────
# Archetypes (Phase C.1) — closed library the LLM picks from
# ──────────────────────────────────────────────────────────────
# Single source of truth: this enum + the per-archetype Param submodels.
# A TS twin lives at frontend src/core/types/archetypes.gen.ts (hand-mirrored
# for the spike; codegen when the enum grows beyond ~5 entries — C1 ruling).
#
# Discipline: the LLM picks `archetype` (closed enum) and fills
# `archetype_params` (per-archetype typed submodel). The materializer
# renders the matching hand-written React archetype. When no archetype
# fits, the LLM MUST emit `archetype: 'fallback_generic'` AND a
# required `archetype_fallback_reason` (C4) — never improvises a surface.

ArchetypeEnum = Literal[
    "fallback_generic",   # render via DynamicModule + show "new archetype owed" banner
    "booking_calendar",   # C.1 vertical slice — appointment / time-slot tracking
]


class BookingCalendarParams(BaseModel):
    """Parameters for the BookingCalendar archetype.
    primary_date_field MUST be the snake_case name of a date or datetime
    field declared in schema.fields. The materializer + the BookingForm
    widget both read entries by this field."""
    primary_date_field: str
    duration_minutes_field: Optional[str] = None     # defaults to 60 in the UI
    color_field: Optional[str] = None                # drives slot color (e.g. 'service_type')


class FallbackGenericParams(BaseModel):
    """No params — the fallback uses DynamicModule's existing list/board
    inference from the schema."""
    pass


# Validators dispatched by archetype value.
_ARCHETYPE_PARAM_MODELS: Dict[str, type] = {
    "booking_calendar": BookingCalendarParams,
    "fallback_generic": FallbackGenericParams,
}


class ModuleSpec(BaseModel):
    slug: str = Field(..., description="kebab-case slug, e.g. 'bookings'")
    name: str
    icon: str = "📋"
    description: str
    intake_excerpt: str
    schema_: ModuleSchema = Field(..., alias="schema")
    agent_config: ModuleAgentConfig = Field(default_factory=ModuleAgentConfig)
    public_display: Optional[PublicDisplaySlot] = None
    workflows: List[WorkflowSpec] = Field(default_factory=list)
    voice_hints: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    reasoning: str

    # ─── Archetype layer (C.1) ──────────────────────────────────────
    archetype: ArchetypeEnum = "fallback_generic"
    archetype_params: Dict[str, Any] = Field(default_factory=dict)
    # C4: required when archetype == 'fallback_generic'. Surfaced on the
    # dock card AND on the materialized module so every fallback is
    # visible as "a new archetype is owed for this shape".
    archetype_fallback_reason: Optional[str] = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_archetype(self):
        # Dispatch archetype_params to its typed submodel.
        model = _ARCHETYPE_PARAM_MODELS.get(self.archetype)
        if model is None:
            raise ValueError(f"unknown archetype '{self.archetype}'")
        try:
            typed = model(**(self.archetype_params or {}))
        except ValidationError as e:
            raise ValueError(
                f"archetype_params invalid for archetype '{self.archetype}': {e}"
            )
        # Re-emit as a normalized dict so downstream code reads the
        # post-validated shape.
        object.__setattr__(self, "archetype_params", typed.model_dump(exclude_none=True))

        # Fallback rule (C4): must explain WHY no archetype fit.
        if self.archetype == "fallback_generic":
            reason = (self.archetype_fallback_reason or "").strip()
            if not reason:
                raise ValueError(
                    "archetype_fallback_reason is REQUIRED when archetype = "
                    "'fallback_generic' — every fallback is a marker that a "
                    "new archetype is owed"
                )

        # booking_calendar-specific: primary_date_field MUST exist in the schema.
        if self.archetype == "booking_calendar":
            field_names = {f.name for f in self.schema_.fields}
            pdf = self.archetype_params.get("primary_date_field")
            if pdf not in field_names:
                raise ValueError(
                    f"booking_calendar primary_date_field '{pdf}' is not "
                    f"in schema.fields (have: {sorted(field_names)})"
                )
            # If duration/color fields referenced, they must exist too.
            for k in ("duration_minutes_field", "color_field"):
                v = self.archetype_params.get(k)
                if v and v not in field_names:
                    raise ValueError(
                        f"booking_calendar {k} '{v}' is not in schema.fields"
                    )

        return self


# ──────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────

# A canonical reference (the existing coach 'clients' blueprint module —
# practitioner-curated quality). The model sees ONE high-quality example so
# its output is anchored to existing standards rather than drifting.
_REFERENCE_EXAMPLE = """
EXAMPLE OUTPUT (a coach 'clients' module — what 'good' looks like):
{
  "slug": "clients",
  "name": "Clients",
  "icon": "🧑‍🤝‍🧑",
  "description": "Who you coach — discovery-first",
  "intake_excerpt": "(would be the practitioner's onboarding sentence here)",
  "schema": {
    "fields": [
      {"name":"name","type":"text","label":"Name","required":true},
      {"name":"contact_id","type":"contact_link","label":"Contact"},
      {"name":"focus_area","type":"text","label":"Focus area"},
      {"name":"engagement_stage","type":"select","label":"Stage",
       "options":["discovery","active","paused","completed"]},
      {"name":"next_session","type":"date","label":"Next session"}
    ],
    "default_view": "board",
    "views": ["list","board"],
    "board_column": "engagement_stage",
    "default_sort": "next_session"
  },
  "agent_config": {"enabled": true, "triggers": [],
                   "closed_statuses": ["paused","completed"]},
  "public_display": null,
  "workflows": [],
  "voice_hints": ["personal","considered"],
  "confidence": "high",
  "reasoning": "Coaches centre client relationships; stage column for kanban is the standard view.",
  "archetype": "fallback_generic",
  "archetype_params": {},
  "archetype_fallback_reason": "no ClientRoster archetype exists yet — this module would benefit from a kanban-by-engagement-stage with last-contact aging dots"
}
""".strip()


_SYSTEM_PROMPT = """You design custom data modules for solo practitioners. Given a free-text \
intake answer describing a tracking/workflow need, you output a JSON envelope \
containing one or more ModuleSpecs plus your decomposition reasoning. Modules \
will be rendered by a generic schema-driven renderer (list + kanban views; \
field types: text, textarea, select, date, number, checkbox, contact_link, \
url, email) and rules in workflows[] will be materialized into a workflow engine.

DECOMPOSITION (G13 ruling): if the intake names 2+ DISTINCT TRACKABLE OBJECTS \
(e.g. "bookings AND a rewards system" → two objects; "appointments with \
recurring slots" → one), return MULTIPLE ModuleSpecs in the list, linked via \
`contact_link` fields where the same person/customer appears in both. If the \
intake describes one trackable object (with details), return ONE ModuleSpec. \
ALWAYS explain `decomposition_reasoning` in plain language the practitioner can \
read: why you split (or didn't), and how the modules link. The practitioner can \
ask to consolidate.

DESIGN PRINCIPLES per ModuleSpec:
- Fields reflect REAL operational data the practitioner needs (not generic placeholders)
- `default_view: board` when one field is a clear status/progress column; else `list`
- `board_column` MUST be the name of a `select` field when using board view
- `contact_link` when an entry should reference a person already in the practitioner's contacts (this is the FK between linked modules — use the same `contact_link` field name across modules so they link cleanly)
- `select` (with options) for any short enumerated value (status, type, category)
- Mark `required: true` ONLY on fields without which the row is meaningless
- `slug` is kebab-case, `name` is Title Case
- `agent_config.closed_statuses` lists the option values meaning "done"
- 1-sentence `description`, 1-3 sentence `reasoning` per module

WORKFLOWS (Phase B — these DO materialize): when the intake implies an automatic \
rule (e.g. "on 7th visit → free reward"), encode it in workflows[] with:
- trigger.event_type = 'module_entry.updated' or 'module_entry.created'
- trigger.conditions = {module_slug, field, value}  — shallow equality
- steps = list of {action, params}; valid actions: 'log', 'emit_event', 'update_context'
- Each workflow has a unique kebab-case slug per business
Only declare workflows for rules the intake genuinely implies — don't invent.

PUBLIC_DISPLAY: ignored this pass (Phase C). Set null unless the intake explicitly \
mentions customer-facing.

ARCHETYPE (closed-enum surface treatment — C.1 vertical slice):
Every ModuleSpec MUST carry an archetype + archetype_params. The archetype \
is a closed enum — pick from the palette below. NEVER invent an archetype \
name; if no archetype fits, you MUST emit "fallback_generic" with a \
mandatory archetype_fallback_reason that explains in one sentence what \
archetype would have fit. You do NOT generate or design React surfaces — \
the archetype just routes the materialized module to a hand-written \
component.

Available archetypes:

  booking_calendar
    purpose: a tracker for appointments / time-slot reservations / sessions
    when to pick: intake describes booking, scheduling, appointments,
      reservations, sessions, slot-based time tracking
    schema requirement: schema.fields MUST contain at least one date or
      datetime field that holds the slot start time
    archetype_params (required keys marked *):
      * primary_date_field — snake_case name of the date field that holds
                             the slot start; MUST match a field in schema.fields
        duration_minutes_field — (optional) name of a number field with slot
                                  length; defaults to 60 minutes in the UI
        color_field — (optional) name of a select field that drives the
                      slot color on the calendar (e.g. 'service_type')
    example intake → archetype:
      "I need a way to book customers into 30-min appointments with my barber chairs"
      → archetype: booking_calendar
        archetype_params: {"primary_date_field": "appointment_at",
                           "duration_minutes_field": "duration_min",
                           "color_field": "service"}

  fallback_generic
    purpose: explicit "no archetype fits yet" — renders through the generic
      DynamicModule (list/board)
    when to pick: ANY module whose shape doesn't fit booking_calendar
    schema requirement: none
    archetype_params: {}  (empty)
    archetype_fallback_reason REQUIRED: one sentence describing what \
      archetype would have fit (e.g. "needs a RewardProgress archetype for \
      counting visits toward a free service")

Picking discipline: read the intake, decide if booking_calendar fits. If \
yes, pick it and fill archetype_params from the schema fields you already \
designed. If no, pick fallback_generic and write the archetype_fallback_reason.

confidence: 'high' if intake is specific, 'medium' if inferred, 'low' if vague.

Output STRICT JSON only matching this envelope:
{
  "decomposition_reasoning": "plain-language explanation",
  "specs": [ <ModuleSpec>, ... ]
}
No markdown, no commentary, no leading text.
"""


_USER_TEMPLATE = """Practitioner business: {business_name} (type: {business_type})

Practitioner's intake answer:
\"\"\"
{intake_excerpt}
\"\"\"

{reference}

Output the JSON envelope now ({{"decomposition_reasoning": ..., "specs": [...]}})."""


class ProposalEnvelope(BaseModel):
    decomposition_reasoning: str
    specs: List[ModuleSpec]

    model_config = {"populate_by_name": True}


# ──────────────────────────────────────────────────────────────
# Generation
# ──────────────────────────────────────────────────────────────

GENERATOR_MODEL = "claude-sonnet-4-5"
GENERATOR_MAX_TOKENS = 4000


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def generate_module_proposal(
    business: Dict[str, Any],
    intake_excerpt: str,
    extra_guidance: Optional[str] = None,
) -> Dict[str, Any]:
    """Call Sonnet to produce a ProposalEnvelope (decomposition_reasoning +
    list[ModuleSpec]), validate via Pydantic, return
    {ok, decomposition_reasoning, specs, error?}. Soft-fails."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
    user = _USER_TEMPLATE.format(
        business_name=business.get("name", ""),
        business_type=business.get("type", "custom"),
        intake_excerpt=intake_excerpt.strip(),
        reference=_REFERENCE_EXAMPLE,
    )
    if extra_guidance:
        user += ("\n\nAdditional practitioner guidance (use to revise the design "
                 "and update decomposition_reasoning):\n" + extra_guidance.strip())
    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=GENERATOR_MODEL,
            max_tokens=GENERATOR_MAX_TOKENS,
            temperature=0.4,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return {"ok": False, "error": f"llm_call_failed: {e}"}

    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"non-JSON envelope: {text[:200]}")
        return {"ok": False, "error": f"non_json: {e}", "raw": text}
    try:
        env = ProposalEnvelope.model_validate(data)
    except ValidationError as ve:
        logger.warning(f"envelope validation failed: {ve}")
        return {"ok": False, "error": f"validation_failed: {ve}", "raw": data}

    # Anchor the intake excerpt on each spec.
    specs = []
    for s in env.specs:
        sd = s.model_dump(by_alias=True, exclude_none=False)
        sd["intake_excerpt"] = intake_excerpt.strip()
        specs.append(sd)
    return {"ok": True, "decomposition_reasoning": env.decomposition_reasoning, "specs": specs}


# Back-compat: single-spec helper still callable for tests.
def generate_module_spec(business, intake_excerpt, extra_guidance=None) -> Dict[str, Any]:
    res = generate_module_proposal(business, intake_excerpt, extra_guidance)
    if not res.get("ok"):
        return res
    return {"ok": True, "spec": res["specs"][0]}


# ──────────────────────────────────────────────────────────────
# Persistence — module_specs (draft + accept lifecycle)
# ──────────────────────────────────────────────────────────────

def store_draft(business_id: str, intake_excerpt: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a draft row, return the persisted row (with id)."""
    row = sb_clients.sb_post_as_service("/module_specs", {
        "business_id": business_id,
        "slug": spec.get("slug"),
        "draft_json": spec,
        "intake_excerpt": intake_excerpt,
        "status": "draft",
    })
    if isinstance(row, list) and row:
        return row[0]
    return None


def propose_module_from_intake(
    business_id: str, intake_excerpt: str, extra_guidance: Optional[str] = None,
) -> Dict[str, Any]:
    """Full propose flow: load biz → generate envelope (1+ specs) → store each
    as a draft. Returns {ok, decomposition_reasoning, proposals: [{spec_id, spec}]}
    so the frontend can render either a single card or a stack with the
    decomposition reasoning at top (G13)."""
    if not intake_excerpt or len(intake_excerpt.strip()) < 5:
        return {"ok": False, "error": "intake_excerpt too short"}
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1"
    ) or []
    if not biz_rows:
        return {"ok": False, "error": "business not found"}
    biz = biz_rows[0]
    gen = generate_module_proposal(biz, intake_excerpt, extra_guidance=extra_guidance)
    if not gen.get("ok"):
        return gen
    proposals = []
    for spec in gen["specs"]:
        draft = store_draft(business_id, intake_excerpt, spec)
        if draft:
            proposals.append({"spec_id": draft["id"], "spec": spec})
    if not proposals:
        return {"ok": False, "error": "no drafts persisted"}
    return {
        "ok": True,
        "decomposition_reasoning": gen["decomposition_reasoning"],
        "proposals": proposals,
    }


# ──────────────────────────────────────────────────────────────
# Materialization — accept turns draft into custom_modules row
# ──────────────────────────────────────────────────────────────

def _materialize_workflows(business_id: str, module_slug: str,
                           workflows: List[Dict[str, Any]]) -> List[str]:
    """Phase B: insert each spec.workflows[] entry as a workflow_definitions
    row. Idempotent on (business_id, slug) — uniq index. Workflow slug is
    prefixed with module_slug to avoid cross-module collisions. Returns the
    created workflow_definitions ids (existing slugs are skipped, not
    duplicated)."""
    if not workflows:
        return []
    existing = {
        r.get("slug") for r in
        (sb_clients.sb_get_as_service(
            f"/workflow_definitions?business_id=eq.{business_id}&select=slug") or [])
        if isinstance(r, dict)
    }
    created_ids: List[str] = []
    for wf in workflows:
        wf_slug_raw = wf.get("slug") or "rule"
        wf_slug = f"{module_slug}-{wf_slug_raw}"
        if wf_slug in existing:
            continue
        trigger = wf.get("trigger") or {}
        steps = wf.get("steps") or []
        body = {
            "business_id": business_id,
            "name": wf.get("name") or wf_slug,
            "slug": wf_slug,
            "trigger": trigger,
            "steps": steps,
            "enabled": bool(wf.get("enabled", True)),
            "source": "module_spec",
        }
        created = sb_clients.sb_post_as_service("/workflow_definitions", body)
        if isinstance(created, list) and created:
            created_ids.append(created[0].get("id"))
            existing.add(wf_slug)
    return [i for i in created_ids if i]


def materialize_spec(spec_id: str) -> Dict[str, Any]:
    """Idempotent on (business_id, slug). Materializes:
      1. custom_modules row (the runtime shape)
      2. workflow_definitions rows for each spec.workflows[] (Phase B)
    Marks the spec accepted + links materialized_module_id.
    Returns {ok, module, workflow_ids, spec_id}."""
    spec_rows = sb_clients.sb_get_as_service(
        f"/module_specs?id=eq.{spec_id}&select=*&limit=1"
    ) or []
    if not spec_rows:
        return {"ok": False, "error": "spec not found"}
    spec_row = spec_rows[0]
    if spec_row.get("status") == "accepted" and spec_row.get("materialized_module_id"):
        mod = sb_clients.sb_get_as_service(
            f"/custom_modules?id=eq.{spec_row['materialized_module_id']}&select=*&limit=1"
        ) or []
        return {"ok": True, "module": mod[0] if mod else None, "spec_id": spec_id,
                "workflow_ids": [], "note": "already accepted"}

    business_id = spec_row["business_id"]
    spec = spec_row["draft_json"] or {}
    slug = spec.get("slug")
    if not slug:
        return {"ok": False, "error": "spec missing slug"}

    # 1. custom_modules — idempotent on (business_id, slug).
    existing = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}&slug=eq.{slug}&select=id&limit=1"
    ) or []
    if existing:
        module_id = existing[0]["id"]
    else:
        cm_payload = {
            "business_id": business_id,
            "name": spec.get("name") or slug,
            "slug": slug,
            "description": spec.get("description"),
            "icon": spec.get("icon") or "📋",
            "schema": spec.get("schema") or {"fields": []},
            "agent_config": spec.get("agent_config") or {"enabled": True, "triggers": []},
            "is_active": True,
            "sort_order": 0,
            # Archetype layer (Phase C.1). Existing rows keep defaults
            # ('fallback_generic' + empty params) via the migration default.
            "archetype": spec.get("archetype") or "fallback_generic",
            "archetype_params": spec.get("archetype_params") or {},
            "archetype_fallback_reason": spec.get("archetype_fallback_reason"),
        }
        created = sb_clients.sb_post_as_service("/custom_modules", cm_payload)
        if not (isinstance(created, list) and created):
            return {"ok": False, "error": "materialize insert failed"}
        module_id = created[0]["id"]

    # 2. workflow_definitions (Phase B) — Best-effort: failures don't block
    # the module from materializing.
    workflow_ids = _materialize_workflows(business_id, slug, spec.get("workflows") or [])

    # Mark accepted + link.
    import time
    sb_clients.sb_patch_as_service(
        f"/module_specs?id=eq.{spec_id}",
        {"status": "accepted",
         "materialized_module_id": module_id,
         "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    )
    mod = sb_clients.sb_get_as_service(
        f"/custom_modules?id=eq.{module_id}&select=*&limit=1") or []
    return {"ok": True, "spec_id": spec_id, "module": mod[0] if mod else None,
            "workflow_ids": workflow_ids}


def reject_spec(spec_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    sb_clients.sb_patch_as_service(
        f"/module_specs?id=eq.{spec_id}",
        {"status": "rejected", "reject_reason": reason or ""},
    )
    return {"ok": True, "spec_id": spec_id}


def list_specs(business_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"/module_specs?business_id=eq.{business_id}&order=created_at.desc&select=*"
    if status:
        q += f"&status=eq.{status}"
    rows = sb_clients.sb_get_as_service(q)
    return rows if isinstance(rows, list) else []
