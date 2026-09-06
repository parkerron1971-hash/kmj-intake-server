"""
business_blueprint.py — bring the idea of a business, get the business.

WHY THIS EXISTS
───────────────
Chief built one module per intake. Kevin's brief (2026-09-06): anyone
with any business should be able to bring the idea to Chief and have it
lay out everything the business needs — custom, without "I can't build
that". The ten hand-written vertical blueprints do this for ten trades;
this does it for the rest, from a rubric rather than a table (the
generalization pattern: the model reasons, the output is a closed shape,
the deterministic layer executes).

TWO STAGES, ONE DESIGN
──────────────────────
  1. The MAP. One model call turns the idea into a BusinessBlueprint: a
     summary, the closest vertical, two to six modules each described as
     an INTAKE paragraph in the practitioner's voice, the offerings, the
     forms a stranger fills in, the site brief, and the rails — how the
     business gets paid, gets found, gets a way in, keeps records and
     follows up, or where it does not. business_quality reviews the map
     and the model revises once if something is missing.
  2. The BUILD. Each module intake goes through the existing module
     generator — skills, archetype palette, presentation, the second
     look — so every module is exactly as good as one asked for on its
     own. Nothing new to trust: the same validators, the same drafts,
     the same cards.

The map itself is kept (module_specs, status='blueprint' — never a card,
never accepted) so the forms and the site brief survive the turn: once
the module cards are accepted, Chief reads BUSINESS BLUEPRINT ON FILE
from its context and finishes the forms and offers the site.

Cost: one map call plus one build call per module (two when revised).
A whole business is roughly a dollar. Nothing materializes until the
practitioner accepts the cards.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

import business_quality
import llm_call
import module_spec_generator as msg
import sb_clients

logger = logging.getLogger("business_blueprint")

# The form field types create_client_form accepts, and its form_type set.
FormFieldType = Literal["text", "textarea", "email", "phone", "select", "date", "number", "checkbox"]
FormType = Literal["general", "intake", "discovery", "consultation", "connect_card",
                   "volunteer", "application", "feedback", "waitlist", "quote"]

BLUEPRINT_STATUS = "blueprint"          # module_specs.status for the map row
BLUEPRINT_SLUG = "business-blueprint"
CONTEXT_WINDOW_DAYS = 30                # how long the map stays in Chief's context


class _Clipped(BaseModel):
    """Prose fields are CLIPPED to their max_length, never refused.

    The first live run (KMJ, 2026-09-06) came back with a good map and
    was thrown away because four sentences ran past a 160-character cap:
    a closed shape is for the STRUCTURE (which fields, which form types,
    how many modules), not for how long the model's sentence is. A cap on
    prose is a display budget, so it trims; only list lengths and enums
    still reject."""

    @model_validator(mode="before")
    @classmethod
    def _clip_prose(cls, data):
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, info in cls.model_fields.items():
            v = out.get(name)
            if not isinstance(v, str):
                continue
            cap = None
            for m in info.metadata:
                cap = getattr(m, "max_length", None) or cap
            if cap and len(v) > cap:
                out[name] = v[:cap].rstrip()
        return out



class BlueprintModule(_Clipped):
    name: str = Field(..., max_length=60)
    # Fed to the module builder verbatim — the practitioner's own voice,
    # a paragraph, with the amounts, dates, people and nudges it needs.
    intake: str = Field(..., min_length=20, max_length=1200)
    why: Optional[str] = Field(default=None, max_length=300)


class FormField(_Clipped):
    label: str = Field(..., max_length=80)
    type: FormFieldType = "text"
    required: bool = False
    options: Optional[List[str]] = None


class BlueprintForm(_Clipped):
    name: str = Field(..., max_length=80)
    form_type: FormType = "intake"
    fields: List[FormField] = Field(..., min_length=1, max_length=12)
    link_module: Optional[str] = None       # a module NAME from this blueprint
    confirmation_message: Optional[str] = Field(default=None, max_length=300)


class SiteBrief(_Clipped):
    headline: str = Field(..., max_length=120)
    tagline: Optional[str] = Field(default=None, max_length=200)
    pages: List[str] = Field(default_factory=list, max_length=8)
    primary_cta: Optional[str] = Field(default=None, max_length=60)
    voice: Optional[str] = Field(default=None, max_length=240)


class RailCoverage(_Clipped):
    covered_by: Optional[str] = Field(default=None, max_length=240)
    gap: Optional[str] = Field(default=None, max_length=300)


class BusinessBlueprint(_Clipped):
    summary: str = Field(..., min_length=20, max_length=1200)
    business_type: str = "custom"
    modules: List[BlueprintModule] = Field(..., min_length=1, max_length=6)
    offerings: List[msg.ProposedOffering] = Field(default_factory=list, max_length=12)
    forms: List[BlueprintForm] = Field(default_factory=list, max_length=4)
    site: SiteBrief
    rails: Dict[str, RailCoverage] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _links_resolve(self):
        names = {m.name.strip().lower() for m in self.modules}
        for f in self.forms:
            if f.link_module and f.link_module.strip().lower() not in names:
                raise ValueError(
                    f"form '{f.name}' links to module '{f.link_module}', which is not "
                    f"one of this blueprint's modules")
        return self


RAILS = ("get_paid", "get_found", "get_booked", "keep_records", "follow_up")

_SYSTEM = """You lay out the operating system of a small business from a description of it. \
The person may be starting out or may run the business already and want everything set up. \
You do not build modules here — you write the MAP: what to track, what is sold, how a \
stranger gets in, what the site says, and how the business gets paid, gets found, keeps \
records and follows up. A separate builder turns each module intake into a real module, so \
the intake paragraphs are the most important thing you write.

Output STRICT JSON only:
{
  "summary": "one paragraph: what this business is, who it serves, how it earns, how a week runs",
  "business_type": "one of __VERTICALS__ — or \\"custom\\" when none fits",
  "modules": [
    {"name": "Title Case name",
     "intake": "a paragraph IN THE PRACTITIONER'S VOICE describing what to track: the thing, per whom, \
with what amounts and dates, what states it moves through, and what should nudge them \
('remind me when an invoice is 7 days overdue', 'tell me the day a client hits their goal'). \
Concrete nouns from the trade. This paragraph is handed to the module builder verbatim.",
     "why": "one sentence on why this business needs it on day one"}
  ],
  "offerings": [
    {"name": "...", "slug": "kebab-case", "category": "service|session|event|course|product|package|custom",
     "current_price": number or null, "currency": "usd", "duration_min": number or null,
     "description": "one customer-facing line", "show_price_to_customer": true, "reasoning": "..."}
  ],
  "forms": [
    {"name": "...", "form_type": "general|intake|discovery|consultation|connect_card|volunteer|application|feedback|waitlist|quote",
     "fields": [{"label": "...", "type": "text|textarea|email|phone|select|date|number|checkbox", "required": true, "options": [...]}],
     "link_module": "the NAME of the module its submissions land in, or null",
     "confirmation_message": "what they see after submitting"}
  ],
  "site": {"headline": "in the customer's words", "tagline": "...", "pages": ["Home", ...],
           "primary_cta": "the one thing a visitor should do first", "voice": "how it should sound"},
  "rails": {
    "get_paid":     {"covered_by": "the offering or module that does it", "gap": null or "what is missing"},
    "get_found":    {"covered_by": "...", "gap": null},
    "get_booked":   {"covered_by": "...", "gap": null},
    "keep_records": {"covered_by": "...", "gap": null},
    "follow_up":    {"covered_by": "...", "gap": null}
  }
}

RULES
- Two to six modules, ordered by what they will open most. Name the thing they add to every \
day first (clients, jobs, sessions, orders). Do not invent a module for every noun in the idea; \
a business that opens to nine tiles closes the app.
- The builder has purpose-built surfaces for: bookings with a customer form; staged work on a \
board; an occasion with people to count; documents to sign; a number tracked toward a goal per \
person; and a log with a front page of totals and trends. Write each intake so the shape is \
unmistakable ('appointments a customer books', 'jobs that move from estimate to invoiced', \
'each client's score climbing toward 720', 'expenses I want to see add up by month').
- Every business needs a way to get paid, a way to be found, a door for a stranger, a place \
its records live, and one thing that nudges the owner without being asked. If the idea does \
not give you one of these, ADD the smallest honest thing that provides it and say so in \
rails.covered_by; if it genuinely cannot be provided, say so in rails.gap rather than \
pretending.
- Offerings: only what the idea names or plainly implies; prices only when given (null \
otherwise). Forms: one intake form is almost always right; link it to the module its answers \
belong in. Do not add a name question — the form adds it itself.
- Write in the trade's words, not software words. No markdown, no commentary outside the JSON.
"""

_USER = """The business: {name} (type so far: {btype})

What they said, in their words:
\"\"\"
{idea}
\"\"\"

Output the JSON map now."""


def _system_prompt() -> str:
    try:
        import vertical_registry
        keys = ", ".join(vertical_registry.canonical_keys())
    except Exception:
        keys = "barber, lawyer, coach, ministry, consultant, contractor, creative, nonprofit"
    return _SYSTEM.replace("__VERTICALS__", keys)


def _call(client, system: str, user: str) -> Dict[str, Any]:
    try:
        m = client.messages.create(
            model=msg.GENERATOR_MODEL, max_tokens=msg.GENERATOR_MAX_TOKENS,
            system=system, messages=[{"role": "user", "content": user}])
        raw = "".join(b.text for b in m.content if getattr(b, "type", None) == "text")
    except Exception as e:
        return {"ok": False, "error": f"llm_call_failed: {e}"}
    text = msg._strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"non_json: {e}", "raw": text[:400]}
    try:
        bp = BusinessBlueprint.model_validate(data)
    except ValidationError as ve:
        return {"ok": False, "error": f"validation_failed: {ve}"}
    return {"ok": True, "blueprint": bp}


def generate_business_blueprint(business: Dict[str, Any], idea: str) -> Dict[str, Any]:
    """Stage one: the map, reviewed once. Returns {ok, blueprint(dict), quality}."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not set"}
    idea = (idea or "").strip()
    if len(idea) < 15:
        return {"ok": False, "error": "say a little more about the business — a sentence or two"}
    try:
        client = llm_call.sdk_client(key=api_key)
    except Exception as e:
        return {"ok": False, "error": f"llm_call_failed: {e}"}
    system = _system_prompt()
    user = _USER.format(name=business.get("name", ""), btype=business.get("type", "custom"), idea=idea)

    first = _call(client, system, user)
    if not first.get("ok"):
        return first
    bp = first["blueprint"].model_dump(exclude_none=True)
    report = business_quality.assess(bp)
    quality: Dict[str, Any] = {"first": report.as_dict(), "revised": None, "used": "first"}
    if msg.CRITIQUE_ENABLED and report.needs_revision:
        logger.info("[business_quality] revising: " + ", ".join(
            f.code for f in report.findings if f.severity == "revise"))
        second = _call(client, system, user + "\n\n" + report.revision_block())
        if second.get("ok"):
            bp2 = second["blueprint"].model_dump(exclude_none=True)
            report2 = business_quality.assess(bp2)
            quality["revised"] = report2.as_dict()
            if report2.score <= report.score:
                bp, quality["used"] = bp2, "revised"
    return {"ok": True, "blueprint": bp, "quality": quality}


# ─── the map on file ────────────────────────────────────────────────────

def _store_blueprint(business_id: str, idea: str, bp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Keep the map. status='blueprint', not 'draft': it is never a card
    and the accept path never sees it."""
    keep = dict(bp)
    keep["__kind"] = "business"
    row = sb_clients.sb_post_as_service("/module_specs", {
        "business_id": business_id,
        "slug": BLUEPRINT_SLUG,
        "draft_json": keep,
        "intake_excerpt": idea[:2000],
        "status": BLUEPRINT_STATUS,
    })
    if isinstance(row, list) and row:
        return row[0]
    return None


def latest_blueprint(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/module_specs?business_id=eq.{business_id}&status=eq.{BLUEPRINT_STATUS}"
        f"&select=id,draft_json,created_at&order=created_at.desc&limit=1") or []
    return rows[0] if isinstance(rows, list) and rows else None


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _form_line(f: Dict[str, Any]) -> str:
    fields = ", ".join(
        f"{x.get('label')}{'*' if x.get('required') else ''}({x.get('type', 'text')}"
        f"{': ' + '/'.join(x.get('options') or []) if x.get('options') else ''})"
        for x in (f.get("fields") or []))
    link = f" → {f['link_module']}" if f.get("link_module") else ""
    conf = f' · after: "{f["confirmation_message"]}"' if f.get("confirmation_message") else ""
    return f"    - {f.get('name')} [{f.get('form_type', 'intake')}{link}]: {fields}{conf}"


def context_block(business_id: str) -> str:
    """BUSINESS BLUEPRINT ON FILE — the map behind the cards, for the turns
    after the practitioner accepts them. Lists the forms not yet created
    (by name, against live intake_forms) and the site brief, so Chief
    can finish the business without being told twice. Empty when there
    is no recent map."""
    row = latest_blueprint(business_id)
    if not row:
        return ""
    when = _parse_ts(row.get("created_at"))
    if when and datetime.now(timezone.utc) - when > timedelta(days=CONTEXT_WINDOW_DAYS):
        return ""
    bp = row.get("draft_json") or {}
    forms = [f for f in (bp.get("forms") or []) if isinstance(f, dict)]
    live = sb_clients.sb_get_as_service(
        f"/intake_forms?business_id=eq.{business_id}&is_active=eq.true&select=name&limit=100") or []
    live_names = {(r.get("name") or "").strip().lower() for r in live if isinstance(r, dict)}
    missing = [f for f in forms if (f.get("name") or "").strip().lower() not in live_names]

    day = when.strftime("%Y-%m-%d") if when else "recently"
    lines = [f"BUSINESS BLUEPRINT ON FILE (laid out from their idea on {day} — the map behind the "
             f"module cards; the forms and the site are YOURS to finish once the cards are accepted, "
             f"one create_client_form per form below, exactly as written, then offer the site):"]
    if bp.get("business_type") and bp["business_type"] != "custom":
        lines.append(f"  Closest trade: {bp['business_type']}")
    if forms:
        if missing:
            lines.append("  Forms still to create:")
            lines.extend(_form_line(f) for f in missing)
        else:
            lines.append("  Forms: all created.")
    site = bp.get("site") if isinstance(bp.get("site"), dict) else {}
    if site.get("headline"):
        bits = [f'headline "{site["headline"]}"']
        if site.get("tagline"):
            bits.append(f'tagline "{site["tagline"]}"')
        if site.get("primary_cta"):
            bits.append(f'first thing a visitor does: {site["primary_cta"]}')
        if site.get("pages"):
            bits.append("pages " + " / ".join(site["pages"]))
        if site.get("voice"):
            bits.append(f'voice: {site["voice"]}')
        lines.append("  Site brief (if PRACTITIONER SITE says no site yet, offer enqueue_job rebuild_site "
                     "with these as brief_notes): " + "; ".join(bits))
    rails = bp.get("rails") if isinstance(bp.get("rails"), dict) else {}
    gaps = [f"{k.replace('_', ' ')}: {v.get('gap')}" for k, v in rails.items()
            if isinstance(v, dict) and (v.get("gap") or "").strip()]
    if gaps:
        lines.append("  Not covered yet (say so if they ask; never pretend): " + "; ".join(gaps))
    return "\n".join(lines)


# ─── the whole door ─────────────────────────────────────────────────────

def propose_business_from_idea(business_id: str, idea: str) -> Dict[str, Any]:
    """map → build each module through the module generator → store every
    draft → return the card stack the dock already knows how to render,
    plus the forms, site brief and rails for Chief to narrate."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1") or []
    if not rows:
        return {"ok": False, "error": "business not found"}
    biz = rows[0]

    mapped = generate_business_blueprint(biz, idea)
    if not mapped.get("ok"):
        return mapped
    bp = mapped["blueprint"]

    proposals: List[Dict[str, Any]] = []
    built_slugs: set = set()
    module_reports: List[Dict[str, Any]] = []
    build_biz = dict(biz)
    if bp.get("business_type") and bp["business_type"] != "custom":
        build_biz["type"] = bp["business_type"]      # the builder's vertical lens

    for m in bp.get("modules") or []:
        gen = msg.generate_module_proposal(build_biz, m["intake"])
        if not gen.get("ok"):
            module_reports.append({"module": m["name"], "ok": False, "error": gen.get("error")})
            continue
        module_reports.append({"module": m["name"], "ok": True, "quality": gen.get("quality")})
        for spec in gen.get("specs") or []:
            slug = spec.get("slug")
            if not slug or slug in built_slugs:
                continue                          # two intakes that decomposed into the same thing
            built_slugs.add(slug)
            draft = msg.store_draft(business_id, m["intake"], spec, kind="module")
            if draft:
                proposals.append({"spec_id": draft["id"], "kind": "module", "spec": spec})
        for off in gen.get("offerings") or []:
            if not off.get("slug") or off.get("slug") in built_slugs:
                continue
            built_slugs.add(off.get("slug"))
            d = msg.store_draft(business_id, m["intake"], off, kind="offering")
            if d:
                proposals.append({"spec_id": d["id"], "kind": "offering", "offering": off})

    # The map's own offerings, minus any the module builder already produced.
    for off in bp.get("offerings") or []:
        if not off.get("slug") or off.get("slug") in built_slugs:
            continue
        built_slugs.add(off.get("slug"))
        d = msg.store_draft(business_id, idea, off, kind="offering")
        if d:
            proposals.append({"spec_id": d["id"], "kind": "offering", "offering": off})

    if not proposals:
        return {"ok": False, "error": "the map came back but no module could be built from it",
                "blueprint": bp, "module_reports": module_reports}

    _store_blueprint(business_id, idea, bp)

    rails = bp.get("rails") or {}
    rail_lines = []
    for key in RAILS:
        r = rails.get(key) or {}
        label = key.replace("_", " ")
        if r.get("gap"):
            rail_lines.append(f"{label}: NOT YET — {r['gap']}")
        elif r.get("covered_by"):
            rail_lines.append(f"{label}: {r['covered_by']}")
    reasoning = (bp.get("summary") or "").strip()
    if rail_lines:
        reasoning += "\n\nHow it runs: " + "; ".join(rail_lines) + "."

    return {
        "ok": True,
        "decomposition_reasoning": reasoning,
        "proposals": proposals,
        "forms": bp.get("forms") or [],
        "site": bp.get("site") or {},
        "rails": rails,
        "business_type": bp.get("business_type"),
        "quality": mapped.get("quality"),
        "module_reports": module_reports,
    }
