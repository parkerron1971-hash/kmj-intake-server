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

IT IS A LONG TASK. The first live run (KMJ, 2026-09-06) took four and a
half minutes inside a chat turn; the stream went silent, the connection
dropped, the app re-sent the message and the business was built twice.
So the door is a chief_jobs kind (`lay_out_business`): Chief enqueues
it and answers at once, the job pill shows each step, and when it lands
the cards come back through replay() — the BUSINESS BLUEPRINT ON FILE
context block tells Chief they are READY, and the frontend can fetch
them straight into the chat. The map itself is kept (module_specs,
status='blueprint' — never a card, never accepted) so the forms and the
site brief survive: once the cards are accepted, Chief finishes the
forms and offers the site.

Cost: one map call plus one build call per module (two when revised).
A whole business is roughly a dollar. Nothing materializes until the
practitioner accepts the cards.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Literal, Optional
from urllib.parse import quote

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
BUILD_WORKERS = 3                       # module builds in flight at once


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

JOB_KIND = "lay_out_business"           # chief_jobs kind — the door is a LONG TASK
MAX_MODULES = 6                         # cards a business opens to on day one
MAX_OFFERINGS = 5                       # the builder's come first, the map fills the rest
REPLAY_WINDOW_HOURS = 24                # how long finished cards can be re-shown

# One intake, ONE module. The map already decided how many pieces the
# business has; without this the builder decomposes each intake again
# (the first KMJ run: 4 map entries became 7 modules).
_ONE_MODULE_GUIDANCE = (
    "This intake is ONE piece of a larger plan whose other pieces are being "
    "built alongside it. Propose exactly ONE module spec for it — do not split "
    "it into several modules and do not add modules for things it mentions in "
    "passing. Offerings for the services it names are welcome.")


def _store_blueprint(business_id: str, idea: str, bp: Dict[str, Any],
                     started_at: str) -> Optional[Dict[str, Any]]:
    """Keep the map. status='blueprint', not 'draft': it is never a card
    and the accept path never sees it. Written LAST, so it carries the
    run's start time — the drafts it owns are the ones created since."""
    keep = dict(bp)
    keep["__kind"] = "business"
    keep["__shown"] = False
    keep["__started_at"] = started_at
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
        f"&select=id,draft_json,intake_excerpt,created_at&order=created_at.desc&limit=1") or []
    return rows[0] if isinstance(rows, list) and rows else None


def mark_shown(blueprint_row: Dict[str, Any]) -> None:
    """The cards went to the dock: the context block stops saying READY."""
    bp = dict(blueprint_row.get("draft_json") or {})
    bp["__shown"] = True
    sb_clients.sb_patch_as_service(
        f"/module_specs?id=eq.{blueprint_row['id']}", {"draft_json": bp})


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _age(row: Dict[str, Any]) -> Optional[timedelta]:
    when = _parse_ts(row.get("created_at"))
    return (datetime.now(timezone.utc) - when) if when else None


def _owned_since(row: Dict[str, Any]) -> str:
    """The drafts a map row owns: everything since its run started."""
    return str((row.get("draft_json") or {}).get("__started_at") or row.get("created_at") or "")


def _drafts_since(business_id: str, created_at: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/module_specs?business_id=eq.{business_id}&status=eq.draft"
        f"&created_at=gte.{quote(created_at, safe='')}&select=id,draft_json,created_at"
        f"&order=created_at.asc&limit=40") or []
    return [r for r in rows if isinstance(r, dict)]


def _proposals_from_drafts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        dj = dict(r.get("draft_json") or {})
        kind = dj.pop("__kind", "module") or "module"
        if kind == "business":
            continue
        out.append({"spec_id": r["id"], "kind": kind,
                    ("offering" if kind == "offering" else "spec"): dj})
    return out


def _narrate(bp: Dict[str, Any]) -> str:
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
    return reasoning


def latest_job(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/chief_jobs?business_id=eq.{business_id}&kind=eq.{JOB_KIND}"
        f"&select=id,status,error,result,created_at,finished_at&order=created_at.desc&limit=1") or []
    return rows[0] if isinstance(rows, list) and rows else None


def active_job(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/chief_jobs?business_id=eq.{business_id}&kind=eq.{JOB_KIND}"
        f"&status=in.(queued,running)&select=id,status,created_at&limit=1") or []
    return rows[0] if isinstance(rows, list) and rows else None


def replay(business_id: str) -> Optional[Dict[str, Any]]:
    """The cards a finished job left behind, as the handler returns them.
    None when there is no recent map or its cards are gone (accepted,
    rejected, or older than the replay window)."""
    row = latest_blueprint(business_id)
    if not row:
        return None
    age = _age(row)
    if age is not None and age > timedelta(hours=REPLAY_WINDOW_HOURS):
        return None
    proposals = _proposals_from_drafts(_drafts_since(business_id, _owned_since(row)))
    if not proposals:
        return None
    bp = row.get("draft_json") or {}
    return {
        "ok": True,
        "blueprint_row": row,
        "idea": row.get("intake_excerpt") or "",
        "shown": bool(bp.get("__shown")),
        "decomposition_reasoning": _narrate(bp),
        "proposals": proposals,
        "forms": bp.get("forms") or [],
        "site": bp.get("site") or {},
        "rails": bp.get("rails") or {},
        "business_type": bp.get("business_type"),
    }


def _form_line(f: Dict[str, Any]) -> str:
    fields = ", ".join(
        f"{x.get('label')}{'*' if x.get('required') else ''}({x.get('type', 'text')}"
        f"{': ' + '/'.join(x.get('options') or []) if x.get('options') else ''})"
        for x in (f.get("fields") or []))
    link = f" → {f['link_module']}" if f.get("link_module") else ""
    conf = f' · after: "{f["confirmation_message"]}"' if f.get("confirmation_message") else ""
    return f"    - {f.get('name')} [{f.get('form_type', 'intake')}{link}]: {fields}{conf}"


def _job_record(business_id: str, row: Optional[Dict[str, Any]]) -> str:
    """The last layout job, when it is not in flight: FAILED (offer to run
    it again) or FINISHED with nothing left to replay (its cards were
    accepted, rejected or aged out). Empty when the cards are still
    waiting — the CARDS READY line covers that — or there was no job."""
    job = latest_job(business_id)
    if not job or job.get("status") in ("queued", "running"):
        return ""
    when = _parse_ts(job.get("finished_at") or job.get("created_at"))
    if when and datetime.now(timezone.utc) - when > timedelta(hours=REPLAY_WINDOW_HOURS):
        return ""
    stamp = when.strftime("%H:%M UTC") if when else "recently"
    if job.get("status") == "failed":
        return (f"BUSINESS LAYOUT FAILED at {stamp}: {str(job.get('error') or 'no reason recorded')[:160]} "
                f"— say so plainly and offer to run it again (emit propose_business_from_idea with their idea).")
    res = job.get("result") if isinstance(job.get("result"), dict) else {}
    if res.get("ok") is False:
        return (f"BUSINESS LAYOUT FAILED at {stamp}: {str(res.get('error') or 'no reason recorded')[:160]} "
                f"— say so plainly and offer to run it again (emit propose_business_from_idea with their idea).")
    if replay(business_id):
        return ""
    names = ", ".join(str(n) for n in (res.get("modules") or [])[:6]) or "the pieces it mapped"
    return (f"BUSINESS LAYOUT FINISHED at {stamp} ({names}). Its cards are no longer waiting — "
            f"each was accepted (see CUSTOM MODULES), rejected, or is older than a day. Never say "
            f"nothing ran; offer to lay it out again if they want more.")


def context_block(business_id: str) -> str:
    """BUSINESS BLUEPRINT ON FILE — the map behind the cards, for the turns
    after the practitioner accepts them, and the two states around the
    job: STILL LAYING OUT (a job is running — do not start another) and
    CARDS READY (the job finished, the cards were never shown — emit the
    action and they render instantly). Empty when there is no recent map
    and no job."""
    job = active_job(business_id)
    row = latest_blueprint(business_id)
    record = "" if job else _job_record(business_id, row)
    if not row:
        if record:
            return record
        if job:
            return (f"BUSINESS LAYOUT IN PROGRESS ({JOB_KIND} job {job.get('status')}): the map "
                    f"and the cards are being built right now — say it is in progress "
                    f"and will be a few minutes; do NOT emit propose_business_from_idea again.")
        return ""
    age = _age(row)
    if age is not None and age > timedelta(days=CONTEXT_WINDOW_DAYS):
        return ""
    bp = row.get("draft_json") or {}
    lines: List[str] = []
    if record:
        lines.append(record)
    if job:
        lines.append(f"BUSINESS LAYOUT IN PROGRESS ({JOB_KIND} job {job.get('status')}): a new "
                     f"layout is being built right now — say so; do NOT emit "
                     f"propose_business_from_idea again.")
    elif not bp.get("__shown") and age is not None and age <= timedelta(hours=REPLAY_WINDOW_HOURS):
        drafts = _drafts_since(business_id, _owned_since(row))
        if any((d.get("draft_json") or {}).get("__kind") != "business" for d in drafts):
            idea = (row.get("intake_excerpt") or "").replace('"', "'")[:400]
            lines.append(
                f'CARDS READY, NOT YET SHOWN: the layout job finished. On their next message '
                f'— whatever it says — emit [ACTION:{{"type":"propose_business_from_idea",'
                f'"idea":"{idea}"}}] and the cards render instantly (no rebuild, no cost). '
                f'Say the layout is ready and the cards are below.')

    forms = [f for f in (bp.get("forms") or []) if isinstance(f, dict)]
    live = sb_clients.sb_get_as_service(
        f"/intake_forms?business_id=eq.{business_id}&is_active=eq.true&select=name&limit=100") or []
    live_names = {(r.get("name") or "").strip().lower() for r in live if isinstance(r, dict)}
    missing = [f for f in forms if (f.get("name") or "").strip().lower() not in live_names]

    when = _parse_ts(row.get("created_at"))
    day = when.strftime("%Y-%m-%d") if when else "recently"
    lines.append(f"BUSINESS BLUEPRINT ON FILE (laid out from their idea on {day} — the map behind the "
                 f"module cards; the forms and the site are YOURS to finish once the cards are accepted, "
                 f"one create_client_form per form below, exactly as written, then offer the site):")
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


# ─── the whole door (runs INSIDE a chief_jobs worker) ───────────────────

def propose_business_from_idea(business_id: str, idea: str,
                               progress_cb: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
    """map → build each module (in parallel, ONE module per intake) → store
    every draft → keep the map. Returns the card stack plus the forms,
    site brief and rails. Four to five minutes serial on the first live
    run; the parallel build brings a four-module business to about two.
    This is the body of the `lay_out_business` job, never a chat turn."""
    def _say(pct: int, msg: str) -> None:
        """progress(pct, stage) — the job pill shows the stage live, so the
        practitioner watches the map land and each piece get built."""
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    started_at = datetime.now(timezone.utc).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1") or []
    if not rows:
        return {"ok": False, "error": "business not found"}
    biz = rows[0]

    _say(5, "drawing the map of the business")
    mapped = generate_business_blueprint(biz, idea)
    if not mapped.get("ok"):
        return mapped
    bp = mapped["blueprint"]
    modules = (bp.get("modules") or [])[:MAX_MODULES]
    _say(15, f"map ready: {len(modules)} pieces — building each one")

    build_biz = dict(biz)
    if bp.get("business_type") and bp["business_type"] != "custom":
        build_biz["type"] = bp["business_type"]      # the builder's vertical lens

    def _build(m: Dict[str, Any]) -> Dict[str, Any]:
        gen = msg.generate_module_proposal(build_biz, m["intake"], _ONE_MODULE_GUIDANCE)
        return {"module": m, "gen": gen}

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=BUILD_WORKERS) as pool:
        for r in pool.map(_build, modules):
            results.append(r)
            _say(15 + int(80 * len(results) / max(1, len(modules))),
                 f"built {r['module']['name']} ({len(results)} of {len(modules)})")

    proposals: List[Dict[str, Any]] = []
    built_slugs: set = set()
    module_reports: List[Dict[str, Any]] = []
    n_modules = 0
    for r in results:
        m, gen = r["module"], r["gen"]
        if not gen.get("ok"):
            module_reports.append({"module": m["name"], "ok": False, "error": gen.get("error")})
            continue
        module_reports.append({"module": m["name"], "ok": True, "quality": gen.get("quality")})
        # ONE module per intake: the first spec is the one asked for; any
        # extra the builder produced anyway is dropped and reported.
        specs = [s for s in (gen.get("specs") or []) if s.get("slug")]
        for spec in specs[1:]:
            module_reports.append({"module": m["name"], "ok": True,
                                   "dropped": spec.get("slug"), "why": "one module per piece"})
        for spec in specs[:1]:
            slug = spec["slug"]
            if slug in built_slugs or n_modules >= MAX_MODULES:
                continue
            built_slugs.add(slug)
            draft = msg.store_draft(business_id, m["intake"], spec, kind="module")
            if draft:
                n_modules += 1
                proposals.append({"spec_id": draft["id"], "kind": "module", "spec": spec})
        for off in gen.get("offerings") or []:
            if not off.get("slug") or off.get("slug") in built_slugs:
                continue
            built_slugs.add(off.get("slug"))
            d = msg.store_draft(business_id, m["intake"], off, kind="offering")
            if d:
                proposals.append({"spec_id": d["id"], "kind": "offering", "offering": off})

    # The map's own offerings, minus any the module builder already produced,
    # up to the cap — eleven cards is a wall, not a business.
    for off in bp.get("offerings") or []:
        if sum(1 for p in proposals if p.get("kind") == "offering") >= MAX_OFFERINGS:
            break
        if not off.get("slug") or off.get("slug") in built_slugs:
            continue
        built_slugs.add(off.get("slug"))
        d = msg.store_draft(business_id, idea, off, kind="offering")
        if d:
            proposals.append({"spec_id": d["id"], "kind": "offering", "offering": off})

    if not proposals:
        return {"ok": False, "error": "the map came back but no module could be built from it",
                "blueprint": bp, "module_reports": module_reports}

    # The map row is written LAST so replay() only ever sees a finished set.
    # Without it the cards are orphans (nothing can show them), so a
    # refused insert is a failed run, said plainly — the first live run
    # lost its map to a status CHECK that did not know 'blueprint'
    # (supabase/APPLY-2026-09-06-module-specs-status-blueprint.sql).
    if not _store_blueprint(business_id, idea, bp, started_at):
        logger.error("[business_blueprint] map row refused — is module_specs.status "
                     "allowed to be 'blueprint'? (APPLY-2026-09-06-module-specs-status-blueprint.sql)")
        return {"ok": False, "error": "built the cards but couldn't keep the map — try again",
                "module_reports": module_reports}
    _say(100, "done — the cards are ready")

    return {
        "ok": True,
        "decomposition_reasoning": _narrate(bp),
        "proposals": proposals,
        "forms": bp.get("forms") or [],
        "site": bp.get("site") or {},
        "rails": bp.get("rails") or {},
        "business_type": bp.get("business_type"),
        "quality": mapped.get("quality"),
        "module_reports": module_reports,
    }


def run_job(business_id: str, params: Dict[str, Any],
            progress_cb: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
    """chief_jobs._execute_kind body. The job row keeps a SUMMARY (names,
    counts); the cards themselves live in module_specs and come back
    through replay() when Chief shows them."""
    idea = str((params or {}).get("idea") or "").strip()
    res = propose_business_from_idea(business_id, idea, progress_cb=progress_cb)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "couldn't lay it out")[:300]}
    mods = [(p.get("spec") or {}).get("name") for p in res["proposals"] if p.get("kind") == "module"]
    offs = [(p.get("offering") or {}).get("name") for p in res["proposals"] if p.get("kind") == "offering"]
    return {"ok": True, "modules": mods, "offerings": offs,
            "forms": len(res.get("forms") or []), "business_type": res.get("business_type"),
            "quality_used": (res.get("quality") or {}).get("used")}
