"""
expense_categories.py — a business's own expense categories, Chief's
suggestions of where a payment goes, and remembering it for next time.

Kevin, 2026-10-31: "can chief make expense catagories if i request it so
transactions can go under there?" then "yes and also allow for chief to have
suggestions on where things go ... hey, I noticed this transaction was to this
particular business. Do you want me to add it to this category? ... do you
want me to save this in my memory so I know to add this in the future".

    A CATEGORY ..... a name ("Utilities", "Benevolence", "Bank fees") and the
                     line of the books it rolls up to (operating, tax,
                     owner_pay, savings, other). It is the label
                     (business_subcategory) the P&L already breaks expenses
                     out by; the list keeps the spelling one, so "Utilities"
                     never becomes "Utility bills" beside it
    IN USE ......... labels already on bank rows and manual expenses this year,
                     with their totals; one not on the list is offered for
                     saving, and one that reads like a saved one is named
    RENAME, MERGE .. a category's rows (bank rows that are expenses, manual
                     expenses) and rules move to the new name in one batch;
                     merged, the old one is archived. One undo puts it back
    SUGGESTIONS .... for a payee waiting for an answer: a saved rule for it,
                     or how the same payee was filed before (the most-used
                     answer and how many times)
    REMEMBERING .... a rule (category_rules, the screen's "every time" rules):
                     the bank feed and statements file that payee's next
                     payments themselves. Chief's rules match the payee's
                     wording (its payee key) as well as Plaid's merchant name

Who may: the Transactions screen's readers read; the owner changes
(plaid_router gates, the church money wall included), as the person talking.
Switched with the bank search (CHIEF_BANK_SEARCH). Table:
supabase/APPLY-2026-10-31-expense-categories.sql.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("expense_categories")

router = APIRouter(prefix="/expense-categories", tags=["expense-categories"])

BUCKETS = ("operating", "tax", "owner_pay", "savings", "other")
BUCKET_SAID = {"operating": "Operating", "tax": "Tax", "owner_pay": "Owner pay", "savings": "Savings", "other": "Other"}
NAME_MAX = 60
HISTORY_ROWS = 5000
UNDO_DAYS = 30
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "reports"}
# The rows a rename or merge may touch, and the fields an undo may put back.
_TABLES = {
    "plaid_transactions": ("transaction_id", ("business_category", "business_subcategory")),
    "business_expenses": ("id", ("category", "subcategory")),
    "category_rules": ("id", ("business_category", "business_subcategory")),
    "expense_categories": ("id", ("name", "bucket", "archived_at")),
}


class Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def _all(path: str) -> List[Dict[str, Any]]:
    import bank_picks
    try:
        return bank_picks.read_all(path, _get, cap=20_000)
    except bank_picks.TooMany as e:
        raise Unavailable(str(e))


def name_of(v: Any) -> str:
    return " ".join(str(v or "").split())[:NAME_MAX]


def key_of(v: Any) -> str:
    """'Utilities', 'utilities ', 'Utility' read the same; so do 'Bank fees'
    and 'bank fee'."""
    k = " ".join(re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).split())
    words = [w[:-3] + "y" if w.endswith("ies") and len(w) > 4 else w[:-1] if w.endswith("s") and len(w) > 3 else w
             for w in k.split()]
    return " ".join(words)


# ─── The list ─────────────────────────────────────────────────────────

def categories(business_id: str) -> List[Dict[str, Any]]:
    return _get(f"/expense_categories?business_id=eq.{_q(business_id)}&archived_at=is.null"
                "&select=id,name,bucket,created_at&order=name.asc&limit=500")


def find(cats: List[Dict[str, Any]], name: Any) -> Optional[Dict[str, Any]]:
    k = key_of(name)
    return next((c for c in cats if key_of(c["name"]) == k), None) if k else None


def _books_accounts(business_id: str) -> List[str]:
    import bank_picks
    return bank_picks.accounts(business_id, _get)


def usage(business_id: str, year: int) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(bucket, label) -> count and total spent, this year: bank rows filed as
    expenses and manual expenses."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add(bucket: Any, label: Any, amt: float) -> None:
        lab = name_of(label)
        if not lab:
            return
        k = (str(bucket or "other"), lab)
        u = out.setdefault(k, {"count": 0, "total": 0.0})
        u["count"] += 1
        u["total"] = round(u["total"] + amt, 2)

    accts = _books_accounts(business_id)
    if accts:
        import bank_picks
        for t in _all(f"/plaid_transactions?business_id=eq.{_q(business_id)}&account_id={bank_picks.in_(accts)}"
                      f"&amount=gt.0&pending=eq.false&excluded_from_books=eq.false"
                      f"&date=gte.{year}-01-01&date=lte.{year}-12-31&business_subcategory=not.is.null"
                      "&select=transaction_id,amount,business_category,business_subcategory,money_kind"
                      "&order=transaction_id.asc"):
            if not t.get("money_kind"):
                add(t.get("business_category"), t.get("business_subcategory"), float(t.get("amount") or 0))
    for e in _all(f"/business_expenses?business_id=eq.{_q(business_id)}&date=gte.{year}-01-01&date=lte.{year}-12-31"
                  "&subcategory=not.is.null&select=id,amount,category,subcategory&order=id.asc"):
        add(e.get("category"), e.get("subcategory"), float(e.get("amount") or 0))
    return out


def picture(business_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    year = int(year or date.today().year)
    cats = categories(business_id)
    used = usage(business_id, year)
    listed = []
    for c in cats:
        k = key_of(c["name"])
        rows = [u for (b, lab), u in used.items() if key_of(lab) == k]
        listed.append({**c, "count": sum(u["count"] for u in rows), "total": round(sum(u["total"] for u in rows), 2)})
    unsaved = []
    for (bucket, lab), u in sorted(used.items(), key=lambda kv: -kv[1]["total"]):
        if find(cats, lab):
            continue
        unsaved.append({"label": lab, "bucket": bucket, **u})
    return {"year": year, "categories": listed, "unsaved": unsaved}


def create(business_id: str, user_id: Any, name: Any, bucket: Any) -> Tuple[Dict[str, Any], bool]:
    """(the category, made now). One of the same name is the one returned."""
    nm = name_of(name)
    if not nm:
        raise HTTPException(422, "Give the category a name.")
    b = str(bucket or "operating").strip().lower()
    if b not in BUCKETS:
        raise HTTPException(422, f"A category rolls up to one of: {', '.join(BUCKETS)}.")
    have = find(categories(business_id), nm)
    if have:
        return have, False
    made = sb_clients.sb_post_as_service("/expense_categories", {
        "business_id": business_id, "name": nm, "bucket": b, "created_by": str(user_id) if user_id else None})
    row = (made[0] if isinstance(made, list) and made else made) if made else None
    if not isinstance(row, dict) or not row.get("id"):
        have = find(categories(business_id), nm)          # made a moment ago elsewhere
        if have:
            return have, False
        raise Unavailable("expense_categories")
    return row, True


# ─── Rename and merge, one batch ──────────────────────────────────────

def _patch_row(business_id: str, table: str, rid: str, guard: Dict[str, Any], body: Dict[str, Any]) -> Optional[bool]:
    key = _TABLES[table][0]
    path = f"/{table}?business_id=eq.{_q(business_id)}&{key}=eq.{_q(rid)}"
    for k, v in guard.items():
        path += f"&{k}=is.null" if v is None else f"&{k}=eq.{_q(v)}"
    res = sb_clients.sb_patch_as_service(path, body)
    if res is None:
        return None
    return bool(res) if isinstance(res, list) else True


def _labelled(business_id: str, old_keys: set) -> List[Tuple[str, Dict[str, Any]]]:
    """Every expense row and rule whose label reads as one of old_keys."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    accts = _books_accounts(business_id)
    if accts:
        import bank_picks
        for t in _all(f"/plaid_transactions?business_id=eq.{_q(business_id)}&account_id={bank_picks.in_(accts)}"
                      "&amount=gt.0&business_subcategory=not.is.null"
                      "&select=transaction_id,business_category,business_subcategory,money_kind&order=transaction_id.asc"):
            if not t.get("money_kind") and key_of(t.get("business_subcategory")) in old_keys:
                out.append(("plaid_transactions", t))
    for e in _all(f"/business_expenses?business_id=eq.{_q(business_id)}&subcategory=not.is.null"
                  "&select=id,category,subcategory&order=id.asc"):
        if key_of(e.get("subcategory")) in old_keys:
            out.append(("business_expenses", e))
    for r in _get(f"/category_rules?business_id=eq.{_q(business_id)}&business_subcategory=not.is.null"
                  "&select=id,business_category,business_subcategory&limit=2000"):
        if key_of(r.get("business_subcategory")) in old_keys:
            out.append(("category_rules", r))
    return out


def relabel(business_id: str, old_names: List[str], new_name: str, new_bucket: str) -> Tuple[List[Dict[str, Any]], int]:
    """Moves every row labelled with one of old_names to new_name under
    new_bucket. Returns (changes for undo, rows that changed meanwhile)."""
    changes, moved = [], 0
    for table, row in _labelled(business_id, {key_of(n) for n in old_names}):
        key, (cat_f, sub_f) = _TABLES[table][0], _TABLES[table][1]
        before = {cat_f: row.get(cat_f), sub_f: row.get(sub_f)}
        after = {cat_f: new_bucket, sub_f: new_name}
        if before == after:
            continue
        ok = _patch_row(business_id, table, str(row[key]), before, after)
        if ok is None:
            raise Unavailable(table)
        if ok:
            changes.append({"table": table, "id": str(row[key]), "before": before, "after": after})
        else:
            moved += 1
    return changes, moved


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _gate(business_id: str, *, write: bool) -> Optional[str]:
    import chief_transactions
    if not chief_transactions.switched_on(business_id):
        return "Categories from chat aren't switched on for this business yet."
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "Categories are read and changed only for a signed-in person who can see the books."
    import plaid_router
    try:
        (plaid_router._require_owner if write else plaid_router._require_reader)(business_id, SimpleNamespace(id=uid))
    except HTTPException as e:
        if write and e.status_code == 403 and not isinstance(e.detail, dict):
            return "Only the owner changes the categories, the same as on the Transactions screen."
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return str(detail or "This login can't see the books.")
    return None


def _uid() -> Any:
    from chief_of_staff import _TURN_USER_ID
    return _TURN_USER_ID.get()


def set_category(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Make one ("name", "bucket"); rename one ("category", "name"); merge one
    into another ("category", "into"). Rename and merge move its rows."""
    atype = "set_expense_category"
    refused = _gate(business_id, write=True)
    if refused:
        return _fail(atype, refused)
    try:
        cats = categories(business_id)
        current = find(cats, action.get("category")) if action.get("category") else None
        if action.get("category") and not current:
            return _fail(atype, f"there's no category called '{name_of(action.get('category'))}' yet")
        batch = uuid.uuid4().hex
        if current and action.get("into"):
            into = find(cats, action.get("into"))
            if not into:
                return _fail(atype, f"there's no category called '{name_of(action.get('into'))}' to merge into")
            if into["id"] == current["id"]:
                return _fail(atype, "that's the same category")
            changes, moved = relabel(business_id, [current["name"]], into["name"], into["bucket"])
            stamp = datetime.now(timezone.utc).isoformat()
            if not _patch_row(business_id, "expense_categories", current["id"], {"archived_at": None}, {"archived_at": stamp}):
                raise Unavailable("expense_categories")
            changes.append({"table": "expense_categories", "id": current["id"], "before": {"archived_at": None},
                            "after": {"archived_at": stamp}})
            text = (f"Merged {current['name']} into {into['name']}: {sum(1 for c in changes if c['table'] != 'expense_categories')} "
                    f"rows and rules now say {into['name']}, under {BUCKET_SAID[into['bucket']]}.")
        elif current:
            new = name_of(action.get("name"))
            bucket = str(action.get("bucket") or current["bucket"]).lower()
            if bucket not in BUCKETS:
                return _fail(atype, f"a category rolls up to one of: {', '.join(BUCKETS)}")
            if not new:
                return _fail(atype, "say the new name, or 'into' to merge it into another category")
            clash = find(cats, new)
            if clash and clash["id"] != current["id"]:
                return _fail(atype, f"{clash['name']} already exists; merge into it instead")
            body = {"name": new, "bucket": bucket}
            before = {"name": current["name"], "bucket": current["bucket"]}
            if not _patch_row(business_id, "expense_categories", current["id"], before, body):
                raise Unavailable("expense_categories")
            changes = [{"table": "expense_categories", "id": current["id"], "before": before, "after": body}]
            moved_rows, moved = relabel(business_id, [current["name"]], new, bucket)
            changes += moved_rows
            text = (f"{current['name']} is now {new} under {BUCKET_SAID[bucket]}: {len(moved_rows)} rows and rules "
                    "moved with it.")
        else:
            row, made = create(business_id, _uid(), action.get("name"), action.get("bucket"))
            if not made:
                return {"type": atype, "result": f"{row['name']} is already a category, under "
                                                  f"{BUCKET_SAID.get(row['bucket'], row['bucket'])}.",
                        "label": f"🗂 {row['name']}", "nav": NAV}
            changes, moved = [{"table": "expense_categories", "id": str(row["id"]), "before": None,
                               "after": {"name": row["name"]}}], 0
            text = (f"Made the category {row['name']}, under {BUCKET_SAID[row['bucket']]}. Payments filed with it "
                    "show as their own line in the Profit & Loss.")
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the categories couldn't be read or saved just now; ask again to finish")
    if moved:
        text += f" {moved} changed while I worked and were left as they are."
    return {"type": atype, "result": text + " One undo puts it back.", "label": "🗂 Categories",
            "batch_id": batch, "changes": changes, "nav": NAV}


# ─── Suggestions and remembering ──────────────────────────────────────

def rules(business_id: str) -> List[Dict[str, Any]]:
    return _get(f"/category_rules?business_id=eq.{_q(business_id)}"
                "&select=id,merchant_name,business_category,business_subcategory&limit=2000")


def history(business_id: str) -> Dict[str, Dict[str, Any]]:
    """payee key -> how its money out was filed before (the most-used answer
    and how many times), from the newest answered rows."""
    import bank_picks
    accts = _books_accounts(business_id)
    if not accts:
        return {}
    rows = _get(f"/plaid_transactions?business_id=eq.{_q(business_id)}&account_id={bank_picks.in_(accts)}"
                "&amount=gt.0&pending=eq.false&excluded_from_books=eq.false"
                "&business_category=not.is.null&business_category=neq.other"
                f"&select=name,merchant_name,business_category,business_subcategory,money_kind"
                f"&order=date.desc&limit={HISTORY_ROWS}")
    seen: Dict[str, Counter] = {}
    for t in rows:
        if t.get("money_kind"):
            continue
        # The same key the waiting list groups by: the merchant's name, else the bank's wording.
        k = bank_picks.payee_key(str(t.get("merchant_name") or t.get("name") or "")) or ""
        if k:
            seen.setdefault(k, Counter())[(t["business_category"], name_of(t.get("business_subcategory")))] += 1
    out = {}
    for k, c in seen.items():
        (bucket, label), n = c.most_common(1)[0]
        out[k] = {"answer": bucket, "label": label or None, "times": n, "of": sum(c.values())}
    return out


def suggest(business_id: str, groups: List[Dict[str, Any]]) -> None:
    """Adds `suggest` to each money-out group: a saved rule for the payee, or
    how it was filed before. Best-effort: none on a failed read."""
    try:
        rs = rules(business_id)
        past = history(business_id)
    except Unavailable:
        return
    by_rule = {key_of(r.get("merchant_name")): r for r in rs if r.get("merchant_name")}
    for g in groups:
        if g.get("direction") != "out":
            continue
        r = by_rule.get(key_of(g["payee"])) or next(
            (by_rule.get(key_of(n)) for n in g.get("names") or [] if by_rule.get(key_of(n))), None)
        if r:
            g["suggest"] = {"from": "rule", "answer": r["business_category"], "label": r.get("business_subcategory")}
        elif g["payee"] in past:
            g["suggest"] = {"from": "history", **past[g["payee"]]}


def remember(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """A rule for a payee: its next payments file themselves."""
    atype = "save_category_rule"
    refused = _gate(business_id, write=True)
    if refused:
        return _fail(atype, refused)
    import bank_picks
    payee = bank_picks.payee_key(str(action.get("payee") or "")) or ""
    if not payee:
        return _fail(atype, "say which payee (its payee key from bank_to_file)")
    try:
        cats = categories(business_id)
        cat = find(cats, action.get("category") or action.get("label"))
        bucket = str(action.get("answer") or (cat or {}).get("bucket") or "").lower()
        if bucket not in BUCKETS[:4]:
            return _fail(atype, "a rule files spending: operating, tax, owner_pay or savings, or a saved category")
        label = (cat or {}).get("name") or name_of(action.get("label")) or None
        have = _get(f"/category_rules?business_id=eq.{_q(business_id)}&merchant_name=eq.{_q(payee)}"
                    "&select=id,business_category,business_subcategory&limit=1")
        body = {"business_category": bucket, "business_subcategory": label,
                "updated_at": datetime.now(timezone.utc).isoformat()}
        if have:
            before = {"business_category": have[0]["business_category"],
                      "business_subcategory": have[0].get("business_subcategory")}
            if not _patch_row(business_id, "category_rules", have[0]["id"], before, body):
                raise Unavailable("category_rules")
            change = {"table": "category_rules", "id": str(have[0]["id"]), "before": before,
                      "after": {"business_category": bucket, "business_subcategory": label}}
        else:
            made = sb_clients.sb_post_as_service("/category_rules", {"business_id": business_id,
                                                                     "merchant_name": payee, **body})
            row = (made[0] if isinstance(made, list) and made else made) if made else None
            if not isinstance(row, dict) or not row.get("id"):
                raise Unavailable("category_rules")
            change = {"table": "category_rules", "id": str(row["id"]), "before": None, "after": body}
    except Unavailable:
        return _fail(atype, "the rule couldn't be saved just now")
    said = f"{BUCKET_SAID[bucket]}" + (f", {label}" if label else "")
    return {"type": atype, "result": f"Remembered: payments to {payee} file as {said} from now on, as they arrive "
                                     "from the bank or a statement. One undo forgets it.",
            "label": f"🧠 {payee} → {label or BUCKET_SAID[bucket]}"[:120], "batch_id": uuid.uuid4().hex,
            "changes": [change], "nav": NAV}


def rule_for(rule_map: Dict[str, Dict[str, Any]], merchant: Any, name: Any) -> Optional[Dict[str, Any]]:
    """The bank feed's and statements' rule lookup: Plaid's merchant name, then
    the payee's wording (Chief's rules are kept by payee key)."""
    import bank_picks
    for k in (str(merchant or "").strip().lower(), bank_picks.payee_key(str(merchant or "")),
              bank_picks.payee_key(str(name or ""))):
        if k and rule_map.get(k):
            return rule_map[k]
    return None


# ─── Undo ─────────────────────────────────────────────────────────────

def undo(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "undo_category_change"
    refused = _gate(business_id, write=True)
    if refused:
        return _fail(atype, refused)
    batch_id = str(action.get("batch_id") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        return _fail(atype, "that isn't a change to the categories I recorded")
    since = (datetime.now(timezone.utc) - timedelta(days=UNDO_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        logs = _get(f"/chief_undo_log?business_id=eq.{_q(business_id)}"
                    "&action_type=in.(set_expense_category,save_category_rule)&status=eq.undoable"
                    f"&created_at=gte.{since}&order=created_at.desc&limit=50&select=id,result_json")
    except Unavailable:
        return _fail(atype, "the record of that change couldn't be read just now; nothing changed")
    log = next((r for r in logs if (r.get("result_json") or {}).get("batch_id") == batch_id), None)
    if not log:
        return _fail(atype, f"there's no such change of mine from the last {UNDO_DAYS} days left to undo")
    back, skipped, failed = 0, 0, 0
    for c in reversed(log["result_json"].get("changes") or []):
        table, rid = c.get("table"), str(c.get("id") or "")
        if table not in _TABLES or not rid:
            failed += 1
            continue
        fields = _TABLES[table][1]
        after = {k: v for k, v in (c.get("after") or {}).items() if k in fields}
        if c.get("before") is None:                          # made by the change: unmade
            if table == "expense_categories":
                ok = _patch_row(business_id, table, rid, {"archived_at": None},
                                {"archived_at": datetime.now(timezone.utc).isoformat()})
            else:
                ok = sb_clients.sb_delete_as_service(f"/{table}?business_id=eq.{_q(business_id)}&id=eq.{_q(rid)}")
        else:
            before = {k: v for k, v in c["before"].items() if k in fields}
            ok = _patch_row(business_id, table, rid, after, before)
        if ok is None or ok is False and table == "expense_categories" and c.get("before") is None:
            failed += 1
        elif ok:
            back += 1
        else:
            skipped += 1
    if failed:
        return _fail(atype, f"only part of it went back ({back} rows); ask again to finish")
    sb_clients.sb_patch_as_service(f"/chief_undo_log?id=eq.{log['id']}", {
        "status": "undone", "undone_at": datetime.now(timezone.utc).isoformat()})
    text = f"Put back {back} change(s) to the categories."
    if skipped:
        text += f" {skipped} had been changed since, so I left them as they are now."
    return {"type": atype, "result": text, "label": f"↩ Put back {back}", "nav": NAV}


# ─── Routes (the screen's list) ───────────────────────────────────────

class CategoryBody(BaseModel):
    business_id: str
    name: str = Field(max_length=NAME_MAX * 2)
    bucket: str = Field(default="operating", max_length=12)


def _route_gate(business_id: str, user: Any, *, write: bool) -> Dict[str, Any]:
    if not _UUID.match(str(business_id or "")):
        raise HTTPException(400, "business_id must be a uuid")
    import plaid_router
    return (plaid_router._require_owner if write else plaid_router._require_reader)(business_id, user)


@router.get("")
def get_categories(business_id: str = Query(...), year: Optional[int] = Query(None, ge=2000, le=2100),
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _route_gate(business_id, user, write=False)
    try:
        return {"ok": True, "can_change": str(row.get("owner_id")) == str(user.id), **picture(business_id, year)}
    except Unavailable:
        raise HTTPException(503, "The categories can't be read just now. If this is new, its table may not be set up yet.")


@router.post("")
def post_category(body: CategoryBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _route_gate(body.business_id, user, write=True)
    try:
        row, made = create(body.business_id, user.id, body.name, body.bucket)
    except Unavailable:
        raise HTTPException(503, "The category didn't save. Try again.")
    return {"ok": True, "category": row, "made": made}


# ─── Chief ────────────────────────────────────────────────────────────

LIST_TOOL = {
    "name": "expense_categories",
    "description": (
        "This business's own expense categories (the lines its Profit & Loss breaks spending into, under "
        "Operating, Tax, Owner pay or Savings), each with this year's count and total; labels in use that aren't "
        "on the list yet; and the 'every time' rules. Use it before filing under a category, when they ask "
        "what categories they have, or to keep names from drifting ('Utilities', never also 'Utility bills')."),
    "input_schema": {"type": "object", "properties": {"year": {"type": "integer"}}},
}


def _list_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "expense_categories"
    refused = _gate(str(biz["id"]), write=False)
    if refused:
        return _fail(atype, refused)
    try:
        p = picture(str(biz["id"]), action.get("year"))
        rs = rules(str(biz["id"]))
    except (Unavailable, ValueError, TypeError):
        return _fail(atype, "the categories couldn't be read just now (if this is new, its table may not be set up "
                            "yet). This is not 'no categories'")
    cats = p["categories"]
    text = (f"{len(cats)} categories: " + "; ".join(
        f"{c['name']} ({BUCKET_SAID.get(c['bucket'], c['bucket'])}, {c['count']} this year, ${c['total']:,.2f})"
        for c in cats[:25]) + "." if cats else "No categories saved yet.")
    if p["unsaved"]:
        text += " In use but not on the list: " + "; ".join(
            f"{u['label']} ({BUCKET_SAID.get(u['bucket'], u['bucket'])}, {u['count']})" for u in p["unsaved"][:10]) + "."
    text += f" {len(rs)} every-time rule(s)."
    return {"type": atype, "result": text, "label": "🗂 Categories", "categories": cats, "unsaved": p["unsaved"][:30],
            "rules": [{"payee": r["merchant_name"], "answer": r["business_category"],
                       "label": r.get("business_subcategory")} for r in rs[:60]],
            "note_for_chief": ("File under the saved names exactly. Offer to save a label that's in use but not "
                               "listed, and to merge two that mean the same thing; ask first."),
            "nav": NAV}


async def handle_expense_categories(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_list_sync, biz, action or {})


async def handle_set_expense_category(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(set_category, str(biz["id"]), action or {})


async def handle_save_category_rule(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(remember, str(biz["id"]), action or {})


async def handle_undo_category_change(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo, str(biz["id"]), action or {})
