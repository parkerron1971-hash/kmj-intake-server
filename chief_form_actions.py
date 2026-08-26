"""
chief_form_actions.py — the Client Forms verbs.

THE GAP THIS CLOSES: `intake_forms` is a real, load-bearing table. The
public submit door (`intake_endpoint.submit_intake`) validates against it,
dedupes the lead through `lead_identity`, scores it, drafts a reply into the
Approval Queue, and can route the submission into a custom module. The
composed public site already advertises every active form
(`public_site.py` → `linked_forms`), and the app has a whole surface for
them — BUILD → "Client Forms".

Everything about that pipeline worked except the front door. There was no
verb to CREATE a form. `_seed_default_intake_form` writes one at signup and
nothing could write a second one, so Chief — asked for a new client
questionnaire — correctly reported that it could not, and the practitioner's
only route was to build it by hand. A capability the whole rest of the
system was already wired for was unreachable from the one surface that
should have reached it.

These verbs add no submission logic of their own. They write the same row
shape `_seed_default_intake_form` already writes, so the honeypot rules, the
required-field validation, the module routing and the dedupe all keep
exactly one home, and it is not here.

═══════════════════════════════════════════════════════════════════════
THE TWO INVARIANTS A CHIEF-WRITTEN FORM MUST HOLD
═══════════════════════════════════════════════════════════════════════
1. A field literally named `name`, and required.
   `submit_intake` raises 400 "Name is required" from `submission_data`
   BEFORE it ever loads the form config. A form without that field is a
   form where every single submission fails — and it fails at the
   client's browser, on the practitioner's own website, where nobody who
   could fix it is watching. So the field is added if the practitioner
   didn't ask for it, rather than accepted as an option.

2. No field name may collide with `intake_endpoint.HONEYPOT_FIELDS`.
   A honeypot's whole job is to be silent, so when it is WRONG it is also
   silent: a non-empty value drops the submission and answers 200. That
   has already cost this product every submission on affected forms once
   (see the HONEYPOT_FIELDS comment). Derivation from a label cannot
   produce one, but an explicitly-passed `name` can, so it is checked.

TRUST-LAYER DISCIPLINE:
  • What changes? create writes ONE `intake_forms` row plus a
    `client_form_created` event. update PATCHes one row it has already
    confirmed belongs to this business. Nothing is sent, nothing reaches
    a client, no money moves.
  • Seen first? The form is inert until the practitioner puts its embed
    on a page — and the result hands them the Client Forms screen to read
    it on. `is_active` is the off switch and update carries it.
  • Reversible? Class A both ways. A form deactivates; a field added is a
    field removable; submissions already captured live in `events` and
    `contacts` and are untouched by any edit here.
  • Ambiguity is refused, not guessed. `link_module` that matches no
    module — or matches several — returns a question rather than wiring
    submissions into whichever row sorted first. A misrouted form quietly
    files real client answers under the wrong solution.

Return shape: every handler returns {type, result, label, …, nav}. `result`
and `label` are NON-NEGOTIABLE — the frontend action card calls
.toLowerCase() on them and a missing key blanks the app.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("chief_form_actions")

# Hard ceiling on a single form. Long forms convert badly and the practitioner
# can always add more; this is a guard against a model emitting forty fields
# from an enthusiastic description, not a product opinion about form length.
MAX_FIELDS = 25

# What the form builder can actually draw. Synonyms are mapped rather than
# rejected — the model will say "dropdown" and "phone number", and refusing a
# form over a vocabulary mismatch is the dead-end this whole module exists to
# remove.
_TYPE_ALIASES = {
    "text": "text", "string": "text", "short_text": "text", "shorttext": "text",
    "name": "text", "single_line": "text",
    "email": "email", "e-mail": "email", "email_address": "email",
    "phone": "phone", "tel": "phone", "telephone": "phone",
    "phone_number": "phone", "mobile": "phone",
    "textarea": "textarea", "long_text": "textarea", "longtext": "textarea",
    "paragraph": "textarea", "message": "textarea", "multiline": "textarea",
    "select": "select", "dropdown": "select", "choice": "select",
    "picklist": "select", "options": "select",
    "checkbox": "checkbox", "boolean": "checkbox", "bool": "checkbox",
    "toggle": "checkbox", "yes_no": "checkbox",
    "date": "date", "datepicker": "date", "day": "date",
    "number": "number", "numeric": "number", "int": "number",
    "integer": "number", "quantity": "number",
}
VALID_TYPES = sorted(set(_TYPE_ALIASES.values()))

# Mirrors the vocabulary the seeded forms use. Anything else falls back to
# "general", which is what `submit_intake` itself defaults to.
_FORM_TYPES = ("general", "intake", "discovery", "consultation", "connect_card",
               "volunteer", "application", "feedback", "waitlist", "quote")

# THE THREE KEYS THE SUBMIT DOOR READS BY EXACT NAME.
#
# `submit_intake` pulls submission_data["name"] / ["email"] / ["phone"]
# directly and hands them to `lead_identity.resolve`. It does not consult
# the form's field list to find them. So a form that asks "Your Name" —
# which the builder transform turns into `your_name` — sends NOTHING under
# `name`, and the endpoint 400s every submission on a form that looks
# completely correct in the builder. Email is worse than an error: it is
# silent, and it turns off lead dedupe, so the same person enquiring twice
# becomes two contacts and two drafted replies.
#
# Every plausible label for those three lands on the canonical key here.
# `first_name` maps too: a contact carries ONE name, and taking the first
# is better than rejecting the submission.
_CANONICAL_NAMES = {
    "name": "name", "your_name": "name", "full_name": "name",
    "your_full_name": "name", "first_name": "name", "client_name": "name",
    "contact_name": "name", "customer_name": "name", "patient_name": "name",
    "email": "email", "your_email": "email", "email_address": "email",
    "your_email_address": "email", "e_mail": "email", "e_mail_address": "email",
    "phone": "phone", "your_phone": "phone", "phone_number": "phone",
    "your_phone_number": "phone", "telephone": "phone", "mobile": "phone",
    "mobile_number": "phone", "cell": "phone", "cell_phone": "phone",
    "contact_number": "phone", "best_number": "phone",
}

# The default form. Deliberately the same four fields
# `_seed_default_intake_form` writes — a practitioner who says "make me a
# contact form" and one who signed up last year should get the same thing.
_DEFAULT_FIELDS = [
    {"name": "name", "type": "text", "label": "Your Name", "required": True},
    {"name": "email", "type": "email", "label": "Email", "required": True},
    {"name": "phone", "type": "phone", "label": "Phone", "required": False},
    {"name": "message", "type": "textarea", "label": "How can we help?",
     "required": False},
]


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    logger.info(f"Action {action_type} failed: {msg}")
    # "failed": True is the machine-readable seam _action_failed reads —
    # without it a failure here is audited and narrated as a success.
    return {
        "type": action_type,
        "result": msg,
        "label": action_type,
        "nav": None,
        "failed": True,
    }


def _nav_forms() -> Dict[str, Any]:
    return {"tab": "build", "page": "intake-forms"}


# ─── field normalization ──────────────────────────────────────────────

def _field_name_from_label(label: str) -> str:
    """Mirror IntakeFormBuilder's label → name transform EXACTLY.

    The frontend builder derives a field's `name` this way, and the
    submission payload is keyed by `name`. A second, nearly-identical
    transform here would produce forms whose fields look right in the
    builder and arrive under different keys — so this is a copy on
    purpose, and the honeypot comment in intake_endpoint documents the
    same regex from the other side.
    """
    return re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")


def _normalize_field(raw: Any, index: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """One incoming field → the stored shape, or (None, error)."""
    if isinstance(raw, str):
        raw = {"label": raw}
    if not isinstance(raw, dict):
        return None, f"field {index + 1} isn't something I can read as a field"

    label = str(raw.get("label") or raw.get("title") or raw.get("question")
                or raw.get("name") or "").strip()
    if not label:
        return None, f"field {index + 1} has no label"

    from intake_endpoint import HONEYPOT_FIELDS

    explicit = str(raw.get("name") or "").strip()
    # Checked BEFORE the transform, which would launder `_hp` into a
    # harmless `hp` and hide the fact that something asked for a spam trap.
    if explicit in HONEYPOT_FIELDS:
        return None, (f"'{label}' collides with a spam-trap field name — "
                      f"rename it and every submission will land.")
    name = _field_name_from_label(explicit or label)
    if not name:
        return None, f"'{label}' doesn't reduce to a usable field name"
    # THE CANONICAL THREE. See _CANONICAL_NAMES.
    name = _CANONICAL_NAMES.get(name, name)

    raw_type = str(raw.get("type") or "").strip().lower()
    ftype = _TYPE_ALIASES.get(raw_type)
    if not ftype:
        # Infer from the name before giving up — "email" and "phone" are the
        # two the endpoint itself reads, and a model that omits the type on
        # those is common enough to be worth catching.
        ftype = _TYPE_ALIASES.get(name, "text")
    # A canonicalized identity field takes the type its key implies: an
    # "Email" question typed as free text is a mailto the client can typo.
    if name in ("email", "phone"):
        ftype = name

    field: Dict[str, Any] = {
        "name": name,
        "type": ftype,
        "label": label,
        "required": bool(raw.get("required")),
    }
    if raw.get("placeholder"):
        field["placeholder"] = str(raw["placeholder"])[:120]
    if ftype == "select":
        options = raw.get("options") or raw.get("choices") or []
        if isinstance(options, str):
            options = [o.strip() for o in options.split(",")]
        options = [str(o).strip() for o in options if str(o).strip()][:20]
        if not options:
            # A select with no options renders an empty dropdown the client
            # cannot answer. Demote rather than ship a dead control.
            field["type"] = "text"
        else:
            field["options"] = options
    return field, None


def _normalize_fields(raw_fields: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Normalize, de-duplicate, guarantee the `name` field, reject honeypots."""
    from intake_endpoint import HONEYPOT_FIELDS

    if raw_fields in (None, "", []):
        return [dict(f) for f in _DEFAULT_FIELDS], None
    if not isinstance(raw_fields, list):
        return [], "I need the fields as a list."
    if len(raw_fields) > MAX_FIELDS:
        return [], (f"That's {len(raw_fields)} questions — I cap a form at "
                    f"{MAX_FIELDS}. Tell me which ones matter most.")

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for i, raw in enumerate(raw_fields):
        field, err = _normalize_field(raw, i)
        if err:
            return [], err
        if field["name"] in HONEYPOT_FIELDS:
            # Unreachable by derivation, reachable by an explicit `name`.
            return [], (f"'{field['label']}' collides with a spam-trap field "
                        f"name — rename it and every submission will land.")
        if field["name"] in seen:
            continue
        seen.add(field["name"])
        out.append(field)

    # INVARIANT 1. The endpoint 400s without it, before it reads the form.
    by_name = {f["name"]: f for f in out}
    if "name" not in by_name:
        out.insert(0, {"name": "name", "type": "text", "label": "Your Name",
                       "required": True})
    else:
        by_name["name"]["required"] = True
        by_name["name"]["type"] = "text"
    return out, None


# ─── module linking ───────────────────────────────────────────────────

def _resolve_module(business_id: str, ref: str) -> Dict[str, Any]:
    """Resolve a module by id, slug or name. Returns {"module": row} or
    {"error": msg}.

    A miss ASKS rather than guessing: a form wired to the wrong module
    files real client answers under the wrong solution, and the
    practitioner finds out when the rows are already mixed.
    """
    ref = (ref or "").strip()
    if not ref:
        return {"error": "Which solution should the answers land in?"}

    if re.fullmatch(r"[0-9a-fA-F-]{36}", ref):
        rows = sb_clients.sb_get_as_service(
            f"/custom_modules?id=eq.{ref}&business_id=eq.{business_id}"
            f"&select=id,name,slug,schema&limit=1") or []
        if rows:
            return {"module": rows[0]}
        return {"error": "I couldn't find that solution."}

    safe = re.sub(r"[,()*]", " ", ref).strip()
    rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"
        f"&name=ilike.*{safe}*&select=id,name,slug,schema&limit=5") or []
    if not rows:
        rows = sb_clients.sb_get_as_service(
            f"/custom_modules?business_id=eq.{business_id}&is_active=eq.true"
            f"&slug=ilike.*{safe}*&select=id,name,slug,schema&limit=5") or []
    if not rows:
        return {"error": f"I don't have a solution called '{ref}'. "
                         f"Want me to build one first?"}
    if len(rows) > 1:
        names = ", ".join(r.get("name") or "" for r in rows)
        return {"error": f"Several solutions match '{ref}': {names}. "
                         f"Which one?"}
    return {"module": rows[0]}


def _auto_field_map(form_fields: List[Dict[str, Any]],
                    module: Dict[str, Any]) -> Dict[str, str]:
    """Map module field → form field where the names already agree.

    `_map_submission_to_module_data` falls back to a direct name match on
    its own, so this map only has to carry the pairs that AGREE — it is
    written explicitly so the practitioner can read the wiring in the
    Client Forms screen instead of inferring it.
    """
    schema_fields = ((module or {}).get("schema") or {}).get("fields") or []
    form_names = {f["name"] for f in form_fields}
    out: Dict[str, str] = {}
    for mf in schema_fields:
        if not isinstance(mf, dict):
            continue
        mname = mf.get("name")
        if mname and mname in form_names:
            out[mname] = mname
    return out


# ─── verbs ────────────────────────────────────────────────────────────

async def handle_create_client_form(client, biz, action) -> Dict[str, Any]:
    """Create a client form — the public questionnaire that captures a lead."""
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("create_client_form", "no business on record")

    name = (action.get("name") or action.get("title")
            or action.get("form_name") or "").strip()
    if not name:
        return _fail("create_client_form",
                     "What should I call the form? Clients see the name, so "
                     "something like 'New Client Questionnaire'.")
    name = name[:120]

    fields, err = _normalize_fields(
        action.get("fields") if action.get("fields") is not None
        else action.get("questions"))
    if err:
        return _fail("create_client_form", err)

    form_type = str(action.get("form_type") or "general").strip().lower()
    if form_type not in _FORM_TYPES:
        form_type = "general"

    settings: Dict[str, Any] = {
        "confirmation_message": (
            str(action.get("confirmation_message")
                or action.get("thank_you_message")
                or "Thanks — we'll be in touch soon.")[:300]),
        # The seeded form sets this and the scoring path reads the flag as a
        # practitioner preference; a Chief-made form matches it.
        "auto_score": True,
    }
    if action.get("description"):
        settings["description"] = str(action["description"])[:400]

    linked_name: Optional[str] = None
    link_ref = (action.get("link_module") or action.get("module_name")
                or action.get("module_id") or "")
    if link_ref:
        resolved = await asyncio.to_thread(_resolve_module, business_id, str(link_ref))
        if resolved.get("error"):
            return _fail("create_client_form", resolved["error"])
        module = resolved["module"]
        settings["linked_module_id"] = module["id"]
        settings["field_map"] = _auto_field_map(fields, module)
        linked_name = module.get("name")

    row = {
        "business_id": business_id,
        "name": name,
        "form_type": form_type,
        "fields": fields,
        "settings": settings,
        "is_active": bool(action.get("is_active", True)),
    }
    try:
        inserted = await asyncio.to_thread(sb_clients.sb_post_as_service,
                                           "/intake_forms", row)
    except Exception as e:
        logger.exception(f"create_client_form insert failed: {e}")
        return _fail("create_client_form",
                     "I couldn't save that form just now — try again in a moment.")
    if not inserted or not isinstance(inserted, list):
        return _fail("create_client_form",
                     "I couldn't save that form just now — try again in a moment.")

    form_id = inserted[0].get("id")

    # Event, best-effort. The form is real whether or not the spine hears.
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/events", {
            "business_id": business_id,
            "event_type": "client_form_created",
            "data": {"form_id": form_id, "name": name, "form_type": form_type,
                     "field_count": len(fields),
                     "linked_module_id": settings.get("linked_module_id")},
            "source": "chief_of_staff",
        }, "return=minimal")
    except Exception as e:
        logger.warning(f"[forms] event write failed (non-fatal): {e}")

    asked = ", ".join(f["label"] for f in fields[:6])
    if len(fields) > 6:
        asked += f", +{len(fields) - 6} more"
    result = (f"Created '{name}' — {len(fields)} question"
              f"{'s' if len(fields) != 1 else ''}: {asked}. It's live in "
              f"Client Forms with an embed snippet for your site, and it "
              f"shows up on your composed site automatically.")
    if linked_name:
        result += f" Every submission also files a row in {linked_name}."

    return {
        "type": "create_client_form",
        "result": result,
        "label": f"New client form — {name}",
        "form_id": form_id,
        "form_name": name,
        "field_count": len(fields),
        "fields": [{"label": f["label"], "type": f["type"],
                    "required": bool(f.get("required"))} for f in fields],
        "linked_module_id": settings.get("linked_module_id"),
        "embed_url": f"/public/widget/form/{form_id}" if form_id else None,
        "nav": _nav_forms(),
    }


async def handle_update_client_form(client, biz, action) -> Dict[str, Any]:
    """Rename a form, add or drop questions, change the thank-you message,
    wire it to a solution, or switch it off."""
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("update_client_form", "no business on record")

    ref = str(action.get("form_id") or action.get("form_name")
              or action.get("name") or "").strip()
    if not ref:
        return _fail("update_client_form", "Which form?")

    form = await asyncio.to_thread(_resolve_form, business_id, ref)
    if form.get("error"):
        return _fail("update_client_form", form["error"])
    form = form["form"]
    form_id = form["id"]

    patch: Dict[str, Any] = {}
    changes: List[str] = []

    new_name = (action.get("new_name") or action.get("rename_to") or "").strip()
    if new_name:
        patch["name"] = new_name[:120]
        changes.append(f"renamed to '{patch['name']}'")

    fields = list(form.get("fields") or [])

    # Wholesale replacement wins over the additive/subtractive ops — a
    # caller that sent a full field list means it.
    if action.get("fields") is not None:
        fields, err = _normalize_fields(action.get("fields"))
        if err:
            return _fail("update_client_form", err)
        changes.append(f"questions replaced ({len(fields)} now)")
    else:
        add = action.get("add_fields") or action.get("add_field")
        if add is not None:
            if isinstance(add, (str, dict)):
                add = [add]
            normalized, err = _normalize_fields(list(fields) + list(add))
            if err:
                return _fail("update_client_form", err)
            added = [f["label"] for f in normalized
                     if f["name"] not in {x.get("name") for x in fields}]
            fields = normalized
            if added:
                changes.append("added " + ", ".join(added))

        remove = action.get("remove_fields") or action.get("remove_field")
        if remove is not None:
            if isinstance(remove, str):
                remove = [remove]
            # Resolve against the form's ACTUAL fields, by name or by label.
            # "remove the phone question" arrives as the LABEL the
            # practitioner reads on screen ("Your Name"), which derives to
            # `your_name` and matches no field named `name` — so a
            # name-derived set alone silently removed nothing AND slipped
            # past the guard below.
            targets = set()
            for r in (remove or []):
                ref = str(r).strip()
                derived = _field_name_from_label(ref)
                for f in fields:
                    if (f.get("name") == ref
                            or f.get("name") == derived
                            or f.get("name") == _CANONICAL_NAMES.get(derived)
                            or _field_name_from_label(f.get("label") or "") == derived):
                        targets.add(f["name"])
            # INVARIANT 1 again, from the other direction: dropping `name`
            # would 400 every future submission at the client's browser.
            if "name" in targets:
                return _fail("update_client_form",
                             "I can't drop the name question — submissions are "
                             "rejected without it. I can rename its label though.")
            dropped = [f["label"] for f in fields if f["name"] in targets]
            fields = [f for f in fields if f["name"] not in targets]
            if dropped:
                changes.append("removed " + ", ".join(dropped))

    if fields != list(form.get("fields") or []):
        if not fields:
            return _fail("update_client_form", "A form needs at least one question.")
        patch["fields"] = fields

    settings = dict(form.get("settings") or {})
    settings_touched = False

    msg = (action.get("confirmation_message")
           or action.get("thank_you_message") or "")
    if msg:
        settings["confirmation_message"] = str(msg)[:300]
        settings_touched = True
        changes.append("new thank-you message")

    link_ref = (action.get("link_module") or action.get("module_name")
                or action.get("module_id") or "")
    if link_ref:
        resolved = await asyncio.to_thread(_resolve_module, business_id, str(link_ref))
        if resolved.get("error"):
            return _fail("update_client_form", resolved["error"])
        module = resolved["module"]
        settings["linked_module_id"] = module["id"]
        settings["field_map"] = _auto_field_map(
            patch.get("fields") or fields, module)
        settings_touched = True
        changes.append(f"answers now file into {module.get('name')}")
    elif action.get("unlink_module"):
        settings.pop("linked_module_id", None)
        settings.pop("field_map", None)
        settings_touched = True
        changes.append("unlinked from its solution")

    if settings_touched:
        patch["settings"] = settings

    if action.get("is_active") is not None:
        patch["is_active"] = bool(action["is_active"])
        changes.append("switched on" if patch["is_active"] else "switched off")

    form_type = str(action.get("form_type") or "").strip().lower()
    if form_type and form_type in _FORM_TYPES:
        patch["form_type"] = form_type
        changes.append(f"type set to {form_type}")

    if not patch:
        return _fail("update_client_form",
                     "Tell me what to change — the name, a question, the "
                     "thank-you message, or switching it off.")

    try:
        await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/intake_forms?id=eq.{form_id}&business_id=eq.{business_id}", patch)
    except Exception as e:
        logger.exception(f"update_client_form patch failed: {e}")
        return _fail("update_client_form",
                     "I couldn't save that change just now — try again in a moment.")

    display_name = patch.get("name") or form.get("name") or "the form"
    return {
        "type": "update_client_form",
        "result": f"Updated '{display_name}' — {'; '.join(changes)}.",
        "label": f"Client form updated — {display_name}",
        "form_id": form_id,
        "form_name": display_name,
        "changes": changes,
        "nav": _nav_forms(),
    }


async def handle_list_client_forms(client, biz, action) -> Dict[str, Any]:
    """What forms exist, and which of them are actually pulling leads."""
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("list_client_forms", "no business on record")

    include_inactive = bool(action.get("include_inactive"))
    query = (f"/intake_forms?business_id=eq.{business_id}"
             f"&select=id,name,form_type,fields,settings,is_active"
             f"&order=created_at.desc&limit=50")
    if not include_inactive:
        query += "&is_active=eq.true"
    try:
        rows = await asyncio.to_thread(sb_clients.sb_get_as_service, query) or []
    except Exception as e:
        logger.exception(f"list_client_forms read failed: {e}")
        return _fail("list_client_forms",
                     "I couldn't read your forms just now — try again in a moment.")

    if not rows:
        return {
            "type": "list_client_forms",
            "result": ("No client forms yet. Tell me what you need to ask new "
                       "clients and I'll build one."),
            "label": "Client forms — none yet",
            "forms": [],
            # `signal` is what the agent surface's handoff predicates read.
            # Prose gets reworded; a count does not (mcp_server.HANDOFFS).
            "signal": {"forms": 0, "active": 0, "submissions": 0},
            "nav": _nav_forms(),
        }

    # Submission counts, one bounded read. Worth the query: "which form is
    # actually working" is the question a list of forms exists to answer,
    # and without it the practitioner is reading names.
    counts: Dict[str, int] = {}
    try:
        events = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/events?business_id=eq.{business_id}&event_type=eq.form_submit"
            f"&select=data&order=created_at.desc&limit=1000") or []
        for ev in events:
            fid = ((ev or {}).get("data") or {}).get("form_id")
            if fid:
                counts[str(fid)] = counts.get(str(fid), 0) + 1
    except Exception as e:
        logger.warning(f"[forms] submission tally failed (non-fatal): {e}")

    forms = []
    for r in rows:
        fields = r.get("fields") or []
        forms.append({
            "form_id": r["id"],
            "name": r.get("name"),
            "form_type": r.get("form_type"),
            "is_active": bool(r.get("is_active", True)),
            "field_count": len(fields) if isinstance(fields, list) else 0,
            "questions": [f.get("label") for f in fields
                          if isinstance(f, dict)][:8],
            "submissions": counts.get(str(r["id"]), 0),
            "linked_module_id": (r.get("settings") or {}).get("linked_module_id"),
            "embed_url": f"/public/widget/form/{r['id']}",
        })

    lines = []
    for f in forms[:10]:
        state = "" if f["is_active"] else " (off)"
        lines.append(f"{f['name']}{state} — {f['field_count']} questions, "
                     f"{f['submissions']} submission"
                     f"{'s' if f['submissions'] != 1 else ''}")
    more = f" (+{len(forms) - 10} more)" if len(forms) > 10 else ""

    return {
        "type": "list_client_forms",
        "result": "; ".join(lines) + more,
        "label": f"{len(forms)} client form{'s' if len(forms) != 1 else ''}",
        "forms": forms,
        "signal": {"forms": len(forms),
                   "active": sum(1 for f in forms if f["is_active"]),
                   "submissions": sum(f["submissions"] for f in forms)},
        "nav": _nav_forms(),
    }


def _resolve_form(business_id: str, ref: str) -> Dict[str, Any]:
    """Resolve a form by id or name. Returns {"form": row} or {"error": msg}."""
    if re.fullmatch(r"[0-9a-fA-F-]{36}", ref):
        rows = sb_clients.sb_get_as_service(
            f"/intake_forms?id=eq.{ref}&business_id=eq.{business_id}"
            f"&select=*&limit=1") or []
        if rows:
            return {"form": rows[0]}
        return {"error": "I couldn't find that form."}

    safe = re.sub(r"[,()*]", " ", ref).strip()
    rows = sb_clients.sb_get_as_service(
        f"/intake_forms?business_id=eq.{business_id}&name=ilike.*{safe}*"
        f"&select=*&limit=5") or []
    if not rows:
        return {"error": f"I don't have a form called '{ref}'."}
    if len(rows) > 1:
        names = ", ".join(r.get("name") or "" for r in rows)
        return {"error": f"Several forms match '{ref}': {names}. Which one?"}
    return {"form": rows[0]}
