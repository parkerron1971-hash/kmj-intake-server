"""
workspace_primitives.py — the primitive registry for the workspace composer.

ONE module. Nothing else declares a primitive. If a layout schema names a
primitive that isn't in `PRIMITIVES`, the validator rejects the schema —
that is check 1, and it only works because there is exactly one place to
look.

Six primitives ship in phase one and no more (docs/WORKSPACE_COMPOSER_SPEC.md
section 1). Each declares:

  bindings      named data contracts. A binding is a collection or a scalar;
                collections declare `fields` (contract field name -> type)
                and may bound their item count.
  options       render options with declared types and ranges. The validator
                enforces the range; the renderer reads the default.
  allowed_roles which surface roles the primitive may occupy. This is where
                "metric_row is footer material, never the hero" stops being
                a convention and becomes an invariant — `lead` is simply not
                in its list, so a layout that leads with it cannot validate.

No primitive fetches its own data. The renderer resolves every binding and
hands down plain values; that is why these declarations describe SHAPE and
never a query.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Surface roles, most prominent first. A layout has exactly one `lead`.
ROLES = ("lead", "secondary", "footer")

# Contract field types the validator understands.
FIELD_TYPES = ("string", "int", "number", "bool", "date", "time")


def _collection(
    fields: Dict[str, str],
    *,
    required: bool = True,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """A repeating binding. `fields` maps contract field name -> type;
    a trailing '?' on the type marks the field optional."""
    parsed: Dict[str, Dict[str, Any]] = {}
    for name, spec in fields.items():
        optional = spec.endswith("?")
        ftype = spec[:-1] if optional else spec
        if ftype not in FIELD_TYPES:
            raise ValueError(f"unknown field type {ftype!r} on {name!r}")
        parsed[name] = {"type": ftype, "required": not optional}
    return {
        "shape": "collection",
        "required": required,
        "fields": parsed,
        "min_items": min_items,
        "max_items": max_items,
    }


def _scalar(fields: Dict[str, str], *, required: bool = False) -> Dict[str, Any]:
    """A single-value binding (one date, one opening balance)."""
    coll = _collection(fields, required=required)
    coll["shape"] = "scalar"
    return coll


def _enum(values: List[str], default: str) -> Dict[str, Any]:
    return {"type": "enum", "values": tuple(values), "default": default}


def _int(lo: int, hi: int, default: int) -> Dict[str, Any]:
    return {"type": "int", "min": lo, "max": hi, "default": default}


def _bool(default: bool) -> Dict[str, Any]:
    return {"type": "bool", "default": default}


def _string(default: str) -> Dict[str, Any]:
    return {"type": "string", "default": default}


def _string_list(default: List[str], *, max_items: int) -> Dict[str, Any]:
    return {"type": "string_list", "default": tuple(default), "max_items": max_items}


PRIMITIVES: Dict[str, Dict[str, Any]] = {

    # ── the day is the product ───────────────────────────────────────
    "timeline_day": {
        "id": "timeline_day",
        "label": "Timeline — one day",
        "purpose": (
            "One day across parallel resource lanes. Events sit where their "
            "start time puts them and are as tall as they are long. Open gaps "
            "are called out, because an empty chair is the thing you can still "
            "do something about."
        ),
        "allowed_roles": ("lead", "secondary"),
        "bindings": {
            # OPTIONAL, and that is a finding rather than a convenience.
            # A salon has no named staff anywhere in this system — no
            # per-person calendar, no assignment, and `concurrent_capacity`
            # on /availability is a COUNT of chairs, not people. A board
            # that draws stylist lanes therefore promises a screen nobody
            # built, and an owner goes hunting for it and concludes the
            # thing is broken rather than empty.
            #
            # Unbound, the primitive draws ONE track: the day, undivided.
            # A trades crew board still binds lanes, because contractors
            # are real rows.
            "lanes": _collection({
                "id": "string",
                "label": "string",
                "subtitle": "string?",
            }, required=False),
            "events": _collection({
                "id": "string",
                # Optional with `lanes`: an unlaned day has nothing to key
                # an event to, and requiring it would force a preset to
                # invent an assignment the business does not record.
                "lane_id": "string?",
                "start": "time",
                "duration_minutes": "int",
                "title": "string",
                "subtitle": "string?",
                "state": "string?",
            }),
            "day": _scalar({"date": "date"}, required=False),
        },
        "options": {
            "day_start": _int(0, 23, 8),
            "day_end": _int(1, 24, 20),
            "gap_threshold_minutes": _int(5, 240, 30),
            "show_gaps": _bool(True),
            "lane_noun": _string("Resource"),
            # A salon board is read mid-shift — where the day has got to
            # is half the information. A board consulted the night before
            # does not want a line through it.
            "show_now": _bool(False),
            # The same empty block means two different things. On a salon
            # floor it is bookable minutes; on a dispatch board it is
            # almost always drive time, which is a cost rather than an
            # opportunity. One option, two readings.
            "gap_tone": _enum(["open", "travel"], "open"),
        },
    },

    # ── ordered by how many days are left, not by what time it is ────
    "priority_docket": {
        "id": "priority_docket",
        "label": "Priority docket",
        "purpose": (
            "Rows ordered by urgency measured in days, not by the clock. "
            "Hairline rules, the metric right-aligned so the eye can run down "
            "the column and stop at the number that is too small."
        ),
        "allowed_roles": ("lead", "secondary"),
        "bindings": {
            "rows": _collection({
                "id": "string",
                "title": "string",
                "metric_value": "number",
                "metric_unit": "string?",
                "subtitle": "string?",
                "stage": "string?",
                "owner": "string?",
            }),
        },
        "options": {
            "sort": _enum(["urgency_days", "stage"], "urgency_days"),
            "metric_label": _string("Due in"),
            # The unit is a property of the docket, not of each row — every
            # row on one docket is measured the same way. Rows may still
            # override via the optional `metric_unit` field.
            "metric_unit": _string("days"),
            "stages": _string_list([], max_items=8),
            "urgent_threshold_days": _int(0, 90, 7),
            # Three ways to lay grouped rows out, and the choice says
            # something about what the groups ARE.
            #   stacked  a list, read top-down
            #   columns  a FLOW — work moves left to right through the
            #            stages, and a stage that has stopped moving is
            #            only visible as a column with things parked in it
            #   grid     PEERS — a set of relationships each holding a few
            #            items. Funders are not a sequence and nothing
            #            moves from one to the next, so laying them out as
            #            columns would assert a progression that does not
            #            exist.
            "stage_layout": _enum(["stacked", "columns", "grid"], "stacked"),
            # A docket ordered by days remaining can be cut into deadline
            # horizons, which answers "how long have I got" before a
            # single number is read. Thresholds are derived from
            # `urgent_threshold_days` rather than declared separately, so
            # the two can never disagree about what urgent means.
            "banding": _enum(["none", "horizon"], "none"),
            # A docket is a list that has been called over, in order. The
            # numbering is not decoration; it is how the thing is spoken
            # about ("item four").
            "numbered": _bool(False),
        },
        # `stages` is meaningless unless the docket sorts by stage, and a
        # stage sort with no stages declared has nothing to sort into.
        # `stage_layout` is deliberately NOT guarded here: the guard fires
        # both ways, so requiring it under a stage sort would reject the
        # nonprofit preset for wanting the default. Set to "columns"
        # without a stage sort it is simply inert.
        "option_requires": {"stages": {"sort": "stage"}},
        # Sorting by stage with no stage bound produces one undifferentiated
        # pile. Check 2 enforces this against the binding, because it is a
        # contract question, not an option question.
        "field_required_when": {
            "rows": {"stage": {"option": "sort", "equals": "stage"}},
        },
    },

    # ── seven columns, events where they fall ────────────────────────
    "week_grid": {
        "id": "week_grid",
        "label": "Week grid",
        "purpose": (
            "Seven day columns. Gatherings land in the column they happen in. "
            "The shape of the week is the information — which days carry "
            "weight and which are empty."
        ),
        "allowed_roles": ("lead", "secondary"),
        "bindings": {
            # No `days` binding. The seven columns are a calendar fact, not
            # tenant data — asking a layout to bind them invites a six-column
            # week. The primitive generates them from `week_of` (or today).
            "week_of": _scalar({"date": "date"}, required=False),
            "events": _collection({
                "id": "string",
                "date": "date",
                "title": "string",
                "time": "time?",
                "subtitle": "string?",
                "attendance": "int?",
                "kind": "string?",
            }),
        },
        "options": {
            "week_start": _enum(["sun", "mon"], "sun"),
            "show_counts": _bool(False),
            "count_noun": _string("attending"),
            # A church week is not seven equal columns and never has
            # been: Sunday carries the weight and the grid should say so
            # before a single event is read. The anchor day takes roughly
            # double width; the rest compress around it.
            "anchor_day": _enum(["none", "sun", "mon", "tue", "wed", "thu", "fri", "sat"],
                                "none"),
            # Days that exist but are not the working week. A private
            # practice runs Monday to Friday, and rendering Saturday at
            # full strength implies an availability that is not offered.
            "dim_days": _string_list([], max_items=7),
        },
    },

    # ── things waiting on a human ────────────────────────────────────
    "attention_queue": {
        "id": "attention_queue",
        "label": "Attention queue",
        "purpose": (
            "An ordered list of things waiting on a person, each carrying how "
            "long it has waited. Age is the whole point — a queue without it "
            "is just a list."
        ),
        "allowed_roles": ("secondary", "footer"),
        "bindings": {
            "items": _collection({
                "id": "string",
                "title": "string",
                "age_days": "int",
                "subtitle": "string?",
                "action_label": "string?",
            }),
        },
        "options": {
            "age_unit": _enum(["days", "weeks", "months"], "days"),
            # Up to three years. The original ceiling of 365 was set on
            # salon and ministry timescales, where a six-week gap is already
            # a problem. Fundraising measures lapse year-over-year — a donor
            # who last gave eighteen months ago is the one worth calling,
            # and capping the option at a year would have forced the
            # nonprofit preset to lie about its own threshold.
            "escalate_after_days": _int(1, 1095, 30),
            "max_visible": _int(3, 25, 8),
        },
    },

    # ── figures at rest ──────────────────────────────────────────────
    "metric_row": {
        "id": "metric_row",
        "label": "Metric row",
        "purpose": (
            "Two to four figures at rest. Reference, not headline — you read "
            "them on the way past, and they never ask to be acted on."
        ),
        # Deliberately no "lead". The brief says footer material, never the
        # hero; putting that here means a layout that leads with numbers
        # fails check 5 instead of shipping.
        "allowed_roles": ("secondary", "footer"),
        "bindings": {
            "metrics": _collection({
                "id": "string",
                "label": "string",
                "value": "number",
                "unit": "string?",
                "trend": "string?",
            }, min_items=2, max_items=4),
        },
        "options": {
            "format": _enum(["number", "currency", "duration", "percent"], "number"),
        },
    },

    # ── a number is noise until it sits next to the band ─────────────
    "benchmark_panel": {
        "id": "benchmark_panel",
        "label": "Benchmark panel",
        "purpose": (
            "The handful of numbers that actually say whether the business is "
            "working, each one placed against its industry average and its "
            "target. A bare figure is noise: 38% means nothing until you can "
            "see that the average is 52% and the target is 50%, and read one "
            "line explaining what to do about the gap."
        ),
        # Deliberately not `lead`. This is a view ON the work, not the work
        # itself — the practitioner acts on the timeline or the docket and
        # consults this. A business whose home screen opens on a scorecard
        # has been given a report, not a workspace.
        "allowed_roles": ("secondary", "footer"),
        "bindings": {
            "rows": _collection({
                "id": "string",
                "label": "string",
                "value": "number",
                # The band. `average` is where the industry sits, `target` is
                # where this business should be, `floor` is where it becomes
                # a problem. All optional because not every metric has a
                # published benchmark, and inventing one would be worse than
                # showing the number alone.
                "average": "number?",
                "target": "number?",
                "floor": "number?",
                "scale_max": "number?",
                "unit": "string?",
                # The one line that turns a number into a decision. Without
                # it the panel is a stat wall.
                "reading": "string?",
                "source": "string?",
                "direction": "string?",
            }, min_items=2, max_items=6),
        },
        "options": {
            "format": _enum(["percent", "number", "days", "currency", "duration"],
                            "percent"),
            "show_average": _bool(True),
            # `cascade` is for the case where the rows multiply through each
            # other rather than standing alone — a law firm's utilization ×
            # realization × collection is one story in three parts, and
            # reading them as three independent gauges misses the point.
            "cascade": _bool(False),
            "cascade_label": _string("of working time survives to cash"),
        },
    },

    # ── money in, money out, where it stands ─────────────────────────
    "ledger": {
        "id": "ledger",
        "label": "Ledger",
        "purpose": (
            "Debits and credits with a running balance. The balance column is "
            "the answer; the rows are how it got there."
        ),
        "allowed_roles": ("secondary", "footer"),
        "bindings": {
            "entries": _collection({
                "id": "string",
                "date": "date",
                "description": "string",
                "debit": "number?",
                "credit": "number?",
                # Optional on purpose. No ledger table stores a running
                # balance — it is an artifact of row order. Bind it when the
                # source really has one; leave it unbound and the primitive
                # accumulates from `opening_balance`.
                "balance": "number?",
            }),
            "opening_balance": _scalar({"value": "number"}, required=False),
        },
        "options": {
            "currency": _string("USD"),
            "max_visible": _int(3, 50, 10),
        },
    },
}


# At most this many surfaces in one layout (spec section 4, check 7).
SURFACE_BUDGET = 5


def exists(primitive_id: str) -> bool:
    return primitive_id in PRIMITIVES


def get(primitive_id: str) -> Dict[str, Any]:
    """Registry lookup. Raises rather than returning a shrug — every caller
    here has already been through check 1."""
    try:
        return PRIMITIVES[primitive_id]
    except KeyError:
        raise KeyError(f"unknown primitive {primitive_id!r}") from None


def ids() -> List[str]:
    return list(PRIMITIVES.keys())


def defaults_for(primitive_id: str) -> Dict[str, Any]:
    """Every option's declared default, so the renderer never guesses."""
    opts = get(primitive_id).get("options") or {}
    out: Dict[str, Any] = {}
    for name, spec in opts.items():
        default = spec.get("default")
        out[name] = list(default) if isinstance(default, tuple) else default
    return out


def required_bindings(primitive_id: str) -> List[str]:
    binds = get(primitive_id).get("bindings") or {}
    return [n for n, b in binds.items() if b.get("required")]


def required_fields(primitive_id: str, binding: str) -> List[str]:
    binds = get(primitive_id).get("bindings") or {}
    spec = binds.get(binding) or {}
    return [n for n, f in (spec.get("fields") or {}).items() if f.get("required")]


def describe() -> List[Dict[str, Any]]:
    """Serializable registry, for the composer API and the renderer."""
    out = []
    for pid, p in PRIMITIVES.items():
        out.append({
            "id": pid,
            "label": p["label"],
            "purpose": p["purpose"],
            "allowed_roles": list(p["allowed_roles"]),
            "bindings": {
                name: {
                    "shape": b["shape"],
                    "required": b["required"],
                    "min_items": b.get("min_items"),
                    "max_items": b.get("max_items"),
                    "fields": {
                        fn: dict(fs) for fn, fs in (b.get("fields") or {}).items()
                    },
                }
                for name, b in (p.get("bindings") or {}).items()
            },
            "options": {
                name: {
                    k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in spec.items()
                }
                for name, spec in (p.get("options") or {}).items()
            },
        })
    return out
