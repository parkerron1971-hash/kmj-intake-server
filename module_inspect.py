"""
module_inspect.py — does the module we just built actually work?

WHY THIS EXISTS
───────────────
`materialize_spec` wrote a custom_modules row and Chief said

    "✅ Bookings is live in Build"

on the strength of the insert coming back. Nobody looked at what landed.
Three distinct ways that sentence could be false:

  1. The renderer refuses it. DynamicModule runs validateModuleSchema and,
     on ANY error, replaces the entire module with a red "This module's
     schema is invalid" panel. A spec with views:['board'] and no valid
     board_column materializes perfectly and renders as that panel. Chief
     reports success; the practitioner clicks through to an error.

  2. The write didn't land. sb_patch_as_service returns None on a 4xx.
     The upgrade path discarded that return value entirely, so a rejected
     PATCH still produced ok:True with the target's own id — success
     reported over a lost write.

  3. The row vanished. The final read-back allowed `module: None` and
     still returned ok:True.

So this module is the eyes. `inspect_module_schema` is a PORT OF THE
RENDERER'S OWN CONTRACT — the checks in
src/core/hooks/useCustomModules.ts::validateModuleSchema, in the same
order, with the same accept/reject set. It answers one question the
backend could not previously answer: **would the frontend draw this?**

DISCIPLINE
──────────
  - Anything that makes DynamicModule show the error panel is a PROBLEM
    (renderable = False). Anything that renders but won't behave as the
    practitioner expects is a WARNING. Do not blur them: a warning that
    blocks a build is as wrong as a problem that ships.
  - This is a MIRROR of a frontend contract. When validateModuleSchema
    changes, this changes with it — test_module_inspect.py pins the
    accept/reject set so the mirror can't drift silently.
  - Vocabulary comes from module_vocabulary; never re-type the type list
    (see the offering_ref incident in that module's docstring).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import module_vocabulary

# Field types whose value is DERIVED rather than typed, and so are allowed
# to be absent from a customer-facing form without that being a problem.
_SYSTEM_SET_OK = {"system_set", "customer_facing"}


class InspectionReport(dict):
    """Plain dict (JSON-serializable straight into a Chief action result)
    with two conveniences. Keys: renderable, problems, warnings, summary."""

    @property
    def renderable(self) -> bool:
        return bool(self.get("renderable"))

    @property
    def problems(self) -> List[str]:
        return list(self.get("problems") or [])


def inspect_module_schema(schema: Any,
                          agent_config: Optional[Dict[str, Any]] = None) -> InspectionReport:
    """Port of validateModuleSchema (frontend) + the trigger checks the
    frontend has no way to make.

    PROBLEMS are exactly the frontend's error set — each one means the
    practitioner sees the red panel instead of their module.
    """
    problems: List[str] = []
    warnings: List[str] = []

    if not isinstance(schema, dict):
        problems.append("schema must be an object")
        return _report(problems, warnings)

    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        problems.append("schema.fields must be a non-empty array")
        fields = []
    else:
        seen: set = set()
        for i, f in enumerate(fields):
            if not isinstance(f, dict):
                problems.append(f"field[{i}] must be an object")
                continue
            name = f.get("name")
            if not name or not isinstance(name, str):
                problems.append(f"field[{i}].name missing")
            if name in seen:
                problems.append(f'field "{name}" is duplicated')
            seen.add(name)
            if not f.get("label"):
                problems.append(f'field "{name}".label missing')

            ftype = f.get("type")
            if ftype not in module_vocabulary.FIELD_TYPES:
                problems.append(f'field "{name}".type invalid: {ftype}')
            elif ftype == "select" and not (isinstance(f.get("options"), list) and f.get("options")):
                problems.append(f'field "{name}" is select but has no options')
            elif ftype == "file" and f.get("customer_facing"):
                # A PROBLEM, not a warning. The customer widget is
                # anonymous and storage writes need a JWT, so this field
                # cannot function on a customer form — and the only way
                # to make it work would reopen anonymous writes to the
                # bucket, which is the hole the storage lockdown closed.
                problems.append(
                    f'field "{name}" is a file marked customer_facing — '
                    f"uploads need a signed-in user, so it cannot work on "
                    f"a customer form"
                )
            elif ftype == "module_ref" and not str(f.get("module_slug") or "").strip():
                # A PROBLEM, not a warning — unlike offering_ref below.
                # module_ref is new, so no live row can already be missing
                # its constraint; enforcing from day one costs nothing and
                # a module_ref without a target renders a dropdown that can
                # never be populated. The offering_ref leniency exists only
                # because rows predate the rule.
                problems.append(
                    f'field "{name}" is module_ref with no module_slug — '
                    f"nothing tells it which module's rows to offer"
                )
            elif ftype == "offering_ref" and not (
                isinstance(f.get("offering_categories"), list) and f.get("offering_categories")
            ):
                # NOT a problem: the frontend validator deliberately does not
                # enforce this yet (tightening a hard render gate can black
                # out a module that renders fine today). It is still wrong —
                # the widget has no categories to source its dropdown from —
                # so it surfaces here, where nothing breaks.
                warnings.append(
                    f'field "{name}" is offering_ref with no offering_categories — '
                    f"its dropdown has nothing to list"
                )

    views = schema.get("views")
    if not isinstance(views, list) or not views:
        problems.append("schema.views must be a non-empty array")
        views = []
    else:
        unknown = [v for v in views if v not in module_vocabulary.VIEW_KINDS]
        if unknown:
            problems.append(f"schema.views has unknown view(s): {', '.join(map(str, unknown))}")

    if "board" in views:
        board_column = schema.get("board_column")
        if not board_column:
            problems.append("board view requires board_column")
        else:
            col = next((f for f in fields
                        if isinstance(f, dict) and f.get("name") == board_column), None)
            if not col:
                problems.append(f'board_column "{board_column}" not found in fields')
            elif col.get("type") != "select":
                problems.append(f'board_column "{board_column}" must be a select field')

    if "calendar" in views:
        cal = schema.get("calendar_field")
        if not cal:
            problems.append("calendar view requires calendar_field")
        else:
            col = next((f for f in fields
                        if isinstance(f, dict) and f.get("name") == cal), None)
            if not col:
                problems.append(f'calendar_field "{cal}" not found in fields')
            elif col.get("type") != "date":
                problems.append(f'calendar_field "{cal}" must be a date field')

    default_view = schema.get("default_view")
    if default_view and views and default_view not in views:
        # Renders (DynamicModule falls back to its own state default), but the
        # practitioner asked for a view the module does not offer.
        warnings.append(
            f'default_view "{default_view}" is not in views — the module opens on '
            f"{views[0]} instead"
        )

    warnings.extend(_inspect_triggers(agent_config, fields))
    return _report(problems, warnings)


def _inspect_triggers(agent_config: Optional[Dict[str, Any]],
                      fields: List[Any]) -> List[str]:
    """Triggers never make the renderer refuse — they make the module
    LOOK fine and quietly do nothing, which is the harder failure to
    notice. All warnings, never problems."""
    out: List[str] = []
    if not isinstance(agent_config, dict):
        return out

    # NOT an early return when triggers is absent — closed_statuses below
    # is checked independently, and returning here made that check
    # unreachable for every module without triggers (which is most of them).
    triggers = agent_config.get("triggers")
    triggers = triggers if isinstance(triggers, list) else []

    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    date_fields = {f.get("name") for f in fields
                   if isinstance(f, dict) and f.get("type") == "date"}

    for i, t in enumerate(triggers):
        if not isinstance(t, dict):
            out.append(f"agent_config.triggers[{i}] is not an object — it will never fire")
            continue
        ttype = t.get("type")
        if ttype not in module_vocabulary.TRIGGER_KINDS:
            out.append(f'trigger[{i}] type "{ttype}" is not a known trigger — it will never fire')
            continue
        if ttype == "overdue":
            fname = t.get("field")
            if not fname:
                out.append('an "overdue" trigger has no field — it will never fire')
            elif fname not in field_names:
                out.append(f'"overdue" trigger points at "{fname}", which is not a field')
            elif fname not in date_fields:
                out.append(f'"overdue" trigger points at "{fname}", which is not a date field')
        elif ttype == "field_change":
            fname = t.get("field")
            if not fname:
                out.append('a "field_change" trigger has no field — it will never fire')
            elif fname not in field_names:
                out.append(f'"field_change" trigger points at "{fname}", which is not a field')

    closed = agent_config.get("closed_statuses")
    if isinstance(closed, list) and closed:
        options: set = set()
        for f in fields:
            if isinstance(f, dict) and f.get("type") == "select" and isinstance(f.get("options"), list):
                options.update(f["options"])
        stray = [c for c in closed if c not in options]
        if stray and options:
            out.append(
                f"closed_statuses {stray} match no option on any choice field — "
                f'"overdue" will keep firing on finished work'
            )
    return out


def _report(problems: List[str], warnings: List[str]) -> InspectionReport:
    renderable = not problems
    if renderable and not warnings:
        summary = "renders and behaves as specified"
    elif renderable:
        summary = f"renders, with {len(warnings)} thing(s) worth a look"
    else:
        summary = f"WILL NOT RENDER — {len(problems)} blocking problem(s)"
    return InspectionReport(
        renderable=renderable,
        problems=problems,
        warnings=warnings,
        summary=summary,
    )


def inspect_module_row(module: Optional[Dict[str, Any]]) -> InspectionReport:
    """Inspect a custom_modules row as READ BACK from the database — not
    the payload we meant to write. The difference is the whole point: a
    row that never landed, or landed with a column dropped, reports here
    instead of in a support ticket."""
    if not module:
        return _report(["the module row could not be read back after writing"], [])

    schema = module.get("schema")
    agent_config = module.get("agent_config")
    report = inspect_module_schema(schema, agent_config)

    problems = report.problems
    if not module.get("name") and not module.get("slug"):
        problems.append("the module has neither a name nor a slug")
    if module.get("is_active") is False:
        report["warnings"].append("the module is inactive — it will not appear in the sidebar")

    if problems != report.problems:
        return _report(problems, report["warnings"])
    return report


# ─── Repair ───────────────────────────────────────────────────────────

def repair_schema(schema: Any) -> tuple[Any, List[str]]:
    """Fix ONLY the unambiguous, structure-preserving faults, and say what
    was changed. Returns (schema, notes).

    Deliberately narrow. A repair that guesses at intent produces a module
    the practitioner did not ask for, which is worse than an honest error
    — so anything requiring a judgement call is left for a human and
    reported as a problem instead.
    """
    notes: List[str] = []
    if not isinstance(schema, dict):
        return schema, notes

    schema = dict(schema)
    fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []
    views = schema.get("views") if isinstance(schema.get("views"), list) else []

    # A board view with no usable column. The board cannot be drawn, and
    # the whole module refuses to render because of it. Dropping the board
    # keeps the list view the practitioner also asked for; inventing a
    # column would invent a workflow.
    if "board" in views:
        board_column = schema.get("board_column")
        col = next((f for f in fields
                    if isinstance(f, dict) and f.get("name") == board_column), None)
        if not board_column or not col or col.get("type") != "select":
            remaining = [v for v in views if v != "board"]
            if remaining:
                schema["views"] = remaining
                schema.pop("board_column", None)
                if schema.get("default_view") == "board":
                    schema["default_view"] = remaining[0]
                notes.append(
                    "removed the board view: it needs a choice field to group by, "
                    "and this module has none"
                )

    # A calendar with no usable date field, same treatment as the board:
    # the calendar cannot be drawn and its presence takes the whole module
    # down, while the list the practitioner also asked for is fine. Never
    # invent a date field — a calendar laid out on a guess is worse than
    # no calendar.
    views = schema.get("views") if isinstance(schema.get("views"), list) else []
    if "calendar" in views:
        cal = schema.get("calendar_field")
        col = next((f for f in fields
                    if isinstance(f, dict) and f.get("name") == cal), None)
        if not cal or not col or col.get("type") != "date":
            remaining = [v for v in views if v != "calendar"]
            if remaining:
                schema["views"] = remaining
                schema.pop("calendar_field", None)
                if schema.get("default_view") == "calendar":
                    schema["default_view"] = remaining[0]
                notes.append(
                    "removed the calendar view: it needs a date field to lay "
                    "entries on, and this module has none")

    # default_view naming a view the module doesn't offer.
    views = schema.get("views") if isinstance(schema.get("views"), list) else []
    if views and schema.get("default_view") and schema["default_view"] not in views:
        notes.append(
            f'default_view "{schema["default_view"]}" is not one of this module\'s '
            f'views — opening on "{views[0]}" instead'
        )
        schema["default_view"] = views[0]

    return schema, notes
