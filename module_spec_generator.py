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
import llm_call
import logging
import os
from typing import Any, Dict, List, Literal, Optional

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
                    "checkbox", "contact_link", "url", "email",
                    # Phase C.1.2 — references an offerings row by id.
                    # Widget resolves the dropdown from offerings filtered
                    # by the field's offering_categories constraint.
                    "offering_ref"]
ViewKind = Literal["list", "board"]
TriggerKind = Literal["new_entry", "overdue", "field_change"]

# Phase C.1.2 — closed enum mirroring the offerings.category CHECK constraint.
# Mirrored to TS in src/core/types/archetypes.gen.ts. 'donation' is
# intentionally NOT a category — donations live in the restricted-modules
# surface (Fork 25 Giving guard).
OfferingCategory = Literal[
    "service", "session", "event", "course", "product", "package", "custom"
]


class ModuleField(BaseModel):
    name: str = Field(..., description="snake_case field key")
    type: FieldType
    label: str
    required: bool = False
    options: Optional[List[str]] = None       # select-only
    placeholder: Optional[str] = None
    # Phase C.1.1 — surface-visibility flags. Both default to closed (false)
    # so that any field the LLM does NOT explicitly mark is practitioner-only.
    # Fail-closed is load-bearing for the customer-side safety guarantee.
    #
    # customer_facing — does the paired customer widget render this field
    #   as a form input?  (DynamicModule, the practitioner-side fallback,
    #   ignores this flag entirely and renders every field.)
    # system_set      — is the field value DERIVED (e.g. duration computed
    #   from the picked service) or DEFAULTED (e.g. status='scheduled')
    #   rather than typed by the customer? system_set fields travel in
    #   config-anon so the widget knows to hide-but-compute.
    customer_facing: bool = False
    system_set: bool = False
    # Phase C.1.2 — for type='offering_ref' fields, constrains which
    # offering categories the dropdown sources from. e.g. Bookings'
    # service field has ['service','session']; future Invoicing line
    # items would accept all categories. Required when type='offering_ref'.
    offering_categories: Optional[List[OfferingCategory]] = None


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


class ServiceCatalogEntry(BaseModel):
    """C16 ruling — inline service catalog on agent_config.services.

    DEPRECATED in Phase C.1.2 — pricing is now canonical via the offerings
    table; the service dropdown sources from offerings filtered by category,
    and duration is read from the picked offering. This class is preserved
    for read-back compatibility of pre-C.1.2 modules until they're upgraded
    via the Chief upgrade_module_archetype action (which migrates
    inline services into offerings rows).

    Generator system prompt no longer asks the LLM to populate this field
    for new specs; upgrade-mode reads it to seed the proposed Offerings."""
    name: str
    duration_min: int = Field(..., gt=0, le=24 * 60)
    price: Optional[float] = None             # currency-agnostic; widget renders raw


class ProposedOffering(BaseModel):
    """Phase C.1.2 — an offering proposal in the dock's multi-card stack.
    Materializes into the offerings table on accept. Sits alongside
    ModuleSpec items in ProposalEnvelope.proposals so the practitioner
    sees Offerings + Bookings together and accepts in one pass.

    Schema mirrors the offerings table columns the LLM is allowed to set
    on creation. is_active defaults true on the table; archived_at is a
    runtime concern."""
    name: str
    slug: str                                  # kebab-case; UNIQUE per business
    description: Optional[str] = None
    category: OfferingCategory
    current_price: Optional[float] = None      # nullable for "contact for quote"
    currency: str = "usd"
    duration_min: Optional[int] = None         # None for product/event categories
    show_price_to_customer: bool = True
    reasoning: Optional[str] = None            # 1-2 sentences for the proposal card


class ModuleAgentConfig(BaseModel):
    enabled: bool = True
    triggers: List[ModuleTrigger] = Field(default_factory=list)
    closed_statuses: List[str] = Field(default_factory=list)
    check_schedule: Optional[str] = None
    # Phase C.1.1 — service catalog for service-based archetypes (booking_calendar
    # today, future massage/consult/lesson archetypes tomorrow). Optional so
    # non-service archetypes ignore it. When present, the widget reads this
    # list for the service dropdown + duration lookup.
    services: Optional[List[ServiceCatalogEntry]] = None


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


# ──────────────────────────────────────────────────────────────
# Archetype metadata (Phase C.1.3 — Navigation Taxonomy)
# ──────────────────────────────────────────────────────────────
# Per NT2/NT2b: each archetype declares which navigation surfaces it lives
# in. The sidebar enumerates modules into surfaces based on these
# declarations.
#
# Per NT8e: chief_can_suggest gates which archetypes Chief is allowed to
# proactively recommend. fallback_generic is NEVER suggestable (it's an
# outcome of failure, not a target); booking_calendar is the only
# currently-suggestable archetype.
#
# Mirrored to TS in src/core/types/archetypes.gen.ts (hand-mirror for now;
# codegen when the enum grows beyond ~5 entries — C1 ruling).
#
# config_surface     — where the practitioner CONFIGURES this archetype
#                       (schema editor / settings / archetype_params)
# daily_use_surface  — where the practitioner OPERATES this archetype
#                       (the hand-written hero, e.g. BookingCalendar week
#                       grid). None when the archetype has no daily-use
#                       hero (fallback_generic uses DynamicModule).
# chief_can_suggest  — may Chief proactively suggest this archetype?
#                       NT8e: load-bearing closed-enum lock.
# operate_group      — NT6 subject grouping under OPERATE. When the value
#                       matches an existing OPERATE_TREE group's id-suffix
#                       (e.g. "schedule" → existing operate:schedule group),
#                       the sidebar APPENDS the module into that group.
#                       Otherwise a new group is created using the
#                       OPERATE_GROUP_META lookup in SolutionistSidebar.tsx.
#                       Going-forward bucket key for customer-record /
#                       loyalty / lifecycle archetypes (RewardProgress,
#                       CustomerRoster, etc.) is "customers" — NOT the
#                       earlier "customer_lifecycle" which was retired in
#                       C.1.3.1b. "Customers" label is a placeholder until
#                       Phase C.1.4 vertical-aware terminology ships
#                       (lawyer→"Clients", ministry→"Members", etc.).

NavSurface = Literal["build", "operate", "grow", "settings", "home"]

ARCHETYPE_METADATA: Dict[str, Dict[str, Any]] = {
    "fallback_generic": {
        # NT2b — fallback_generic renders in BUILD only; no daily-use hero.
        # The whole point of fallback_generic is "no daily-use hero exists
        # yet for this shape" — its surface is DynamicModule, which IS
        # configuration-flavored.
        "config_surface": "build",
        "daily_use_surface": None,
        "chief_can_suggest": False,    # NEVER suggest the fallback
        "label": "Generic Module",
        "operate_group": None,
    },
    "event_roster": {
        # An occasion and the people attached to it. Covers headcount RSVP
        # AND named volunteer roles — those looked like two features and are
        # one: both are slots filled by people, counted or named. A church
        # picnic has a headcount AND needs three volunteers to run it.
        #
        # Deliberately NOT work_pipeline. That archetype is many items each
        # holding one stage; this is the inverted cardinality (one occasion,
        # many people). Forcing it in would have produced a board where every
        # card read "attending".
        "config_surface": "build",
        "daily_use_surface": "operate",
        "chief_can_suggest": True,
        "label": "Roster",
        "operate_group": "schedule",
    },
    "work_pipeline": {
        # Work in progress moving through stages. ONE archetype covering a
        # lawyer's Matters, a contractor's Jobs, a creative's Projects and a
        # consultant's Engagements — the same shape with different words.
        # Stage names come from archetype_params, the noun from useTerm, so
        # the vertical differences are configuration rather than four
        # components.
        #
        # NOT single-instance: a firm can legitimately run Matters AND a
        # separate Referrals pipeline. booking_calendar is single-instance
        # because a business has one calendar; that reasoning does not carry.
        "config_surface": "build",
        "daily_use_surface": "operate",
        "chief_can_suggest": True,
        "label": "Pipeline",
        "operate_group": None,
    },
    "booking_calendar": {
        "config_surface": "build",       # services + schema config
        "daily_use_surface": "operate",  # the BookingCalendar week-grid hero
        "chief_can_suggest": True,
        "label": "Bookings",
        # C.1.3.1b — Bookings lives inside the existing OPERATE → Schedule
        # group alongside Calendar + Tasks (sidebar's append-into-existing
        # merge step picks this up).
        "operate_group": "schedule",
    },
}


def archetype_metadata(archetype: Optional[str]) -> Dict[str, Any]:
    """Safe lookup — returns the fallback_generic metadata for any unknown
    or null archetype. Never raises."""
    return ARCHETYPE_METADATA.get(archetype or "fallback_generic", ARCHETYPE_METADATA["fallback_generic"])


def suggestable_archetypes() -> List[str]:
    """NT8e — returns the closed set of archetypes Chief may proactively
    suggest. Single source of truth for the proactive-suggestion gate."""
    return [name for name, meta in ARCHETYPE_METADATA.items() if meta.get("chief_can_suggest") is True]


# C.1.5 Plan A (M3-δ) — archetypes that are single-instance per business
# under the current product. The materialize_spec guard refuses to
# create a second active row of these archetypes on a business; the
# Chief intake-side M9-B guard filters them out of propose envelopes
# without explicit override; the M9-C system prompt addition instructs
# the LLM to propose offering additions instead of duplicate modules.
#
# Re-audit triggers documented in CLAUDE memory `project_c15_deferred.md`.
# When a real practitioner with multi-module needs arrives, re-open the
# C.1.5 audit (M3 will need a real-context ruling) and adjust this set.
_SINGLE_INSTANCE_ARCHETYPES: frozenset = frozenset({"booking_calendar"})


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

    # ─── Upgrade target (C.1.1) ─────────────────────────────────────
    # Set ONLY when this spec is the result of `upgrade_module_archetype`
    # against an existing materialized module. Accept handler reads this
    # to UPDATE the existing custom_modules row in place rather than
    # INSERT a new one — practitioner re-accepts; module_id is preserved;
    # existing module_entries continue to render under the refined schema.
    upgrade_target_module_id: Optional[str] = None

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
            field_by_name = {f.name: f for f in self.schema_.fields}
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

            # ─── Phase C.1.1 invariants (preserved) ──────────────────
            # 1. The primary_date_field MUST be customer_facing — the
            #    customer can't book without picking a slot.
            if not field_by_name[pdf].customer_facing:
                raise ValueError(
                    f"booking_calendar primary_date_field '{pdf}' must be "
                    f"customer_facing=true (customer needs to pick a slot)"
                )
            # 2. The duration_minutes_field (if specified) MUST be system_set
            #    — duration comes from the picked offering, never typed by
            #    the customer.
            dmf = self.archetype_params.get("duration_minutes_field")
            if dmf:
                f = field_by_name[dmf]
                if not f.system_set:
                    raise ValueError(
                        f"booking_calendar duration_minutes_field '{dmf}' "
                        f"must be system_set=true (duration is derived from "
                        f"the picked offering; customer never types it)"
                    )
                if f.customer_facing:
                    raise ValueError(
                        f"booking_calendar duration_minutes_field '{dmf}' "
                        f"must NOT be customer_facing (system-derived)"
                    )
            # 3. At least ONE field must be customer_facing — otherwise the
            #    widget renders nothing.
            customer_visible = [f for f in self.schema_.fields if f.customer_facing]
            if not customer_visible:
                raise ValueError(
                    "booking_calendar must declare at least one customer_facing "
                    "field for the widget to render"
                )

            # ─── Phase C.1.2 invariants ──────────────────────────────
            # 4. The color_field (if specified) MUST be type='offering_ref'
            #    for new specs — that's the canonical pointer to the service
            #    offering. Pre-upgrade modules with type='select' are
            #    handled by the upgrade flow, not by the validator (the
            #    validator only runs on freshly-generated specs).
            cf = self.archetype_params.get("color_field")
            if cf and field_by_name[cf].type not in ("offering_ref", "select"):
                raise ValueError(
                    f"booking_calendar color_field '{cf}' must be type "
                    f"'offering_ref' (got '{field_by_name[cf].type}'); "
                    f"'select' is permitted only for pre-C.1.2 upgrade compat"
                )
            # 5. Any offering_ref field MUST declare offering_categories.
            #    Without it the widget can't filter the dropdown.
            for f in self.schema_.fields:
                if f.type == "offering_ref":
                    if not f.offering_categories:
                        raise ValueError(
                            f"field '{f.name}' has type='offering_ref' "
                            f"but no offering_categories — required so the "
                            f"widget knows which offerings to source"
                        )

        return self


# ──────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────

# A canonical reference (the existing coach 'clients' blueprint module —
# practitioner-curated quality). The model sees ONE high-quality example so
# its output is anchored to existing standards rather than drifting.
_REFERENCE_EXAMPLE = """
EXAMPLE OUTPUT (a coach 'clients' module — what 'good' looks like for a
PRACTITIONER-ONLY archetype where every field defaults to customer_facing=false):
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

EXAMPLE OUTPUT — a barber Bookings spec under Phase C.1.2 discipline
(offering_ref + canonical Offerings; agent_config.services NOT set
for new specs — that's pre-C.1.2 read-back compat only):
{
  "slug": "bookings",
  "name": "Bookings",
  "icon": "📅",
  "description": "Customer appointments",
  "intake_excerpt": "(practitioner's intake here)",
  "schema": {
    "fields": [
      {"name":"appointment_at","type":"date","label":"Appointment date & time",
       "required":true,"customer_facing":true},
      {"name":"service","type":"offering_ref","label":"Service",
       "customer_facing":true,
       "offering_categories":["service","session"]},
      {"name":"duration_min","type":"number","label":"Duration (min)",
       "customer_facing":false,"system_set":true},
      {"name":"status","type":"select","label":"Status",
       "options":["scheduled","completed","cancelled","no_show"],
       "customer_facing":false,"system_set":true},
      {"name":"customer_notes","type":"textarea","label":"Anything we should know?",
       "customer_facing":true},
      {"name":"contact_id","type":"contact_link","label":"Customer"}
    ],
    "default_view": "list",
    "views": ["list"]
  },
  "agent_config": {
    "enabled": true,
    "triggers": [],
    "closed_statuses": ["completed","cancelled","no_show"]
  },
  "public_display": null,
  "workflows": [],
  "voice_hints": ["friendly","brief"],
  "confidence": "high",
  "reasoning": "Customer picks a service offering + slot; duration auto-fills from the picked offering; status defaults to 'scheduled' on book.",
  "archetype": "booking_calendar",
  "archetype_params": {
    "primary_date_field": "appointment_at",
    "duration_minutes_field": "duration_min",
    "color_field": "service"
  }
}
""".strip()


_SYSTEM_PROMPT = """You design custom data modules for solo practitioners. Given a free-text \
intake answer describing a tracking/workflow need, you output a JSON envelope \
containing one or more ModuleSpecs plus your decomposition reasoning. Modules \
will be rendered by a generic schema-driven renderer (list + kanban views; \
field types: text, textarea, select, date, number, checkbox, contact_link, \
url, email) and rules in workflows[] will be materialized into a workflow engine.

═══════════════════════════════════════════════════════════════════════
VERTICAL AWARENESS — open knowledge inside a closed archetype (NT8f)
═══════════════════════════════════════════════════════════════════════

The practitioner's business type is provided to you each turn (barber, \
lawyer, coach, ministry, course_creator, financial_educator, ecommerce, \
agency, personal_services, nonprofit, custom, etc). USE YOUR KNOWLEDGE \
OF THAT VERTICAL when shaping the proposal — inside the closed archetype \
palette. Specifically, your broader training-data knowledge of how that \
profession works is allowed to inform:

  - WHICH FIELDS belong on the schema (a lawyer's booking_calendar \
    typically needs consultation_type, retainer_status, conflict_check; \
    a barber's needs service + duration; a coach's needs session_type \
    + cadence; a ministry's event_registration needs RSVP + dietary + \
    childcare. These are not invented — they're the vertical norms.)
  - SENSIBLE DEFAULTS for select options and field values (a lawyer's \
    consultation_type options ["initial_consult","follow_up","deposition_prep","mediation"] vs a barber's ["Haircut","Beard Trim","Combo"])
  - DESCRIPTIONS written in vertical-appropriate language (a coach's \
    Sessions module description reads differently from a barber's Bookings)
  - ARCHETYPE_PARAMS tuned to the practice (which field is the color-key, \
    sensible duration_minutes defaults, etc)
  - OFFERINGS extracted from intake using vertical-appropriate categories \
    + reasonable durations (a lawyer's hour-long consult; a barber's 30-min \
    haircut; a coach's 60-min session)

WHAT YOUR VERTICAL KNOWLEDGE MUST NOT DO:

  - NEVER invent an archetype outside the closed enum. The closed-archetype \
    discipline is hard. If no archetype fits even with vertical-aware \
    tuning, you MUST pick fallback_generic with an explicit \
    archetype_fallback_reason — the library_gap_log captures these so the \
    team knows what archetypes are owed next.
  - NEVER assume a vertical needs a feature that the archetype doesn't \
    support. E.g. don't fabricate a "conflict_check_workflow" on \
    booking_calendar; if conflict-check is genuinely architectural, \
    that's a fallback_generic + reason ("this vertical needs an extension \
    to booking_calendar that doesn't ship yet").
  - NEVER claim the proposal will do something it won't. The practitioner \
    sees the proposal in the dock with full field list. Honesty.

The boundary: archetype shape is closed; vertical-aware tuning inside it is open.

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

    CUSTOMER-FACING FIELD DISCIPLINE (Phase C.1.1):
      The booking_calendar archetype has a paired customer widget (BookingForm).
      Each ModuleField declares:
        customer_facing — true if the customer sees + fills this field
                          in the booking widget. Default false.
        system_set      — true if the value is DERIVED (e.g. duration from
                          the picked offering) or DEFAULTED (e.g. status=
                          'scheduled' on book). Default false.
      For booking_calendar, set these per the table below. Any field NOT
      in this table defaults to false / false (practitioner-only, typed).

        field role                          customer_facing  system_set
        primary_date_field (slot start)     true             false
        the service field (offering_ref)    true             false
        a customer_notes field if present   true             false
        duration_minutes_field              false            true
        status                              false            true
        anything else (internal_notes,
          no_show, payment_status, etc.)    false            false

    OFFERING_REF + OFFERINGS (Phase C.1.2 — REPLACES inline service catalog):
      The 'service' field MUST be type='offering_ref' (NOT 'select') with
      offering_categories=['service','session']. The widget resolves the
      dropdown at runtime from the practitioner's offerings table filtered
      by those categories. DO NOT populate the field's options[].

      Alongside the booking_calendar ModuleSpec, you also emit one
      ProposedOffering envelope item per service the practitioner mentions
      in their intake. The envelope shape is:

        {
          "decomposition_reasoning": "...",
          "specs": [<ModuleSpec for Bookings>],
          "offerings": [<ProposedOffering>, ...]
        }

      Each ProposedOffering: name, slug (kebab-case), category
      ('service' | 'session' | 'event' | 'course' | 'product' | 'package' |
      'custom'), current_price (number or null for "contact for quote"),
      currency (default "usd"), duration_min (for service/session;
      null for product/event), show_price_to_customer (default true),
      description (a brief customer-facing line — see below), and a
      brief reasoning. Extract names + durations + prices ONLY from the
      intake — never invent. If the intake doesn't mention a price, leave
      current_price null (the practitioner can fill it in later).

      DESCRIPTION (customer-facing — practitioner can edit later):
        One short sentence the customer sees in the booking widget
        beneath the service name. 1 line, ≤120 chars ideally, hard cap
        500. Write it from the customer's frame ("what they'll get"),
        not the practitioner's ("how I deliver it").
        Examples:
          Haircut          → "Standard adult haircut with finish styling"
          Beard Trim       → "Beard cleanup and edge shaping"
          Haircut + Beard  → "Full reset — haircut plus beard trim"
          Consultation     → "30-min intro call to see if we're a fit"
        If the practitioner's intake gives obvious detail ("hot towel
        included", "ages 6-12", "60-min therapeutic"), reflect it. If
        not, write a sensible default — leaving description null is OK
        but populated is preferred (the customer surface looks bare
        without it).

      DO NOT populate agent_config.services for new specs — that field
      is a C.1.1 read-back-only shape kept for pre-C.1.2 modules until
      they're upgraded via the Chief upgrade_module_archetype action.

    example intake → envelope:
      "I do 30-min haircuts at $30 and 15-min beard trims at $15"
      → envelope: {
          "decomposition_reasoning": "Bookings module references the two
            services as a canonical Offerings catalog.",
          "specs": [{
            "archetype": "booking_calendar",
            "archetype_params": {"primary_date_field": "appointment_at",
                                 "duration_minutes_field": "duration_min",
                                 "color_field": "service"},
            "schema": {"fields": [
              {"name":"appointment_at","type":"date",
               "label":"Appointment date & time","customer_facing":true,
               "required":true},
              {"name":"service","type":"offering_ref","label":"Service",
               "customer_facing":true,
               "offering_categories":["service","session"]},
              {"name":"duration_min","type":"number","label":"Duration (min)",
               "customer_facing":false,"system_set":true},
              {"name":"status","type":"select","label":"Status",
               "options":["scheduled","completed","cancelled","no_show"],
               "customer_facing":false,"system_set":true},
              {"name":"contact_id","type":"contact_link","label":"Customer"}
            ]},
            ...
          }],
          "offerings": [
            {"name":"Haircut","slug":"haircut","category":"service",
             "current_price":30,"duration_min":30,
             "description":"Standard adult haircut with finish styling",
             "show_price_to_customer":true,
             "reasoning":"Mentioned by name and price in intake"},
            {"name":"Beard Trim","slug":"beard-trim","category":"service",
             "current_price":15,"duration_min":15,
             "description":"Beard cleanup and edge shaping",
             "show_price_to_customer":true,
             "reasoning":"Mentioned by name and price in intake"}
          ]
        }

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
    specs: List[ModuleSpec] = Field(default_factory=list)
    # Phase C.1.2 — Offerings proposed alongside the module specs. Each
    # materializes to an offerings row when the practitioner accepts the
    # corresponding proposal card. Bookings (and future archetypes that
    # use offering_ref fields) typically come paired with offerings the
    # LLM extracts from the intake (e.g. "haircut at $30").
    offerings: List[ProposedOffering] = Field(default_factory=list)

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
        client = llm_call.sdk_client(key=api_key)
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
    offerings = [o.model_dump(exclude_none=False) for o in env.offerings]
    return {
        "ok": True,
        "decomposition_reasoning": env.decomposition_reasoning,
        "specs": specs,
        "offerings": offerings,
    }


# Back-compat: single-spec helper still callable for tests.
def generate_module_spec(business, intake_excerpt, extra_guidance=None) -> Dict[str, Any]:
    res = generate_module_proposal(business, intake_excerpt, extra_guidance)
    if not res.get("ok"):
        return res
    return {"ok": True, "spec": res["specs"][0]}


# ──────────────────────────────────────────────────────────────
# Persistence — module_specs (draft + accept lifecycle)
# ──────────────────────────────────────────────────────────────

def store_draft(
    business_id: str,
    intake_excerpt: str,
    payload: Dict[str, Any],
    *,
    kind: str = "module",
) -> Optional[Dict[str, Any]]:
    """Insert a draft row, return the persisted row (with id).

    Phase C.1.2 — `kind` discriminator stamped INTO draft_json so the
    accept handler can route to materialize_spec (kind='module') vs
    materialize_offering (kind='offering'). Stored on the draft itself
    rather than as a column so we don't need a schema migration for the
    new kind."""
    stamped = dict(payload)
    stamped["__kind"] = kind
    row = sb_clients.sb_post_as_service("/module_specs", {
        "business_id": business_id,
        "slug": payload.get("slug"),
        "draft_json": stamped,
        "intake_excerpt": intake_excerpt,
        "status": "draft",
    })
    if isinstance(row, list) and row:
        return row[0]
    return None


def _existing_single_instance_modules(business_id: str) -> List[Dict[str, Any]]:
    """C.1.5 Plan A (M9-C) — return the business's active modules whose
    archetype is in _SINGLE_INSTANCE_ARCHETYPES. The LLM uses this list
    to avoid proposing duplicate modules; the M9-B intake-side filter
    uses the same data to gate the proposal envelope."""
    if not _SINGLE_INSTANCE_ARCHETYPES:
        return []
    csv = ",".join(_SINGLE_INSTANCE_ARCHETYPES)
    rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"
        f"&archetype=in.({csv})&select=id,name,slug,archetype"
    ) or []
    return rows if isinstance(rows, list) else []


def _single_instance_guidance(existing: List[Dict[str, Any]]) -> Optional[str]:
    """C.1.5 Plan A (M9-C) — render the LLM-facing instruction block
    that lists the business's existing single-instance modules and
    tells the generator to propose OFFERING additions, not duplicate
    modules, for those archetypes. Returns None when nothing applies
    so callers can skip the extra_guidance concat cleanly."""
    if not existing:
        return None
    lines = ["EXISTING SINGLE-INSTANCE MODULES (this business already has these):"]
    for r in existing:
        lines.append(
            f"  - archetype={r.get('archetype')!r} "
            f"name={r.get('name')!r} slug={r.get('slug')!r}"
        )
    lines.append("")
    lines.append(
        "Constraint: this product currently supports only ONE module per "
        "single-instance archetype per business (C.1.5 Plan A). If the "
        "practitioner's intake mentions a need that would normally produce "
        "any of the archetypes listed above, DO NOT propose a duplicate "
        "module. Instead:"
    )
    lines.append(
        "  - Propose ONLY ProposedOffering items for what the intake describes "
        "    (these flow into the existing module via offering_ref)."
    )
    lines.append(
        "  - In decomposition_reasoning, briefly note that you skipped a "
        "    new module of the existing archetype because the business "
        "    already has one."
    )
    lines.append(
        "  - If the intake genuinely needs a structurally-different module "
        "    that ISN'T the existing archetype, propose it normally. The "
        "    constraint applies only to duplicates of single-instance archetypes."
    )
    return "\n".join(lines)


def propose_module_from_intake(
    business_id: str, intake_excerpt: str, extra_guidance: Optional[str] = None,
    override: bool = False,
) -> Dict[str, Any]:
    """Full propose flow: load biz → generate envelope → store each spec
    AND each offering as a draft → return a unified proposals[] stack that
    the dock renders as a card per item. Each proposal carries a `kind`
    discriminator ('module' | 'offering') so the frontend dispatches to
    the right card shape (spec card with tabs vs offering card single-tab).

    Phase C.1.2: envelope now carries both specs[] and offerings[]. For
    booking_calendar specs the LLM is told to emit one ProposedOffering
    per service mentioned in the intake (the Offerings the Bookings spec
    references via offering_ref).

    Phase C.1.5 Plan A (M9-C): when the business already has active
    modules of single-instance archetypes (per
    `_SINGLE_INSTANCE_ARCHETYPES`), an extra_guidance block is appended
    instructing the LLM to skip duplicate module proposals and emit
    only offering additions for those archetypes. The M9-B filter in
    chief_of_staff additionally drops any leaked duplicates from the
    envelope before the dock renders it; the materialize_spec guard
    catches anything that slips both layers (defense-in-depth)."""
    if not intake_excerpt or len(intake_excerpt.strip()) < 5:
        return {"ok": False, "error": "intake_excerpt too short"}
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1"
    ) or []
    if not biz_rows:
        return {"ok": False, "error": "business not found"}
    biz = biz_rows[0]
    # C.1.5 Plan A M9-C — inject existing-single-instance context.
    # C.1.5.3 — when the practitioner explicitly overrode the duplicate
    # guard via an override phrase ("add another one anyway", etc.), the
    # M9-B filter is bypassed by the handler; M9-C guidance must also be
    # suppressed so the LLM doesn't get contradictory signals (practitioner
    # asking for a duplicate vs. system telling it not to). Without this
    # suppression the LLM honors M9-C and produces an empty envelope →
    # "no drafts persisted".
    if not override:
        si_existing = _existing_single_instance_modules(business_id)
        si_guidance = _single_instance_guidance(si_existing)
        if si_guidance:
            extra_guidance = (
                (extra_guidance or "").rstrip()
                + ("\n\n" if extra_guidance else "")
                + si_guidance
            )
    gen = generate_module_proposal(biz, intake_excerpt, extra_guidance=extra_guidance)
    if not gen.get("ok"):
        return gen

    proposals: List[Dict[str, Any]] = []
    # Offerings FIRST in the stack so the practitioner sees the Offerings
    # that the Bookings module is about to reference. Matches the
    # "build from leaf to root" mental order.
    for off in gen.get("offerings") or []:
        draft = store_draft(business_id, intake_excerpt, off, kind="offering")
        if draft:
            proposals.append({"spec_id": draft["id"], "kind": "offering", "offering": off})
    for spec in gen.get("specs") or []:
        draft = store_draft(business_id, intake_excerpt, spec, kind="module")
        if draft:
            proposals.append({"spec_id": draft["id"], "kind": "module", "spec": spec})
    if not proposals:
        return {"ok": False, "error": "no drafts persisted"}
    return {
        "ok": True,
        "decomposition_reasoning": gen["decomposition_reasoning"],
        "proposals": proposals,
    }


# ──────────────────────────────────────────────────────────────
# Upgrade flow (C.1.1) — refine an existing materialized module
# ──────────────────────────────────────────────────────────────

_UPGRADE_GUIDANCE = """UPGRADE MODE — this is NOT a fresh proposal.

The practitioner already has this module materialized and working. Your job
is to REFINE the existing spec to apply the latest discipline.

Discipline to apply (all current passes, cumulative):
  - C.1.1: customer_facing + system_set flags per the archetype palette
  - C.1.2: pricing migrates from inline agent_config.services to canonical
    Offerings. For booking_calendar:
      * The 'service' field becomes type='offering_ref' with
        offering_categories=['service','session']; DROP its options[].
      * agent_config.services is REMOVED from the refined spec —
        materialize_spec stamps it as deprecated for read-back.
      * For each entry in the CURRENT agent_config.services array, emit
        ONE ProposedOffering in the envelope (category='service',
        name + duration_min + price from the inline entry; slug =
        kebab-case of name). The Bookings spec references them by ID
        at booking-time, but the spec itself only declares offering_ref —
        no need to list specific offering ids in the spec.

  - Keep slug, name, icon, the OTHER schema fields, and archetype
    unchanged unless the existing spec is structurally broken.
  - The envelope MUST contain exactly ONE ModuleSpec.
  - The envelope MUST contain ONE ProposedOffering per inline service
    in the current module (if any).
  - Use the CURRENT inline services as the source of truth for offering
    names + durations + prices; do not re-extract from the intake text.

CURRENT MODULE STATE (refine this, don't replace):
{current_state}
"""


def regenerate_for_upgrade(business_id: str, module_id: str) -> Dict[str, Any]:
    """Read an existing custom_modules row + its source intake; ask the LLM
    to produce a refined ModuleSpec applying the latest discipline (currently
    Phase C.1.1: customer_facing + service catalog). The refined spec is
    stored as a draft with upgrade_target_module_id set, so the materialize
    accept path UPDATEs the existing row in place.

    Returns the same envelope shape as propose_module_from_intake so the
    dock can render it through the existing ModuleSpecProposalCard."""
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1"
    ) or []
    if not biz_rows:
        return {"ok": False, "error": "business not found"}
    biz = biz_rows[0]

    mod_rows = sb_clients.sb_get_as_service(
        f"/custom_modules?id=eq.{module_id}"
        f"&business_id=eq.{business_id}&select=*&limit=1"
    ) or []
    if not mod_rows:
        return {"ok": False, "error": "module not found"}
    module = mod_rows[0]

    # Source intake — find the most recent accepted module_specs row that
    # materialized to this module_id. Falls back to the module's description
    # if no source spec exists (pre-Phase A modules don't have a backing spec).
    spec_rows = sb_clients.sb_get_as_service(
        f"/module_specs?materialized_module_id=eq.{module_id}"
        f"&status=eq.accepted&order=accepted_at.desc&limit=1&select=intake_excerpt"
    ) or []
    intake = (
        spec_rows[0].get("intake_excerpt") if spec_rows
        else (module.get("description") or f"existing {module.get('name', 'module')}")
    )

    # Build the upgrade prompt context. We pass the current state INSIDE the
    # extra_guidance so the LLM refines vs. replaces.
    import json as _json
    current_state = _json.dumps({
        "slug": module.get("slug"),
        "name": module.get("name"),
        "icon": module.get("icon"),
        "description": module.get("description"),
        "schema": module.get("schema") or {"fields": []},
        "agent_config": module.get("agent_config") or {},
        "archetype": module.get("archetype"),
        "archetype_params": module.get("archetype_params") or {},
    }, indent=2)
    guidance = _UPGRADE_GUIDANCE.format(current_state=current_state)

    gen = generate_module_proposal(biz, intake, extra_guidance=guidance)
    if not gen.get("ok"):
        return gen
    specs = gen.get("specs") or []
    if len(specs) != 1:
        # Upgrade is meant to refine ONE module — if the LLM tries to
        # decompose, that's a generator drift; surface as error.
        return {"ok": False, "error": f"upgrade expects 1 spec, got {len(specs)}"}

    spec = specs[0]
    # Stamp the upgrade target on the draft so materialize_spec UPDATEs
    # rather than INSERTs.
    spec["upgrade_target_module_id"] = module_id

    proposals: List[Dict[str, Any]] = []
    # C.1.2 — Offerings FIRST (LLM extracts them from the inline
    # agent_config.services per the upgrade guidance). Each becomes its
    # own draft + proposal card in the dock.
    for off in gen.get("offerings") or []:
        odraft = store_draft(business_id, intake, off, kind="offering")
        if odraft:
            proposals.append({"spec_id": odraft["id"], "kind": "offering", "offering": off})

    mdraft = store_draft(business_id, intake, spec, kind="module")
    if not mdraft:
        return {"ok": False, "error": "draft persist failed"}
    proposals.append({"spec_id": mdraft["id"], "kind": "module", "spec": spec})

    return {
        "ok": True,
        "decomposition_reasoning": gen.get("decomposition_reasoning")
            or f"Refining your existing {module.get('name')} module to apply the latest customer-facing + canonical-pricing discipline.",
        "proposals": proposals,
        "is_upgrade": True,
        "upgrade_target_module_id": module_id,
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


def materialize_offering(spec_id: str) -> Dict[str, Any]:
    """Phase C.1.2 — materializes a draft Offering proposal into an
    offerings table row. Idempotent on (business_id, lower(slug)) via
    the unique index — re-accepting the same offering draft is a no-op."""
    spec_rows = sb_clients.sb_get_as_service(
        f"/module_specs?id=eq.{spec_id}&select=*&limit=1"
    ) or []
    if not spec_rows:
        return {"ok": False, "error": "spec not found"}
    row = spec_rows[0]
    if row.get("status") == "accepted":
        return {"ok": True, "spec_id": spec_id, "note": "already accepted"}

    business_id = row["business_id"]
    payload = row["draft_json"] or {}
    if (payload.get("__kind") or "module") != "offering":
        return {"ok": False, "error": "not an offering draft"}

    slug = (payload.get("slug") or "").strip()
    if not slug:
        return {"ok": False, "error": "offering missing slug"}

    # Idempotent on (business_id, lower(slug)) — unique index in migration.
    existing = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&slug=eq.{slug}&select=id&limit=1"
    ) or []
    if existing:
        offering_id = existing[0]["id"]
    else:
        insert_payload = {
            "business_id": business_id,
            "name": payload.get("name"),
            "slug": slug,
            "description": payload.get("description"),
            "category": payload.get("category"),
            "current_price": payload.get("current_price"),
            "currency": payload.get("currency") or "usd",
            "duration_min": payload.get("duration_min"),
            "show_price_to_customer": bool(payload.get("show_price_to_customer", True)),
            "is_active": True,
        }
        created = sb_clients.sb_post_as_service("/offerings", insert_payload)
        if not (isinstance(created, list) and created):
            return {"ok": False, "error": "offering insert failed"}
        offering_id = created[0]["id"]

    import time
    sb_clients.sb_patch_as_service(
        f"/module_specs?id=eq.{spec_id}",
        {"status": "accepted",
         "materialized_module_id": None,  # offerings aren't custom_modules
         "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    )
    off = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&select=*&limit=1") or []
    return {"ok": True, "spec_id": spec_id, "offering": off[0] if off else None,
            "offering_id": offering_id}


def _scope_refusal(business_id: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """R1 — HIPAA scope guard at the materialize seam itself, so ANY caller
    (router, Chief handler, future automation) inherits it rather than each
    one remembering to wire vertical_scope. Returns a refusal dict shaped
    like the other materialize failures ({ok:False, error, detail}) or None
    when the spec is in scope.

    Fails CLOSED: if the check can't run (import failure, business lookup
    down), refuse — a false refusal is a retry; a false allow is a HIPAA
    exposure."""
    try:
        import vertical_scope
        biz_rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=type&limit=1")
        if biz_rows is None:
            raise RuntimeError("business type lookup failed")
        biz_type = biz_rows[0].get("type") if biz_rows else None
        fields = (spec.get("schema") or {}).get("fields") or []
        labels = " ".join(
            str(f.get("label") or f.get("name") or "")
            for f in fields if isinstance(f, dict))
        ok, refusal = vertical_scope.check_module_scope(
            biz_type, spec.get("name"), spec.get("slug"),
            spec.get("description"), labels)
    except Exception as e:
        logger.warning(f"[scope] materialize guard could not run (refusing): {e}")
        return {
            "ok": False,
            "error": "scope_check_unavailable",
            "detail": ("The safety check for this module couldn't run, so "
                       "nothing was created. Please try again."),
        }
    if not ok:
        return {"ok": False, "error": "module_out_of_scope", "detail": refusal}
    return None


def materialize_spec(spec_id: str) -> Dict[str, Any]:
    """Idempotent on (business_id, slug). Materializes:
      1. custom_modules row (the runtime shape)
      2. workflow_definitions rows for each spec.workflows[] (Phase B)
    Marks the spec accepted + links materialized_module_id.
    Returns {ok, module, workflow_ids, spec_id}.

    Phase C.1.2 — dispatches on draft_json.__kind: 'offering' drafts
    route to materialize_offering. The dock accept-button calls this
    single entry point regardless of card type."""
    spec_rows = sb_clients.sb_get_as_service(
        f"/module_specs?id=eq.{spec_id}&select=*&limit=1"
    ) or []
    if not spec_rows:
        return {"ok": False, "error": "spec not found"}
    spec_row = spec_rows[0]

    # Phase C.1.2 dispatch.
    draft = spec_row.get("draft_json") or {}
    if (draft.get("__kind") or "module") == "offering":
        return materialize_offering(spec_id)

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

    # R1 — vertical scope guard before ANY write (see _scope_refusal).
    refused = _scope_refusal(business_id, spec)
    if refused:
        return refused

    # Common shape used for both fresh-insert AND upgrade UPDATE.
    write_payload = {
        "name": spec.get("name") or slug,
        "slug": slug,
        "description": spec.get("description"),
        "icon": spec.get("icon") or "📋",
        "schema": spec.get("schema") or {"fields": []},
        "agent_config": spec.get("agent_config") or {"enabled": True, "triggers": []},
        "is_active": True,
        # Archetype layer (Phase C.1). Existing rows keep defaults
        # ('fallback_generic' + empty params) via the migration default.
        "archetype": spec.get("archetype") or "fallback_generic",
        "archetype_params": spec.get("archetype_params") or {},
        "archetype_fallback_reason": spec.get("archetype_fallback_reason"),
    }

    # ─── Upgrade path (C.1.1) ────────────────────────────────────────
    # If this spec carries upgrade_target_module_id, UPDATE the existing
    # custom_modules row instead of inserting a new one. Preserves the
    # module_id so existing module_entries continue to render under the
    # refined schema. Slug + name + description can all change in an
    # upgrade — the practitioner saw the new shape on the proposal card
    # before accepting.
    upgrade_target = spec.get("upgrade_target_module_id")
    if upgrade_target:
        current_rows = sb_clients.sb_get_as_service(
            f"/custom_modules?id=eq.{upgrade_target}"
            f"&business_id=eq.{business_id}&select=*&limit=1"
        ) or []
        if not current_rows:
            return {"ok": False, "error": f"upgrade target module not found: {upgrade_target}"}
        # ─── Phase C.1.2 — preserve legacy agent_config.services as
        # deprecated read-back on upgrade. The refined spec drops services
        # entirely (pricing now lives in the offerings table). Stamping
        # __deprecated_pre_c12=true keeps the history readable + obvious.
        legacy_services = (current_rows[0].get("agent_config") or {}).get("services")
        if legacy_services:
            merged_ac = dict(write_payload.get("agent_config") or {})
            merged_ac["__deprecated_services"] = legacy_services
            merged_ac["__deprecated_pre_c12"] = True
            write_payload = {**write_payload, "agent_config": merged_ac}
        sb_clients.sb_patch_as_service(
            f"/custom_modules?id=eq.{upgrade_target}", write_payload
        )
        module_id = upgrade_target
    else:
        # ─── C.1.5 Plan A — single-instance archetype guard (M3-δ) ─────
        # Block fresh-propose of a second instance for archetypes that are
        # single-per-business under Plan A. Multi-module mechanism deferred
        # per the C.1.5 audit; re-audit triggers documented in CLAUDE
        # memory `project_c15_deferred.md`. This is the load-bearing
        # backend enforcement — the Chief intake guard (M9-B) is the
        # outer politeness layer; this guard is the inner correctness
        # one (defense-in-depth).
        spec_archetype = (write_payload.get("archetype") or "fallback_generic")
        if spec_archetype in _SINGLE_INSTANCE_ARCHETYPES:
            already = sb_clients.sb_get_as_service(
                f"/custom_modules?business_id=eq.{business_id}"
                f"&archetype=eq.{spec_archetype}&is_active=eq.true"
                f"&select=id,name,slug&limit=1"
            ) or []
            if already:
                prior = already[0]
                prior_label = prior.get("name") or prior.get("slug") or "the existing one"
                return {
                    "ok": False,
                    "error": "multi_module_not_supported",
                    "detail": (
                        f"This business already has a {spec_archetype} module "
                        f"({prior_label!r}). Multiple {spec_archetype} modules "
                        f"per business aren't supported yet — the limit is one. "
                        f"Edit the existing module, or archive it first if you "
                        f"want a fresh setup."
                    ),
                    "archetype": spec_archetype,
                    "existing_module_id": prior.get("id"),
                }

        # 1. custom_modules — idempotent on (business_id, slug) for the
        # fresh-propose path.
        existing = sb_clients.sb_get_as_service(
            f"/custom_modules?business_id=eq.{business_id}&slug=eq.{slug}&select=id&limit=1"
        ) or []
        if existing:
            module_id = existing[0]["id"]
        else:
            cm_payload = {**write_payload, "business_id": business_id, "sort_order": 0}
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
    # NT8g — when fallback_generic materializes, the audit + library_gap_log
    # discipline says we capture the gap. The practitioner sees their
    # module render through DynamicModule + FallbackBanner; the team sees
    # a library_gap_log row that says "this shape didn't fit anything in
    # the palette — here's what the LLM reasoned." Best-effort; failures
    # never block the materialization.
    if (spec.get("archetype") or "fallback_generic") == "fallback_generic":
        try:
            _log_library_gap_from_spec(business_id, spec_row, spec)
        except Exception as _gap_err:
            logger.warning(f"library_gap_log insert failed (non-blocking): {_gap_err}")

    mod = sb_clients.sb_get_as_service(
        f"/custom_modules?id=eq.{module_id}&select=*&limit=1") or []
    return {"ok": True, "spec_id": spec_id, "module": mod[0] if mod else None,
            "workflow_ids": workflow_ids}


def _log_library_gap_from_spec(business_id: str, spec_row: Dict[str, Any],
                                spec: Dict[str, Any]) -> None:
    """Best-effort: insert a library_gap_log row capturing a fallback_generic
    acceptance. Includes the practitioner's intake_excerpt + the LLM's
    fallback_reason as the rationale. Snapshots the business_type at gap
    time so historical analysis survives later type changes."""
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=type&limit=1") or []
    biz_type = biz_rows[0].get("type") if biz_rows else None
    sb_clients.sb_post_as_service("/library_gap_log", {
        "business_id": business_id,
        "business_type": biz_type,
        "intake_excerpt": spec_row.get("intake_excerpt") or spec.get("intake_excerpt") or "",
        "rationale": spec.get("archetype_fallback_reason") or "",
        "nearest_archetype": "fallback_generic",
        "outcome": "accepted_nearest",
    })


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
