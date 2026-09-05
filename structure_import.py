"""
structure_import.py — Stage 0 of the Structure Import arc: the rubric.

A business arrives already running, with its structure in a spreadsheet.
This module reads the headers and a SAMPLE of rows from one or more CSV
exports and proposes what each sheet IS in our vocabulary — a surface we
already have (contacts), or a new custom module with an archetype and
typed fields — so the practitioner does not rebuild their business by
hand inside our schema. Spec: STRUCTURE_IMPORT_ARC_SPEC.md (frontend
repo root), §3–§5.

WHY THIS IS A RUBRIC AND NOT A MODEL CALL
  The spec wrote the recognition rules down as evidence over sampled
  values (§4). Evidence rules are deterministic, cost nothing, cannot
  hallucinate a field type outside module_vocabulary, and are testable
  row by row — so the proposer is pure Python. The header is a hint; the
  VALUES decide. Nothing here reads the database: the caller passes the
  business's known contacts in, which keeps every rule unit-testable.

RECONCILE, DO NOT MIRROR (§5)
  * A sheet of PEOPLE routes to `contacts`. Never a new module. Without
    this one rule every import creates a shadow CRM.
  * At most MAX_FIELDS fields per module; the surplus folds into one
    textarea and is LISTED as folded.
  * Empty columns are dropped and NAMED. `dropped` is a list of names,
    never a count.
  * Two columns whose values overlap become one field, and the note
    says which two.
  * Every sheet carries one plain-language `reason`.

Never proposed: `file` (needs an authenticated upload) and `offering_ref`
(offerings are a curated surface). `module_ref` only between sheets in
the SAME upload.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

from module_vocabulary import FIELD_TYPES

# ─── Caps (enforced server-side; the router also enforces at the wire) ──
MAX_SHEETS = 6
MAX_SAMPLE_ROWS = 20
MAX_CELL_CHARS = 120
MAX_FIELDS = 20
MAX_SELECT_OPTIONS = 12

PEOPLE_MATCH = 0.60          # share of values matching contacts → contact_link
CONTACT_LINK_HIGH = 0.85     # below this the practitioner confirms
CROSS_SHEET_MATCH = 0.60     # share of values matching another sheet's key
MERGE_OVERLAP = 0.80         # two columns with this much overlap → one field

_NEVER_PROPOSED = frozenset({"file", "offering_ref"})
PROPOSABLE_TYPES: Tuple[str, ...] = tuple(t for t in FIELD_TYPES if t not in _NEVER_PROPOSED)

# ─── Small detectors ─────────────────────────────────────────────────

_DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T].*)?$"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}([ ,].*)?$"),
    re.compile(r"^\d{1,2}-\d{1,2}-\d{2,4}$"),
    re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{2,4}$", re.I),
    re.compile(r"^\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{2,4}$", re.I),
]
_CURRENCY_RE = re.compile(r"^[-+]?\s?[$€£]\s?\d[\d,]*(\.\d{1,2})?$|^[-+]?\d[\d,]*\.\d{2}$")
_NUMBER_RE = re.compile(r"^[-+]?\d[\d,]*(\.\d+)?%?$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[+(]?[\d\s().-]{6,20}$")
_URL_RE = re.compile(r"^https?://", re.I)
_BOOL_VALUES = frozenset({"yes", "no", "true", "false", "y", "n", "x", "✓", "✔", "1", "0"})
_WORDY_RE = re.compile(r"^[A-Za-z][\w\s/&'().-]{0,40}$")
_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'.-]+(\s+[A-Z][a-zA-Z'.-]+){1,3}$")

_NAME_HEADERS = ("full name", "client name", "customer name", "contact name", "member name",
                 "patient name", "student name", "name", "client", "customer", "contact",
                 "member", "patient", "attendee", "person", "who")
_STAGE_HEADERS = ("stage", "status", "state", "phase", "step", "pipeline")
_EVENT_HEADERS = ("event", "service", "session", "class", "occasion", "meeting", "gathering", "workshop")
_LOCATION_HEADERS = ("address", "location", "site", "venue", "where", "job site")
_RATING_HEADERS = ("rating", "score", "stars", "rank")
_DONE_WORDS = ("done", "complete", "completed", "closed", "delivered", "paid", "won", "lost",
               "cancel", "cancelled", "canceled", "archived", "finished", "shipped")


def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip()


def _lower(v: Any) -> str:
    return _norm(v).lower()


def _is_date(v: str) -> bool:
    return any(p.match(v) for p in _DATE_PATTERNS)


def _is_currency(v: str) -> bool:
    return bool(_CURRENCY_RE.match(v.replace(" ", "")))


def _is_number(v: str) -> bool:
    return bool(_NUMBER_RE.match(v.replace(" ", "")))


def _is_email(v: str) -> bool:
    return bool(_EMAIL_RE.match(v))


def _is_phone(v: str) -> bool:
    digits = re.sub(r"\D", "", v)
    return bool(_PHONE_RE.match(v)) and 7 <= len(digits) <= 15 and not _is_date(v)


def _is_url(v: str) -> bool:
    return bool(_URL_RE.match(v))


def _share(values: Sequence[str], pred) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if pred(v)) / len(values)


def _header_has(header: str, words: Sequence[str]) -> bool:
    h = header.strip().lower()
    return any(h == w or w in h for w in words)


def slugify(name: str, fallback: str = "module") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")[:60]
    return s or fallback


def field_name(header: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_")[:40]
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    return s


def humanize(header: str) -> str:
    h = re.sub(r"[_\-]+", " ", (header or "").strip())
    h = re.sub(r"\s+", " ", h)
    return (h[:1].upper() + h[1:]) if h else "Field"


# ─── Column classification (§4.2) ────────────────────────────────────

def classify_column(header: str, raw_values: Sequence[Any]) -> Dict[str, Any]:
    """One column → {type, options?, note, empty, distinct, non_empty}.

    Evidence in the sampled values decides; the header only breaks ties
    (rating) — the spec's order, top to bottom."""
    values = [_norm(v)[:MAX_CELL_CHARS] for v in raw_values]
    non_empty = [v for v in values if v]
    out: Dict[str, Any] = {"empty": not non_empty, "non_empty": len(non_empty),
                           "distinct": len(set(non_empty)), "note": ""}
    if not non_empty:
        out.update(type="text", note="Empty in every sampled row.")
        return out

    counts = Counter(non_empty)
    distinct = list(counts.keys())
    lowers = [v.lower() for v in non_empty]

    # 1. select — a small closed set that repeats. The spec's "3+ repeats
    # each" is read over a 20-row SAMPLE: six options cannot each repeat
    # three times in twenty rows, so the test is that values repeat on
    # average (≤ half as many distinct values as rows), and every value
    # is a word, not a date or a number.
    # A column of PEOPLE repeating (the same four customers across twelve
    # jobs) is not a choice list, however few distinct names it holds.
    # "Sunday Service" and "Youth Night" are two capitalised words too —
    # an occasion column is never a people column, whatever its values.
    people_like = (_share(non_empty, lambda v: bool(_NAME_RE.match(v))) >= 0.6
                   and not _header_has(header, _EVENT_HEADERS))
    if (len(distinct) <= MAX_SELECT_OPTIONS and len(non_empty) >= 6
            and len(distinct) * 2 <= len(non_empty) and not people_like
            and all(_WORDY_RE.match(v) and not _is_date(v) and not _is_number(v) for v in distinct)):
        opts = [v for v, _ in counts.most_common()]
        out.update(type="select", options=opts,
                   note=f"{len(opts)} distinct values across {len(non_empty)} rows — treated as a choice list.")
        return out
    # 2. date
    if _share(non_empty, _is_date) >= 0.8:
        out.update(type="date", note="Reads as a date in most rows.")
        return out
    # 3. currency
    if _share(non_empty, _is_currency) >= 0.8 and not all(_is_number(v) and "." not in v for v in non_empty):
        out.update(type="currency", note="Money — a currency symbol or two decimals throughout.")
        return out
    # 4. phone
    if _share(non_empty, _is_phone) >= 0.8:
        out.update(type="phone", note="Phone-shaped throughout.")
        return out
    # 5. email
    if _share(non_empty, _is_email) >= 0.8:
        out.update(type="email", note="Email addresses.")
        return out
    # 6. url
    if _share(non_empty, _is_url) >= 0.8:
        out.update(type="url", note="Links.")
        return out
    # 7. rating — small integers AND a rating-ish header
    if (_header_has(header, _RATING_HEADERS)
            and all(v.isdigit() and 1 <= int(v) <= 5 for v in non_empty)):
        out.update(type="rating", note="Whole numbers 1–5 under a rating heading.")
        return out
    # 8. checkbox
    if all(v in _BOOL_VALUES for v in lowers) and len(set(lowers)) <= 2:
        out.update(type="checkbox", note="Yes/no throughout.")
        return out
    # 9. textarea
    if median(len(v) for v in non_empty) > 120:
        out.update(type="textarea", note="Long text — kept as notes.")
        return out
    # 10. number
    if _share(non_empty, _is_number) >= 0.9:
        out.update(type="number", note="Numbers.")
        return out
    # 11. text
    out.update(type="text", note="")
    return out


# ─── Sheet-level evidence ────────────────────────────────────────────

def _column_values(sheet: Dict[str, Any], idx: int) -> List[str]:
    return [_norm(r[idx]) if idx < len(r) else "" for r in sheet.get("sample_rows") or []]


def _looks_like_people(values: Sequence[str]) -> float:
    vals = [v for v in values if v]
    return _share(vals, lambda v: bool(_NAME_RE.match(v))) if vals else 0.0


def _contact_match_share(values: Sequence[str], contact_keys: set) -> float:
    vals = [v.lower() for v in values if v]
    if not vals or not contact_keys:
        return 0.0
    return sum(1 for v in vals if v in contact_keys) / len(vals)


def _contact_keys(contacts: Sequence[Dict[str, Any]]) -> set:
    keys = set()
    for c in contacts or []:
        for k in ("name", "email"):
            v = _lower(c.get(k))
            if v:
                keys.add(v)
    return keys


def _key_column(cols: List[Dict[str, Any]]) -> Optional[int]:
    """The column another sheet would reference: the title-ish text
    column — first text column, preferring name/title-like headers."""
    for c in cols:
        if c["type"] == "text" and _header_has(c["header"], ("title", "name", "subject", "job", "matter", "project")):
            return c["index"]
    for c in cols:
        if c["type"] == "text" and not c["empty"]:
            return c["index"]
    return None


# ─── The proposal ────────────────────────────────────────────────────

def _analyse_sheet(sheet: Dict[str, Any], contacts_keys: set) -> List[Dict[str, Any]]:
    headers = [_norm(h) for h in (sheet.get("headers") or [])]
    cols: List[Dict[str, Any]] = []
    for i, h in enumerate(headers):
        values = _column_values(sheet, i)
        c = classify_column(h, values)
        c.update(index=i, header=h or f"Column {i + 1}", values=values)
        # contact_link: their sheet is about people we already know.
        if c["type"] in ("text", "email") and not c["empty"]:
            share = _contact_match_share(values, contacts_keys)
            if share >= PEOPLE_MATCH:
                c.update(type="contact_link", contact_share=share,
                         note=f"{int(round(share * 100))}% of these match people already in your list — linked instead of copied.")
        c["name_like"] = (not _header_has(c["header"], _EVENT_HEADERS)
                          and (_header_has(c["header"], _NAME_HEADERS) or _looks_like_people(values) >= 0.6))
        cols.append(c)
    return cols


def _pick(cols, pred) -> Optional[Dict[str, Any]]:
    for c in cols:
        if pred(c):
            return c
    return None


def _sheet_verdict(sheet: Dict[str, Any], cols: List[Dict[str, Any]]) -> Tuple[str, str, str]:
    """→ (kind, archetype, reason). kind ∈ contacts|module|ignore."""
    rows = sheet.get("sample_rows") or []
    live = [c for c in cols if not c["empty"]]
    if len(rows) < 2 or not live:
        return "ignore", "", "Fewer than two rows with anything in them — nothing to build from."

    name_col = _pick(live, lambda c: c["name_like"] and c["type"] in ("text", "contact_link"))
    email_col = _pick(live, lambda c: c["type"] == "email")
    phone_col = _pick(live, lambda c: c["type"] == "phone")
    date_cols = [c for c in live if c["type"] == "date"]
    # A stage column has a stage-ish header, or is a small set that
    # actually varies — one value repeated is a label, not a pipeline.
    stage_col = (_pick(live, lambda c: c["type"] == "select" and _header_has(c["header"], _STAGE_HEADERS))
                 or _pick(live, lambda c: c["type"] == "select" and 2 <= len(c.get("options") or []) <= 8
                          and not _header_has(c["header"], _EVENT_HEADERS)))
    person_col = _pick(live, lambda c: c["type"] == "contact_link" or c["name_like"])

    # 1. people
    if name_col is not None and (email_col is not None or phone_col is not None):
        return ("contacts", "",
                "This looks like your people — one row each, with a way to reach them. "
                "They go into your contact list, not a separate table.")
    # 2. work
    if stage_col is not None and date_cols:
        return ("module", "work_pipeline",
                f"This looks like a pipeline — one row per piece of work, with a "
                f"“{stage_col['header']}” that moves and a date that matters.")
    # 3. roster — many rows share one occasion, one row per attendee.
    # Checked before the schedule rule because a sign-up sheet usually
    # carries the occasion's date too, and "one date + a person" would
    # otherwise claim it as appointments. The tell is the OCCASION column:
    # an event-ish header whose values each repeat.
    occ = _pick(live, lambda c: c["type"] == "select" and _header_has(c["header"], _EVENT_HEADERS)
                and c["distinct"] >= 2 and c["non_empty"] / max(1, c["distinct"]) >= 3)
    if occ is not None and person_col is not None:
        return ("module", "event_roster",
                f"This looks like sign-ups — several rows share one “{occ['header']}”, "
                f"one row per person attending.")
    # 4. scheduled
    if len(date_cols) == 1 and person_col is not None and stage_col is None:
        return ("module", "booking_calendar",
                f"This looks like a schedule — one row per appointment, with a "
                f"“{date_cols[0]['header']}” and who it is for.")
    # 5. fallback with the archetype that would have fit
    if date_cols and stage_col is None:
        why = "it would be a pipeline if it had a stage or status column"
    elif stage_col is not None:
        why = "it would be a pipeline if it had a date column"
    elif person_col is not None:
        why = "it would be a schedule if it had a date column"
    else:
        why = "no archetype fits a sheet with no dates, stages or people"
    return ("module", "fallback_generic",
            f"This looks like a plain list — {why}. It becomes a simple table you can sort and search.")


def _contacts_columns(cols: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Map a people-sheet onto the six contact fields. Everything else is
    dropped BY NAME."""
    taken: set = set()
    out: List[Dict[str, Any]] = []
    dropped: List[str] = []

    def claim(target: str, pred, note: str) -> None:
        c = _pick(cols, lambda c: c["index"] not in taken and not c["empty"] and pred(c))
        if c is None:
            return
        taken.add(c["index"])
        out.append({"header": c["header"], "decision": "map", "confidence": "high",
                    "field": {"name": target, "type": "text", "label": humanize(target)},
                    "note": note})

    claim("name", lambda c: c["name_like"] and c["type"] in ("text", "contact_link"), "Their name.")
    claim("email", lambda c: c["type"] == "email", "How to reach them.")
    claim("phone", lambda c: c["type"] == "phone", "How to reach them.")
    claim("status", lambda c: c["distinct"] <= MAX_SELECT_OPTIONS
          and _header_has(c["header"], _STAGE_HEADERS + ("type",)),
          "Kept as their status.")
    claim("tags", lambda c: _header_has(c["header"], ("tag", "label", "group", "category")), "Kept as tags.")
    claim("note", lambda c: c["type"] == "textarea" or _header_has(c["header"], ("note", "comment", "description")),
          "Kept on the record.")
    for c in cols:
        if c["index"] not in taken:
            dropped.append(c["header"])
            out.append({"header": c["header"], "decision": "drop", "confidence": "high",
                        "field": None,
                        "note": "Empty in every sampled row." if c["empty"]
                        else "Contacts keep name, email, phone, status, tags and a note — this column has no home there yet."})
    return out, dropped


def _stage_id(label: str, used: set) -> str:
    base = field_name(label, "stage") or "stage"
    s, n = base, 2
    while s in used:
        s, n = f"{base}_{n}", n + 1
    used.add(s)
    return s


def _module_columns(cols: List[Dict[str, Any]], archetype: str,
                    cross_refs: Dict[int, Tuple[str, float]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
    """→ (column decisions, schema fields, dropped names, folded names)."""
    decisions: List[Dict[str, Any]] = []
    fields: List[Dict[str, Any]] = []
    dropped: List[str] = []
    folded: List[str] = []
    used_names: set = set()

    # Rule 4 — two columns with overlapping values become one.
    merged_into: Dict[int, str] = {}
    live = [c for c in cols if not c["empty"] and c["type"] in ("select", "text")]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            av, bv = set(v for v in a["values"] if v), set(v for v in b["values"] if v)
            if not av or not bv or b["index"] in merged_into:
                continue
            overlap = len(av & bv) / min(len(av), len(bv))
            if overlap >= MERGE_OVERLAP:
                merged_into[b["index"]] = a["header"]

    kept = 0
    for c in cols:
        if c["empty"]:
            dropped.append(c["header"])
            decisions.append({"header": c["header"], "decision": "drop", "confidence": "high",
                              "field": None, "note": "Empty in every sampled row."})
            continue
        if c["index"] in merged_into:
            decisions.append({"header": c["header"], "decision": "drop", "confidence": "low",
                              "field": None,
                              "note": f"Same values as “{merged_into[c['index']]}” — kept as one field."})
            continue
        if kept >= MAX_FIELDS:
            folded.append(c["header"])
            continue
        ftype = c["type"]
        name = field_name(c["header"], f"field_{c['index'] + 1}")
        n, k = name, 2
        while n in used_names:
            n, k = f"{name}_{k}", k + 1
        name = n
        used_names.add(name)
        field: Dict[str, Any] = {"name": name, "type": ftype, "label": humanize(c["header"])}
        confidence = "high"
        note = c.get("note") or ""
        if ftype == "select":
            field["options"] = list(c.get("options") or [])
        elif ftype == "contact_link":
            confidence = "high" if c.get("contact_share", 0) >= CONTACT_LINK_HIGH else "low"
        if c["index"] in cross_refs and ftype in ("text", "contact_link"):
            slug, share = cross_refs[c["index"]]
            field = {"name": name, "type": "module_ref", "label": humanize(c["header"]), "module_slug": slug}
            confidence = "high" if share >= CONTACT_LINK_HIGH else "low"
            note = f"{int(round(share * 100))}% of these name rows in the “{slug}” sheet — linked."
        if ftype not in PROPOSABLE_TYPES and field["type"] not in PROPOSABLE_TYPES:
            field["type"] = "text"
        decision = "new_field"
        decisions.append({"header": c["header"], "decision": decision, "confidence": confidence,
                          "field": field, "note": note})
        fields.append(field)
        kept += 1

    if folded:
        fields.append({"name": "notes" if "notes" not in used_names else "extra_notes",
                       "type": "textarea", "label": "Notes",
                       "placeholder": "Folded columns: " + ", ".join(folded)})
        for h in folded:
            decisions.append({"header": h, "decision": "map", "confidence": "low",
                              "field": {"name": fields[-1]["name"], "type": "textarea", "label": "Notes"},
                              "note": f"Past {MAX_FIELDS} fields — folded into Notes, with its heading."})
    return decisions, fields, dropped, folded


def _archetype_params(archetype: str, cols: List[Dict[str, Any]], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_header = {c["header"]: c for c in cols}
    name_of = {}
    for c in cols:
        for f in fields:
            if f["label"] == humanize(c["header"]):
                name_of[c["index"]] = f["name"]
                break

    def first(pred) -> Optional[str]:
        c = _pick(cols, lambda c: not c["empty"] and c["index"] in name_of and pred(c))
        return name_of[c["index"]] if c else None

    if archetype == "work_pipeline":
        stage_c = (_pick(cols, lambda c: c["type"] == "select" and c["index"] in name_of
                         and _header_has(c["header"], _STAGE_HEADERS))
                   or _pick(cols, lambda c: c["type"] == "select" and c["index"] in name_of
                            and 2 <= len(c.get("options") or []) <= 8
                            and not _header_has(c["header"], _EVENT_HEADERS)))
        used: set = set()
        stages = []
        if stage_c:
            for label in stage_c.get("options") or []:
                sid = _stage_id(label, used)
                st = {"id": sid, "label": label}
                if any(w in label.lower() for w in _DONE_WORDS):
                    st["done"] = True
                stages.append(st)
        params: Dict[str, Any] = {
            "stage_field": name_of.get(stage_c["index"]) if stage_c else None,
            "title_field": first(lambda c: c["type"] == "text" and not c["name_like"]) or first(lambda c: c["type"] == "text"),
            "contact_field": first(lambda c: c["type"] == "contact_link") or first(lambda c: c["name_like"]),
            "date_field": first(lambda c: c["type"] == "date"),
            "value_field": first(lambda c: c["type"] == "currency"),
            "location_field": first(lambda c: _header_has(c["header"], _LOCATION_HEADERS)),
        }
        if stages:
            params["stages"] = stages
        return {k: v for k, v in params.items() if v}
    if archetype == "booking_calendar":
        return {k: v for k, v in {
            "primary_date_field": first(lambda c: c["type"] == "date"),
            "color_field": first(lambda c: c["type"] == "select"),
        }.items() if v}
    if archetype == "event_roster":
        return {k: v for k, v in {
            "title_field": first(lambda c: c["type"] == "select" and _header_has(c["header"], _EVENT_HEADERS)),
            "date_field": first(lambda c: c["type"] == "date"),
            "location_field": first(lambda c: _header_has(c["header"], _LOCATION_HEADERS)),
        }.items() if v}
    return {}


_ICONS = {"work_pipeline": "Briefcase", "booking_calendar": "CalendarDays",
          "event_roster": "Users", "agreement_ledger": "FileSignature",
          "progress_tracker": "TrendingUp", "fallback_generic": "Table"}


def _module_spec(sheet_name: str, archetype: str, fields: List[Dict[str, Any]],
                 params: Dict[str, Any], reason: str, slugs_used: set) -> Dict[str, Any]:
    base = re.sub(r"\.(csv|tsv|txt)$", "", sheet_name or "", flags=re.I).strip() or "Imported list"
    name = humanize(base)[:80]
    slug = slugify(name)
    s, n = slug, 2
    while s in slugs_used:
        s, n = f"{slug}-{n}", n + 1
    slugs_used.add(s)
    views: List[str] = ["list"]
    schema: Dict[str, Any] = {"fields": fields, "views": views, "default_view": "list"}
    if archetype == "work_pipeline" and params.get("stage_field"):
        views.insert(0, "board")
        schema["board_column"] = params["stage_field"]
        schema["default_view"] = "board"
    if archetype == "booking_calendar" and params.get("primary_date_field"):
        views.insert(0, "calendar")
        schema["calendar_field"] = params["primary_date_field"]
        schema["default_view"] = "calendar"
    spec = {
        "name": name, "slug": s,
        "description": f"Imported from “{sheet_name}”.",
        "icon": _ICONS.get(archetype, "Table"),
        "schema": schema,
        "archetype": archetype,
        "archetype_params": params,
        "archetype_fallback_reason": reason if archetype == "fallback_generic" else None,
    }
    return spec


def _neutralize(s: str) -> str:
    """Practitioner data: strip control characters and cap length before
    it is echoed back in a proposal. Kept local so the rubric has no
    prompt-layer dependency; the router applies _neutralize_untrusted on
    top for anything that reaches a model."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s or ""))[:MAX_CELL_CHARS]


def propose(sheets: Sequence[Dict[str, Any]], contacts: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """The §3.1 response body, minus proposal_id and credits (router adds).

    `sheets`: [{name, headers[], sample_rows[][], total_rows}], already
    capped by the caller. `contacts`: [{name, email}] for this business."""
    sheets = list(sheets)[:MAX_SHEETS]
    for sh in sheets:
        sh["headers"] = [_neutralize(h) for h in (sh.get("headers") or [])]
        sh["sample_rows"] = [[_neutralize(v) for v in (r or [])] for r in (sh.get("sample_rows") or [])[:MAX_SAMPLE_ROWS]]
    ckeys = _contact_keys(contacts)

    analysed = []
    for sh in sheets:
        cols = _analyse_sheet(sh, ckeys)
        kind, archetype, reason = _sheet_verdict(sh, cols)
        analysed.append({"sheet": sh, "cols": cols, "kind": kind, "archetype": archetype, "reason": reason})

    # Slugs first, so cross-sheet references can name their target.
    slugs_used: set = set()
    for a in analysed:
        if a["kind"] == "module":
            base = re.sub(r"\.(csv|tsv|txt)$", "", a["sheet"].get("name") or "", flags=re.I).strip() or "Imported list"
            slug = slugify(humanize(base))
            s, n = slug, 2
            while s in slugs_used:
                s, n = f"{slug}-{n}", n + 1
            slugs_used.add(s)
            a["slug"] = s

    # module_ref — only between sheets in THIS upload.
    for a in analysed:
        a["cross"] = {}
        if a["kind"] != "module":
            continue
        for b in analysed:
            if b is a or b["kind"] != "module":
                continue
            key_idx = _key_column(b["cols"])
            if key_idx is None:
                continue
            keys = set(v.lower() for v in b["cols"][key_idx]["values"] if v)
            if not keys:
                continue
            for c in a["cols"]:
                if c["empty"] or c["type"] not in ("text", "contact_link") or c["index"] == key_idx and b is a:
                    continue
                vals = [v.lower() for v in c["values"] if v]
                if not vals:
                    continue
                share = sum(1 for v in vals if v in keys) / len(vals)
                if share >= CROSS_SHEET_MATCH and c["index"] not in a["cross"]:
                    a["cross"][c["index"]] = (b["slug"], share)

    out_sheets: List[Dict[str, Any]] = []
    dropped_all: List[str] = []
    slugs_final: set = set()
    for a in analysed:
        sh, cols = a["sheet"], a["cols"]
        entry: Dict[str, Any] = {"sheet": sh.get("name") or "Sheet", "verdict": None,
                                 "reason": a["reason"], "target": None, "columns": [],
                                 "total_rows": int(sh.get("total_rows") or len(sh.get("sample_rows") or []))}
        if a["kind"] == "ignore":
            entry["verdict"] = "ignore"
            entry["columns"] = [{"header": c["header"], "decision": "drop", "confidence": "high",
                                 "field": None, "note": "Sheet ignored."} for c in cols]
            dropped_all.extend(f"{entry['sheet']}: {c['header']}" for c in cols)
        elif a["kind"] == "contacts":
            entry["verdict"] = "existing_surface"
            entry["target"] = {"kind": "contacts"}
            decisions, dropped = _contacts_columns(cols)
            entry["columns"] = decisions
            dropped_all.extend(f"{entry['sheet']}: {h}" for h in dropped)
        else:
            entry["verdict"] = "new_module"
            decisions, fields, dropped, folded = _module_columns(cols, a["archetype"], a["cross"])
            params = _archetype_params(a["archetype"], cols, fields)
            spec = _module_spec(sh.get("name") or "Imported list", a["archetype"], fields, params,
                                a["reason"], slugs_final)
            spec["slug"] = a["slug"]
            entry["target"] = {"kind": "module", "spec": spec}
            entry["columns"] = decisions
            entry["folded"] = folded
            dropped_all.extend(f"{entry['sheet']}: {h}" for h in dropped)
        out_sheets.append(entry)

    return {"sheets": out_sheets, "dropped": dropped_all}


# ─── Server-side re-validation (§3.2) ────────────────────────────────
# Twin of the frontend validateModuleSchema, over the same vocabulary. A
# proposal the practitioner edited is untrusted input.

_REQUIRES_OPTIONS = frozenset({"select"})
_REQUIRES_MODULE_SLUG = frozenset({"module_ref"})


def validate_module_schema(raw: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(raw, dict):
        return ["schema must be an object"]
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("schema.fields must be a non-empty array")
    else:
        names: set = set()
        for i, f in enumerate(fields):
            if not isinstance(f, dict):
                errors.append(f"field[{i}] must be an object")
                continue
            name = f.get("name")
            if not name or not isinstance(name, str):
                errors.append(f"field[{i}].name missing")
            if name in names:
                errors.append(f'field "{name}" is duplicated')
            names.add(name)
            if not f.get("label"):
                errors.append(f'field "{name}".label missing')
            ftype = f.get("type")
            if ftype not in FIELD_TYPES:
                errors.append(f'field "{name}".type invalid: {ftype}')
            elif ftype in _REQUIRES_OPTIONS and (not isinstance(f.get("options"), list) or not f["options"]):
                errors.append(f'field "{name}" is {ftype} but has no options')
            elif ftype in _REQUIRES_MODULE_SLUG and not str(f.get("module_slug") or "").strip():
                errors.append(f'field "{name}" is a linked record but names no module')
            if ftype in _NEVER_PROPOSED:
                errors.append(f'field "{name}" is {ftype}, which an import cannot fill')
    views = raw.get("views")
    if not isinstance(views, list) or not views:
        errors.append("schema.views must be a non-empty array")
        views = []
    by_name = {f.get("name"): f for f in fields if isinstance(f, dict)} if isinstance(fields, list) else {}
    if "calendar" in views:
        cf = raw.get("calendar_field")
        if not cf:
            errors.append("calendar view requires calendar_field")
        elif cf not in by_name:
            errors.append(f'calendar_field "{cf}" not found in fields')
        elif by_name[cf].get("type") != "date":
            errors.append(f'calendar_field "{cf}" must be a date field')
    if "board" in views:
        bc = raw.get("board_column")
        if not bc:
            errors.append("board view requires board_column")
        elif bc not in by_name:
            errors.append(f'board_column "{bc}" not found in fields')
        elif by_name[bc].get("type") != "select":
            errors.append(f'board_column "{bc}" must be a select field')
    return errors


# ─── Row → entry.data (the run step's pure half) ─────────────────────

def _coerce(ftype: str, raw: str, field: Dict[str, Any]) -> Any:
    v = _norm(raw)
    if v == "":
        return None
    if ftype == "number":
        try:
            return float(v.replace(",", "").rstrip("%"))
        except ValueError:
            return None
    if ftype == "currency":
        try:
            return float(re.sub(r"[^\d.\-]", "", v))
        except ValueError:
            return None
    if ftype == "checkbox":
        return v.lower() in ("yes", "true", "y", "x", "1", "✓", "✔")
    if ftype == "rating":
        try:
            n = int(float(v))
            return max(1, min(5, n))
        except ValueError:
            return None
    if ftype == "select":
        opts = field.get("options") or []
        for o in opts:
            if o.lower() == v.lower():
                return o
        return v  # kept verbatim; the run reports it as an unlisted value
    return v[:2000] if ftype == "textarea" else v[:500]


def rows_to_entries(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                    columns: Sequence[Dict[str, Any]], fields: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply the confirmed column decisions to full rows.

    → (entries: [{row, data}], problems: [{row, action, reason}]).
    A row with nothing mapped into it is skipped and SAID."""
    header_idx = {_norm(h): i for i, h in enumerate(headers)}
    by_name = {f["name"]: f for f in fields if isinstance(f, dict) and f.get("name")}
    plan = []
    for col in columns:
        if col.get("decision") not in ("map", "new_field") or not col.get("field"):
            continue
        idx = header_idx.get(_norm(col.get("header")))
        fname = col["field"].get("name")
        if idx is None or fname not in by_name:
            continue
        plan.append((idx, fname, by_name[fname]))
    entries, problems = [], []
    for r_i, row in enumerate(rows):
        data: Dict[str, Any] = {}
        for idx, fname, f in plan:
            raw = row[idx] if idx < len(row) else ""
            val = _coerce(f.get("type", "text"), raw, f)
            if f.get("type") == "textarea" and f.get("placeholder", "").startswith("Folded"):
                # Folded columns append, heading first, so nothing is lost.
                if _norm(raw):
                    data[fname] = (data.get(fname) + "\n" if data.get(fname) else "") + f"{headers[idx]}: {_norm(raw)}"
                continue
            if val is not None and val != "":
                data[fname] = val
        if not data:
            problems.append({"row": r_i, "action": "skipped", "reason": "nothing in this row maps to a field"})
            continue
        entries.append({"row": r_i, "data": data})
    return entries, problems
