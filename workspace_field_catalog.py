"""
workspace_field_catalog.py — what a layout binding is allowed to reach.

Validator checks 3 (`fields_resolve`) and 4 (`tenant_scope`) resolve against
this. It is an ALLOW-LIST, deliberately narrower than the database: a source
that isn't here cannot be bound, and a column that isn't listed on a source
cannot be named — even if the table has it. That is the point. Phase two
lets Chief author bindings, and the blast radius of that is exactly this
file.

Every source declares:

  table          the Postgres relation
  tenant_column  the column carrying the owning business. `None` means the
                 source is not tenant-scoped, and check 4 rejects any
                 binding to it — there is no such source today, and the
                 field exists so that adding one is a visible decision.
  columns        the bindable columns, each with the contract type it can
                 satisfy.
  json_column    optional. `module_entries` keeps practitioner-defined
                 fields inside a jsonb blob; a binding may name
                 "data.deadline" and check 3 accepts it as long as the
                 prefix matches this column. The leaf is not checked —
                 the module's own spec owns that shape, not the composer.

Columns were read off the live callers (sessions/contacts/invoices/
module_entries/business_users/contractors), not invented.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# The only legal binding scope. Written out because check 4 compares against
# it by name, and a second scope is a policy change, not a config change.
LEGAL_SCOPE = "business"


# Which storage types can satisfy which contract field type. A timestamp
# answers a `date` question and a `time` question both, because the column
# genuinely carries both; a `string` column cannot answer a `number` one.
# Without this, every binding is a guess the renderer discovers at runtime.
TYPE_SATISFIES: Dict[str, frozenset] = {
    "timestamp": frozenset({"date", "time", "string"}),
    "date":      frozenset({"date", "string"}),
    "time":      frozenset({"time", "string"}),
    "string":    frozenset({"string"}),
    "int":       frozenset({"int", "number", "string"}),
    "number":    frozenset({"number", "string"}),
    "bool":      frozenset({"bool"}),
}


# Derivations a binding may apply to a column. `age_days` is the one that
# forces this to exist: an attention queue is ordered by how long something
# has waited, and no table stores that — it is `now - last_interaction`,
# computed at read time. Declaring the derivation here means the validator
# can prove the arithmetic lands on the contract's type instead of the
# renderer finding out.
DERIVATIONS: Dict[str, Dict[str, Any]] = {
    "days_since":         {"from": ("date", "timestamp"), "to": "int",
                           "label": "whole days since"},
    "days_until":         {"from": ("date", "timestamp"), "to": "int",
                           "label": "whole days until"},
    "cents_to_amount":    {"from": ("int", "number"), "to": "number",
                           "label": "cents as a currency amount"},
    "minutes_to_hours":   {"from": ("int", "number"), "to": "number",
                           "label": "minutes as decimal hours"},
    "date_part":          {"from": ("timestamp", "date"), "to": "date",
                           "label": "the date half of a timestamp"},
    "time_part":          {"from": ("timestamp", "time"), "to": "time",
                           "label": "the time half of a timestamp"},
}


def satisfies(storage_type: Optional[str], contract_type: str) -> bool:
    """True if a column of `storage_type` can answer a `contract_type` field.

    An unknown storage type (a jsonb leaf) returns True: the module spec
    owns that shape, and the composer is not entitled to an opinion about
    a field the practitioner just defined.
    """
    if storage_type is None:
        return True
    return contract_type in TYPE_SATISFIES.get(storage_type, frozenset())


def derivation(name: str) -> Optional[Dict[str, Any]]:
    return DERIVATIONS.get(name)


def derivations() -> List[str]:
    return list(DERIVATIONS.keys())


def _src(
    table: str,
    columns: Dict[str, str],
    *,
    tenant_column: Optional[str] = "business_id",
    json_column: Optional[str] = None,
    label: str = "",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "table": table,
        "tenant_column": tenant_column,
        "columns": dict(columns),
        "json_column": json_column,
        "label": label or table,
        # A source that is not a plain relation. The resolver calls the
        # named module instead of building a query — used where rows are
        # assembled in code rather than stored, and invisible to a layout.
        "provider": provider,
    }


CATALOG: Dict[str, Dict[str, Any]] = {

    # One calendar. Every booking path mirrors into here.
    "sessions": _src("sessions", {
        "id": "string",
        "business_id": "string",
        "contact_id": "string",
        "title": "string",
        "session_type": "string",
        "status": "string",
        "scheduled_for": "timestamp",
        "duration_minutes": "int",
        "notes": "string",
        # Who is doing the work. Added by
        # supabase/APPLY-2026-08-26-workspace-composer.sql — a salon floor
        # binds it to business_users, a crew board to contractors. It is
        # deliberately unconstrained: the layout declares the lane source,
        # so a FK to one table would pick a winner between two verticals.
        "assigned_to": "string",
    }, label="Sessions / bookings"),

    # The CRM spine.
    "contacts": _src("contacts", {
        "id": "string",
        "business_id": "string",
        "name": "string",
        "email": "string",
        "phone": "string",
        "role": "string",
        "status": "string",
        "source": "string",
        "tags": "string",
        "health_score": "number",
        "lead_score": "number",
        "last_interaction": "timestamp",
        "created_at": "timestamp",
    }, label="Contacts"),

    # Practitioner-defined records: matters, jobs, engagements, gatherings.
    # The composer binds the envelope columns and reaches into `data.*` for
    # whatever the module's spec declared.
    "module_entries": _src("module_entries", {
        "id": "string",
        "business_id": "string",
        "module_id": "string",
        "status": "string",
        "created_by": "string",
        "created_at": "timestamp",
        "data": "string",
    }, json_column="data", label="Module entries"),

    "invoices": _src("invoices", {
        "id": "string",
        "business_id": "string",
        "customer_name": "string",
        "description": "string",
        "status": "string",
        "currency": "string",
        "subtotal_cents": "number",
        "total_cents": "number",
        "amount_due_cents": "number",
        "amount_paid_cents": "number",
        "due_date": "date",
        "paid_at": "timestamp",
        "created_at": "timestamp",
    }, label="Invoices"),

    # Lanes. Staff seats for a salon floor; contractors for a crew board.
    "business_users": _src("business_users", {
        "id": "string",
        "business_id": "string",
        "user_id": "string",
        "display_name": "string",
        "role": "string",
        "status": "string",
    }, label="Team seats"),

    "contractors": _src("contractors", {
        "id": "string",
        "business_id": "string",
        "name": "string",
        "trade": "string",
        "status": "string",
        "phone": "string",
    }, label="Contractors / crew"),

    # Immutable double-entry lines. Note there is no running-balance
    # column — a balance is an artifact of row order, which is why the
    # `ledger` primitive computes it rather than binding it.
    "ledger_entries": _src("ledger_entries", {
        "id": "string",
        "business_id": "string",
        "account_code": "string",
        "account_type": "string",
        "source_type": "string",
        "debit": "number",
        "credit": "number",
        "entry_date": "date",
        "currency": "string",
        "memo": "string",
        "created_at": "timestamp",
    }, label="Ledger lines"),

    # Benchmarked metrics: the figure AND the band it should be read
    # against. Not a relation — a PROVIDER. The bands are editorial claims
    # with citations and live in workspace_benchmarks.py where they get
    # reviewed; only the per-tenant VALUE comes out of the database. The
    # resolver calls the provider instead of building a query, and the
    # layout schema cannot tell the difference.
    "business_benchmarks": _src("business_benchmarks", {
        "business_id": "string",
        "key": "string",
        "label": "string",
        "value": "number",
        "average": "number",
        "target": "number",
        "floor": "number",
        "scale_max": "number",
        "unit": "string",
        "direction": "string",
        "reading": "string",
        "source": "string",
        "computed_at": "timestamp",
    }, label="Benchmarked metrics", provider="workspace_benchmarks"),

    # Named figures, one row per figure. A metric row binds three keys and
    # gets three numbers; without this it would have to bind three separate
    # queries through one collection descriptor, which the schema has no way
    # to express. Backed by the view in
    # supabase/APPLY-2026-08-26-workspace-composer.sql.
    "business_metrics": _src("business_metrics", {
        "business_id": "string",
        "key": "string",
        "label": "string",
        "value": "number",
        "unit": "string",
        "trend": "string",
        "computed_at": "timestamp",
    }, label="Named figures"),

    "customer_balances": _src("customer_balances", {
        "id": "string",
        "business_id": "string",
        "contact_id": "string",
        "balance_cents": "number",
        "updated_at": "timestamp",
    }, label="Customer balances"),
}


def exists(source: str) -> bool:
    return source in CATALOG


def get(source: str) -> Dict[str, Any]:
    try:
        return CATALOG[source]
    except KeyError:
        raise KeyError(f"unknown source {source!r}") from None


def sources() -> List[str]:
    return list(CATALOG.keys())


def column_exists(source: str, column: str) -> bool:
    """True if `column` is bindable on `source`.

    Accepts a jsonb path ("data.deadline") when the source declares a
    `json_column` and the prefix matches it. The leaf key is intentionally
    not validated — the module spec owns that, and the composer refusing a
    field the practitioner just defined would be wrong.
    """
    entry = CATALOG.get(source)
    if not entry:
        return False
    if column in entry["columns"]:
        return True
    jc = entry.get("json_column")
    if jc and "." in column:
        head, rest = column.split(".", 1)
        return head == jc and bool(rest.strip())
    return False


def column_type(source: str, column: str) -> Optional[str]:
    """Declared contract type, or None for a jsonb leaf (unknowable here)."""
    entry = CATALOG.get(source)
    if not entry:
        return None
    return entry["columns"].get(column)


def tenant_column(source: str) -> Optional[str]:
    entry = CATALOG.get(source)
    return entry.get("tenant_column") if entry else None


def order_columns(order: str) -> List[Tuple[str, str]]:
    """Split a PostgREST-style order clause into (column, direction) pairs.

    "start.asc,name.desc" -> [("start", "asc"), ("name", "desc")]
    A bare "start" yields ("start", "asc").
    """
    out: List[Tuple[str, str]] = []
    for part in (order or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(".")
        # A jsonb path orders as data.deadline.asc — the direction is only
        # the final segment when it actually is one.
        if len(bits) >= 2 and bits[-1] in ("asc", "desc"):
            out.append((".".join(bits[:-1]), bits[-1]))
        else:
            out.append((part, "asc"))
    return out


def describe() -> List[Dict[str, Any]]:
    return [
        {
            "source": name,
            "label": entry["label"],
            "table": entry["table"],
            "tenant_column": entry["tenant_column"],
            "json_column": entry["json_column"],
            "columns": dict(entry["columns"]),
        }
        for name, entry in CATALOG.items()
    ]
