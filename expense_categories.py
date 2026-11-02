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

Who may: the Transactions screen's readers read; the owner, or a church's
Admin seat (the treasurer), changes (plaid_router gates, the church money
wall included), as the person talking.
Switched with the bank search (CHIEF_BANK_SEARCH). Table:
supabase/APPLY-2026-10-31-expense-categories.sql.

THE CARD (Bookkeeping -> Transactions -> Rules, 2026-11-01): the same list,
add, rename, merge and undo on screen (POST /expense-categories/change and
/undo). Its changes go in Chief's undo log, so either one takes them back.
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
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "transactions", "bkView": "rules"}   # the card
# The rows a rename or merge may touch, and the fields an undo may put back.
_TABLES = {
    "plaid_transactions": ("transaction_id", ("business_category", "business_subcategory")),
    "business_expenses": ("id", ("category", "subcategory")),
    "bills": ("id", ("category", "subcategory")),           # a bill under a category moves with it
    "category_rules": ("id", ("business_category", "business_subcategory")),
    "expense_categories": ("id", ("name", "bucket", "archived_at", "line")),
    "expense_lines": ("id", ("name", "archived_at")),
}
_ARCHIVED = ("expense_categories", "expense_lines")      # unmade by archiving, never deleted


from expense_lines import Unavailable  # noqa: E402  (one failure type for categories and lines)


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
                "&select=id,name,bucket,line,created_at&order=name.asc&limit=500")


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


def line_of(c: Dict[str, Any], keys: set) -> str:
    """The line a category rolls up to: its own line when that's one of the
    business's live lines, else its bucket's built-in line."""
    return c["line"] if c.get("line") in keys else str(c.get("bucket") or "other")


def picture(business_id: str, year: Optional[int] = None) -> Dict[str, Any]:
    import expense_lines
    year = int(year or date.today().year)
    ls = expense_lines.lines(business_id, strict=True)
    keys = {ln["key"] for ln in ls}
    cats = categories(business_id)
    used = usage(business_id, year)
    listed = []
    for c in cats:
        k = key_of(c["name"])
        rows = [u for (b, lab), u in used.items() if key_of(lab) == k]
        listed.append({**c, "line": line_of(c, keys), "count": sum(u["count"] for u in rows),
                       "total": round(sum(u["total"] for u in rows), 2)})
    unsaved = []
    for (bucket, lab), u in sorted(used.items(), key=lambda kv: -kv[1]["total"]):
        if find(cats, lab):
            continue
        unsaved.append({"label": lab, "bucket": bucket, "line": bucket if bucket in keys else "other", **u})
    return {"year": year, "categories": listed, "unsaved": unsaved,
            "lines": [{k: ln[k] for k in ("key", "name", "base", "builtin")} for ln in ls]}


def create(business_id: str, user_id: Any, name: Any, bucket: Any, line: Any = None) -> Tuple[Dict[str, Any], bool]:
    """(the category, made now). One of the same name is the one returned. It
    rolls up to `line` (a key or a name: one of the five or the business's
    own), else to `bucket`; its bucket is always that line's base."""
    import expense_lines
    nm = name_of(name)
    if not nm:
        raise HTTPException(422, "Give the category a name.")
    ls = expense_lines.lines(business_id, strict=True)
    tl = expense_lines.find(ls, line or bucket or "operating")
    if not tl:
        raise HTTPException(422, "A category rolls up to one of your lines: "
                                 f"{', '.join(ln['name'] for ln in ls)}.")
    b = tl["base"]
    have = find(categories(business_id), nm)
    if have:
        return have, False
    body = {"business_id": business_id, "name": nm, "bucket": b, "created_by": str(user_id) if user_id else None}
    if not tl["builtin"]:
        body["line"] = tl["key"]
    made = sb_clients.sb_post_as_service("/expense_categories", body)
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
    """Every expense row, bill and rule whose label reads as one of old_keys."""
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
    # Bills under the category (the Bills tab files under the saved names too).
    for b in _get(f"/bills?business_id=eq.{_q(business_id)}&subcategory=not.is.null"
                  "&select=id,category,subcategory&limit=5000"):
        if key_of(b.get("subcategory")) in old_keys:
            out.append(("bills", b))
    for r in _get(f"/category_rules?business_id=eq.{_q(business_id)}&business_subcategory=not.is.null"
                  "&select=id,business_category,business_subcategory&limit=2000"):
        if key_of(r.get("business_subcategory")) in old_keys:
            out.append(("category_rules", r))
    return out


def relabel(business_id: str, old_names: List[str], new_name: str,
            new_bucket: str) -> Tuple[List[Dict[str, Any]], int, int]:
    """Moves every row labelled with one of old_names to new_name under
    new_bucket. Returns (changes for undo, rows that changed meanwhile, rows
    whose write failed). A failed write never stops the rest; the caller
    leaves the category as it was, so asking again moves what's left."""
    changes, moved, failed = [], 0, 0
    for table, row in _labelled(business_id, {key_of(n) for n in old_names}):
        key, (cat_f, sub_f) = _TABLES[table][0], _TABLES[table][1]
        before = {cat_f: row.get(cat_f), sub_f: row.get(sub_f)}
        after = {cat_f: new_bucket, sub_f: new_name}
        if before == after:
            continue
        ok = _patch_row(business_id, table, str(row[key]), before, after)
        if ok is None:
            failed += 1
        elif ok:
            changes.append({"table": table, "id": str(row[key]), "before": before, "after": after})
        else:
            moved += 1
    return changes, moved, failed


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _partial(atype: str, batch: str, changes: List[Dict[str, Any]], failed: int, what: str) -> Dict[str, Any]:
    """Part of a rename or merge went through: what moved is recorded (one undo
    takes it back), the category is left as it was, and asking again finishes."""
    text = (f"Partway through {what}: {len(changes)} rows and rules moved, {failed} didn't save. The category "
            "is as it was, so ask again to finish; one undo takes back what moved.")
    out = {"type": atype, "result": text, "label": "🗂 Partly done", "partial": True, "nav": NAV}
    if changes:
        out.update(batch_id=batch, changes=changes)
    else:
        out.update(failed=True, result="Failed: " + text)
    return out


def _gate(business_id: str, *, write: bool) -> Optional[str]:
    import chief_transactions
    if not chief_transactions.switched_on(business_id):
        return "Categories from chat aren't switched on for this business yet."
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "Categories are read and changed only for a signed-in person who can see the books."
    import plaid_router
    who = SimpleNamespace(id=uid)
    try:
        if write:
            plaid_router._require_money_writer(business_id, who)
        else:
            plaid_router._require_reader(business_id, who)
    except HTTPException as e:
        if write and e.status_code == 403 and not isinstance(e.detail, dict):
            return ("Only the owner, or a church's Admin, changes the categories, the same as on the "
                    "Transactions screen.")
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return str(detail or "This login can't see the books.")
    return None


def _uid() -> Any:
    from chief_of_staff import _TURN_USER_ID
    return _TURN_USER_ID.get()


def set_category(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Chief's verb: make one ("name", "bucket"); rename one ("category",
    "name"); merge one into another ("category", "into"). Rename and merge
    move its rows."""
    refused = _gate(business_id, write=True)
    if refused:
        return _fail("set_expense_category", refused)
    return change(business_id, _uid(), action)


def change(business_id: str, user_id: Any, action: Dict[str, Any], *, say_undo: bool = True) -> Dict[str, Any]:
    """The change itself, for Chief's verb and the screen's card (each gates
    first). "category" may also be a label in use that isn't on the list, to
    merge it "into" a saved one ('Utility bills' into 'Utilities')."""
    import expense_lines
    atype = "set_expense_category"
    try:
        ls = expense_lines.lines(business_id, strict=True)
        keys = {ln["key"] for ln in ls}
        cats = categories(business_id)
        current = find(cats, action.get("category")) if action.get("category") else None
        loose = None                                    # a label in use, not on the list
        if action.get("category") and not current:
            if not action.get("into"):
                return _fail(atype, f"there's no category called '{name_of(action.get('category'))}' yet")
            loose = name_of(action.get("category"))
        batch = uuid.uuid4().hex
        if (current or loose) and action.get("into"):
            into = find(cats, action.get("into"))
            if not into:
                return _fail(atype, f"there's no category called '{name_of(action.get('into'))}' to merge into")
            if current and into["id"] == current["id"]:
                return _fail(atype, "that's the same category")
            old = current["name"] if current else loose
            changes, moved, failed = relabel(business_id, [old], into["name"], into["bucket"])
            if failed:
                return _partial(atype, batch, changes, failed, f"merging {old} into {into['name']}")
            if current:
                stamp = datetime.now(timezone.utc).isoformat()
                if _patch_row(business_id, "expense_categories", current["id"], {"archived_at": None},
                              {"archived_at": stamp}):
                    changes.append({"table": "expense_categories", "id": current["id"],
                                    "before": {"archived_at": None}, "after": {"archived_at": stamp}})
                else:
                    return _partial(atype, batch, changes, 1, f"merging {old} into {into['name']}")
            elif not changes and not moved:
                return _fail(atype, f"nothing is filed under '{loose}'")
            text = (f"Merged {old} into {into['name']}: {sum(1 for c in changes if c['table'] != 'expense_categories')} "
                    f"rows and rules now say {into['name']}, under {expense_lines.said(ls, line_of(into, keys))}.")
        elif current:
            new = name_of(action.get("name")) or current["name"]
            want = action.get("line") or action.get("bucket")
            if want:
                tl = expense_lines.find(ls, want)
                if not tl:
                    return _fail(atype, f"there's no line called '{name_of(want)}'; your lines are "
                                        f"{', '.join(ln['name'] for ln in ls)}")
                bucket, line = tl["base"], (None if tl["builtin"] else tl["key"])
            else:
                bucket, line = current["bucket"], (current.get("line") if current.get("line") in keys else None)
            clash = find(cats, new)
            if clash and clash["id"] != current["id"]:
                return _fail(atype, f"{clash['name']} already exists; merge into it instead")
            body = {"name": new, "bucket": bucket, "line": line}
            before = {"name": current["name"], "bucket": current["bucket"], "line": current.get("line")}
            if body == before:
                return _fail(atype, "say the new name, the line to move it to, or 'into' to merge it into another "
                                    "category")
            # The rows first, the category last: if a write fails, the old
            # name still stands, so asking again moves what's left.
            moved_rows, moved, failed = relabel(business_id, [current["name"]], new, bucket)
            if failed:
                return _partial(atype, batch, moved_rows, failed, f"renaming {current['name']} to {new}")
            if not _patch_row(business_id, "expense_categories", current["id"], before, body):
                return _partial(atype, batch, moved_rows, 1, f"renaming {current['name']} to {new}")
            changes = moved_rows + [{"table": "expense_categories", "id": current["id"], "before": before, "after": body}]
            on = expense_lines.said(ls, line or bucket)
            text = (f"{new} now rolls up to {on}." if new == current["name"]
                    else f"{current['name']} is now {new} under {on}.")
            if moved_rows:
                text += f" {len(moved_rows)} rows and rules moved with it."
        else:
            row, made = create(business_id, user_id, action.get("name"), action.get("bucket"), action.get("line"))
            if not made:
                return {"type": atype, "result": f"{row['name']} is already a category, under "
                                                  f"{expense_lines.said(ls, line_of(row, keys))}.",
                        "label": f"🗂 {row['name']}", "nav": NAV}
            changes, moved = [{"table": "expense_categories", "id": str(row["id"]), "before": None,
                               "after": {"name": row["name"]}}], 0
            text = (f"Made the category {row['name']}, under {expense_lines.said(ls, line_of(row, keys))}. "
                    "Payments filed with it show as their own line in the Profit & Loss.")
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    except Unavailable:
        return _fail(atype, "the categories couldn't be read or saved just now; ask again to finish")
    if moved:
        text += f" {moved} changed meanwhile and were left as they are."
    return {"type": atype, "result": text + (" One undo puts it back." if say_undo else ""), "label": "🗂 Categories",
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
    import expense_lines
    try:
        ls = expense_lines.lines(business_id)
        cats = categories(business_id)
        cat = find(cats, action.get("category") or action.get("label"))
        bucket = str(action.get("answer") or (cat or {}).get("bucket") or "").lower()
        if bucket not in BUCKETS and expense_lines.find(ls, action.get("answer")):
            bucket = expense_lines.find(ls, action.get("answer"))["base"]
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
    said = expense_lines.said(ls, line_of(cat, {ln["key"] for ln in ls}) if cat else bucket) + (f", {label}" if label else "")
    return {"type": atype, "result": f"Remembered: payments to {payee} file as {said} from now on, as they arrive "
                                     "from the bank or a statement. One undo forgets it.",
            "label": f"🧠 {payee} → {label or expense_lines.said(ls, bucket)}"[:120], "batch_id": uuid.uuid4().hex,
            "changes": [change], "nav": NAV}


def rule_for(rule_map: Dict[str, Dict[str, Any]], merchant: Any, name: Any,
             money_out: bool = True) -> Optional[Dict[str, Any]]:
    """The bank feed's and statements' rule lookup: Plaid's merchant name (as
    it always matched, either way), then, for money out only, the payee's
    wording (Chief's rules are kept by payee key): a refund from a payee is
    never filed as its spending."""
    import bank_picks
    hit = rule_map.get(str(merchant or "").strip().lower())
    if hit or not money_out:
        return hit
    for k in (bank_picks.payee_key(str(merchant or "")), bank_picks.payee_key(str(name or ""))):
        if k and rule_map.get(k):
            return rule_map[k]
    return None


# ─── Undo ─────────────────────────────────────────────────────────────

def undo(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    refused = _gate(business_id, write=True)
    if refused:
        return _fail("undo_category_change", refused)
    return take_back(business_id, action.get("batch_id"))


def take_back(business_id: str, batch_id: Any) -> Dict[str, Any]:
    """Puts one recorded change back (Chief's or the card's), skipping a row
    changed since. Each caller gates first."""
    atype = "undo_category_change"
    batch_id = str(batch_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        return _fail(atype, "that isn't a recorded change to the categories")
    since = (datetime.now(timezone.utc) - timedelta(days=UNDO_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        logs = _get(f"/chief_undo_log?business_id=eq.{_q(business_id)}"
                    "&action_type=in.(set_expense_category,save_category_rule,set_expense_line)&status=eq.undoable"
                    f"&created_at=gte.{since}&order=created_at.desc&limit=50&select=id,result_json")
    except Unavailable:
        return _fail(atype, "the record of that change couldn't be read just now; nothing changed")
    log = next((r for r in logs if (r.get("result_json") or {}).get("batch_id") == batch_id), None)
    if not log:
        return _fail(atype, f"there's no such change from the last {UNDO_DAYS} days left to undo")
    back, skipped, failed = 0, 0, 0
    for c in reversed(log["result_json"].get("changes") or []):
        table, rid = c.get("table"), str(c.get("id") or "")
        if table not in _TABLES or not rid:
            failed += 1
            continue
        fields = _TABLES[table][1]
        after = {k: v for k, v in (c.get("after") or {}).items() if k in fields}
        if c.get("before") is None:                          # made by the change: unmade
            if table in _ARCHIVED:
                ok = _patch_row(business_id, table, rid, {"archived_at": None},
                                {"archived_at": datetime.now(timezone.utc).isoformat()})
            else:
                ok = sb_clients.sb_delete_as_service(f"/{table}?business_id=eq.{_q(business_id)}&id=eq.{_q(rid)}")
        else:
            before = {k: v for k, v in c["before"].items() if k in fields}
            ok = _patch_row(business_id, table, rid, after, before)
        if ok is None or ok is False and table in _ARCHIVED and c.get("before") is None:
            failed += 1
        elif ok:
            back += 1
        else:
            skipped += 1
    if failed:
        return _fail(atype, f"only part of it went back ({back} rows); ask again to finish")
    sb_clients.sb_patch_as_service(f"/chief_undo_log?id=eq.{log['id']}", {
        "status": "undone", "undone_at": datetime.now(timezone.utc).isoformat()})
    text = f"Put back {back} change{'' if back == 1 else 's'} to the categories."
    if skipped:
        text += f" {skipped} had been changed since, so they were left as they are now."
    return {"type": atype, "result": text, "label": f"↩ Put back {back}", "nav": NAV}


# ─── Routes (the screen's list) ───────────────────────────────────────

class CategoryBody(BaseModel):
    business_id: str
    name: str = Field(max_length=NAME_MAX * 2)
    bucket: str = Field(default="operating", max_length=12)
    line: Optional[str] = Field(default=None, max_length=80)      # a line's key or name; wins over bucket


def _route_gate(business_id: str, user: Any, *, write: bool) -> Dict[str, Any]:
    if not _UUID.match(str(business_id or "")):
        raise HTTPException(400, "business_id must be a uuid")
    import plaid_router
    if write:
        return plaid_router._require_money_writer(business_id, user)
    return plaid_router._require_reader(business_id, user)


def _can_change(business_id: str, user: Any, row: Dict[str, Any]) -> bool:
    import church_money_gate
    return church_money_gate.can_write(business_id, user, row)


def _card_on(business_id: str) -> bool:
    """The card switches on with Chief's categories (CHIEF_BANK_SEARCH)."""
    import chief_transactions
    return bool(chief_transactions.switched_on(business_id))


@router.get("")
def get_categories(business_id: str = Query(...), year: Optional[int] = Query(None, ge=2000, le=2100),
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _route_gate(business_id, user, write=False)
    try:
        return {"ok": True, "can_change": _can_change(business_id, user, row),
                "card": _card_on(business_id), **picture(business_id, year)}
    except Unavailable:
        raise HTTPException(503, "The categories can't be read just now. If this is new, its table may not be set up yet.")


@router.post("")
def post_category(body: CategoryBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _route_gate(body.business_id, user, write=True)
    try:
        row, made = create(body.business_id, user.id, body.name, body.bucket, body.line)
    except Unavailable:
        raise HTTPException(503, "The category didn't save. Try again.")
    return {"ok": True, "category": row, "made": made}


class ChangeBody(BaseModel):
    business_id: str
    category: str = Field(max_length=NAME_MAX * 2)
    name: Optional[str] = Field(default=None, max_length=NAME_MAX * 2)
    bucket: Optional[str] = Field(default=None, max_length=12)
    into: Optional[str] = Field(default=None, max_length=NAME_MAX * 2)
    line: Optional[str] = Field(default=None, max_length=80)


class UndoBody(BaseModel):
    business_id: str
    batch_id: str = Field(max_length=64)


def _card_gate(business_id: str, user: Any) -> None:
    _route_gate(business_id, user, write=True)
    if not _card_on(business_id):
        raise HTTPException(403, "Changing categories here isn't switched on for this business yet.")


def _said(out: Dict[str, Any]) -> str:
    r = str(out.get("result") or "")
    r = r[len("Failed: "):] if r.startswith("Failed: ") else r
    return r[:1].upper() + r[1:]


def _record(business_id: str, user_id: Any, action: Dict[str, Any], out: Dict[str, Any],
            action_type: str = "set_expense_category") -> bool:
    """The card's change goes in the same undo log as Chief's, so its Undo
    button and 'Chief, undo that' both take it back."""
    if out.get("failed") or not out.get("batch_id") or not out.get("changes"):
        return False
    try:
        res = sb_clients.sb_post_as_service("/chief_undo_log", {
            "business_id": business_id, "user_id": str(user_id), "action_type": action_type,
            "action_json": action, "result_json": out, "status": "undoable"})
    except Exception as e:                                # the change stands; only its undo is lost
        print(f"[expense_categories] undo log write failed: {e}")
        return False
    return bool(res)


@router.post("/change")
def post_change(body: ChangeBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Rename one (a new name and/or bucket) or merge one into another, from
    the card. A label in use but not on the list can be merged too."""
    _card_gate(body.business_id, user)
    if not name_of(body.category):
        raise HTTPException(422, "Say which category to change.")
    if not (name_of(body.name) or name_of(body.into) or body.line or body.bucket):
        raise HTTPException(422, "Give it a new name or line, or say which category to merge it into.")
    action = {k: v for k, v in {"category": body.category, "name": body.name, "bucket": body.bucket,
                                "into": body.into, "line": body.line}.items() if v}
    return _answer(body.business_id, user.id, action, change(body.business_id, user.id, action, say_undo=False),
                   "set_expense_category")


def _answer(business_id: str, user_id: Any, action: Dict[str, Any], out: Dict[str, Any], atype: str) -> Dict[str, Any]:
    if out.get("failed"):
        raise HTTPException(409, _said(out))
    logged = _record(business_id, user_id, action, out, atype)
    text = _said(out)
    if out.get("changes") and not logged:               # it stands, but nothing can take it back: say so
        text += " Its undo record didn't save, so this one can't be undone from here or by Chief."
    return {"ok": True, "said": text, "batch_id": out["batch_id"] if logged else None,
            "partial": bool(out.get("partial"))}


# ─── The lines (expense_lines.py) ─────────────────────────────────────

class LineBody(BaseModel):
    business_id: str
    line: Optional[str] = Field(default=None, max_length=80)      # which line: its key or name
    name: Optional[str] = Field(default=None, max_length=80)      # its new name, or a new line's
    base: Optional[str] = Field(default=None, max_length=80)      # a new line counts as this one in the books
    remove: bool = False


@router.get("/lines")
def get_lines(business_id: str = Query(...), user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The business's lines and their names, for every screen that shows one."""
    import expense_lines
    row = _route_gate(business_id, user, write=False)
    try:
        ls = expense_lines.lines(business_id, strict=True)
    except Unavailable:
        raise HTTPException(503, "The lines can't be read just now.")
    return {"ok": True, "lines": [{k: ln[k] for k in ("key", "name", "base", "builtin")} for ln in ls],
            "card": _card_on(business_id), "can_change": _can_change(business_id, user, row)}


@router.post("/lines")
def post_line(body: LineBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Rename a line, add one, or remove one of the business's own, from the card."""
    import expense_lines
    _card_gate(body.business_id, user)
    action = {k: v for k, v in {"line": body.line, "name": body.name, "base": body.base,
                                "remove": body.remove}.items() if v}
    if not (body.line or name_of(body.name)):
        raise HTTPException(422, "Say which line, or give a new line its name.")
    return _answer(body.business_id, user.id, action,
                   expense_lines.change(body.business_id, user.id, action, say_undo=False), "set_expense_line")


@router.post("/undo")
def post_undo(body: UndoBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _card_gate(body.business_id, user)
    out = take_back(body.business_id, body.batch_id)
    if out.get("failed"):
        raise HTTPException(409, _said(out))
    return {"ok": True, "said": out["result"]}


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
    import expense_lines
    cats, ls = p["categories"], p["lines"]
    text = ("Lines: " + "; ".join(
        ln["name"] + ("" if ln["builtin"] else f" (counts as {expense_lines.said(ls, ln['base'])})") for ln in ls) + ". ")
    text += (f"{len(cats)} categories: " + "; ".join(
        f"{c['name']} ({expense_lines.said(ls, c['line'])}, {c['count']} this year, ${c['total']:,.2f})"
        for c in cats[:25]) + "." if cats else "No categories saved yet.")
    if p["unsaved"]:
        text += " In use but not on the list: " + "; ".join(
            f"{u['label']} ({expense_lines.said(ls, u['line'])}, {u['count']})" for u in p["unsaved"][:10]) + "."
    text += f" {len(rs)} every-time rule(s)."
    return {"type": atype, "result": text, "label": "🗂 Categories", "lines": ls, "categories": cats,
            "unsaved": p["unsaved"][:30],
            "rules": [{"payee": r["merchant_name"], "answer": r["business_category"],
                       "label": r.get("business_subcategory")} for r in rs[:60]],
            "note_for_chief": ("File under the saved names exactly. Offer to save a label that's in use but not "
                               "listed, and to merge two that mean the same thing; ask first. Say the lines by "
                               "these names, never Operating/Owner pay/Tax/Savings when they're named otherwise."),
            "nav": NAV}


async def handle_expense_categories(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_list_sync, biz, action or {})


async def handle_set_expense_category(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(set_category, str(biz["id"]), action or {})


async def handle_save_category_rule(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(remember, str(biz["id"]), action or {})


async def handle_undo_category_change(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo, str(biz["id"]), action or {})


def set_line(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Chief's verb: rename a line, add one, or remove one of the business's own."""
    refused = _gate(business_id, write=True)
    if refused:
        return _fail("set_expense_line", refused.replace("Categories", "Lines").replace("categories", "lines"))
    import expense_lines
    return expense_lines.change(business_id, _uid(), action)


async def handle_set_expense_line(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(set_line, str(biz["id"]), action or {})
