"""
chief_module_actions.py — custom modules: propose, inspect, accept,
reject, extend, summarize, upgrade.

Split out of chief_of_staff.py on 2026-09-04, the third slice of
"split the monolith along the registry" (after chief_strategy_actions
and chief_grow_actions). Seven verbs and one helper, bodies
byte-identical to where they were.

WHAT LIVES HERE
  The conversational path into custom modules: a free-text intake
  answer becomes one or more module proposals (propose_module_from_intake),
  a proposal is materialised or declined (accept_module_spec /
  reject_module_spec), an existing module is read, extended or rolled
  up (inspect_module, add_module_field, summarize_module), and a module
  is promoted to a richer archetype (upgrade_module_archetype). The
  schema work itself lives in module_vocabulary; these handlers are the
  politeness layer over it.

  _has_dup_override — the phrase match for "I really do want a second
  one of this archetype". The turn also consults it (chief_of_staff
  imports it back by name) so the outer politeness layer and the
  handler agree on what counts as an override.

HOST HELPERS. _sb, _fail and _nav resolve into chief_of_staff at call
time through chief_host, so tests that monkeypatch `cos._sb` still
cover these handlers. module_vocabulary and sb_clients are imported as
modules, so a test that patches an attribute on either patches what
these handlers see.

REGISTRATION. chief_of_staff imports every handle_* by name, so
`chief_of_staff.handle_accept_module_spec` is the same function object
test_module_inspect and test_chat_trust_gate drive.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import module_vocabulary
import sb_clients

from chief_host import _sb, _fail, _nav

# Same logger name as the file this came from.
logger = logging.getLogger("chief_of_staff")


def _has_dup_override(text: str) -> bool:
    """C.1.5 Plan A (M9-B) — conservative phrase match for 'I really want
    a second one of this archetype' override intent. False negatives are
    recoverable (Chief surfaces the override hint in its reply); false
    positives are also caught by the materialize_spec server guard. The
    point is to make the OUTER politeness layer correct most of the
    time; the INNER correctness layer is materialize_spec's guard."""
    s = (text or "").lower()
    overrides = (
        "anyway",
        "add another",
        "another booking",
        "second booking",
        "second one",
        "force it",
        "i still want",
        "i want another",
        "make a second",
    )
    return any(p in s for p in overrides)


async def handle_propose_module_from_intake(client, biz, action):
    """Phase B / G13 — turn a free-text intake answer into ONE OR MORE
    ModuleSpec drafts (multi-module decomposition when 2+ trackable objects).
    Returns proposals[] + decomposition_reasoning inline so the dock card stack
    can render. action: {intake_excerpt, revise_feedback?}

    Phase C.1.5 Plan A (M9-B): filter out module-kind proposals whose
    archetype is in _SINGLE_INSTANCE_ARCHETYPES if the business already
    has an active module of that archetype AND the practitioner did NOT
    include an explicit override phrase in the intake. When everything
    is filtered, surface a result that prompts the practitioner for an
    override. With override, the proposals pass through to the dock
    (the materialize_spec guard catches them at accept-time as the
    inner correctness layer — defense-in-depth)."""
    intake = (action.get("intake_excerpt") or "").strip()
    if not intake:
        return _fail("propose_module_from_intake", "intake_excerpt required")
    try:
        import asyncio as _aio
        import module_spec_generator as msg
    except Exception as e:
        return _fail("propose_module_from_intake", f"generator unavailable: {e}")
    # C.1.5.3 — compute override BEFORE the spec call so we can suppress
    # M9-C guidance injection on the generator side. Otherwise M9-C tells
    # the LLM "don't propose duplicate module" exactly when the
    # practitioner is asking for an override → contradictory signals →
    # the LLM honors M9-C → empty envelope → "no drafts persisted".
    #
    # C.1.5.4 A-fix-2 — read the pre-injected override flag from the
    # action dict first. The chat handler computes this from the
    # practitioner's actual message (effective_message), so it sees the
    # authoritative override signal regardless of how the first-pass LLM
    # paraphrased the intake. Falls back to LLM-paraphrase detection
    # for back-compat with anything that bypasses the chat handler.
    override = bool(action.get("override"))
    if not override:
        override = _has_dup_override(intake) or _has_dup_override(
            action.get("revise_feedback") or ""
        )
    res = await _aio.to_thread(
        msg.propose_module_from_intake,
        biz["id"], intake, action.get("revise_feedback"),
        override,
    )
    if not res.get("ok"):
        return _fail("propose_module_from_intake", res.get("error", "generation failed"))
    proposals = res.get("proposals") or []

    # ─── C.1.5 Plan A (M9-B) duplicate-archetype filter ────────────────
    # If any module-kind proposal duplicates an existing single-instance
    # archetype for this business AND the practitioner didn't explicitly
    # override, drop the duplicates and ask for an override.
    existing_si = await _aio.to_thread(
        msg._existing_single_instance_modules, biz["id"]
    )
    existing_archs = {(r.get("archetype") or "") for r in existing_si}
    filtered_dup_names: List[str] = []
    if existing_archs and not override:
        survivors: List[Dict[str, Any]] = []
        for p in proposals:
            if (p.get("kind") or "module") != "module":
                survivors.append(p)
                continue
            spec = p.get("spec") or {}
            spec_arch = (spec.get("archetype") or "").strip()
            if spec_arch and spec_arch in existing_archs:
                filtered_dup_names.append(
                    spec.get("name") or spec.get("slug") or spec_arch
                )
                continue
            survivors.append(p)
        proposals = survivors

    n = len(proposals)

    # If everything got filtered by the M9-B guard, surface an
    # override-request result. Kept as result="awaiting override" (not
    # "Failed:") so the second-pass LLM treats this as informational —
    # the proposal flow succeeded; it just hit a product constraint.
    if not proposals and filtered_dup_names:
        plural = "modules" if len(filtered_dup_names) > 1 else "module"
        names_str = " and ".join(repr(n) for n in filtered_dup_names)
        return {
            "type": "propose_module_from_intake",
            "result": "awaiting override",
            "label": (
                f"⚠️ You already have the {plural} you described "
                f"({names_str}). Multiple of those per business aren't "
                f"supported yet — say 'add another one anyway' if you "
                f"truly want a second copy. Otherwise tell me what you "
                f"want to change in the existing one and I'll help."
            ),
            "decomposition_reasoning": (
                f"Generator proposed {filtered_dup_names} but the business "
                f"already has matching active single-instance modules. C.1.5 "
                f"Plan A blocks duplicates without explicit practitioner "
                f"override."
            ),
            "proposals": [],
            "filtered_duplicates": filtered_dup_names,
            "nav": _nav("build"),
        }
    # C.1.2 — proposals are now heterogeneous: each item carries a `kind`
    # discriminator ('module' | 'offering') and a payload key (`spec` or
    # `offering`). The label-builder must read by kind, not assume `.spec`.
    def _name_of(p):
        if (p.get("kind") or "module") == "offering":
            return (p.get("offering") or {}).get("name") or "offering"
        return (p.get("spec") or {}).get("name") or (p.get("spec") or {}).get("slug") or "module"

    if n == 1:
        p0 = proposals[0]
        if (p0.get("kind") or "module") == "offering":
            off = p0.get("offering") or {}
            price = off.get("current_price")
            price_str = f" (${price})" if price is not None else ""
            label = f"📐 Proposed offering: {off.get('name', 'offering')}{price_str}"
        else:
            spec = p0.get("spec") or {}
            wf_count = len(spec.get("workflows") or [])
            wf_note = f", {wf_count} rule{'s' if wf_count != 1 else ''}" if wf_count else ""
            label = (
                f"📐 Proposed: {spec.get('name', spec.get('slug', 'module'))} "
                f"({len((spec.get('schema') or {}).get('fields') or [])} fields"
                f"{wf_note}, {spec.get('confidence', 'medium')} confidence)"
            )
    else:
        n_modules = sum(1 for p in proposals if (p.get("kind") or "module") == "module")
        n_offerings = sum(1 for p in proposals if p.get("kind") == "offering")
        names = ", ".join(_name_of(p) for p in proposals)
        if n_offerings and n_modules:
            label = (
                f"📐 Proposed {n_modules} module{'s' if n_modules != 1 else ''} "
                f"+ {n_offerings} offering{'s' if n_offerings != 1 else ''}: {names}"
            )
        elif n_offerings:
            label = f"📐 Proposed {n_offerings} offering{'s' if n_offerings != 1 else ''}: {names}"
        else:
            label = f"📐 Proposed {n} linked modules: {names}"

    # Mixed M9-B outcome: some proposals survived, some duplicate-archetype
    # ones were filtered. Append a note so the practitioner sees what was
    # skipped + the override phrase if they want it back.
    if filtered_dup_names:
        skipped = " and ".join(repr(n) for n in filtered_dup_names)
        label = (
            f"{label}  (Skipped {skipped} — already on file. "
            f"Say 'add another one anyway' to include.)"
        )

    # ─── C.1.5.1 L1 — M9-C deflection breadcrumb ────────────────────────
    # When the business has single-instance modules, the LLM produced
    # zero module-kind proposals, AND the practitioner didn't override,
    # we infer the LLM was deflected by M9-C's existing-modules guidance
    # (it proposed offerings instead of a duplicate module). Surface the
    # breadcrumb so the practitioner sees the substitution AND the
    # second-pass LLM has signal to write an honest reply (rule #7 in
    # _POST_ACTION_REPLY_SYSTEM reads this label as the substitution
    # signal). Without this, M9-C is silent end-to-end and Chief's
    # first-pass narration ("Drafting a booking system proposal...")
    # contradicts what actually shipped.
    n_modules_in_proposals = sum(
        1 for p in proposals if (p.get("kind") or "module") == "module"
    )
    m9c_deflected: List[str] = []
    if existing_archs and n_modules_in_proposals == 0 and not override and not filtered_dup_names:
        # Offering-only envelope on a business with single-instance
        # modules + no override + nothing already filtered by M9-B →
        # almost certainly an M9-C-driven LLM deflection.
        m9c_deflected = sorted(existing_archs)

    if m9c_deflected:
        arch_phrase = " and ".join(repr(a) for a in m9c_deflected)
        label = (
            f"{label}  (You already have a {arch_phrase} module on this "
            f"business — I added the offering(s) instead. Say "
            f"'add another one anyway' if you want a duplicate module.)"
        )

    # C.1.5.1 adjacent — dynamic result token. The legacy hardcoded
    # "module spec proposed" lied when the envelope was offering-only.
    # Recompute from the actual envelope shape so the action panel +
    # second-pass LLM see honest summary text.
    n_offerings_in = sum(1 for p in proposals if p.get("kind") == "offering")
    if not proposals:
        result_token = "awaiting override"  # already covered above; defensive
    elif n_modules_in_proposals and n_offerings_in:
        result_token = "module + offering(s) proposed"
    elif n_modules_in_proposals:
        result_token = (
            "module spec proposed" if n_modules_in_proposals == 1
            else f"{n_modules_in_proposals} module specs proposed"
        )
    else:
        result_token = (
            "offering proposed" if n_offerings_in == 1
            else f"{n_offerings_in} offerings proposed"
        )

    return {
        "type": "propose_module_from_intake",
        "result": result_token,
        "label": label,
        "decomposition_reasoning": res.get("decomposition_reasoning"),
        "proposals": proposals,            # [{spec_id, kind, spec | offering}, ...]
        "nav": _nav("build"),
    }




async def handle_summarize_module(client, biz, action) -> Dict:
    """Turn a module's rows into an answer. Pure read, no LLM.

    Chief stored data beautifully and summarised none of it. A
    practitioner with Bookings and Payments could not ask "what am I owed,
    by stage" or "how many jobs finished this month" — the data was right
    there and nothing counted it.

    Deliberately ARITHMETIC, not a model call. Counting rows is not a
    judgement, and routing it through an LLM would make a deterministic
    fact cost money and vary between asks.

    action: {module, group_by?: <select field>, sum?: <currency/number
             field>, since?: YYYY-MM-DD, until?: YYYY-MM-DD}
    """
    import re as _re
    from collections import OrderedDict

    ref = (action.get("module") or action.get("module_id")
           or action.get("slug") or "").strip()
    if not ref:
        return _fail("summarize_module", "which module? pass module=<slug>")

    is_uuid = bool(_re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", ref))
    q = f"/custom_modules?business_id=eq.{biz['id']}&select=*&limit=1"
    q += f"&id=eq.{ref}" if is_uuid else f"&slug=eq.{ref}"
    mods = await _sb(client, "GET", q) or []
    if not mods:
        return _fail("summarize_module", f"no module called '{ref}'")
    module = mods[0]
    fields = {f.get("name"): f for f in (module.get("schema") or {}).get("fields") or []
              if isinstance(f, dict)}

    group_by = (action.get("group_by") or "").strip() or None
    sum_field = (action.get("sum") or "").strip() or None
    for label, fname, wanted in (("group_by", group_by, ("select",)),
                                 ("sum", sum_field, ("currency", "number"))):
        if fname and fname not in fields:
            return _fail("summarize_module",
                         f"'{fname}' is not a field on {module.get('name')}")
        if fname and fields[fname].get("type") not in wanted:
            return _fail("summarize_module",
                         f"{label} needs a {' or '.join(wanted)} field; "
                         f"'{fname}' is {fields[fname].get('type')}")

    # Default: group by the first select field, sum the first currency one.
    # A summary nobody had to configure is the one a practitioner asks for.
    if not group_by:
        group_by = next((n for n, f in fields.items() if f.get("type") == "select"), None)
    if not sum_field:
        sum_field = next((n for n, f in fields.items() if f.get("type") == "currency"), None)

    rows = await _sb(client, "GET",
                     f"/module_entries?module_id=eq.{module['id']}"
                     f"&select=data,created_at&limit=2000") or []

    since, until = action.get("since"), action.get("until")
    if since or until:
        kept = []
        for r in rows:
            stamp = str(r.get("created_at") or "")[:10]
            if since and stamp < str(since)[:10]:
                continue
            if until and stamp > str(until)[:10]:
                continue
            kept.append(r)
        rows = kept

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    buckets: "OrderedDict[str, Dict[str, float]]" = OrderedDict()
    total_sum = 0.0
    # Bucket order follows the select's declared options, so a summary
    # reads in workflow order rather than alphabetically or by luck.
    if group_by:
        for opt in (fields[group_by].get("options") or []):
            buckets[str(opt)] = {"count": 0, "sum": 0.0}
    for r in rows:
        d = r.get("data") or {}
        key = str(d.get(group_by) or "(not set)") if group_by else "all"
        b = buckets.setdefault(key, {"count": 0, "sum": 0.0})
        b["count"] += 1
        if sum_field:
            v = _num(d.get(sum_field))
            b["sum"] += v
            total_sum += v

    shown = [(k, v) for k, v in buckets.items() if v["count"]]
    name = module.get("name") or module.get("slug")
    if not rows:
        return {"type": "summarize_module",
                "result": f"{name} has no rows yet, so there is nothing to total.",
                "label": f"{name}: empty", "nav": None,
                "summary": {"total_rows": 0, "buckets": []}}

    def _money(x):
        return f"${x:,.2f}"

    parts = []
    for k, v in shown:
        seg = f"{k}: {v['count']}"
        if sum_field:
            seg += f" ({_money(v['sum'])})"
        parts.append(seg)

    headline = f"{len(rows)} {'row' if len(rows) == 1 else 'rows'}"
    if sum_field:
        headline += f", {_money(total_sum)} total"
    if group_by:
        headline += f" — by {fields[group_by].get('label') or group_by}"

    return {
        "type": "summarize_module",
        "result": headline + (": " + "; ".join(parts) if parts else ""),
        "label": f"📊 {name} — {headline}",
        "nav": None,
        "summary": {
            "module": name,
            "total_rows": len(rows),
            "group_by": group_by,
            "sum_field": sum_field,
            "total": round(total_sum, 2) if sum_field else None,
            "buckets": [{"key": k, "count": v["count"],
                         "sum": round(v["sum"], 2) if sum_field else None}
                        for k, v in shown],
        },
    }


async def handle_add_module_field(client, biz, action) -> Dict:
    """Add a field to a module that already exists. ADDITIVE ONLY.

    Chief could build a module and then never touch it again — the verbs
    were create / accept / reject / upgrade-archetype / inspect and row
    CRUD, with nothing that edits a schema. So "add a phone number to my
    bookings" had no answer from the one surface whose whole promise is
    that you can just ask.

    WHY ADDITIVE ONLY. Removing or retyping a field does not delete the
    data — module_entries.data is jsonb and keeps every key — it makes it
    INVISIBLE, silently, with no way for the practitioner to know a value
    is still in there. Adding is reversible by removing; removing is not
    reversible by adding, because nobody can see what was lost. Renames
    and deletions stay in the manual editor where the whole schema is on
    screen at once.

    action: {module: slug|uuid, name, type, label, required?, options?,
             module_slug?, placeholder?}
    """
    import module_inspect
    import module_vocabulary

    ref = (action.get("module") or action.get("module_id")
           or action.get("slug") or "").strip()
    if not ref:
        return _fail("add_module_field", "which module? pass module=<slug>")

    fname = (action.get("name") or "").strip()
    ftype = (action.get("type") or "").strip()
    if not fname:
        return _fail("add_module_field", "the new field needs a name")
    if ftype not in module_vocabulary.FIELD_TYPES:
        return _fail("add_module_field",
                     f"'{ftype}' is not a field type — one of: "
                     + ", ".join(module_vocabulary.FIELD_TYPES))

    # A uuid is 36 chars with 4 hyphens; slugs are kebab-case and never
    # that shape, so this cannot mistake one for the other.
    import re as _re
    is_uuid = bool(_re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", ref))
    q = f"/custom_modules?business_id=eq.{biz['id']}&select=*&limit=1"
    q += f"&id=eq.{ref}" if is_uuid else f"&slug=eq.{ref}"
    rows = await _sb(client, "GET", q) or []
    if not rows:
        return _fail("add_module_field", f"no module called '{ref}'")
    module = rows[0]

    schema = dict(module.get("schema") or {})
    fields = list(schema.get("fields") or [])
    if any((f.get("name") or "") == fname for f in fields if isinstance(f, dict)):
        return _fail("add_module_field",
                     f"'{fname}' is already a field on {module.get('name')}")

    new_field: Dict[str, Any] = {
        "name": fname,
        "type": ftype,
        "label": (action.get("label") or fname.replace("_", " ").title()),
    }
    for k in ("required", "options", "module_slug", "placeholder",
              "offering_categories"):
        if action.get(k) is not None:
            new_field[k] = action[k]

    candidate = {**schema, "fields": fields + [new_field]}

    # CHECK BEFORE WRITING. The renderer replaces the entire module with an
    # error panel on any schema fault, so a bad field would not damage one
    # row — it would take the whole module and every entry in it off the
    # screen. Inspect the candidate first and refuse rather than repair:
    # the practitioner asked for a specific field, and quietly writing a
    # different one is worse than saying no.
    report = module_inspect.inspect_module_schema(
        candidate, module.get("agent_config"), module.get("archetype"))
    if not report["renderable"]:
        return _fail("add_module_field",
                     "that field would stop the module displaying: "
                     + "; ".join(report["problems"][:2]))

    patched = await _sb(client, "PATCH",
                        f"/custom_modules?id=eq.{module['id']}", {"schema": candidate})
    if not patched:
        return _fail("add_module_field", "the change was rejected — nothing was saved")

    # Read back. A 200 is not evidence the column holds what we sent.
    after = await _sb(client, "GET",
                      f"/custom_modules?id=eq.{module['id']}&select=schema&limit=1") or []
    landed = [f.get("name") for f in
              ((after[0].get("schema") or {}).get("fields") or [])] if after else []
    if fname not in landed:
        return _fail("add_module_field",
                     "the save reported success but the field is not there")

    label = f"✅ {new_field['label']} added to {module.get('name') or module.get('slug')}"
    result = f"added a {ftype} field"
    if report["warnings"]:
        result += " — " + "; ".join(report["warnings"][:2])
    return {"type": "add_module_field", "result": result, "label": label,
            "module_id": module["id"], "nav": _nav("build")}


async def handle_inspect_module(client, biz, action):
    """Look at a module that already exists and say whether it actually
    works. Pure read.

    Chief could build a module and never see it again. This is the verb
    that closes that loop: it checks a live custom_modules row against the
    renderer's own contract (module_inspect), so "is it working?" has an
    answer that doesn't require the practitioner to click into Build and
    find a red panel.

    action: {module_id: str} or {slug: str} or {} for every module.
    """
    import module_inspect

    module_id = (action.get("module_id") or "").strip()
    slug = (action.get("slug") or action.get("module") or "").strip()

    q = f"/custom_modules?business_id=eq.{biz['id']}&select=*"
    if module_id:
        q += f"&id=eq.{module_id}"
    elif slug:
        q += f"&slug=eq.{slug}"
    q += "&order=sort_order.asc,created_at.asc"

    rows = await _sb(client, "GET", q) or []
    if not rows:
        which = module_id or slug or "any module"
        return _fail("inspect_module", f"no module found for {which}")

    reports = []
    broken = 0
    for row in rows:
        rep = module_inspect.inspect_module_row(row)
        if not rep["renderable"]:
            broken += 1
        reports.append({
            "module_id": row.get("id"),
            "name": row.get("name") or row.get("slug"),
            "renderable": rep["renderable"],
            "summary": rep["summary"],
            "problems": rep["problems"],
            "warnings": rep["warnings"],
        })

    if len(reports) == 1:
        r = reports[0]
        detail = r["summary"]
        if r["problems"]:
            detail += " — " + "; ".join(r["problems"][:3])
        elif r["warnings"]:
            detail += " — " + "; ".join(r["warnings"][:2])
        label = ("✅ " if r["renderable"] else "⚠️ ") + f"{r['name']}: {r['summary']}"
        return {"type": "inspect_module", "result": detail, "label": label,
                "reports": reports, "nav": None}

    label = (f"⚠️ {broken} of {len(reports)} modules won't display"
             if broken else f"✅ all {len(reports)} modules render")
    return {
        "type": "inspect_module",
        "result": "; ".join(f"{r['name']}: {r['summary']}" for r in reports),
        "label": label,
        "reports": reports,
        "nav": None,
    }


async def handle_accept_module_spec(client, biz, action):
    """Materialize a draft ModuleSpec into a custom_modules row. Idempotent.
    action: {spec_id: str}"""
    spec_id = action.get("spec_id")
    if not spec_id:
        return _fail("accept_module_spec", "spec_id required")
    try:
        import asyncio as _aio
        import module_spec_generator as msg
    except Exception as e:
        return _fail("accept_module_spec", f"generator unavailable: {e}")

    # Scope guard on the OTHER create path. ensure_module is the hand-typed
    # route; this is the one where an LLM-authored spec gets materialized,
    # and it is the likelier of the two to drift into clinical territory
    # because nobody typed the name.
    try:
        import vertical_scope
        rows = await _aio.to_thread(
            sb_clients.sb_get_as_service,
            f"/module_specs?id=eq.{spec_id}&business_id=eq.{biz['id']}"
            "&select=draft_json&limit=1") or []
        draft = (rows[0].get("draft_json") or {}) if rows else {}
        fields = draft.get("fields") or []
        labels = " ".join(
            str(f.get("label") or f.get("name") or "")
            for f in fields if isinstance(f, dict))
        ok, refusal = vertical_scope.check_module_scope(
            biz.get("type"), draft.get("name"), draft.get("slug"),
            draft.get("description"), labels)
        if not ok:
            return {"type": "accept_module_spec",
                    "result": f"refused: {refusal}",
                    "label": "Out of scope", "nav": None}
    except Exception as e:
        # Fail CLOSED. Same scope-of-practice boundary as ensure_module —
        # a guard that can't run must refuse, not allow.
        logger.warning(f"[scope] accept_module_spec guard error (refusing): {e}")
        return {"type": "accept_module_spec",
                "result": ("Failed: a safety check couldn't run just now, so I "
                           "didn't accept the module. Try again in a moment."),
                "label": "Module acceptance held", "nav": None, "failed": True}

    res = await _aio.to_thread(msg.materialize_spec, spec_id)
    if not res.get("ok"):
        return _fail("accept_module_spec", res.get("error", "materialize failed"))
    mod = res.get("module") or {}
    name = mod.get("name") or mod.get("slug") or "module"

    # What did we actually build? materialize_spec now reads the row back
    # and checks it against the renderer's contract. "Is live in Build" was
    # previously said on the strength of an insert returning — including for
    # modules that were about to show the practitioner a red error panel.
    verification = res.get("verification") or {}
    problems = verification.get("problems") or []
    warnings = verification.get("warnings") or []
    repairs = verification.get("repairs") or []

    if problems:
        return {
            "type": "accept_module_spec",
            "result": ("saved, but it will not display correctly: "
                       + "; ".join(problems[:3])),
            "label": f"⚠️ {name} saved — but it won't display yet",
            "module_id": mod.get("id"),
            "nav": _nav("build"),
        }

    label = f"✅ {name} is live in Build"
    if repairs:
        label += f" — {repairs[0]}"
    result = "module accepted"
    if warnings:
        result = "module accepted — " + "; ".join(warnings[:2])

    return {
        "type": "accept_module_spec",
        "result": result,
        "label": label,
        "module_id": mod.get("id"),
        "nav": _nav("build"),
    }


async def handle_reject_module_spec(client, biz, action):
    """Reject a draft. action: {spec_id, reason?}"""
    spec_id = action.get("spec_id")
    if not spec_id:
        return _fail("reject_module_spec", "spec_id required")
    try:
        import asyncio as _aio
        import module_spec_generator as msg
    except Exception as e:
        return _fail("reject_module_spec", f"generator unavailable: {e}")
    await _aio.to_thread(msg.reject_spec, spec_id, action.get("reason"))
    return {"type": "reject_module_spec", "result": "spec rejected",
            "label": "🗑️ Spec rejected"}


async def handle_upgrade_module_archetype(client, biz, action):
    """Refine an existing materialized module against the CURRENT archetype
    palette: a fallback_generic module whose shape now has an archetype
    (progress_tracker, work_pipeline, …) comes back on it with its rows
    intact; a booking_calendar gets customer_facing flags + the canonical
    service catalog (the original C.1.1 purpose). There is deliberately no
    archetype guard here — the generator decides, the practitioner accepts.
    Returns the same envelope shape as propose_module_from_intake so the
    dock renders it through the existing ModuleSpecProposalCard, but with
    is_upgrade=true so the card UI can show "Upgrade [Bookings]" instead
    of "Bookings" as a fresh proposal.

    On accept, materialize_spec UPDATEs the existing custom_modules row
    in place (preserving module_id + existing module_entries) because
    the draft carries upgrade_target_module_id.

    action: {module_id: str | None, module_slug: str | None, module_name: str | None}
    Caller can identify the target module by id, slug, or name (the LLM
    typically gets a name from the practitioner; we resolve to id).
    """
    target_id = action.get("module_id")
    slug = action.get("module_slug")
    name = action.get("module_name")

    if not target_id:
        # Resolve from slug or name (case-insensitive) within this business.
        biz_id = biz["id"]
        if slug:
            rows = await _sb(
                client, "GET",
                f"/custom_modules?business_id=eq.{biz_id}&slug=eq.{slug}"
                f"&is_active=eq.true&select=id&limit=1",
            ) or []
            if rows:
                target_id = rows[0]["id"]
        if not target_id and name:
            import urllib.parse as _up
            safe = _up.quote(name, safe="")
            rows = await _sb(
                client, "GET",
                f"/custom_modules?business_id=eq.{biz_id}&name=ilike.*{safe}*"
                f"&is_active=eq.true&select=id,name&limit=5",
            ) or []
            if len(rows) == 1:
                target_id = rows[0]["id"]
            elif len(rows) > 1:
                opts = ", ".join(r["name"] for r in rows)
                return _fail(
                    "upgrade_module_archetype",
                    f"multiple modules match '{name}': {opts} — be specific",
                )

    if not target_id:
        return _fail(
            "upgrade_module_archetype",
            "module_id, module_slug, or module_name required",
        )

    try:
        import asyncio as _aio
        import module_spec_generator as msg
    except Exception as e:
        return _fail("upgrade_module_archetype", f"generator unavailable: {e}")

    res = await _aio.to_thread(msg.regenerate_for_upgrade, biz["id"], target_id)
    if not res.get("ok"):
        return _fail("upgrade_module_archetype", res.get("error", "upgrade failed"))

    proposals = res.get("proposals") or []
    if not proposals:
        return _fail("upgrade_module_archetype", "no upgrade proposal returned")

    # C.1.2 — the upgrade flow emits Offerings BEFORE the module spec in
    # the proposals list (so the practitioner sees the offerings the
    # refined module is about to reference). Find the module spec by kind
    # rather than blindly indexing [0].
    module_proposal = next(
        (p for p in proposals if (p.get("kind") or "module") == "module"),
        None,
    )
    if not module_proposal:
        return _fail("upgrade_module_archetype", "upgrade envelope missing module spec")
    spec = module_proposal.get("spec") or {}
    n_offerings = sum(1 for p in proposals if p.get("kind") == "offering")
    offering_note = (
        f" + {n_offerings} offering{'s' if n_offerings != 1 else ''}"
        if n_offerings else ""
    )
    label = (
        f"🔧 Upgrade proposed: {spec.get('name', spec.get('slug', 'module'))} "
        f"({len((spec.get('schema') or {}).get('fields') or [])} fields, "
        f"{spec.get('confidence', 'medium')} confidence{offering_note})"
    )
    return {
        "type": "propose_module_from_intake",  # Reuse the dock's existing card
        "result": "upgrade proposed",
        "label": label,
        "decomposition_reasoning": res.get("decomposition_reasoning"),
        "proposals": proposals,
        "is_upgrade": True,                    # frontend shows "Upgrade" UI hint
        "upgrade_target_module_id": target_id,
        "nav": _nav("build"),
    }
