"""subsplash_import.py — a church's people and giving history, off Subsplash.

D3 of docs/plans/SUBSPLASH_EXIT_PLAN_2026-10-14.md. Reads Subsplash's two
CSV exports:

  People → All people → Export                    people-export.csv
  Giving → Gifts → (pick the year) → Export       gifts-YYYY-MM-DD.csv

Planning is pure (plan_people, plan_gifts); one writer (write_plan) talks
to the database. A dry run prints every count before anything is
written, and a second run writes nothing new.

PEOPLE: no duplicates (Kevin, 2026-10-14: "Don't copy duplicates from the
membership list"). Subsplash keeps a new person for every form a visitor
fills in, so one name can appear 20 times. Rows are one person when:
  * they have the same name and the same email or phone, or
  * they have the same name and their birthdays don't disagree
    (a parent and child can share a name; a new email is not a new person).
Different names never merge, even sharing an email or phone. Families do
that, and they are different people. A shared email or phone stays on ONE
record (an adult, a giver first), because the member page signs in by
email or phone and a value on two records signs nobody in. The other
records keep it in metadata. People already in the workspace (by Subsplash
person id, email, phone or name) are matched, never added twice.

STATUS: Subsplash's Member → active ("Member" in a church's app). Visitor,
and a blank status, → lead ("Visitor"), with first_response_at set so an
imported visitor never sits in the "nobody has replied" alerts. A blank
status on someone who gave this year → active.

GIFTS: written straight to invoices (is_gift), the shape the manual-gift
path writes. Not record_gift(), which emails a receipt and stamps today's
date on the giver. Failed gifts are skipped. Cash, check and app gifts
(PayPal, Zelle, Cash App) are manual gifts the church can correct in the
app. Card and bank gifts went through Subsplash and were paid out to the
church's bank. Gifts that aren't tax-deductible (Subsplash's "Other (Non
tax deductible)" and donor-advised funds) are kept in the books with no
giver attached, so they never print on a tax statement.

Run (service role, production):
  railway run python subsplash_import.py --business <id> \\
      --people people-export.csv --gifts gifts-2026.csv            # dry run
  ... --write                                                      # write
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

SOURCE = "subsplash_import"
TAG = "From Subsplash"
CHILD_TAG = "child"
_ANONYMOUS_NAMES = {"loose cash", "anonymous", "anonymous giver", "cash", "loose offering"}
_NON_DEDUCTIBLE = {"other (non tax deductible)", "donor-advised fund"}
_CARD = {"visa", "mastercard", "master card", "discover", "american express", "amex", "card"}
_UUID_NS = uuid.UUID("6b1d2a1e-4c1f-4b55-9f0e-5ab5a5c10e01")


# ─── small normalizers ───────────────────────────────────────────────

def _s(v: Any) -> str:
    return str(v if v is not None else "").strip()


def norm_email(v: Any) -> str:
    e = _s(v).lower()
    return e if "@" in e and "." in e.split("@")[-1] else ""


def phone_match(v: Any) -> str:
    import contact_fields
    return contact_fields.phone_match_key(v) if _s(v) else ""


def norm_name(first: Any, last: Any) -> str:
    return " ".join(f"{_s(first)} {_s(last)}".lower().split())


def _birthdate(v: Any) -> Optional[str]:
    raw = _s(v)[:10]
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    return d.isoformat() if date(1900, 1, 2) <= d <= date.today() else None


def _money(v: Any) -> float:
    try:
        return round(float(re.sub(r"[^0-9.\-]", "", _s(v)) or 0), 2)
    except ValueError:
        return 0.0


def read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "") for k, v in r.items()} for r in csv.DictReader(f)]


# ─── people ──────────────────────────────────────────────────────────

def group_people(rows: List[Dict[str, str]]) -> List[List[int]]:
    """Indexes of rows that are one person (see module docstring)."""
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    names = [norm_name(r.get("first_name"), r.get("last_name")) for r in rows]
    by_name: Dict[str, List[int]] = defaultdict(list)
    for i, n in enumerate(names):
        if n:
            by_name[n].append(i)
    for idx in by_name.values():
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                da = _birthdate(rows[idx[a]].get("date_of_birth"))
                db = _birthdate(rows[idx[b]].get("date_of_birth"))
                if da and db and da != db:
                    continue
                union(idx[a], idx[b])
    out: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(rows)):
        out[find(i)].append(i)
    return list(out.values())


def _filled(r: Dict[str, str]) -> int:
    keys = ("email", "phone", "date_of_birth", "street", "city", "postal_code", "gender",
            "membership_status")
    return sum(1 for k in keys if _s(r.get(k)))


def _merge(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """One person from their rows: the fullest row first, gaps filled from
    the others, extra emails and phones kept."""
    rows = sorted(rows, key=_filled, reverse=True)
    p: Dict[str, Any] = {k: "" for k in rows[0]}
    for r in rows:
        for k, v in r.items():
            if not _s(p.get(k)) and _s(v):
                p[k] = _s(v)
    emails, phones = [], []
    for r in rows:
        e, ph = norm_email(r.get("email")), _s(r.get("phone"))
        if e and e not in emails:
            emails.append(e)
        if ph and phone_match(ph) not in [phone_match(x) for x in phones]:
            phones.append(ph)
    statuses = {_s(r.get("membership_status")).lower() for r in rows}
    p["membership_status"] = ("member" if "member" in statuses
                              else "visitor" if "visitor" in statuses else "")
    p["_emails"] = emails
    p["_phones"] = phones
    p["_person_ids"] = [_s(r.get("person_id")) for r in rows if _s(r.get("person_id"))]
    p["_rows"] = len(rows)
    p["_child"] = any(_s(r.get("household_role")).lower() == "child" for r in rows)
    return p


def _address(p: Dict[str, Any]) -> str:
    street = ", ".join(x for x in (_s(p.get("street")), _s(p.get("street_2"))) if x)
    st_zip = " ".join(x for x in (_s(p.get("state")), _s(p.get("postal_code"))) if x)
    return ", ".join(x for x in (street, _s(p.get("city")), st_zip) if x)


def plan_people(rows: List[Dict[str, str]], *, givers: Iterable[str] = (),
                existing: Iterable[Dict[str, Any]] = (),
                now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Contact rows to insert, the people already there, and the counts.
    `givers` are emails and names (norm_name) seen in the gifts export."""
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    giver_keys = {g for g in givers if g}
    people = [_merge([rows[i] for i in g]) for g in group_people(rows)]

    # One holder per shared email/phone: an adult before a child, a giver
    # before a non-giver, a member before a visitor.
    def rank(p: Dict[str, Any]) -> Tuple[int, int, int, int]:
        # A shared email names a household, not a giver; the giver's own
        # name is the stronger sign of whose address it is.
        named = norm_name(p["first_name"], p["last_name"]) in giver_keys
        mailed = bool(set(p["_emails"]) & giver_keys)
        return (0 if not p["_child"] else 1, 0 if named else 1, 0 if mailed else 1,
                0 if p["membership_status"] == "member" else 1)

    holders: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for i, p in enumerate(people):
        if p["_emails"]:
            holders[("e", p["_emails"][0])].append(i)
        if p["_phones"]:
            holders[("p", phone_match(p["_phones"][0]))].append(i)
    shared_away: Dict[int, Dict[str, str]] = defaultdict(dict)
    for (kind, value), idx in holders.items():
        if len(idx) < 2:
            continue
        keep = min(idx, key=lambda i: rank(people[i]))
        for i in idx:
            if i != keep:
                shared_away[i]["email" if kind == "e" else "phone"] = (
                    people[i]["_emails"][0] if kind == "e" else people[i]["_phones"][0])

    # Who is already in the workspace.
    by_pid: Dict[str, str] = {}
    by_email: Dict[str, str] = {}
    by_phone: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    known: Dict[str, Dict[str, Any]] = {}
    for c in existing or []:
        cid = str(c.get("id"))
        known[cid] = c
        md = c.get("metadata") or {}
        for pid in ((md.get("imported") or {}).get("Subsplash person IDs") or []):
            by_pid[str(pid)] = cid
        if norm_email(c.get("email")):
            by_email.setdefault(norm_email(c.get("email")), cid)
        if phone_match(c.get("phone")):
            by_phone.setdefault(phone_match(c.get("phone")), cid)
        if _s(c.get("name")):
            by_name.setdefault(" ".join(_s(c.get("name")).lower().split()), cid)

    inserts: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    matched: List[Tuple[Dict[str, Any], str]] = []
    claimed: set = set()
    statuses: Counter = Counter()
    for i, p in enumerate(people):
        name_key = norm_name(p["first_name"], p["last_name"])
        email = "" if "email" in shared_away[i] else (p["_emails"][0] if p["_emails"] else "")
        phone_raw = "" if "phone" in shared_away[i] else (p["_phones"][0] if p["_phones"] else "")
        hit = (next((by_pid[x] for x in p["_person_ids"] if x in by_pid), None)
               or (by_email.get(email) if email else None)
               or (by_phone.get(phone_match(phone_raw)) if phone_raw else None)
               or by_name.get(name_key))
        if hit in claimed:
            # Someone earlier in this file already matched that contact
            # (a parent and child with one name): this one is new.
            hit = None
        gave = (bool(set(p["_emails"]) & giver_keys) or name_key in giver_keys)
        ms = p["membership_status"]
        status = "active" if ms == "member" or (not ms and gave) else "lead"
        imported: Dict[str, Any] = {"Subsplash person IDs": p["_person_ids"],
                                    "Membership status": ms or "(none)"}
        for label, key in (("Gender", "gender"), ("Household role", "household_role"),
                           ("Household ID", "household_id"), ("Marital status", "marital_status"),
                           ("Baptism date", "baptism_date"), ("Grade", "grade_level")):
            if _s(p.get(key)):
                imported[label] = _s(p.get(key))
        if "email" in shared_away[i]:
            imported["Email (shared)"] = shared_away[i]["email"]
        if "phone" in shared_away[i]:
            imported["Phone (shared)"] = shared_away[i]["phone"]
        if len(p["_emails"]) > 1:
            imported["Other emails"] = p["_emails"][1:]
        if len(p["_phones"]) > 1:
            imported["Other phones"] = p["_phones"][1:]
        if p["_rows"] > 1:
            imported["Merged Subsplash records"] = p["_rows"]
        metadata: Dict[str, Any] = {"imported_at": now_iso, "imported_from": "Subsplash",
                                    "imported": imported}
        if _s(p.get("first_name")) and _s(p.get("last_name")):
            metadata["first_name"] = _s(p["first_name"])
            metadata["last_name"] = _s(p["last_name"])
        addr = _address(p)
        if addr:
            metadata["address"] = addr
        import contact_fields
        phone = contact_fields.phone_key(phone_raw) if phone_raw else ""
        if phone_raw and not phone and len(re.sub(r"\D", "", phone_raw)) >= 7:
            phone = phone_raw
        name = " ".join(f"{_s(p.get('first_name'))} {_s(p.get('last_name'))}".split())[:200] or "Unknown"
        row: Dict[str, Any] = {
            "name": name, "email": email or None, "phone": phone or None,
            "status": status, "source": SOURCE, "source_detail": "Subsplash people export",
            "tags": [TAG] + ([CHILD_TAG] if p["_child"] else []),
            "metadata": metadata, "created_at": now_iso,
        }
        bd = _birthdate(p.get("date_of_birth"))
        if bd:
            row["birthdate"] = bd
        if status == "lead":
            # Imported, not waiting: keeps them out of "nobody has replied".
            row["first_response_at"] = now_iso
        if hit:
            claimed.add(hit)
            matched.append((p, hit))
            have = known.get(hit) or {}
            if _from_gifts_export(have):
                # A giver this importer added from the gifts export (a run
                # where the people didn't land first): fill them in now.
                fields = {k: v for k, v in row.items() if k not in ("created_at", "source")}
                old_imp = ((have.get("metadata") or {}).get("imported") or {})
                if old_imp.get("Other emails"):
                    extra = [e for e in old_imp["Other emails"] if e != fields.get("email")]
                    imp = fields["metadata"]["imported"]
                    imp["Other emails"] = sorted(set(imp.get("Other emails") or []) | set(extra))
                updates.append({"id": hit, "fields": fields})
            continue
        statuses[status] += 1
        inserts.append(row)
    for u in updates:
        statuses[u["fields"]["status"] + "_filled_in"] += 1
    return {
        "inserts": inserts, "matched": matched, "updates": updates,
        "counts": {"rows": len(rows), "people": len(people),
                   "duplicate_rows_dropped": len(rows) - len(people),
                   "already_in_workspace": len(matched), "to_add": len(inserts),
                   "givers_filled_in": len(updates),
                   "members": statuses["active"], "visitors": statuses["lead"],
                   "children": sum(1 for r in inserts if CHILD_TAG in r["tags"]),
                   "shared_email_or_phone_moved": sum(1 for v in shared_away.values() if v)},
    }


# ─── gifts ───────────────────────────────────────────────────────────

def _method(raw: str) -> Tuple[str, str, bool]:
    """(kind, payment_method, deductible). kind is 'online' or 'manual'."""
    m = raw.strip().lower()
    if m in _NON_DEDUCTIBLE:
        return "manual", "other", False
    if m in _CARD or m == "ach":
        # Paid through Subsplash and deposited to the church's bank.
        return "online", "subsplash bank payout", True
    if m == "cash":
        return "manual", "cash", True
    if m == "check":
        return "manual", "check", True
    return "manual", "other", True


def plan_gifts(rows: List[Dict[str, str]], *, contact_for, business_id: str,
               existing_numbers: Iterable[str] = ()) -> Dict[str, Any]:
    """Invoice rows to insert. contact_for(email, first, last) -> contact id
    or None (None for anonymous gifts)."""
    from giving_router import fund_label, is_designated, RESTRICTED_CATEGORY
    have = set(existing_numbers or [])
    inserts: List[Dict[str, Any]] = []
    c: Counter = Counter()
    seen: Counter = Counter()
    total = 0.0
    for r in rows:
        status = _s(r.get("Status")).lower()
        if status in ("failed", "refunded", "canceled", "cancelled"):
            c["skipped_" + status] += 1
            continue
        gift_id = _s(r.get("Gift ID"))
        amount = _money(r.get("Gross amount"))
        day = _s(r.get("Transaction date"))[:10]
        if not gift_id or amount <= 0 or not day:
            c["skipped_unreadable"] += 1
            continue
        kind, method, deductible = _method(_s(r.get("Payment method")))
        # One Gift ID per transaction; a gift split across funds is one
        # row per fund, all with that ID. Each row is its own record (the
        # second gets "-2"), which is how Subsplash's own totals count them.
        seen[gift_id] += 1
        line = gift_id if seen[gift_id] == 1 else f"{gift_id}-{seen[gift_id]}"
        number = (f"GIVE-subsplash-{line}" if kind == "online"
                  else f"GIVE-manual-{uuid.uuid5(_UUID_NS, 'subsplash:' + line)}")
        if number in have:
            c["already_imported"] += 1
            continue
        first, last = _s(r.get("First name")), _s(r.get("Last name"))
        anonymous = norm_name(first, last) in _ANONYMOUS_NAMES
        contact_id = None
        if deductible and not anonymous:
            contact_id = contact_for(norm_email(r.get("Email")), first, last)
        fund = _s(r.get("Fund")) or "General"
        note = [f"Imported from Subsplash · {_s(r.get('Payment method'))} · gift {gift_id}"]
        if _s(r.get("Check number")):
            note.append(f"check #{_s(r.get('Check number'))}")
        covered = _money(r.get("Donor covered fee"))
        if kind == "online":
            note.append(f"fee ${_money(r.get('Fee')):.2f}" + (f", giver covered ${covered:.2f}" if covered else ""))
        if not deductible:
            note.append("not tax-deductible: kept off giving statements")
        elif anonymous:
            note.append(f"no giver ({first} {last})".strip())
        if _s(r.get("Memo")):
            note.append("memo: " + _s(r.get("Memo"))[:200])
        paid_at = f"{day}T12:00:00Z"
        inserts.append({
            "business_id": business_id, "contact_id": contact_id,
            "invoice_number": number, "status": "paid", "is_gift": True,
            "gift_fund": fund,
            "category": RESTRICTED_CATEGORY if is_designated(fund) else None,
            "payment_method": method,
            "items": [{"description": f"Gift — {fund_label(fund)}", "quantity": 1,
                       "unit_price": amount, "total": amount}],
            "subtotal": amount, "tax_rate": 0, "tax_amount": 0, "total": amount,
            "currency": "USD", "paid_at": paid_at, "sent_at": paid_at, "due_date": day,
            "notes": " · ".join(note),
        })
        total += amount
        c["to_add"] += 1
        c["linked_to_a_giver" if contact_id else "no_giver"] += 1
        c[f"method_{method}"] += 1
    return {"inserts": inserts, "counts": dict(c), "total": round(total, 2)}


def giver_keys(gift_rows: List[Dict[str, str]]) -> List[str]:
    keys = []
    for r in gift_rows:
        if _s(r.get("Status")).lower() == "failed":
            continue
        keys.append(norm_email(r.get("Email")))
        keys.append(norm_name(r.get("First name"), r.get("Last name")))
    return [k for k in keys if k]


# ─── the database ────────────────────────────────────────────────────

def _from_gifts_export(contact: Dict[str, Any]) -> bool:
    imp = ((contact.get("metadata") or {}).get("imported") or {})
    return contact.get("source") == SOURCE and imp.get("From") == "gifts export"


def _uniform(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PostgREST's bulk insert needs every object to have the same keys
    (PGRST102), so a row without a birthday carries birthdate: null."""
    keys = sorted({k for r in rows for k in r})
    return [{k: r.get(k) for k in keys} for r in rows]


def _existing_contacts(business_id: str) -> List[Dict[str, Any]]:
    import sb_clients
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        page = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&select=id,name,email,phone,source,metadata"
            f"&order=created_at.asc&limit=1000&offset={offset}") or []
        out += page
        if len(page) < 1000:
            return out
        offset += 1000


def _existing_gift_numbers(business_id: str) -> List[str]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{business_id}&is_gift=is.true&select=invoice_number"
        f"&limit=100000") or []
    return [r.get("invoice_number") for r in rows if r.get("invoice_number")]


def run(business_id: str, people_csv: str, gifts_csv: Optional[str], *, write: bool) -> Dict[str, Any]:
    import sb_clients
    gift_rows = read_csv(gifts_csv) if gifts_csv else []
    biz = (sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type&limit=1") or [None])[0]
    if not biz:
        raise SystemExit("business not found")
    people = plan_people(read_csv(people_csv), givers=giver_keys(gift_rows),
                         existing=_existing_contacts(business_id))
    report: Dict[str, Any] = {"business": biz["name"], "people": people["counts"]}
    created: List[Dict[str, Any]] = []
    if write and people["inserts"]:
        for i in range(0, len(people["inserts"]), 100):
            chunk = _uniform([{**r, "business_id": business_id} for r in people["inserts"][i:i + 100]])
            created += sb_clients.sb_post_as_service("/contacts", chunk) or []
        report["people"]["written"] = len(created)
        if len(created) != len(people["inserts"]):
            # Never link gifts to a half-written people list: the next run
            # picks up where this one stopped.
            report["stopped"] = "not every person saved; gifts were not written"
            return report
    if write and people["updates"]:
        filled = 0
        for u in people["updates"]:
            if sb_clients.sb_patch_as_service(
                    f"/contacts?id=eq.{u['id']}&business_id=eq.{business_id}", u["fields"]):
                filled += 1
        report["people"]["filled_in"] = filled

    # Gifts link to contacts by email, then by name, after the people land.
    contacts = _existing_contacts(business_id) if write else [
        {"id": f"new-{i}", **r} for i, r in enumerate(people["inserts"])
    ] + [{"id": cid, "name": "", "metadata": {}} for _, cid in people["matched"]]
    by_email: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for c in contacts:
        md = c.get("metadata") or {}
        imp = md.get("imported") or {}
        for e in [c.get("email"), imp.get("Email (shared)"), *(imp.get("Other emails") or [])]:
            if norm_email(e):
                by_email.setdefault(norm_email(e), str(c["id"]))
        if _s(c.get("name")):
            by_name.setdefault(" ".join(_s(c["name"]).lower().split()), str(c["id"]))
    for p, cid in people["matched"]:
        for e in p["_emails"]:
            by_email.setdefault(e, cid)
        by_name.setdefault(norm_name(p["first_name"], p["last_name"]), cid)

    missing: Dict[str, Dict[str, Any]] = {}

    def contact_for(email: str, first: str, last: str) -> Optional[str]:
        hit = (by_email.get(email) if email else None) or by_name.get(norm_name(first, last))
        if hit:
            return hit
        # Keyed by name: a giver who left an email on some gifts and not on
        # others is still one person.
        key = norm_name(first, last) or email
        found = missing.setdefault(key, {"email": email, "first": first, "last": last})
        if email and not found["email"]:
            found["email"] = email
        return f"missing:{key}"

    gifts = plan_gifts(gift_rows, contact_for=contact_for, business_id=business_id,
                       existing_numbers=_existing_gift_numbers(business_id))
    report["gifts"] = {**gifts["counts"], "total": gifts["total"],
                       "givers_not_in_people_list": len(missing)}

    if write and missing:
        # A giver Subsplash's people list didn't have: added as active.
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = [{"business_id": business_id,
                 "name": " ".join(f"{m['first']} {m['last']}".split()) or m["email"],
                 "email": m["email"] or None, "status": "active", "source": SOURCE,
                 "source_detail": "Subsplash gifts export", "tags": [TAG],
                 "metadata": {"imported_at": now_iso, "imported_from": "Subsplash",
                              "imported": {"From": "gifts export"}},
                 "created_at": now_iso} for m in missing.values()]
        made = sb_clients.sb_post_as_service("/contacts", _uniform(rows)) or []
        for k, row in zip(missing, made):
            by_email.setdefault(k, str(row["id"]))
            by_name.setdefault(k, str(row["id"]))
    for g in gifts["inserts"]:
        cid = g.get("contact_id")
        if cid and cid.startswith("missing:"):
            key = cid[len("missing:"):]
            g["contact_id"] = by_email.get(key) or by_name.get(key) if write else None
        elif cid and cid.startswith("new-"):
            g["contact_id"] = None   # dry run only

    if write and gifts["inserts"]:
        written = 0
        for i in range(0, len(gifts["inserts"]), 100):
            written += len(sb_clients.sb_post_as_service("/invoices", gifts["inserts"][i:i + 100]) or [])
        report["gifts"]["written"] = written
        import audit_log
        audit_log.record(business_id, actor_type="system", verb="import.subsplash",
                         summary=(f"Imported {len(created)} people and {written} gifts "
                                  f"from Subsplash"),
                         payload={"people": report["people"], "gifts": report["gifts"]},
                         source=SOURCE)
    return report


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--business", required=True)
    ap.add_argument("--people", required=True)
    ap.add_argument("--gifts")
    ap.add_argument("--write", action="store_true", help="without it, a dry run")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.business, a.people, a.gifts, write=a.write), indent=2, default=str))


if __name__ == "__main__":
    main()
