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
from pydantic import BaseModel, Field, ValidationError

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


# Phase B / C slots — captured in the spec, NOT materialized this spike.

class WorkflowSpecSlot(BaseModel):
    """Rule sketch (Phase B will materialize as workflow_definitions)."""
    name: str
    trigger: Dict[str, Any]
    steps: List[Dict[str, Any]] = Field(default_factory=list)


class PublicDisplaySlot(BaseModel):
    """Widget hint (Phase C). Whether/how this module surfaces customer-side."""
    component: Optional[str] = None        # 'BookingCalendar' / 'RewardProgressCard'
    visibility: Literal["internal_only", "customer_visible"] = "internal_only"


class ModuleSpec(BaseModel):
    slug: str = Field(..., description="kebab-case slug, e.g. 'bookings'")
    name: str
    icon: str = "📋"
    description: str
    intake_excerpt: str
    schema_: ModuleSchema = Field(..., alias="schema")
    agent_config: ModuleAgentConfig = Field(default_factory=ModuleAgentConfig)
    public_display: Optional[PublicDisplaySlot] = None
    workflows: List[WorkflowSpecSlot] = Field(default_factory=list)
    voice_hints: List[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    reasoning: str

    model_config = {"populate_by_name": True}


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
  "reasoning": "Coaches centre client relationships; stage column for kanban is the standard view."
}
""".strip()


_SYSTEM_PROMPT = """You design custom data modules for solo practitioners. Given a free-text \
intake answer describing a tracking/workflow need, you output ONE ModuleSpec \
as JSON that matches the schema below. The module will be rendered by a \
generic schema-driven renderer (list + kanban views, field types: text, \
textarea, select, date, number, checkbox, contact_link, url, email).

Design principles:
- Fields should reflect REAL operational data the practitioner needs (not generic placeholders)
- Pick `default_view: board` when one field is a clear status/progress column; otherwise `list`
- `board_column` MUST be the name of a `select` field if you use board view
- Use `contact_link` when an entry should reference a person already in the practitioner's contacts
- Use `select` (with options) for any short enumerated value (status, type, category)
- Mark `required: true` ONLY on fields without which the row is meaningless
- `slug` is kebab-case, `name` is human-readable Title Case
- `agent_config.closed_statuses` lists the option values that mean "done" (so overdue checks skip them)
- Capture intent in `description` (1 sentence) and reasoning (1-3 sentences explaining the design choices)
- `workflows[]` and `public_display` MAY be filled if the intake clearly implies rules or a customer-facing surface, but they are NOT materialized this pass — be honest, not aspirational
- Set `confidence` honestly: 'high' if the intake is specific, 'medium' if you inferred, 'low' if vague

Output STRICT JSON only — no markdown, no commentary, no leading text.
"""


_USER_TEMPLATE = """Practitioner business: {business_name} (type: {business_type})

Practitioner's intake answer:
\"\"\"
{intake_excerpt}
\"\"\"

{reference}

Output the ModuleSpec JSON now."""


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


def generate_module_spec(
    business: Dict[str, Any],
    intake_excerpt: str,
    extra_guidance: Optional[str] = None,
) -> Dict[str, Any]:
    """Call Sonnet to produce a ModuleSpec, validate via Pydantic, return
    {ok, spec | error, raw}. Soft-fails so the Chief turn never crashes."""
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
        user += "\n\nAdditional practitioner guidance (use to revise the design):\n" + extra_guidance.strip()
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
        logger.warning(f"non-JSON spec: {text[:200]}")
        return {"ok": False, "error": f"non_json: {e}", "raw": text}
    try:
        spec = ModuleSpec.model_validate(data)
    except ValidationError as ve:
        logger.warning(f"spec validation failed: {ve}")
        return {"ok": False, "error": f"validation_failed: {ve}", "raw": data}

    # Anchor the intake excerpt so the LLM can't drift away from the source.
    spec_dict = spec.model_dump(by_alias=True, exclude_none=False)
    spec_dict["intake_excerpt"] = intake_excerpt.strip()
    return {"ok": True, "spec": spec_dict}


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
    """Full propose flow: load biz → generate → store draft. Returns
    {ok, spec_id, spec} on success."""
    if not intake_excerpt or len(intake_excerpt.strip()) < 5:
        return {"ok": False, "error": "intake_excerpt too short"}
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1"
    ) or []
    if not biz_rows:
        return {"ok": False, "error": "business not found"}
    biz = biz_rows[0]
    gen = generate_module_spec(biz, intake_excerpt, extra_guidance=extra_guidance)
    if not gen.get("ok"):
        return gen
    draft = store_draft(business_id, intake_excerpt, gen["spec"])
    if not draft:
        return {"ok": False, "error": "draft persist failed", "spec": gen["spec"]}
    return {"ok": True, "spec_id": draft["id"], "spec": gen["spec"]}


# ──────────────────────────────────────────────────────────────
# Materialization — accept turns draft into custom_modules row
# ──────────────────────────────────────────────────────────────

def materialize_spec(spec_id: str) -> Dict[str, Any]:
    """Idempotent on (business_id, slug): if a custom_modules row with that
    slug already exists, reuse it (no double-create). Otherwise insert.
    Marks the spec accepted + links materialized_module_id.
    Returns {ok, module, spec_id}."""
    spec_rows = sb_clients.sb_get_as_service(
        f"/module_specs?id=eq.{spec_id}&select=*&limit=1"
    ) or []
    if not spec_rows:
        return {"ok": False, "error": "spec not found"}
    spec_row = spec_rows[0]
    if spec_row.get("status") == "accepted" and spec_row.get("materialized_module_id"):
        # Already materialized — idempotent return.
        mod = sb_clients.sb_get_as_service(
            f"/custom_modules?id=eq.{spec_row['materialized_module_id']}&select=*&limit=1"
        ) or []
        return {"ok": True, "module": mod[0] if mod else None, "spec_id": spec_id,
                "note": "already accepted"}

    business_id = spec_row["business_id"]
    spec = spec_row["draft_json"] or {}
    slug = spec.get("slug")
    if not slug:
        return {"ok": False, "error": "spec missing slug"}

    # Pre-check idempotency on (business_id, slug).
    existing = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}&slug=eq.{slug}&select=id&limit=1"
    ) or []
    if existing:
        module_id = existing[0]["id"]
    else:
        # Materialize only what custom_modules supports today (Phase A scope).
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
        }
        created = sb_clients.sb_post_as_service("/custom_modules", cm_payload)
        if not (isinstance(created, list) and created):
            return {"ok": False, "error": "materialize insert failed"}
        module_id = created[0]["id"]

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
    return {"ok": True, "spec_id": spec_id, "module": mod[0] if mod else None}


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
