"""
workspace_layout_validator.py — the guardrail.

Runs on any layout schema before persist or before render. It REJECTS; it
never silently repairs. A schema that fails comes back with structured
errors naming the check, a machine code, the JSON path, and the offending
value — never a boolean and never a patched-up document.

Chief isn't composing layouts yet. This exists anyway, because phase two
hands Chief the pen and the only thing standing between a hallucinated
binding and a practitioner's data is this file.

Seven checks, in the order the spec fixes (docs/WORKSPACE_COMPOSER_SPEC.md
section 4):

  1 primitive_exists     the primitive is in the registry
  2 contract_satisfied   required bindings and fields are all bound
  3 fields_resolve       every source and column exists in the catalog
  4 tenant_scope         nothing reaches outside this business
  5 options_in_range     options are known, typed, and in range
  6 rationale_present    the document says why, and what it left out
  7 surface_budget       at most five surfaces, exactly one lead

Checks 1-5 are per-surface and each depends on the one before it: a surface
that fails check N is skipped for N+1..5, so an unknown primitive produces
one error rather than a cascade of "unknown binding" noise it can't help.
Checks 6 and 7 are document-level and always run. Everything that survives
is reported together, so a malformed schema is fixed in one pass.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set

import workspace_field_catalog as catalog
import workspace_primitives as registry

logger = logging.getLogger("workspace_layout_validator")

CHECKS = (
    "primitive_exists",
    "contract_satisfied",
    "fields_resolve",
    "tenant_scope",
    "options_in_range",
    "rationale_present",
    "surface_budget",
)

VALID_ROLES = registry.ROLES
VALID_ORIGINS = ("preset", "user_override")


class LayoutValidationError(Exception):
    """Raised by assert_valid(). Carries the full structured error list —
    callers that surface this to a practitioner should read `.errors`, not
    str(e)."""

    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        first = errors[0] if errors else {}
        super().__init__(
            f"{len(errors)} layout validation error(s); first: "
            f"{first.get('code')} at {first.get('path')}"
        )


class ValidationResult:
    __slots__ = ("errors",)

    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok

    def codes(self) -> List[str]:
        return [e["code"] for e in self.errors]

    def checks(self) -> List[str]:
        return [e["check"] for e in self.errors]

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors)}


def _err(check: str, code: str, path: str, message: str, value: Any = None) -> Dict[str, Any]:
    return {
        "check": check,
        "code": code,
        "path": path,
        "message": message,
        "value": value,
    }


def _is_int(v: Any) -> bool:
    # bool is an int in Python and would sail through an isinstance check.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ─── check 1 ─────────────────────────────────────────────────────────

def _check_primitive_exists(surfaces: List[Any]) -> (List[Dict[str, Any]], Set[int]):
    errors: List[Dict[str, Any]] = []
    failed: Set[int] = set()
    for i, s in enumerate(surfaces):
        path = f"surfaces[{i}]"
        if not isinstance(s, dict):
            errors.append(_err("primitive_exists", "surface_not_an_object", path,
                               "surface must be an object", s))
            failed.add(i)
            continue
        pid = s.get("primitive")
        if not pid or not isinstance(pid, str):
            errors.append(_err("primitive_exists", "missing_primitive",
                               f"{path}.primitive",
                               "surface declares no primitive", pid))
            failed.add(i)
            continue
        if not registry.exists(pid):
            errors.append(_err(
                "primitive_exists", "unknown_primitive", f"{path}.primitive",
                f"{pid!r} is not a registered primitive; known: "
                f"{', '.join(registry.ids())}",
                pid,
            ))
            failed.add(i)
    return errors, failed


# ─── check 2 ─────────────────────────────────────────────────────────

def _check_contract_satisfied(surfaces, skip: Set[int]) -> (List[Dict[str, Any]], Set[int]):
    errors: List[Dict[str, Any]] = []
    failed: Set[int] = set()
    for i, s in enumerate(surfaces):
        if i in skip:
            continue
        path = f"surfaces[{i}]"
        prim = registry.get(s["primitive"])
        declared = prim.get("bindings") or {}
        bindings = s.get("bindings")
        if bindings is None or not isinstance(bindings, dict):
            errors.append(_err("contract_satisfied", "missing_bindings",
                               f"{path}.bindings",
                               f"{s['primitive']} declares "
                               f"{len(declared)} binding(s); none supplied",
                               bindings))
            failed.add(i)
            continue

        surface_failed = False

        for name, spec in declared.items():
            if not spec.get("required"):
                continue
            if name not in bindings:
                errors.append(_err(
                    "contract_satisfied", "missing_required_binding",
                    f"{path}.bindings.{name}",
                    f"{s['primitive']} requires binding {name!r}",
                    None,
                ))
                surface_failed = True

        for name, bound in bindings.items():
            bpath = f"{path}.bindings.{name}"
            spec = declared.get(name)
            if spec is None:
                errors.append(_err(
                    "contract_satisfied", "unknown_binding", bpath,
                    f"{s['primitive']} has no binding named {name!r}; "
                    f"declared: {', '.join(declared.keys())}",
                    name,
                ))
                surface_failed = True
                continue
            if not isinstance(bound, dict):
                errors.append(_err("contract_satisfied", "binding_not_an_object",
                                   bpath, "binding must be a source descriptor object",
                                   bound))
                surface_failed = True
                continue

            fields = bound.get("fields")
            if not isinstance(fields, dict) or not fields:
                errors.append(_err("contract_satisfied", "missing_field_map",
                                   f"{bpath}.fields",
                                   "binding declares no field map", fields))
                surface_failed = True
                continue

            for fname, fspec in (spec.get("fields") or {}).items():
                if fspec.get("required") and fname not in fields:
                    errors.append(_err(
                        "contract_satisfied", "missing_required_field",
                        f"{bpath}.fields.{fname}",
                        f"binding {name!r} must bind required contract field "
                        f"{fname!r} ({fspec['type']})",
                        None,
                    ))
                    surface_failed = True

            for fname in fields:
                if fname not in (spec.get("fields") or {}):
                    errors.append(_err(
                        "contract_satisfied", "unknown_contract_field",
                        f"{bpath}.fields.{fname}",
                        f"binding {name!r} has no contract field {fname!r}",
                        fname,
                    ))
                    surface_failed = True

            # Fields that are optional in general but required by the
            # options this surface chose — a docket sorted by stage with no
            # stage bound is one undifferentiated pile.
            conditional = (prim.get("field_required_when") or {}).get(name) or {}
            for fname, cond in conditional.items():
                opt = cond["option"]
                have = (s.get("options") or {}).get(
                    opt, ((prim.get("options") or {}).get(opt) or {}).get("default"))
                if have == cond["equals"] and fname not in fields:
                    errors.append(_err(
                        "contract_satisfied", "missing_conditional_field",
                        f"{bpath}.fields.{fname}",
                        f"{opt} is {cond['equals']!r}, which requires binding "
                        f"{name!r} to bind {fname!r}",
                        None,
                    ))
                    surface_failed = True

            # Item-count bounds. `expect_items` is how a preset declares the
            # shape it intends (week_grid's seven columns, metric_row's two
            # to four figures) without the data being present yet.
            expect = bound.get("expect_items")
            lo, hi = spec.get("min_items"), spec.get("max_items")
            if expect is not None:
                if not _is_int(expect) or expect < 0:
                    errors.append(_err("contract_satisfied", "bad_expect_items",
                                       f"{bpath}.expect_items",
                                       "expect_items must be a non-negative integer",
                                       expect))
                    surface_failed = True
                elif lo is not None and expect < lo:
                    errors.append(_err(
                        "contract_satisfied", "too_few_items",
                        f"{bpath}.expect_items",
                        f"binding {name!r} needs at least {lo} item(s); declares {expect}",
                        expect,
                    ))
                    surface_failed = True
                elif hi is not None and expect > hi:
                    errors.append(_err(
                        "contract_satisfied", "too_many_items",
                        f"{bpath}.expect_items",
                        f"binding {name!r} allows at most {hi} item(s); declares {expect}",
                        expect,
                    ))
                    surface_failed = True

        if surface_failed:
            failed.add(i)
    return errors, failed


# ─── check 3 ─────────────────────────────────────────────────────────

def _check_fields_resolve(surfaces, skip: Set[int]) -> (List[Dict[str, Any]], Set[int]):
    errors: List[Dict[str, Any]] = []
    failed: Set[int] = set()
    for i, s in enumerate(surfaces):
        if i in skip:
            continue
        path = f"surfaces[{i}]"
        surface_failed = False
        for name, bound in (s.get("bindings") or {}).items():
            bpath = f"{path}.bindings.{name}"
            source = bound.get("source")
            if not source or not isinstance(source, str):
                errors.append(_err("fields_resolve", "missing_source",
                                   f"{bpath}.source",
                                   "binding names no source", source))
                surface_failed = True
                continue
            if not catalog.exists(source):
                errors.append(_err(
                    "fields_resolve", "unknown_source", f"{bpath}.source",
                    f"{source!r} is not in the field catalog; known: "
                    f"{', '.join(catalog.sources())}",
                    source,
                ))
                surface_failed = True
                continue

            contract_fields = (
                registry.get(s["primitive"]).get("bindings") or {}
            ).get(name, {}).get("fields") or {}

            for fname, ref in (bound.get("fields") or {}).items():
                fpath = f"{bpath}.fields.{fname}"
                # A field maps either to a bare column ("name") or to a
                # derivation ({"column": "last_interaction",
                #              "derive": "days_since"}).
                derive = None
                if isinstance(ref, dict):
                    column = ref.get("column")
                    derive = ref.get("derive")
                    if not derive:
                        errors.append(_err("fields_resolve", "bad_column_reference",
                                           fpath,
                                           "field descriptor must name a derive",
                                           ref))
                        surface_failed = True
                        continue
                else:
                    column = ref

                if not isinstance(column, str) or not column:
                    errors.append(_err("fields_resolve", "bad_column_reference",
                                       fpath,
                                       "field must map to a column name", ref))
                    surface_failed = True
                    continue
                if not catalog.column_exists(source, column):
                    errors.append(_err(
                        "fields_resolve", "unresolvable_field", fpath,
                        f"{source}.{column} does not resolve for this tenant",
                        column,
                    ))
                    surface_failed = True
                    continue

                stored = catalog.column_type(source, column)
                want = (contract_fields.get(fname) or {}).get("type")

                if derive is not None:
                    spec = catalog.derivation(derive)
                    if spec is None:
                        errors.append(_err(
                            "fields_resolve", "unknown_derivation",
                            f"{fpath}.derive",
                            f"{derive!r} is not a known derivation; known: "
                            f"{', '.join(catalog.derivations())}",
                            derive,
                        ))
                        surface_failed = True
                        continue
                    if stored is not None and stored not in spec["from"]:
                        errors.append(_err(
                            "fields_resolve", "derivation_type_mismatch", fpath,
                            f"{derive!r} reads {' or '.join(spec['from'])}; "
                            f"{source}.{column} is {stored}",
                            stored,
                        ))
                        surface_failed = True
                        continue
                    stored = spec["to"]

                if want and not catalog.satisfies(stored, want):
                    errors.append(_err(
                        "fields_resolve", "field_type_mismatch", fpath,
                        f"contract field {fname!r} is {want}; "
                        f"{source}.{column} resolves to {stored}",
                        stored,
                    ))
                    surface_failed = True

            for column in (bound.get("filter") or {}):
                if not catalog.column_exists(source, column):
                    errors.append(_err(
                        "fields_resolve", "unresolvable_filter_column",
                        f"{bpath}.filter.{column}",
                        f"{source}.{column} does not resolve for this tenant",
                        column,
                    ))
                    surface_failed = True

            order = bound.get("order")
            if order:
                if not isinstance(order, str):
                    errors.append(_err("fields_resolve", "bad_order_clause",
                                       f"{bpath}.order",
                                       "order must be a string", order))
                    surface_failed = True
                else:
                    for column, direction in catalog.order_columns(order):
                        if not catalog.column_exists(source, column):
                            errors.append(_err(
                                "fields_resolve", "unresolvable_order_column",
                                f"{bpath}.order",
                                f"{source}.{column} does not resolve for this tenant",
                                column,
                            ))
                            surface_failed = True
        if surface_failed:
            failed.add(i)
    return errors, failed


# ─── check 4 ─────────────────────────────────────────────────────────

def _check_tenant_scope(surfaces, skip: Set[int], business_id: Optional[str]
                        ) -> (List[Dict[str, Any]], Set[int]):
    """The one that matters. A binding may declare only `scope: "business"`,
    and if it pins a tenant column at all it must pin it to THIS business.

    This runs independently of RLS on purpose — same posture as the
    app-layer owner checks. A layout is data the practitioner (and later
    Chief) authors, and data that names a table is data that can name
    someone else's row."""
    errors: List[Dict[str, Any]] = []
    failed: Set[int] = set()
    for i, s in enumerate(surfaces):
        if i in skip:
            continue
        path = f"surfaces[{i}]"
        surface_failed = False
        for name, bound in (s.get("bindings") or {}).items():
            bpath = f"{path}.bindings.{name}"
            scope = bound.get("scope")
            if scope != catalog.LEGAL_SCOPE:
                errors.append(_err(
                    "tenant_scope", "illegal_scope", f"{bpath}.scope",
                    f"binding scope must be {catalog.LEGAL_SCOPE!r}; got {scope!r}",
                    scope,
                ))
                surface_failed = True
                continue

            source = bound.get("source")
            tcol = catalog.tenant_column(source)
            if not tcol:
                errors.append(_err(
                    "tenant_scope", "untenanted_source", f"{bpath}.source",
                    f"{source!r} carries no tenant column and cannot be bound",
                    source,
                ))
                surface_failed = True
                continue

            filt = bound.get("filter") or {}
            if tcol in filt:
                pinned = filt[tcol]
                # Pinning to our own id is redundant but harmless; pinning
                # to anything else is the attack this check exists for.
                if business_id is None or str(pinned) != str(business_id):
                    errors.append(_err(
                        "tenant_scope", "cross_tenant_binding",
                        f"{bpath}.filter.{tcol}",
                        f"binding reaches {tcol} {pinned!r}; tenant is "
                        f"{business_id!r}",
                        pinned,
                    ))
                    surface_failed = True

            # A filter value is a literal, or a list of literals meaning IN.
            # It is never a PostgREST fragment — the descriptor is a
            # declaration, not a hole to smuggle a query through. This is
            # the check that stops `status: "neq.x&business_id=eq.other"`
            # from becoming a cross-tenant read once Chief is authoring
            # bindings in phase two.
            for column, value in filt.items():
                fpath = f"{bpath}.filter.{column}"
                candidates = value if isinstance(value, list) else [value]
                if isinstance(value, list) and not value:
                    errors.append(_err(
                        "tenant_scope", "empty_filter_list", fpath,
                        "an empty filter list matches nothing; omit the filter",
                        value,
                    ))
                    surface_failed = True
                for item in candidates:
                    if isinstance(item, (dict, list)):
                        errors.append(_err(
                            "tenant_scope", "raw_filter_expression", fpath,
                            "filter values are literals, or a flat list of them",
                            item,
                        ))
                        surface_failed = True
                    elif isinstance(item, str) and (
                            item.startswith(("not.", "or(", "and(", "in.", "eq.",
                                             "neq.", "gt.", "lt.", "gte.", "lte."))
                            or any(c in item for c in "&=*")):
                        errors.append(_err(
                            "tenant_scope", "raw_filter_expression", fpath,
                            "filter values are literals, not PostgREST expressions",
                            item,
                        ))
                        surface_failed = True
        if surface_failed:
            failed.add(i)
    return errors, failed


# ─── check 5 ─────────────────────────────────────────────────────────

def _check_options_in_range(surfaces, skip: Set[int]) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    for i, s in enumerate(surfaces):
        if i in skip:
            continue
        path = f"surfaces[{i}]"
        prim = registry.get(s["primitive"])
        declared = prim.get("options") or {}
        options = s.get("options") or {}

        if not isinstance(options, dict):
            errors.append(_err("options_in_range", "bad_options_object",
                               f"{path}.options", "options must be an object",
                               options))
            options = {}

        # Role lives here: it is the option that decides prominence, and
        # `metric_row` not listing `lead` is what keeps numbers out of the
        # hero slot.
        role = s.get("role")
        rpath = f"{path}.role"
        if role not in VALID_ROLES:
            errors.append(_err("options_in_range", "unknown_role", rpath,
                               f"role must be one of {', '.join(VALID_ROLES)}",
                               role))
        elif role not in prim["allowed_roles"]:
            errors.append(_err(
                "options_in_range", "role_not_allowed", rpath,
                f"{s['primitive']} may not occupy the {role!r} role; allowed: "
                f"{', '.join(prim['allowed_roles'])}",
                role,
            ))

        for name, value in options.items():
            opath = f"{path}.options.{name}"
            spec = declared.get(name)
            if spec is None:
                errors.append(_err(
                    "options_in_range", "unknown_option", opath,
                    f"{s['primitive']} has no option {name!r}; declared: "
                    f"{', '.join(declared.keys()) or 'none'}",
                    name,
                ))
                continue
            otype = spec["type"]
            if otype == "enum":
                if value not in spec["values"]:
                    errors.append(_err(
                        "options_in_range", "option_out_of_range", opath,
                        f"{name} must be one of {', '.join(spec['values'])}",
                        value,
                    ))
            elif otype == "int":
                if not _is_int(value):
                    errors.append(_err("options_in_range", "option_wrong_type",
                                       opath, f"{name} must be an integer", value))
                elif not (spec["min"] <= value <= spec["max"]):
                    errors.append(_err(
                        "options_in_range", "option_out_of_range", opath,
                        f"{name} must be between {spec['min']} and {spec['max']}",
                        value,
                    ))
            elif otype == "bool":
                if not isinstance(value, bool):
                    errors.append(_err("options_in_range", "option_wrong_type",
                                       opath, f"{name} must be a boolean", value))
            elif otype == "string":
                if not isinstance(value, str):
                    errors.append(_err("options_in_range", "option_wrong_type",
                                       opath, f"{name} must be a string", value))
            elif otype == "string_list":
                if not isinstance(value, (list, tuple)) or any(
                        not isinstance(v, str) for v in value):
                    errors.append(_err("options_in_range", "option_wrong_type",
                                       opath, f"{name} must be a list of strings",
                                       value))
                elif len(value) > spec["max_items"]:
                    errors.append(_err(
                        "options_in_range", "option_out_of_range", opath,
                        f"{name} allows at most {spec['max_items']} entries",
                        len(value),
                    ))

        # Options that only mean something under another option's value.
        for name, condition in (prim.get("option_requires") or {}).items():
            for other, needed in condition.items():
                have = options.get(other, (declared.get(other) or {}).get("default"))
                present = bool(options.get(name))
                if present and have != needed:
                    errors.append(_err(
                        "options_in_range", "option_requires_unmet",
                        f"{path}.options.{name}",
                        f"{name} only applies when {other} is {needed!r}; it is {have!r}",
                        have,
                    ))
                elif not present and have == needed:
                    errors.append(_err(
                        "options_in_range", "option_required_by_peer",
                        f"{path}.options.{name}",
                        f"{other} is {needed!r} and requires {name} to be set",
                        None,
                    ))

        # day_start must precede day_end — a range check no single option
        # can make about itself.
        if s["primitive"] == "timeline_day":
            start = options.get("day_start", declared["day_start"]["default"])
            end = options.get("day_end", declared["day_end"]["default"])
            if _is_int(start) and _is_int(end) and start >= end:
                errors.append(_err(
                    "options_in_range", "option_out_of_range",
                    f"{path}.options.day_end",
                    f"day_end ({end}) must be after day_start ({start})",
                    end,
                ))
    return errors


# ─── check 6 ─────────────────────────────────────────────────────────

def _check_rationale_present(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chief has to be able to say what it chose and what it threw away.
    A layout with no rationale can still render, which is exactly why this
    is a hard reject: the narration is the product, not decoration."""
    errors: List[Dict[str, Any]] = []

    rationale = layout.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append(_err("rationale_present", "missing_rationale", "rationale",
                           "layout must carry a non-empty rationale", rationale))

    suppressed = layout.get("suppressed")
    if suppressed is None:
        errors.append(_err(
            "rationale_present", "missing_suppressed", "suppressed",
            "layout must declare what it suppressed (an empty list is a "
            "claim, and an absent one is a shrug)",
            None,
        ))
    elif not isinstance(suppressed, list):
        errors.append(_err("rationale_present", "bad_suppressed", "suppressed",
                           "suppressed must be a list", suppressed))
    else:
        used = {s.get("primitive") for s in layout.get("surfaces") or []
                if isinstance(s, dict)}
        for j, entry in enumerate(suppressed):
            spath = f"suppressed[{j}]"
            if not isinstance(entry, dict):
                errors.append(_err("rationale_present", "bad_suppressed_entry",
                                   spath, "suppressed entry must be an object",
                                   entry))
                continue
            pid = entry.get("primitive")
            if not pid or not registry.exists(pid):
                errors.append(_err(
                    "rationale_present", "unknown_suppressed_primitive",
                    f"{spath}.primitive",
                    f"{pid!r} is not a registered primitive", pid,
                ))
            elif pid in used:
                errors.append(_err(
                    "rationale_present", "suppressed_primitive_in_use",
                    f"{spath}.primitive",
                    f"{pid!r} is listed as suppressed but the layout renders it",
                    pid,
                ))
            reason = entry.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(_err("rationale_present", "missing_suppression_reason",
                                   f"{spath}.reason",
                                   "every suppression must say why", reason))

    # `refused` is the capability-level companion to `suppressed`. Some
    # of what Chief leaves out is not a primitive at all — a therapist
    # workspace refuses clinical notes outright, and that refusal is the
    # most important thing on the screen. It gets the same treatment:
    # say what, and say why.
    refused = layout.get("refused")
    if refused is not None:
        if not isinstance(refused, list):
            errors.append(_err("rationale_present", "bad_refused", "refused",
                               "refused must be a list", refused))
        else:
            for j, entry in enumerate(refused):
                rpath = f"refused[{j}]"
                if not isinstance(entry, dict):
                    errors.append(_err("rationale_present", "bad_refused_entry",
                                       rpath, "refused entry must be an object",
                                       entry))
                    continue
                if not str(entry.get("what") or "").strip():
                    errors.append(_err("rationale_present", "missing_refused_what",
                                       f"{rpath}.what",
                                       "a refusal must name what is refused", None))
                if len(str(entry.get("reason") or "").strip()) < 20:
                    errors.append(_err(
                        "rationale_present", "missing_refusal_reason",
                        f"{rpath}.reason",
                        "a refusal must explain itself — an unexplained one "
                        "reads as a missing feature", entry.get("reason"),
                    ))

    for i, s in enumerate(layout.get("surfaces") or []):
        if isinstance(s, dict) and s.get("role") == "lead":
            r = s.get("rationale")
            if not isinstance(r, str) or not r.strip():
                errors.append(_err(
                    "rationale_present", "missing_surface_rationale",
                    f"surfaces[{i}].rationale",
                    "the lead surface must say why it leads", r,
                ))
    return errors


# ─── check 7 ─────────────────────────────────────────────────────────

def _check_surface_budget(surfaces: List[Any]) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    n = len(surfaces)
    if n == 0:
        errors.append(_err("surface_budget", "no_surfaces", "surfaces",
                           "a layout must render at least one surface", 0))
        return errors
    if n > registry.SURFACE_BUDGET:
        errors.append(_err(
            "surface_budget", "surface_budget_exceeded", "surfaces",
            f"a layout may declare at most {registry.SURFACE_BUDGET} surfaces; "
            f"this one declares {n}",
            n,
        ))

    leads = [i for i, s in enumerate(surfaces)
             if isinstance(s, dict) and s.get("role") == "lead"]
    if len(leads) == 0:
        errors.append(_err("surface_budget", "no_lead_surface", "surfaces",
                           "a layout must have exactly one lead surface", 0))
    elif len(leads) > 1:
        errors.append(_err(
            "surface_budget", "multiple_lead_surfaces", "surfaces",
            f"a layout must have exactly one lead surface; found {len(leads)} "
            f"at {leads}",
            len(leads),
        ))

    seen: Set[str] = set()
    for i, s in enumerate(surfaces):
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not sid or not isinstance(sid, str):
            errors.append(_err("surface_budget", "missing_surface_id",
                               f"surfaces[{i}].id", "surface needs a stable id", sid))
        elif sid in seen:
            errors.append(_err("surface_budget", "duplicate_surface_id",
                               f"surfaces[{i}].id",
                               f"surface id {sid!r} is used twice", sid))
        else:
            seen.add(sid)
    return errors


# ─── terminology (document-level, folded into check 6's pass) ────────

def _check_terminology(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    terms = layout.get("terminology")
    if terms is None:
        return errors
    if not isinstance(terms, dict):
        errors.append(_err("rationale_present", "bad_terminology", "terminology",
                           "terminology must be an object", terms))
        return errors
    for key, row in terms.items():
        tpath = f"terminology.{key}"
        if not isinstance(row, dict):
            errors.append(_err("rationale_present", "bad_terminology_row", tpath,
                               "terminology row must be {value, origin}", row))
            continue
        value = row.get("value")
        if not isinstance(value, str) or not value.strip():
            errors.append(_err("rationale_present", "missing_term_value",
                               f"{tpath}.value", "terminology row needs a value",
                               value))
        origin = row.get("origin")
        if origin not in VALID_ORIGINS:
            errors.append(_err(
                "rationale_present", "unknown_term_origin", f"{tpath}.origin",
                f"origin must be one of {', '.join(VALID_ORIGINS)}", origin,
            ))
    return errors


# ─── entry points ────────────────────────────────────────────────────

def validate_layout(layout: Any, business_id: Optional[str] = None) -> ValidationResult:
    """Run all seven checks and return everything that failed.

    `business_id` is the tenant the layout is being validated FOR. Omitting
    it does not relax check 4 — it tightens it, because a binding that pins
    a tenant column then has nothing legitimate to match.
    """
    if not isinstance(layout, dict):
        return ValidationResult([_err(
            "primitive_exists", "layout_not_an_object", "",
            "layout schema must be an object", layout,
        )])

    surfaces = layout.get("surfaces")
    if surfaces is None or not isinstance(surfaces, list):
        return ValidationResult([_err(
            "surface_budget", "missing_surfaces", "surfaces",
            "layout must declare a surfaces list", surfaces,
        )])

    errors: List[Dict[str, Any]] = []
    skip: Set[int] = set()

    e, failed = _check_primitive_exists(surfaces)
    errors += e
    skip |= failed

    e, failed = _check_contract_satisfied(surfaces, skip)
    errors += e
    skip |= failed

    e, failed = _check_fields_resolve(surfaces, skip)
    errors += e
    skip |= failed

    e, failed = _check_tenant_scope(surfaces, skip, business_id)
    errors += e
    skip |= failed

    errors += _check_options_in_range(surfaces, skip)
    errors += _check_rationale_present(layout)
    errors += _check_terminology(layout)
    errors += _check_surface_budget(surfaces)

    # Report in the spec's check order, not discovery order, so a caller
    # reading top-down fixes causes before symptoms.
    order = {name: i for i, name in enumerate(CHECKS)}
    errors.sort(key=lambda x: (order.get(x["check"], 99), x["path"]))
    return ValidationResult(errors)


def assert_valid(layout: Any, business_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate or raise. Returns the layout unchanged on success — it is
    never repaired, so the object you get back is the object you passed."""
    result = validate_layout(layout, business_id)
    if not result.ok:
        raise LayoutValidationError(result.errors)
    return layout
