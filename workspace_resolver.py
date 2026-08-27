"""
workspace_resolver.py — the piece that turns a layout into a workspace.

A layout schema says WHERE the data comes from. Until now nothing executed
it: `GET /workspace/layout` handed the frontend a description and no rows,
and the demo faked the difference with hardcoded fixtures. This is that
missing half.

    resolve(layout, business_id) -> { surface_id: { binding: rows|scalar } }

which is exactly the shape the renderer's `propsFor()` reads, so nothing
in the render tree ever learns what a binding is.

═══════════════════════════════════════════════════════════════════════
IT DOES NOT TRUST THE VALIDATOR
═══════════════════════════════════════════════════════════════════════
Check 4 already proved no binding reaches another tenant — but the
validator is a separate function that a caller can forget to run, and
this module is the one holding the service-role key, which bypasses RLS
entirely. So it re-asserts the boundary itself:

  * the tenant filter is applied by THIS code from the business_id
    argument, never copied from the descriptor
  * a descriptor that pins the tenant column to anything else is refused
    outright rather than overridden, because a layout trying it is either
    corrupt or hostile and both deserve a stop
  * every table, column and filter key is checked against the field
    catalog again
  * filter values are escaped before they reach PostgREST

Duplicated effort is the point. The validator stops a bad layout being
SAVED; this stops a bad layout being EXECUTED, and the two failures have
different causes.

═══════════════════════════════════════════════════════════════════════
PROVIDERS
═══════════════════════════════════════════════════════════════════════
Some sources are not relations. `business_benchmarks` joins editorial
bands held in code to values computed per tenant, so the catalog marks it
with a provider and the resolver calls that instead of building a query.
The layout schema cannot tell the difference, which is the point — a
binding is a binding.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import workspace_field_catalog as catalog
import workspace_primitives as registry

logger = logging.getLogger("workspace_resolver")

# A caller may not ask for the whole table.
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


class ResolveError(Exception):
    """A layout that cannot be executed safely. Never rendered past."""


# ─── providers ───────────────────────────────────────────────────────

def _benchmark_provider(business_id: str, descriptor: Dict[str, Any]
                        ) -> List[Dict[str, Any]]:
    import workspace_benchmarks
    wanted = (descriptor.get("filter") or {}).get("key")
    if isinstance(wanted, str):
        wanted = [wanted]
    return workspace_benchmarks.rows_for(business_id, list(wanted or []))


PROVIDERS = {"business_benchmarks": _benchmark_provider}


# ─── derivations ─────────────────────────────────────────────────────

def _as_date(value: Any) -> Optional[_dt.date]:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _days_since(value: Any) -> Optional[int]:
    d = _as_date(value)
    return None if d is None else (_dt.date.today() - d).days


def _days_until(value: Any) -> Optional[int]:
    d = _as_date(value)
    return None if d is None else (d - _dt.date.today()).days


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cents_to_amount(value: Any) -> Optional[float]:
    n = _number(value)
    return None if n is None else n / 100.0


def _minutes_to_hours(value: Any) -> Optional[float]:
    n = _number(value)
    return None if n is None else round(n / 60.0, 2)


def _date_part(value: Any) -> Optional[str]:
    d = _as_date(value)
    return None if d is None else d.isoformat()


def _time_part(value: Any) -> Optional[str]:
    """The clock half of a timestamp, as HH:MM. Accepts a bare time too,
    because `sessions.scheduled_for` is a timestamp but a seeded fixture
    may hand over '14:30'."""
    if value is None:
        return None
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[1]
    elif " " in text and ":" in text:
        text = text.split(" ", 1)[1]
    match = re.match(r"(\d{1,2}):(\d{2})", text)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


DERIVATIONS = {
    "days_since": _days_since,
    "days_until": _days_until,
    "cents_to_amount": _cents_to_amount,
    "minutes_to_hours": _minutes_to_hours,
    "date_part": _date_part,
    "time_part": _time_part,
}


# ─── reading a value off a row ───────────────────────────────────────

def _column_value(row: Dict[str, Any], column: str) -> Any:
    """A column, or a jsonb path like `data.matter_name`.

    Only the declared json_column may be traversed — the catalog decides
    which blob a layout is allowed to reach into, and a path through any
    other column is a layout inventing storage that was never offered.
    """
    if "." not in column:
        return row.get(column)
    head, rest = column.split(".", 1)
    blob = row.get(head)
    if not isinstance(blob, dict):
        return None
    cursor: Any = blob
    for part in rest.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def _base_column(column: str) -> str:
    return column.split(".", 1)[0]


# ─── query building ──────────────────────────────────────────────────

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 _.@:+/\-]*$")


def _escape(value: Any) -> str:
    """A PostgREST filter value.

    Anything outside a conservative character set is refused rather than
    quoted-and-hoped-for. A layout is authored data and phase two hands
    the pen to a model — the moment a value can carry `&`, `(` or `,`
    unescaped it can carry a second filter, and the tenant pin below
    stops being a boundary.
    """
    text = "" if value is None else str(value)
    if not _SAFE_VALUE.match(text):
        raise ResolveError(f"filter value is not a plain literal: {text!r}")
    return text


def _filter_clause(column: str, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        if not value:
            raise ResolveError(f"empty filter list on {column!r} matches nothing")
        joined = ",".join('"' + _escape(v) + '"' for v in value)
        return f"{column}=in.({joined})"
    if isinstance(value, bool):
        return f"{column}=is.{'true' if value else 'false'}"
    if value is None:
        return f"{column}=is.null"
    return f"{column}=eq.{_escape(value)}"


def _build_query(source: str, descriptor: Dict[str, Any],
                 business_id: str) -> str:
    entry = catalog.get(source)
    tenant_column = entry.get("tenant_column")
    if not tenant_column:
        raise ResolveError(f"{source!r} carries no tenant column")

    fields = descriptor.get("fields") or {}
    filters = descriptor.get("filter") or {}

    # Only the columns this binding actually reads.
    columns = {tenant_column}
    for ref in fields.values():
        column = ref.get("column") if isinstance(ref, dict) else ref
        if not isinstance(column, str) or not catalog.column_exists(source, column):
            raise ResolveError(f"{source}.{column!r} does not resolve")
        columns.add(_base_column(column))

    parts = [f"{tenant_column}=eq.{_escape(business_id)}"]

    for column, value in filters.items():
        if not catalog.column_exists(source, column):
            raise ResolveError(f"{source}.{column!r} does not resolve")
        if column == tenant_column:
            # Refused, not overridden. A layout pinning someone else's
            # tenant is corrupt or hostile; either way it stops here.
            if str(value) != str(business_id):
                raise ResolveError(
                    f"binding reaches {tenant_column} {value!r}; "
                    f"tenant is {business_id!r}")
            continue
        parts.append(_filter_clause(column, value))
        columns.add(_base_column(column))

    order = descriptor.get("order")
    if order:
        rebuilt = []
        for column, direction in catalog.order_columns(str(order)):
            if not catalog.column_exists(source, column):
                raise ResolveError(f"cannot order by {source}.{column!r}")
            columns.add(_base_column(column))
            rebuilt.append(f"{_base_column(column)}.{direction}")
        if rebuilt:
            parts.append("order=" + ",".join(rebuilt))

    try:
        limit = int(descriptor.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    parts.append(f"limit={max(1, min(limit, MAX_LIMIT))}")
    parts.append("select=" + ",".join(sorted(columns)))

    return f"/{entry['table']}?" + "&".join(parts)


# ─── mapping rows onto the contract ──────────────────────────────────

def _map_row(row: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, ref in fields.items():
        if isinstance(ref, dict):
            column, derive = ref.get("column"), ref.get("derive")
            raw = _column_value(row, column)
            fn = DERIVATIONS.get(derive)
            if fn is None:
                raise ResolveError(f"unknown derivation {derive!r}")
            out[name] = fn(raw)
        else:
            out[name] = _column_value(row, ref)
    return out


def _resolve_binding(binding_name: str, descriptor: Dict[str, Any],
                     spec: Dict[str, Any], business_id: str) -> Any:
    if not isinstance(descriptor, dict):
        raise ResolveError(f"binding {binding_name!r} is not a descriptor")

    if descriptor.get("scope") != catalog.LEGAL_SCOPE:
        raise ResolveError(
            f"binding {binding_name!r} scope is {descriptor.get('scope')!r}; "
            f"only {catalog.LEGAL_SCOPE!r} is executable")

    source = descriptor.get("source")
    if not source or not catalog.exists(source):
        raise ResolveError(f"unknown source {source!r}")

    provider = PROVIDERS.get(source)
    if provider is not None:
        rows = provider(business_id, descriptor)
    else:
        import sb_clients
        query = _build_query(source, descriptor, business_id)
        raw = sb_clients.sb_get_as_service(query) or []
        fields = descriptor.get("fields") or {}
        rows = [_map_row(r, fields) for r in raw]

    # A scalar binding is one value, not a list of one — `week_of` hands
    # the primitive a date, and handing it a list instead would make every
    # consumer unwrap it.
    if spec.get("shape") == "scalar":
        return rows[0] if rows else None
    return rows


# ─── the entry point ─────────────────────────────────────────────────

def resolve(layout: Dict[str, Any], business_id: str) -> Dict[str, Dict[str, Any]]:
    """Every surface's data, keyed the way the renderer reads it.

    ONE SURFACE FAILING DOES NOT TAKE THE PAGE DOWN. A missing table or a
    malformed binding yields an empty bundle for that surface and a logged
    error; the rest of the workspace still renders. A practitioner opening
    to a blank screen learns nothing, whereas a board with one panel
    missing is still a working board.

    A cross-tenant attempt is the exception and is re-raised, because that
    is not a degraded render — it is a boundary being tested, and it must
    reach the caller loudly.
    """
    if not business_id:
        raise ResolveError("no business_id to resolve against")

    out: Dict[str, Dict[str, Any]] = {}

    for surface in (layout or {}).get("surfaces") or []:
        surface_id = surface.get("id")
        primitive = surface.get("primitive")
        if not surface_id or not registry.exists(primitive):
            logger.error("skipping unrenderable surface %r", surface_id)
            continue

        declared = (registry.get(primitive).get("bindings") or {})
        bundle: Dict[str, Any] = {}

        for name, descriptor in (surface.get("bindings") or {}).items():
            spec = declared.get(name)
            if spec is None:
                logger.error("surface %s binds unknown %r on %s",
                             surface_id, name, primitive)
                continue
            try:
                bundle[name] = _resolve_binding(name, descriptor, spec, business_id)
            except ResolveError as e:
                if "reaches" in str(e):
                    raise
                logger.error("surface %s binding %s did not resolve: %s",
                             surface_id, name, e)
                bundle[name] = None if spec.get("shape") == "scalar" else []
            except Exception:
                logger.exception("surface %s binding %s blew up", surface_id, name)
                bundle[name] = None if spec.get("shape") == "scalar" else []

        out[surface_id] = bundle

    return out
