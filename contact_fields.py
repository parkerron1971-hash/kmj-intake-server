"""
contact_fields.py — what a column in somebody's client list means.

ONE MAPPING, TWO DOORS
═══════════════════════════════════════════════════════════════════════
People enter the system through two importers: the Contacts room's
"Bring your clients over" dialog (contacts_import_router) and the
Structure Import's people-sheet verdict (structure_import /
structure_import_router). Both used to know six fields — name, email,
phone, status, tags, note — and both dropped everything else, which
meant a Square export lost every last name, birthday and address on the
way in. This module is the ONE place that knows:

  • the field vocabulary a column can be mapped to (FIELDS),
  • which export headers mean which field (guess_columns) — Square,
    Vagaro, Booksy, Mailchimp, Google Contacts, Outlook, Acuity,
    HoneyBook and plain spreadsheets,
  • how a confirmed mapping turns a table into import rows
    (rows_from_table), and what happens to each column (column_report),
  • how a column says somebody opted out (opt_out_reason),
  • the phone key both importers dedupe on (phone_key / phone_match_key).

Nothing here reads or writes the database, so every rule is unit-tested
row by row (__tests__/test_contact_import_fidelity.py).

NOTHING IS SILENTLY DROPPED
  A column either lands in a contacts column (name, email, phone,
  status, tags, role), in contacts.metadata under a named key
  (organization, birthday, address, first/last name), or — when it has
  no home of its own — in metadata.imported under its original header.
  The only columns left out are ones the practitioner leaves out, or
  ones that are empty in every row, and the preview names each one.

AN IMPORT CAN ONLY EVER TAKE PERMISSION AWAY
  opt_out_reason() answers one question: does this cell say the person
  must NOT be marketed to? It never answers "they said yes". A "Yes" in
  an "SMS Opt In" column grants nothing — a file somebody exported from
  another system is not consent to text from this one.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ─── The vocabulary ──────────────────────────────────────────────────
# `lands` is the plain-language fate the preview shows for the column.

FIELDS: Tuple[Dict[str, str], ...] = (
    {"id": "name",         "label": "Full name",           "lands": "Their name"},
    {"id": "first_name",   "label": "First name",          "lands": "Their first name"},
    {"id": "last_name",    "label": "Last name",           "lands": "Their last name"},
    {"id": "email",        "label": "Email",               "lands": "Their email"},
    {"id": "phone",        "label": "Phone",               "lands": "Their phone"},
    {"id": "status",       "label": "Status",              "lands": "Their status"},
    {"id": "tags",         "label": "Tags",                "lands": "Kept as tags"},
    {"id": "note",         "label": "Note",                "lands": "Kept as a note on their record"},
    {"id": "company",      "label": "Company",             "lands": "Their company"},
    {"id": "title",        "label": "Job title",           "lands": "Their role or title"},
    {"id": "birthday",     "label": "Birthday",            "lands": "Their birthday"},
    {"id": "address",      "label": "Street address",      "lands": "Part of their address"},
    {"id": "address2",     "label": "Address line 2",      "lands": "Part of their address"},
    {"id": "city",         "label": "City",                "lands": "Part of their address"},
    {"id": "region",       "label": "State or region",     "lands": "Part of their address"},
    {"id": "postal_code",  "label": "ZIP or postal code",  "lands": "Part of their address"},
    {"id": "country",      "label": "Country",             "lands": "Part of their address"},
    {"id": "email_optout", "label": "Email unsubscribe",   "lands": "Anyone it marks unsubscribed gets no marketing email"},
    {"id": "sms_optout",   "label": "Text opt-out",        "lands": "Anyone it marks opted out gets no texts"},
    {"id": "optout_all",   "label": "Do not contact",      "lands": "Anyone it marks gets no marketing email or texts"},
    {"id": "detail",       "label": "Keep as a detail",    "lands": "Kept on their record"},
    {"id": "skip",         "label": "Leave out",           "lands": "Left out"},
)
FIELD_IDS = frozenset(f["id"] for f in FIELDS)
LABELS = {f["id"]: f["label"] for f in FIELDS}
LANDS = {f["id"]: f["lands"] for f in FIELDS}

# A row needs one of these to become a person.
IDENTITY = ("name", "first_name", "last_name", "email", "phone")
# Fields a column can claim at most once in the auto-guess; a second
# column that wants the same field is kept as a detail instead.
MULTI = frozenset({"detail", "skip", "tags", "note", "email_optout", "sms_optout", "optout_all"})
ADDRESS_PARTS = ("address", "address2", "city", "region", "postal_code", "country")
OPTOUT_FIELDS = ("email_optout", "sms_optout", "optout_all")

MAX_COLUMNS = 120
MAX_DETAILS = 40
MAX_DETAIL_CHARS = 500


# ─── Header recognition ──────────────────────────────────────────────

def norm_header(h: Any) -> str:
    """'E-mail 1 - Value' → 'email 1 value'; 'UNSUB_TIME' → 'unsub time'."""
    s = str(h if h is not None else "").strip().lower()
    s = s.replace("e-mail", "email").replace("e mail", "email")
    s = re.sub(r"[_\-–—:/.,()#*]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Synonyms per field, BEST FIRST: when two columns want one field, the
# column whose header matches an earlier synonym wins (a Mobile Phone
# beats a Home Phone). Matching is exact first, then whole-word
# containment where the LONGEST matching synonym across every field
# wins — so "Email Subscription Status" is an unsubscribe column, not
# an email column, and "Company Name" is a company, not a name.
#
# Synonyms of one short word only match EXACTLY (see _CONTAIN_MIN):
# "Last" is a last name, "Last Visit" is not.
_SYN: Dict[str, Tuple[str, ...]] = {
    "name": ("name", "full name", "contact name", "client name", "customer name", "display name",
             "member name", "patient name", "student name", "guest name", "person", "client",
             "customer", "contact", "who"),
    "first_name": ("first name", "firstname", "first", "given name", "given", "fname", "forename",
                   "first name s", "client first name", "customer first name"),
    "last_name": ("last name", "lastname", "last", "surname", "family name", "lname",
                  "client last name", "customer last name"),
    "email": ("email", "email address", "email 1 value", "email address 1", "primary email",
              "email 1", "client email", "customer email", "contact email", "emailaddress", "mail",
              "personal email", "home email", "work email", "email 2 value", "email 2 address"),
    "phone": ("mobile phone", "mobile", "cell phone", "cell", "mobile number", "cell phone number",
              "mobile phone number", "sms phone", "phone number", "phone", "telephone", "tel",
              "primary phone", "phone 1 value", "client phone", "customer phone", "contact phone",
              "home phone", "work phone", "business phone", "phone 2 value", "other phone"),
    "status": ("status", "stage", "client status", "customer status", "contact status", "lead status",
               "lifecycle stage", "client type", "customer type"),
    "tags": ("tags", "tag", "labels", "label", "groups", "group", "group membership", "categories",
             "category", "segments", "segment", "lists", "customer groups"),
    "note": ("notes", "note", "comments", "comment", "memo", "description", "remarks",
             "client notes", "customer notes", "contact notes", "additional notes", "internal notes",
             "client note", "private notes", "alert notes"),
    "company": ("company", "company name", "organization", "organisation", "organization name",
                "organization 1 name", "business", "business name", "employer", "org"),
    "title": ("job title", "organization title", "organization 1 title", "position", "role",
              "occupation", "job"),
    "birthday": ("birthday", "birth date", "birthdate", "date of birth", "dob", "bday", "birth day"),
    "address": ("street address", "address", "street", "street address 1", "address 1",
                "address line 1", "address1", "home street", "home address", "mailing address",
                "address 1 street", "address 1 formatted", "street 1", "billing address",
                "business street", "shipping address"),
    "address2": ("address 2", "address line 2", "street address 2", "address2", "home street 2",
                 "street 2", "apt", "suite", "unit", "apartment"),
    "city": ("city", "town", "home city", "address 1 city", "locality", "business city", "suburb"),
    "region": ("state", "province", "state province", "state region", "state or province",
               "home state", "address 1 region", "business state", "county"),
    "postal_code": ("zip", "zip code", "zipcode", "postal code", "postcode", "post code",
                    "home postal code", "address 1 postal code", "business postal code"),
    "country": ("country", "country region", "home country region", "home country",
                "address 1 country", "business country region"),
    "email_optout": ("email subscription status", "email marketing status", "email marketing",
                     "accepts email marketing", "email opt in", "email optin", "email opt out",
                     "email optout", "email opted out", "email consent", "email status",
                     "email subscribed", "email unsubscribed", "subscribed to email",
                     "unsubscribed from email", "email permission", "marketing email",
                     "marketing emails", "newsletter", "accepts marketing", "marketing consent",
                     "marketing opt in", "marketing opt out", "subscription status",
                     "subscriber status", "subscribed", "unsubscribed", "unsubscribe", "unsub time",
                     "unsubscribed at", "unsubscribe date", "date unsubscribed", "clean time",
                     "cleaned at", "cleaned", "bounced", "email bounced", "hard bounce",
                     "do not email", "no email", "opted out", "opt out", "optout",
                     "email marketing consent", "marketing emails opt in"),
    "sms_optout": ("sms subscription status", "sms marketing status", "sms marketing",
                   "accepts sms marketing", "sms opt in", "sms optin", "sms opt out", "sms optout",
                   "sms consent", "sms status", "sms subscribed", "sms unsubscribed", "text opt in",
                   "text opt out", "text message opt in", "text messages", "text marketing",
                   "texting consent", "marketing sms", "do not text", "no text", "no sms",
                   "text reminders opt in", "sms marketing consent", "marketing text messages",
                   "text message marketing", "sms notifications", "mobile opt in"),
    "optout_all": ("do not contact", "dnc", "do not solicit", "no contact", "contact opt out",
                   "opted out of all", "do not market", "no marketing"),
    # Columns that LOOK like a field but are not. Longest-match lets
    # "Middle Name" beat "name" and "Emergency Contact Phone" beat
    # "phone" — they land as details under their own heading.
    "detail": ("middle name", "name prefix", "name suffix", "prefix", "suffix", "nickname",
               "phonetic first name", "phonetic middle name", "phonetic last name", "file as",
               "staff name", "service name", "provider name", "employee name", "pet name",
               "campaign name", "referral name", "referred by", "referral source",
               "emergency contact", "emergency contact name", "emergency contact phone",
               "emergency phone", "unsub reason", "unsub reason other", "unsub campaign title",
               "unsub campaign id", "clean campaign title", "clean campaign id", "gender",
               "pronouns", "anniversary", "website", "web page", "last visit", "first visit",
               "total spend", "total visits", "transaction count", "customer since",
               "days since last appointment", "reference id", "square customer id",
               "customer id", "client id", "member id", "creation source", "source",
               "email 2 label", "phone 2 label", "email display name", "email 2 display name",
               "email 3 display name", "department", "organization department", "spouse",
               "children", "hobby", "manager's name", "assistant's name"),
    # Mailchimp/Google system noise — IP addresses, geo-guesses, internal ids.
    "skip": ("optin time", "optin ip", "confirm time", "confirm ip", "latitude", "longitude",
             "gmtoff", "dstoff", "timezone", "cc", "last changed", "leid", "euid", "member rating",
             "photo", "instant profile", "priority", "sensitivity", "private"),
}

# Word-count below which a synonym must match exactly. One-word
# synonyms ("last", "state", "cell", "email") may also CONTAIN-match
# when they are in _CONTAIN_OK — a header like "Client Email (work)".
_CONTAIN_OK = frozenset({"email", "phone", "mobile", "birthday", "zip", "notes", "company",
                         "tags", "newsletter", "unsubscribed", "subscribed", "address", "city",
                         "country", "dob", "telephone", "organization", "organisation", "memo",
                         "surname", "province", "postcode"})

# Google/Outlook "Phone 1 - Type", "E-mail 2 - Label", "Address 1 - Type":
# these describe the column next to them.
_DESCRIBES_RE = re.compile(r"^(email|phone|address|website|relation|event|im|organization) ?\d* (type|label)$")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}/\d{1,2}/\d{2,4}$")
_PERSON_RE = re.compile(r"^[A-Z][a-zA-Z'.-]+(\s+[A-Z][a-zA-Z'.-]+){1,3}$")

_MAILCHIMP_STATUS = frozenset({"subscribed", "unsubscribed", "cleaned", "pending", "transactional",
                               "non subscribed", "nonsubscribed", "archived", "not subscribed"})


def _match(h: str) -> Optional[Tuple[str, int, int]]:
    """Best (field, kind, rank) for one normalized header. kind 0 =
    exact, 1 = contained; lower rank = earlier synonym."""
    if not h:
        return None
    if _DESCRIBES_RE.match(h):
        return ("skip", 0, 0)
    for f, syns in _SYN.items():
        if h in syns:
            return (f, 0, syns.index(h))
    best: Optional[Tuple[int, str, int]] = None   # (-len, field, rank)
    for f, syns in _SYN.items():
        for rank, s in enumerate(syns):
            if " " not in s and s not in _CONTAIN_OK:
                continue
            if re.search(rf"(^| ){re.escape(s)}( |$)", h):
                cand = (-len(s), f, rank)
                if best is None or cand < best:
                    best = cand
    if best is None:
        return None
    return (best[1], 1, best[2])


def _share(values: Sequence[str], pred) -> float:
    vals = [v for v in values if v]
    return (sum(1 for v in vals if pred(v)) / len(vals)) if vals else 0.0


def _is_phone(v: str) -> bool:
    digits = re.sub(r"\D", "", v)
    return (bool(re.match(r"^[+(]?[\d\s().-]{6,22}$", v)) and 7 <= len(digits) <= 15
            and not _DATE_RE.match(v))


def guess_columns(headers: Sequence[Any], sample_rows: Sequence[Sequence[Any]] = ()) -> List[Dict[str, Any]]:
    """headers (+ a sample of rows) → one decision per column:
    {index, header, field, label, note}. The header is read first; the
    VALUES settle what the header cannot (an unlabelled email column, a
    "Status" column that is really Mailchimp's subscription state)."""
    hs = [str(h if h is not None else "").strip() for h in headers]
    samples = [[_cell(r, i) for r in (sample_rows or [])] for i in range(len(hs))]
    have_samples = any(any(v for v in col) for col in samples)

    picks: List[Optional[Tuple[str, int, int]]] = []
    for i, h in enumerate(hs):
        m = _match(norm_header(h))
        vals = samples[i]
        # Mailchimp's "Status" column holds subscription state, not a stage.
        if m and m[0] == "status" and vals and all(norm_header(v) in _MAILCHIMP_STATUS for v in vals if v) \
                and any(v for v in vals):
            m = ("email_optout", 0, 0)
        picks.append(m)

    out: List[Dict[str, Any]] = [
        {"index": i, "header": hs[i] or f"Column {i + 1}", "field": "detail", "note": ""}
        for i in range(len(hs))
    ]
    # Empty columns — every sampled value blank — are left out, by name.
    empty = {i for i in range(len(hs)) if have_samples and not any(samples[i])}

    # Single-claim fields: the best-scoring column wins, the rest are details.
    claimed: Dict[str, int] = {}
    order = sorted((i for i in range(len(hs)) if picks[i] and i not in empty),
                   key=lambda i: (picks[i][1], picks[i][2], i))
    for i in order:
        field = picks[i][0]
        if field in MULTI:
            out[i]["field"] = field
            continue
        if field in claimed:
            out[i]["note"] = f"Another column is already their {LABELS[field].lower()} — kept as a detail."
            continue
        claimed[field] = i
        out[i]["field"] = field

    # A full name column and first/last columns can all stay mapped: the
    # full name is used, and first + last fill in any row where it is blank.

    # Value shapes fill the gaps a header left.
    def unclaimed_detail(pred) -> Optional[int]:
        for c in out:
            i = c["index"]
            if c["field"] == "detail" and picks[i] is None and i not in empty \
                    and _share(samples[i], pred) >= 0.8:
                return i
        return None
    if "email" not in claimed and have_samples:
        i = unclaimed_detail(lambda v: bool(_EMAIL_RE.match(v)))
        if i is not None:
            out[i].update(field="email", note="Reads as email addresses.")
            claimed["email"] = i
    if "phone" not in claimed and have_samples:
        i = unclaimed_detail(_is_phone)
        if i is not None:
            out[i].update(field="phone", note="Reads as phone numbers.")
            claimed["phone"] = i
    if not any(f in claimed for f in ("name", "first_name", "last_name")) and have_samples:
        i = unclaimed_detail(lambda v: bool(_PERSON_RE.match(v)))
        if i is not None:
            out[i].update(field="name", note="Reads as people's names.")

    for i in empty:
        out[i].update(field="skip", note="Empty in every row we looked at.")
    for c in out:
        if c["field"] == "skip" and not c["note"]:
            c["note"] = ("Describes the column next to it." if _DESCRIBES_RE.match(norm_header(c["header"]))
                         else "System data from the old tool.")
        if c["field"] in OPTOUT_FIELDS and not c["note"]:
            c["note"] = "Unsubscribes carry over. A yes here never signs anyone up."
        c["label"] = LABELS[c["field"]]
    return out


# ─── Opt-outs ────────────────────────────────────────────────────────

def _nv(v: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_\-]+", " ", str(v if v is not None else "").strip().lower())).strip()


_NEGATIVE = {
    "unsubscribed": "unsubscribed", "unsubscribe": "unsubscribed", "unsub": "unsubscribed",
    "opted out": "opted out", "opt out": "opted out", "optout": "opted out",
    "cleaned": "cleaned (the address bounced)", "clean": "cleaned (the address bounced)",
    "bounced": "bounced", "bounce": "bounced", "hard bounce": "bounced", "hardbounce": "bounced",
    "invalid": "bounced", "undeliverable": "bounced",
    "complained": "marked it as spam", "complaint": "marked it as spam", "spam": "marked it as spam",
    "spam report": "marked it as spam",
    "do not email": "asked not to be contacted", "do not contact": "asked not to be contacted",
    "do not text": "asked not to be contacted", "dnc": "asked not to be contacted",
    "blocked": "asked not to be contacted", "stop": "texted STOP", "stopped": "texted STOP",
    "revoked": "withdrew permission", "withdrawn": "withdrew permission",
    "suppressed": "on a do-not-send list",
    "non subscribed": "never agreed to marketing", "nonsubscribed": "never agreed to marketing",
    "not subscribed": "never agreed to marketing", "never subscribed": "never agreed to marketing",
    "declined": "never agreed to marketing", "denied": "never agreed to marketing",
    "no consent": "never agreed to marketing", "pending": "never confirmed their sign-up",
}
_STRONG = ("not subscribed", "non subscribed", "never subscribed", "do not contact", "do not email",
           "do not text", "unsubscribed", "opted out", "cleaned", "bounced", "hard bounce",
           "complained", "spam")
_YES = frozenset({"yes", "y", "true", "t", "1", "x", "checked", "on", "✓", "✔"})
_NO = frozenset({"no", "n", "false", "f", "0", "unchecked", "off"})
# Header shapes.
_PRESENCE_RE = re.compile(r"(unsub|clean|bounce|opt ?out|opted out)\w*( \w+)* (time|date|at|on|timestamp)$"
                          r"|^date (unsubscribed|opted out|cleaned|bounced)")
_OUT_Q_RE = re.compile(r"unsub|opt ?out|opted out|do not|\bdnc\b|bounce|clean|\bno (email|sms|text|contact|marketing)|suppress|blocked")
_VALUE_DATE_RE = re.compile(r"^\d{4} \d{1,2} \d{1,2}|^\d{1,2}/\d{1,2}/\d{2,4}")
_IN_Q_RE = re.compile(r"opt ?in|accepts|consent|permission|subscribed|newsletter|marketing|agree")


def opt_out_reason(header: Any, value: Any) -> str:
    """'' when the cell says nothing against contacting them; otherwise
    a short plain reason. NEVER returns anything that means 'yes' — an
    import only ever takes permission away."""
    v = _nv(value)
    if not v or v in ("unknown", "n a", "na", "none", "null", "subscribed", "transactional"):
        return ""
    h = norm_header(header)
    if v in _NEGATIVE:
        return _NEGATIVE[v]
    # "Unsubscribed (2024-03-01)", "cleaned - hard bounce"
    for word in _STRONG:
        if re.search(rf"(^| ){re.escape(word)}( |$)", v):
            return _NEGATIVE[word]
    if _PRESENCE_RE.search(h):
        # UNSUB_TIME / CLEAN_TIME: any timestamp means it happened.
        if v in _NO:
            return ""
        if "clean" in h:
            return "cleaned (the address bounced)"
        if "bounce" in h:
            return "bounced"
        return "unsubscribed"
    if _OUT_Q_RE.search(h):
        # "Unsubscribed: Yes", "Do Not Email: TRUE", "Unsubscribed: 3/1/2024"
        if v in _YES or _VALUE_DATE_RE.match(v):
            return "opted out"
        return ""
    if _IN_Q_RE.search(h):
        # "Accepts Email Marketing: no", "SMS Opt In: FALSE" — they did
        # not agree, so they are not marketed to. "yes" grants nothing.
        return "did not agree to marketing" if v in _NO else ""
    return ""


# ─── Phones ──────────────────────────────────────────────────────────

_EXT_RE = re.compile(r"\s*(ext\.?|extension|x|#)\s*\d+\s*$", re.I)


def phone_key(raw: Any) -> str:
    """E.164 for anything sms_service.normalize_phone can read, after
    the formatting normalize_phone itself does not strip: '+1 (555)
    010-2233', 'tel:+15550102233', '555.010.2233 ext 4'. '' otherwise."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return ""
    s = re.sub(r"^tel:", "", s, flags=re.I)
    s = _EXT_RE.sub("", s)
    digits = re.sub(r"\D", "", s)
    if s.lstrip().startswith("+"):
        return f"+{digits}" if 8 <= len(digits) + 1 <= 16 else ""
    if s.startswith("00") and 9 <= len(digits) - 2 <= 15:
        return f"+{digits[2:]}"
    try:
        from sms_service import normalize_phone
        return normalize_phone(digits) or ""
    except Exception:
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return ""


def phone_match_key(raw: Any) -> str:
    """What two phones must share to be the same person: the E.164 form
    when there is one, else the bare digits (7+), so a number kept as
    written still dedupes against itself on a re-import."""
    k = phone_key(raw)
    if k:
        return k
    digits = re.sub(r"\D", "", _EXT_RE.sub("", str(raw or "")))
    return f"#{digits}" if len(digits) >= 7 else ""


# ─── Table → import rows ─────────────────────────────────────────────

def _cell(row: Sequence[Any], i: int) -> str:
    if not isinstance(row, (list, tuple)) or i >= len(row) or row[i] is None:
        return ""
    v = str(row[i]).strip()
    # Outlook writes 0/0/00 into every empty date column.
    return "" if _OUTLOOK_EMPTY_DATE.match(v) else v


_OUTLOOK_EMPTY_DATE = re.compile(r"^0{1,2}/0{1,2}/0{2,4}$")
_MULTI_SPLIT = re.compile(r"\s*:::\s*|\s*;\s*")
_STATUS_WORDS = {
    "active": "active", "client": "active", "customer": "active", "current": "active",
    "member": "active", "regular": "active", "booked": "active",
    "lead": "lead", "prospect": "lead", "inquiry": "lead", "enquiry": "lead", "new": "lead",
    "vip": "vip", "inactive": "inactive", "past": "inactive", "former": "inactive",
    "lapsed": "inactive", "archived": "inactive", "paused": "inactive",
    "churned": "churned", "lost": "churned", "cancelled": "churned", "canceled": "churned",
}
_TAG_NOISE = frozenset({"mycontacts", "my contacts", "starred", "* mycontacts", "* starred"})


def normalize_status(v: str) -> str:
    return _STATUS_WORDS.get(_nv(v), _nv(v))


def validate_fields(headers: Sequence[Any], fields: Sequence[str]) -> str:
    """'' when the mapping is usable, else the plain reason it is not."""
    if len(fields) != len(headers):
        return "every column needs a choice — the mapping and the header row differ in length"
    if len(headers) > MAX_COLUMNS:
        return f"{len(headers)} columns is over the {MAX_COLUMNS}-column limit"
    bad = [f for f in fields if f not in FIELD_IDS]
    if bad:
        return f"unknown field {bad[0]!r}"
    if not any(f in IDENTITY for f in fields):
        return "pick at least one column for their name, email or phone"
    return ""


def rows_from_table(headers: Sequence[Any], rows: Sequence[Sequence[Any]],
                    fields: Sequence[str]) -> List[Dict[str, Any]]:
    """A confirmed mapping over a table → one dict per row, shaped like
    contacts_import_router.ImportRow. Unknown field ids are kept as
    details — a mapping handed back by a browser is untrusted, and the
    safe reading of a field we do not know is 'keep it', never 'drop it'."""
    hs = [str(h if h is not None else "").strip() or f"Column {i + 1}" for i, h in enumerate(headers)]
    fs = [f if f in FIELD_IDS else "detail" for f in fields]
    out: List[Dict[str, Any]] = []
    for r in rows:
        got: Dict[str, List[Tuple[str, str]]] = {}
        for i, f in enumerate(fs):
            if f == "skip":
                continue
            v = _cell(r, i)
            if v:
                got.setdefault(f, []).append((hs[i], v))
        out.append(_build_row(got))
    return out


def _first(got: Dict[str, List[Tuple[str, str]]], f: str,
           details: Dict[str, str]) -> str:
    """The first value mapped to a single field; any further columns
    mapped to the same field are kept as details, never lost."""
    vals = got.get(f) or []
    if not vals:
        return ""
    for h, v in vals[1:]:
        if v != vals[0][1]:
            details.setdefault(h, v)
    return vals[0][1]


def _build_row(got: Dict[str, List[Tuple[str, str]]]) -> Dict[str, Any]:
    details: Dict[str, str] = {}

    name = _first(got, "name", details)
    first = _first(got, "first_name", details)
    last = _first(got, "last_name", details)
    if not name:
        name = " ".join(x for x in (first, last) if x)

    email_all = [e for e in _MULTI_SPLIT.split(_first(got, "email", details)) if e]
    email = email_all[0] if email_all else ""
    if len(email_all) > 1:
        details["Other email"] = ", ".join(email_all[1:])

    phone_all = [p for p in _MULTI_SPLIT.split(_first(got, "phone", details)) if p]
    phone = phone_all[0] if phone_all else ""
    if len(phone_all) > 1:
        details["Other phone"] = ", ".join(phone_all[1:])

    tags: List[str] = []
    for _, v in got.get("tags") or []:
        for t in re.split(r"\s*(?::::|[;|,])\s*", v):
            t = t.strip().lstrip("*").strip()
            if t and t.lower() not in _TAG_NOISE and t not in tags:
                tags.append(t)

    notes = got.get("note") or []
    note = (notes[0][1] if len(notes) == 1
            else "\n".join(f"{h}: {v}" for h, v in notes))

    parts = {p: _first(got, p, details) for p in ADDRESS_PARTS}
    region_zip = " ".join(x for x in (parts["region"], parts["postal_code"]) if x)
    address = ", ".join(x for x in (parts["address"], parts["address2"], parts["city"],
                                    region_zip, parts["country"]) if x)

    for h, v in got.get("detail") or []:
        details.setdefault(h, v)

    email_out, sms_out = "", ""
    for f in OPTOUT_FIELDS:
        for h, v in got.get(f) or []:
            why = opt_out_reason(h, v)
            if not why:
                # "Subscribed" / "Yes" is deliberately NOT carried, not
                # even as a detail: a record that reads like consent is
                # one step from being treated as consent.
                continue
            if f in ("email_optout", "optout_all") and not email_out:
                email_out = why
            if f in ("sms_optout", "optout_all") and not sms_out:
                sms_out = why

    capped = {str(k)[:80]: str(v)[:MAX_DETAIL_CHARS] for k, v in list(details.items())[:MAX_DETAILS]}
    return {
        "name": name, "first_name": first, "last_name": last,
        "email": email, "phone": phone,
        "status": normalize_status(_first(got, "status", details)) if got.get("status") else "",
        "tags": tags[:20], "note": note,
        "company": _first(got, "company", details), "title": _first(got, "title", details),
        "birthday": _first(got, "birthday", details), "address": address,
        "details": capped,
        "email_opt_out": email_out, "sms_opt_out": sms_out,
    }


def column_report(headers: Sequence[Any], rows: Sequence[Sequence[Any]],
                  fields: Sequence[str]) -> List[Dict[str, Any]]:
    """What happens to each column, in the practitioner's words — the
    dry-run preview's per-column line."""
    out: List[Dict[str, Any]] = []
    for i, h in enumerate(headers):
        header = str(h if h is not None else "").strip() or f"Column {i + 1}"
        f = fields[i] if i < len(fields) and fields[i] in FIELD_IDS else "detail"
        filled = sum(1 for r in rows if _cell(r, i))
        line = LANDS[f]
        count = None
        if f in OPTOUT_FIELDS:
            count = sum(1 for r in rows if opt_out_reason(header, _cell(r, i)))
            what = {"email_optout": "will get no marketing email",
                    "sms_optout": "will get no texts",
                    "optout_all": "will get no marketing email or texts"}[f]
            line = (f"{count} {'person' if count == 1 else 'people'} {what}"
                    if count else "Nobody in this column opted out")
        elif f == "detail":
            line = f"Kept on their record as “{header}”"
        elif f == "skip":
            line = "Left out" if filled else "Left out (empty)"
        out.append({"index": i, "header": header, "field": f, "label": LABELS[f],
                    "lands": line, "filled": filled, "opted_out": count})
    return out
