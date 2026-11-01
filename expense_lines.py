"""
expense_lines.py — a business's own names for the lines of its books, and
lines of its own.

Kevin, 2026-11-01: "build option 1 with church names as default but allow for
them to be changed because other business would want different names also
allow for there to be added more to this list."

    THE FIVE ........ operating, owner_pay, tax, savings, other: the books'
                      expense accounts (5000-5900, gl_engine) and the only
                      values business_category takes. They never move; a
                      business only names them
    DEFAULT NAMES ... a church starts with church names (Ministry &
                      operations, Pastor & staff pay, Taxes, Reserves, Other);
                      everyone else with Operating, Owner pay, Tax, Savings,
                      Other. Either can rename any of them
    ADDED LINES ..... a line of the business's own ("Missions") that counts as
                      one of the five in the books (its base). Categories
                      placed on it (expense_categories.line) show under it as
                      its own section of the Profit & Loss (present()); the
                      accounts, the ledger and the accountant's trial balance
                      don't change
    CHANGES ......... rename, add, remove (an added line only: its categories
                      go back to its base line); one batch, undone like a
                      category change (expense_categories.take_back)

Switched with Chief's categories (CHIEF_BANK_SEARCH). Off: the standard five
names and no added lines, exactly as before. Table:
supabase/APPLY-2026-11-01-expense-lines.sql.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("expense_lines")

BASE = ("operating", "owner_pay", "tax", "savings", "other")       # the list's order
STANDARD = {"operating": "Operating", "owner_pay": "Owner pay", "tax": "Tax", "savings": "Savings", "other": "Other"}
CHURCH = {"operating": "Ministry & operations", "owner_pay": "Pastor & staff pay", "tax": "Taxes",
          "savings": "Reserves", "other": "Other"}
NAME_MAX = 40
MAX_ADDED = 20
_ADDED_KEY = re.compile(r"^l_[0-9a-f]{8}$")


class Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise Unavailable(path.split("?")[0])
    return rows


def name_of(v: Any) -> str:
    return " ".join(str(v or "").split())[:NAME_MAX]


def _key(v: Any) -> str:
    import expense_categories
    return expense_categories.key_of(v)


# ─── The list ─────────────────────────────────────────────────────────

def on(business_id: Any) -> bool:
    """Named and added lines switch on with Chief's categories."""
    try:
        import chief_transactions
        return bool(chief_transactions.switched_on(business_id))
    except Exception:
        return False


def _is_church(business_id: str) -> bool:
    rows = _get(f"/businesses?id=eq.{_q(business_id)}&select=type&limit=1")
    try:
        import vertical_registry
        return bool(rows) and vertical_registry.resolve(rows[0].get("type")) == "ministry"
    except Exception:
        return False


def standard() -> List[Dict[str, Any]]:
    return [{"key": b, "name": STANDARD[b], "base": b, "builtin": True} for b in BASE]


def _rows(business_id: str) -> List[Dict[str, Any]]:
    return _get(f"/expense_lines?business_id=eq.{_q(business_id)}&archived_at=is.null"
                "&select=id,key,name,base,created_at&order=created_at.asc&limit=200")


def lines(business_id: str, *, strict: bool = False) -> List[Dict[str, Any]]:
    """[{key, name, base, builtin}] in the list's order: each built-in line,
    then the lines added on it. Off: the standard five. A failed read raises
    when strict, else answers the standard five (a label never breaks a page)."""
    if not on(business_id):
        return standard()
    try:
        rows = _rows(business_id)
        names = dict(CHURCH if _is_church(business_id) else STANDARD)
    except Unavailable:
        if strict:
            raise
        return standard()
    for r in rows:
        if r.get("key") in BASE:
            names[r["key"]] = r["name"]
    out: List[Dict[str, Any]] = []
    for b in BASE:
        out.append({"key": b, "name": names[b], "base": b, "builtin": True})
        out += [{"key": r["key"], "name": r["name"], "base": b, "builtin": False, "id": r["id"]}
                for r in rows if _ADDED_KEY.match(str(r.get("key") or "")) and r.get("base") == b]
    return out


def names(business_id: str) -> Dict[str, str]:
    """key -> the business's name for it (the five always present)."""
    return {ln["key"]: ln["name"] for ln in lines(business_id)}


def find(ls: List[Dict[str, Any]], v: Any) -> Optional[Dict[str, Any]]:
    """A line by its key, its name, or a built-in's own key ('operating')."""
    s = str(v or "").strip()
    if not s:
        return None
    hit = next((ln for ln in ls if ln["key"] == s or ln["key"] == s.lower()), None)
    if hit:
        return hit
    k = _key(s)
    return next((ln for ln in ls if _key(ln["name"]) == k), None) or \
        next((ln for ln in ls if ln["builtin"] and _key(STANDARD[ln["key"]]) == k), None)


def said(ls: List[Dict[str, Any]], key: Any) -> str:
    ln = next((x for x in ls if x["key"] == key), None)
    return ln["name"] if ln else STANDARD.get(str(key), str(key or "Other"))


# ─── Changes: rename, add, remove ─────────────────────────────────────

def _fail(msg: str) -> Dict[str, Any]:
    import expense_categories
    return expense_categories._fail("set_expense_line", msg)


def change(business_id: str, user_id: Any, action: Dict[str, Any], *, say_undo: bool = True) -> Dict[str, Any]:
    """Rename one ("line", "name"); add one ("name", "base": the line it counts
    as in the books); remove an added one ("line", "remove": true). Each
    caller gates first (Chief's verb, the card's route)."""
    import expense_categories as ec
    atype = "set_expense_line"
    try:
        ls = lines(business_id, strict=True)
        batch = uuid.uuid4().hex
        current = find(ls, action.get("line")) if action.get("line") else None
        if action.get("line") and not current:
            return _fail(f"there's no line called '{name_of(action.get('line'))}'")
        new = name_of(action.get("name"))
        if current and action.get("remove"):
            if current["builtin"]:
                return _fail(f"{current['name']} is one of the five lines your books are built on, so it stays; "
                             "rename it instead")
            changes: List[Dict[str, Any]] = []
            for c in ec.categories(business_id):
                if c.get("line") == current["key"]:
                    if not ec._patch_row(business_id, "expense_categories", c["id"], {"line": current["key"]},
                                         {"line": None}):
                        return ec._partial(atype, batch, changes, 1, f"removing {current['name']}")
                    changes.append({"table": "expense_categories", "id": c["id"], "before": {"line": current["key"]},
                                    "after": {"line": None}})
            stamp = datetime.now(timezone.utc).isoformat()
            if not ec._patch_row(business_id, "expense_lines", current["id"], {"archived_at": None},
                                 {"archived_at": stamp}):
                return ec._partial(atype, batch, changes, 1, f"removing {current['name']}")
            changes.append({"table": "expense_lines", "id": current["id"], "before": {"archived_at": None},
                            "after": {"archived_at": stamp}})
            moved = sum(1 for c in changes if c["table"] == "expense_categories")
            text = (f"Removed the line {current['name']}."
                    + (f" Its {moved} categor{'y' if moved == 1 else 'ies'} went back under "
                       f"{said(ls, current['base'])}." if moved else ""))
        elif current:
            if not new:
                return _fail("say the line's new name")
            clash = find(ls, new)
            if clash and clash["key"] != current["key"]:
                return _fail(f"there's already a line called {clash['name']}")
            if new == current["name"]:
                return _fail(f"it's already called {new}")
            row = next((r for r in _rows(business_id) if r["key"] == current["key"]), None)
            if row:
                if not ec._patch_row(business_id, "expense_lines", row["id"], {"name": row["name"]}, {"name": new}):
                    raise Unavailable("expense_lines")
                changes = [{"table": "expense_lines", "id": row["id"], "before": {"name": row["name"]},
                            "after": {"name": new}}]
            else:                                   # a built-in line's first name of its own
                made = _post({"business_id": business_id, "key": current["key"], "base": current["base"],
                              "name": new, "created_by": str(user_id) if user_id else None})
                changes = [{"table": "expense_lines", "id": made["id"], "before": None, "after": {"name": new}}]
            text = (f"{current['name']} is now called {new}. Its categories and payments stay where they are"
                    + (" in your books." if current["builtin"] else f"; in your books it still counts as "
                       f"{said(ls, current['base'])}."))
        else:
            if not new:
                return _fail("give the new line a name")
            base_line = find(ls, action.get("base") or "operating")
            if not base_line:
                return _fail(f"say which of your lines it counts as in the books: "
                             f"{', '.join(ln['name'] for ln in ls if ln['builtin'])}")
            base = base_line["base"]
            clash = find(ls, new)
            if clash:
                return _fail(f"there's already a line called {clash['name']}")
            if sum(1 for ln in ls if not ln["builtin"]) >= MAX_ADDED:
                return _fail(f"a business keeps at most {MAX_ADDED} lines of its own")
            made = _post({"business_id": business_id, "key": f"l_{uuid.uuid4().hex[:8]}", "base": base,
                          "name": new, "created_by": str(user_id) if user_id else None})
            changes = [{"table": "expense_lines", "id": made["id"], "before": None, "after": {"name": new}}]
            text = (f"Added the line {new}. In your books it counts as {said(ls, base)}; put categories on it "
                    "and your Profit & Loss shows it as its own section.")
    except Unavailable:
        return _fail("the lines couldn't be read or saved just now; nothing changed")
    return {"type": atype, "result": text + (" One undo puts it back." if say_undo else ""), "label": "🗂 Lines",
            "batch_id": batch, "changes": changes, "nav": _nav()}


def _post(body: Dict[str, Any]) -> Dict[str, Any]:
    made = sb_clients.sb_post_as_service("/expense_lines", body)
    row = (made[0] if isinstance(made, list) and made else made) if made else None
    if not isinstance(row, dict) or not row.get("id"):
        raise Unavailable("expense_lines")
    return row


def _nav() -> Dict[str, Any]:
    import expense_categories
    return expense_categories.NAV


# ─── The Profit & Loss, in the business's own lines ───────────────────

def present(business_id: str, report: Dict[str, Any], *, split: bool = True) -> Dict[str, Any]:
    """The P&L's expense sections named as the business names them; with
    `split`, an added line's categories leave their base section for one of
    their own. The totals never change. Works on a whole report (current and
    comparison) or one window. Off, or a failed read: the report as it was."""
    if not on(business_id):
        return report
    try:
        ls = lines(business_id, strict=True)
        added = {ln["key"]: ln for ln in ls if not ln["builtin"]}
        cat_line: Dict[str, str] = {}
        if split and added:
            import expense_categories
            cat_line = {_key(c["name"]): c["line"] for c in expense_categories.categories(business_id)
                        if c.get("line") in added}
    except Exception as e:                           # a label never breaks a report
        print(f"[expense_lines] present skipped for {business_id}: {e}")
        return report
    windows = [report.get("current"), (report.get("comparison") or {}).get("data")] if "current" in report else [report]
    for w in windows:
        exp = (w or {}).get("expenses")
        if isinstance(exp, dict) and isinstance(exp.get("by_bucket"), list):
            exp["by_bucket"] = _sections(exp["by_bucket"], float(exp.get("total") or 0), ls, cat_line)
    return report


def _sections(by_bucket: List[Dict[str, Any]], total: float, ls: List[Dict[str, Any]],
              cat_line: Dict[str, str]) -> List[Dict[str, Any]]:
    by_line: Dict[str, Dict[str, Any]] = {}
    for sec in by_bucket:
        base = sec.get("bucket") if sec.get("bucket") in BASE else "other"
        for ln in sec.get("lines") or []:
            target = cat_line.get(_key(ln.get("subcategory")))
            line = target if target and next((x for x in ls if x["key"] == target), {}).get("base") == base else base
            s = by_line.setdefault(line, {"bucket": base, "line": line, "label": said(ls, line), "total": 0.0, "lines": []})
            s["total"] += float(ln.get("amount") or 0)
            s["lines"].append(ln)
    out = []
    for ln in ls:                                     # the list's order
        s = by_line.get(ln["key"])
        if not s:
            continue
        s["total"] = round(s["total"], 2)
        s["pct"] = round(s["total"] / total * 100, 1) if total else 0.0
        s["lines"] = sorted(s["lines"], key=lambda x: -float(x.get("amount") or 0))
        out.append(s)
    return out
