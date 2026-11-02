"""
chief_file_bank.py — "put these in expense and revenue": Chief files the bank
rows waiting for an answer, as one batch the owner can check and undo.

Kevin, 2026-10-31, with Love City's January to July statements just added
(327 rows, none with a category): "NOW CAN I ASK CHIEF TO PLACE IN EXPENSE AND
REVENUE ETC WOULD CHIEF DO THAT?" The To review screen answers one row at a
time; chief_bookkeeping_actions approves one proposal at a time; reconcile
settles payouts but never says what money IS. This is the batch, under his
2026-10-30 rule: Chief does what he can do, as one batch he can check and undo.

    bank_to_file ...... the rows waiting for an answer (the To review queue,
                        bookkeeping_overview.build_review: the same rows, the
                        same suggestions), grouped by payee: "40 overdraft
                        fees, money out, $X". A read; Chief proposes an
                        answer per group and asks. A church that records its
                        gifts in Giving is told its giving deposits are those
                        gifts arriving, never income (gifts_recorded)
    file_bank_rows .... the answers the owner CONFIRMED, by payee (every row
                        of that payee still waiting, money in or out) or by
                        transaction id. The same answers the screen gives:
                          money in .... income, owner (money from the owner),
                                        transfer (from another own account)
                          money out ... operating, tax, owner_pay, savings,
                                        owner (a draw), transfer
                          either ...... personal (out of the books)
                        and an optional label (business_subcategory:
                        "Giving", "Utilities", "Bank fees"). Only rows still
                        waiting are touched, each guarded on its values from
                        before, so an answer given meanwhile is never
                        overwritten. One batch; the card lists every row
    undo_file_bank_rows puts one batch back (the newest, or a batch_id),
                        guarded on what Chief wrote, so a later answer stays

The ledger re-posts each row itself (the bank table's update trigger watches
these columns). Who may: the Transactions screen's readers read; the owner,
or a church's Admin seat (the treasurer), files (plaid_router gates, the
church money wall included), as the person talking. Bulk, so it never runs unprompted. Switched with the bank
search: CHIEF_BANK_SEARCH.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("chief_file_bank")

ROW_MAX = 600              # rows filed in one batch
QUEUE_MAX = 5000           # rows read from the queue
GROUPS_SHOWN = 60
IDS_SHOWN = 25             # ids listed per group (a payee files the whole group)
CARD_ROWS = 60
UNDO_DAYS = 30
_CHUNK = 40
_FIELDS = ("money_kind", "business_category", "business_subcategory", "excluded_from_books")
_TX = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
NAV = {"tab": "operate", "sub": "bookkeeping", "bkTab": "transactions"}

# answer -> (what it writes, which way the money may go)
ANSWERS: Dict[str, Tuple[Dict[str, Any], Tuple[str, ...]]] = {
    "income":    ({"money_kind": "income"}, ("in",)),
    "owner":     ({"money_kind": "owner"}, ("in", "out")),
    "transfer":  ({"money_kind": "transfer"}, ("in", "out")),
    "operating": ({"business_category": "operating"}, ("out",)),
    "tax":       ({"business_category": "tax"}, ("out",)),
    "owner_pay": ({"business_category": "owner_pay"}, ("out",)),
    "savings":   ({"business_category": "savings"}, ("out",)),
    "personal":  ({"excluded_from_books": True}, ("in", "out")),
}
SAID = {
    "income": "income", "owner": "money between the owner and the business", "transfer":
    "a move between your own accounts", "operating": "operating expense", "tax": "tax", "owner_pay":
    "owner pay", "savings": "savings", "personal": "personal (out of the books)",
}
COLUMNS = [
    {"key": "date", "label": "Date", "kind": "date"},
    {"key": "description", "label": "Description", "kind": "text"},
    {"key": "amount", "label": "Amount", "kind": "money"},
    {"key": "filed", "label": "Filed as", "kind": "text"},
]


class _Unavailable(Exception):
    """A read or write failed: never shown as nothing."""


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _money(n: float) -> str:
    return f"{'-' if n < 0 else ''}${abs(n):,.2f}"


def _gate(business_id: str, *, write: bool) -> Optional[str]:
    """None when the person talking may; else why not."""
    import chief_transactions
    if not chief_transactions.switched_on(business_id):
        return ("Filing bank rows from chat isn't switched on for this business yet. "
                "Bookkeeping, Transactions, To review does it on screen.")
    from chief_of_staff import _TURN_USER_ID
    uid = _TURN_USER_ID.get()
    if not uid:
        return "The bank rows are read and filed only for a signed-in person who can see the books."
    from fastapi import HTTPException
    import plaid_router
    who = SimpleNamespace(id=uid)
    try:
        if write:
            plaid_router._require_money_writer(business_id, who)
        else:
            plaid_router._require_reader(business_id, who)
    except HTTPException as e:
        if write and e.status_code == 403 and not isinstance(e.detail, dict):
            return ("Only the owner, or a church's Admin, files the bank rows, the same as on the To review "
                    "screen.")
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return str(detail or "This login can't see the books.")
    return None


# ─── Recorded gifts ───────────────────────────────────────────────────

GIFTS_TWICE = ("this church records its gifts in Giving, where they already count as income, so a giving "
               "deposit is those gifts arriving: filing it as income would count it twice. Leave it for the "
               "giving match; if it isn't giving (rent, a sale), say so with not_a_gift")


# How giving reaches a church's bank: a deposit that reads like one of these
# is never filed as income where gifts are recorded, whatever the item says.
_GIVING_CHANNEL = re.compile(r"subsplash|tithe|givelify|pushpay|cash ?app|zelle|venmo|paypal|square|stripe|"
                             r"brch|branch|\batm\b|offering|donat|\bgift", re.I)


def looks_like_giving(name: str) -> bool:
    return bool(_GIVING_CHANNEL.search(name or ""))


def gifts_recorded(business_id: str) -> bool:
    """Does this business record its gifts in Giving (any paid gift in the
    last 400 days)? Then its giving deposits are those gifts arriving, never
    new income. Love City records its gifts by person (Subsplash, cash,
    check, other); every one is already income in the books."""
    since = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{quote(business_id, safe='')}&is_gift=eq.true&status=eq.paid"
        f"&paid_at=gte.{since}&select=id&limit=1")
    if rows is None:
        raise _Unavailable("invoices")
    return bool(rows)


# ─── The queue, grouped ───────────────────────────────────────────────

def spending(business_id: str) -> List[Dict[str, Any]]:
    """Rows already filed as spending (money out, in the books, no money_kind,
    a bucket past 'other'), shaped like the waiting rows, for moving between
    categories."""
    import bank_picks
    import bookkeeping_overview as bo

    def get(path):
        r = sb_clients.sb_get_as_service(path)
        if r is None:
            raise _Unavailable(path.split("?")[0])
        return r
    accts = bank_picks.accounts(business_id, get)
    if not accts:
        return []
    try:
        rows = bank_picks.read_all(
            f"/plaid_transactions?business_id=eq.{quote(business_id, safe='')}&account_id={bank_picks.in_(accts)}"
            "&amount=gt.0&pending=eq.false&excluded_from_books=eq.false&business_category=not.is.null"
            "&business_category=neq.other&select=transaction_id,date,amount,name,merchant_name,business_category,"
            "business_subcategory,money_kind&order=date.desc,transaction_id.asc", get, cap=20_000)
    except bank_picks.TooMany as e:
        raise _Unavailable(str(e))
    return [{"transaction_id": t["transaction_id"], "date": t.get("date"), "name": bo.tx_name(t),
             "amount": float(t.get("amount") or 0), "direction": "out", "business_category": t.get("business_category"),
             "business_subcategory": t.get("business_subcategory"), "money_kind": t.get("money_kind")}
            for t in rows if not t.get("money_kind")]


def queue(business_id: str) -> List[Dict[str, Any]]:
    """The To review queue itself: every row still waiting, newest first."""
    import bookkeeping_overview as bo
    try:
        got = bo.build_review(business_id, QUEUE_MAX)
    except bo.SourceFailed as e:
        raise _Unavailable(str(e))
    return got.get("rows") or []


def _key(r: Dict[str, Any]) -> str:
    import bank_picks
    return bank_picks.payee_key(str(r.get("name") or "")) or "(no description)"


def group(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """By payee and direction, the most rows first. Amounts as the business
    sees them: money in positive, money out negative."""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["direction"], _key(r)), []).append(r)
    out = []
    for (direction, payee), g in groups.items():
        g = sorted(g, key=lambda r: (str(r.get("date") or ""), r["transaction_id"]))
        sugg = {(s or {}).get("label") for s in (r.get("suggestion") for r in g)}
        names = []
        for r in g:
            n = str(r.get("name") or "")[:60]
            if n and n not in names:
                names.append(n)
        out.append({
            "payee": payee, "direction": direction, "count": len(g),
            "total": round(sum(-float(r["amount"]) for r in g), 2),
            "first": str(g[0].get("date") or "")[:10], "last": str(g[-1].get("date") or "")[:10],
            "names": names[:3],
            "suggestion": next(iter(sugg)) if len(sugg) == 1 and None not in sugg else None,
            "transaction_ids": [r["transaction_id"] for r in g][:IDS_SHOWN],
        })
    return sorted(out, key=lambda x: (-x["count"], -abs(x["total"])))


def _to_file_sync(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "bank_to_file"
    business_id = str(biz["id"])
    refused = _gate(business_id, write=False)
    if refused:
        return _fail(atype, refused)
    try:
        rows = queue(business_id)
    except _Unavailable:
        return _fail(atype, "the bank rows couldn't be read just now. This is not 'nothing to file'")
    try:
        gifts: Optional[bool] = gifts_recorded(business_id)
    except _Unavailable:
        gifts = None                     # the groups still show; income waits on the check
    words = [w.lower() for w in (action.get("words") or []) if isinstance(w, str) and w.strip()][:6]
    if action.get("direction") in ("in", "out"):
        rows = [r for r in rows if r["direction"] == action["direction"]]
    if words:
        rows = [r for r in rows if any(w in str(r.get("name") or "").lower() for w in words)]
    if not rows:
        return {"type": atype, "label": "Nothing to file", "nav": NAV,
                "result": "No bank rows are waiting for an answer" + (" that match" if words else "") + "."}
    groups = group(rows)
    shown = groups[:GROUPS_SHOWN]
    import expense_categories as ec
    ec.suggest(business_id, shown)                 # a saved rule, or how the payee was filed before
    try:
        cats = [{"name": c["name"], "bucket": c["bucket"]} for c in ec.categories(business_id)]
    except ec.Unavailable:
        cats = []
    import expense_lines
    lines = expense_lines.names(business_id)       # the business's own names for the answers' lines
    ins = sum(1 for r in rows if r["direction"] == "in")
    text = (f"{len(rows)} bank rows wait for an answer ({ins} money in, {len(rows) - ins} money out), "
            f"in {len(groups)} groups by payee. Largest: " + "; ".join(
                f"{g['names'][0] if g['names'] else g['payee']} ({g['count']}, money {g['direction']}, "
                f"{_money(g['total'])})" for g in shown[:8]) + ".")
    known = sum(1 for g in shown if g.get("suggest"))
    if known:
        text += f" {known} of these payees have been filed before or have a rule, so there's a suggestion for each."
    note = ("Propose an answer for each group in plain words and ASK before filing: where a group has 'suggest', "
            "say so ('your last 6 Duke Energy payments went under Utilities; same here?'); otherwise propose one "
            "from the payee's name and the saved categories. File only what the owner confirms, with "
            "file_bank_rows (by payee, or by transaction_ids for part of a group). After filing a payee the owner "
            "confirmed that has no rule, offer to remember it (save_category_rule) so its next payments file "
            "themselves. ")
    note += ("Never guess money in from a person or an app (Cash App, Zelle, PayPal, a transfer): ask "
            "whether it's giving, the owner's own money, or a move between accounts.")
    if gifts is None:
        text += " Whether this business records its gifts couldn't be checked just now, so nothing is filed as income."
        note += " Don't file anything as income this turn: the gift check is unavailable."
    if gifts:
        text += (" This church records its gifts in Giving, so its giving deposits are those gifts arriving: "
                 "they aren't filed as income (that would count them twice).")
        note += (" IMPORTANT: " + GIFTS_TWICE[0].upper() + GIFTS_TWICE[1:] + ". Propose answers for the "
                 "spending and for money in that isn't giving; leave the giving deposits as they are.")
    return {"type": atype, "label": f"{len(rows)} bank rows to file", "result": text, "nav": NAV,
            "total": len(rows), "groups": shown, "more_groups": max(0, len(groups) - len(shown)),
            "gifts_recorded": gifts, "categories": cats, "lines": lines,
            "note_for_chief": note + " Say a spending answer by its line's name in 'lines' (the answer key stays "
                                     "operating, tax, owner_pay or savings)."}


# ─── Filing ───────────────────────────────────────────────────────────

def _guard(values: Dict[str, Any]) -> str:
    parts = []
    for k in _FIELDS:
        if k not in values:
            continue
        v = values[k]
        if v is None:
            parts.append(f"{k}=is.null")
        elif isinstance(v, bool):
            parts.append(f"{k}=is.{str(v).lower()}")
        else:
            parts.append(f"{k}=eq.{quote(str(v), safe='')}")
    return "&".join(parts)


def _write(business_id: str, ids: List[str], guard: Dict[str, Any], body: Dict[str, Any]) -> List[str]:
    """Rows written (those still holding `guard`); raises when a write fails."""
    done: List[str] = []
    stamp = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(ids), _CHUNK):
        part = ids[i:i + _CHUNK]
        path = (f"/plaid_transactions?business_id=eq.{quote(business_id, safe='')}"
                f"&transaction_id=in.({','.join(quote(t, safe='') for t in part)})")
        g = _guard(guard)
        res = sb_clients.sb_patch_as_service(path + (f"&{g}" if g else ""), {**body, "updated_at": stamp})
        if res is None:
            raise _Unavailable("plaid_transactions")
        done += [str(r.get("transaction_id")) for r in (res if isinstance(res, list) else [])]
    return done


def _label(v: Any) -> Optional[str]:
    s = " ".join(str(v or "").split())[:60]
    return s or None


REFILE_ANSWERS = ("operating", "tax", "owner_pay", "savings")


def plan(rows: List[Dict[str, Any]], items: List[Dict[str, Any]], kinds: bool,
         gifts: Optional[bool] = False, cats: Optional[List[Dict[str, Any]]] = None,
         filed: Optional[List[Dict[str, Any]]] = None,
         paying: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Which rows get which answer: waiting rows, or (an item with "refile")
    rows already filed as spending. Returns (changes, problems)."""
    import expense_categories as ec
    taken: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            problems.append(f"item {n} isn't an answer")
            continue
        refile = it.get("refile") is True
        source = (filed or []) if refile else rows
        by_id = {r["transaction_id"]: r for r in source}
        # A saved category names both the line and the bucket it rolls up to,
        # and its spelling is the one written.
        cat = ec.find(cats or [], it.get("category") or it.get("label"))
        if it.get("category") and not cat:
            problems.append(f"item {n}: there's no category called '{ec.name_of(it.get('category'))}' yet "
                            "(make it with set_expense_category first)")
            continue
        answer = str(it.get("answer") or (cat or {}).get("bucket") or "").strip().lower()
        if cat and answer != cat["bucket"]:
            problems.append(f"item {n}: {cat['name']} is under {ec.BUCKET_SAID[cat['bucket']]}, not "
                            f"{ec.BUCKET_SAID.get(answer, answer)}; leave the answer out, or pick another category")
            continue
        if refile and answer not in REFILE_ANSWERS:
            problems.append(f"item {n}: moving filed rows changes their spending line only "
                            f"({', '.join(REFILE_ANSWERS)}, or a saved category)")
            continue
        if answer not in ANSWERS:
            problems.append(f"item {n}: '{answer}' isn't one of {', '.join(ANSWERS)}")
            continue
        write, ways = ANSWERS[answer]
        if "money_kind" in write and not kinds:
            problems.append(f"item {n}: {SAID[answer]} needs the bank money update, which isn't on yet")
            continue
        if answer == "income" and gifts is None:
            problems.append(f"item {n}: whether this business records its gifts couldn't be checked just now, "
                            "so nothing is filed as income; try again")
            continue
        if answer == "income" and gifts and (it.get("not_a_gift") is not True or not it.get("transaction_ids")):
            problems.append(f"item {n}: {GIFTS_TWICE}" + ("" if it.get("not_a_gift") is not True else
                            " (not_a_gift names rows one by one, never a whole payee)"))
            continue
        ids = [str(t) for t in (it.get("transaction_ids") or []) if isinstance(t, str) and _TX.match(t)]
        payee = " ".join(str(it.get("payee") or "").lower().split())
        direction = it.get("direction") if it.get("direction") in ("in", "out") else None
        from_cat = ec.key_of(it.get("from_category")) if refile and it.get("from_category") else ""
        where = "filed as spending" if refile else "waiting"
        if ids:
            picked = [by_id[t] for t in ids if t in by_id]
            if len(picked) < len(ids):
                problems.append(f"item {n}: {len(ids) - len(picked)} of its rows aren't {where} "
                                + ("(not money out filed as an expense)" if refile else
                                   "any more (answered already, or not in the books)"))
        elif payee or from_cat:
            picked = [r for r in source if (not payee or _key(r) == payee)
                      and (not from_cat or ec.key_of(r.get("business_subcategory")) == from_cat)
                      and (direction is None or r["direction"] == direction)]
            if not picked:
                problems.append(f"item {n}: nothing {where} matches" + (f" '{payee}'" if payee else "")
                                + (f" in {ec.name_of(it.get('from_category'))}" if from_cat else ""))
        else:
            problems.append(f"item {n} names no payee, category or rows")
            continue
        label = (cat or {}).get("name") or _label(it.get("label"))
        for r in picked:
            if answer == "income" and gifts and looks_like_giving(str(r.get("name") or "")):
                problems.append(f"{r.get('name')} on {str(r.get('date'))[:10]} reads like a giving deposit, so it "
                                "isn't filed as income here; if it truly isn't giving, answer it on the screen")
                continue
            if r["direction"] not in ways:
                problems.append(f"{r.get('name')} on {str(r.get('date'))[:10]} is money {r['direction']}, "
                                f"so it can't be {SAID[answer]}")
                continue
            if r["transaction_id"] in (paying or {}) and "business_category" not in write:
                problems.append(f"{r.get('name')} on {str(r.get('date'))[:10]} paid a bill, so it stays money out "
                                "in the books; unmatch it from the bill on the Bills tab first")
                continue
            if r["transaction_id"] in taken:
                continue                      # the first answer for a row stands
            after = dict(write)
            if label and answer != "personal":
                after["business_subcategory"] = label
            elif refile:
                after["business_subcategory"] = None   # moved to a bucket alone: the old line goes
            if refile and all(r.get(k) == v for k, v in after.items()):
                continue                      # already there
            before = {k: (r.get(k) if k != "excluded_from_books" else False) for k in after}
            # Every answer is guarded on what makes the row "waiting": in the
            # books, no bucket past 'other', and (where the column is there)
            # no money_kind. An answer given on screen meanwhile fails it.
            before.setdefault("excluded_from_books", False)
            before.setdefault("business_category", r.get("business_category"))
            if kinds:
                before.setdefault("money_kind", r.get("money_kind"))
            taken[r["transaction_id"]] = {
                "id": r["transaction_id"], "answer": answer, "before": before, "after": after,
                "row": {"id": r["transaction_id"], "date": str(r.get("date") or "")[:10],
                        "description": str(r.get("name") or "")[:80], "amount": round(-float(r["amount"]), 2),
                        "filed": (SAID[answer] + (" (not giving, per the owner)" if answer == "income" and gifts
                                                  else "") + (f": {label}" if label and answer != "personal" else ""))[:80]}}
    return list(taken.values()), problems


def file_rows(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import bank_money
    atype = "file_bank_rows"
    refused = _gate(business_id, write=True)
    if refused:
        return _fail(atype, refused)
    items = action.get("items")
    if not isinstance(items, list) or not items:
        return _fail(atype, "say which rows get which answer (items: payee or transaction_ids, and answer)")
    import expense_categories as ec
    try:
        rows = queue(business_id)
        filed = spending(business_id) if any(isinstance(it, dict) and it.get("refile") is True
                                             for it in items[:100]) else []
    except _Unavailable:
        return _fail(atype, "the bank rows couldn't be read just now, so nothing was filed. Try again")
    # The saved list sets a label's spelling. Unreadable, a label is written as
    # typed (as before the list existed); only an item naming a saved
    # "category" needs it, and that one says so.
    cats: List[Dict[str, Any]] = []
    if any(isinstance(it, dict) and (it.get("category") or it.get("label")) for it in items[:100]):
        try:
            cats = ec.categories(business_id)
        except ec.Unavailable:
            if any(isinstance(it, dict) and it.get("category") for it in items[:100]):
                return _fail(atype, "the saved categories couldn't be read just now, so nothing was filed. Try again")
    # Gifts are looked up only when something would be filed as income; a
    # spending-only batch never waits on them.
    gifts: Optional[bool] = False
    if any(isinstance(it, dict) and str(it.get("answer") or "").lower() == "income" for it in items[:100]):
        try:
            gifts = gifts_recorded(business_id)
        except _Unavailable:
            gifts = None
    try:                                              # rows that paid a bill stay money out (bill_payments)
        import bill_payments
        paying = bill_payments._paying(business_id)
    except Exception:
        paying = None
    if paying is None:
        return {"type": atype, "result": "Failed: the bills couldn't be checked just now, so nothing was filed; "
                                         "ask again", "label": "Not filed", "failed": True, "nav": NAV}
    changes, problems = plan(rows, items[:100], bank_money.supported(), gifts, cats, filed, paying)
    if len(changes) > ROW_MAX:
        return _fail(atype, f"that's {len(changes)} rows; one batch files at most {ROW_MAX}. Split it")
    if not changes:
        return _fail(atype, "nothing to file. " + "; ".join(problems[:5]) if problems else "nothing to file")
    # One write per shape (the same values before and after), in chunks.
    shapes: Dict[str, List[Dict[str, Any]]] = {}
    for c in changes:
        shapes.setdefault(repr((sorted(c["before"].items()), sorted(c["after"].items()))), []).append(c)
    written: set = set()
    failed = 0
    for cs in shapes.values():
        try:
            written.update(_write(business_id, [c["id"] for c in cs], cs[0]["before"], cs[0]["after"]))
        except _Unavailable:
            failed += len(cs)
    done = [c for c in changes if c["id"] in written]
    moved = len(changes) - len(done) - failed
    return summarize(done, problems, moved=moved, failed=failed)


def summarize(done: List[Dict[str, Any]], problems: List[str], *, moved: int, failed: int) -> Dict[str, Any]:
    by: Dict[Tuple[str, str], int] = {}
    for c in done:
        k = (c["answer"], c["after"].get("business_subcategory") or "")
        by[k] = by.get(k, 0) + 1
    bits = [f"{n} as {SAID[a]}" + (f" ({lab})" if lab else "") for (a, lab), n in
            sorted(by.items(), key=lambda kv: -kv[1])]
    result = (f"Filed {len(done)} bank rows: " + "; ".join(bits) + "." if done
              else "Nothing was filed.")
    if moved:
        result += f" {moved} were answered by someone else while I worked, so I left them."
    if failed:
        result += f" {failed} didn't save; nothing else was affected. Ask again to retry them."
    if problems:
        result += " Not filed: " + "; ".join(problems[:6]) + ("; and more." if len(problems) > 6 else ".")
    if done:
        result += " Every row is listed and the batch can be undone as one."
    out: Dict[str, Any] = {
        "type": "file_bank_rows", "display": "table", "view": "filed", "filter": "batch",
        "title": "What I filed", "form": "list", "date_key": "date", "columns": COLUMNS,
        "rows": [c["row"] for c in done[:CARD_ROWS]], "summary": {"count": len(done)},
        "limit_reached": len(done) > CARD_ROWS, "result": result, "speak": result,
        "label": (f"🏦 Filed {len(done)} bank rows" if done else "🏦 Nothing filed")[:120],
        "note_for_chief": ("Say what was filed in plain words and that the card lists every row. Offer undo "
                           "(undo_file_bank_rows) without pushing it. Mention anything not filed."),
        "nav": NAV,
    }
    if done:
        out["batch_id"] = uuid.uuid4().hex
        out["changes"] = [{"id": c["id"], "before": c["before"], "after": c["after"]} for c in done]
    if failed and not done:
        out["failed"] = True
        out["result"] = "Failed: " + result
    return out


# ─── Undo ─────────────────────────────────────────────────────────────

def _batch(business_id: str, batch_id: Optional[str]) -> Optional[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=UNDO_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sb_clients.sb_get_as_service(
        f"/chief_undo_log?business_id=eq.{quote(business_id, safe='')}&action_type=eq.file_bank_rows"
        f"&status=eq.undoable&created_at=gte.{since}&order=created_at.desc&limit=50&select=id,result_json,created_at")
    if rows is None:
        raise _Unavailable("chief_undo_log")
    for r in rows:
        res = r.get("result_json") or {}
        if isinstance(res, dict) and res.get("changes") and (batch_id is None or res.get("batch_id") == batch_id):
            return r
    return None


def undo(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "undo_file_bank_rows"
    refused = _gate(business_id, write=True)
    if refused:
        return _fail(atype, refused)
    batch_id = str(action.get("batch_id") or "").strip() or None
    if batch_id and not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        return _fail(atype, "that isn't a batch of bank rows I filed")
    try:
        row = _batch(business_id, batch_id)
    except _Unavailable:
        return _fail(atype, "the record of what I filed couldn't be read just now; nothing changed")
    if not row:
        return _fail(atype, f"there's no batch of bank rows I filed in the last {UNDO_DAYS} days left to undo. "
                            "Single rows can be changed on the Transactions screen.")
    shapes: Dict[str, List[Dict[str, Any]]] = {}
    bad = 0
    for c in row["result_json"]["changes"]:
        if not (isinstance(c, dict) and isinstance(c.get("before"), dict) and isinstance(c.get("after"), dict)
                and _TX.match(str(c.get("id")))):
            bad += 1
            continue
        before = {k: v for k, v in c["before"].items() if k in _FIELDS}
        after = {k: v for k, v in c["after"].items() if k in _FIELDS}
        shapes.setdefault(repr((sorted(before.items()), sorted(after.items()))), []).append(
            {"id": str(c["id"]), "before": before, "after": after})
    put_back, failed = 0, bad
    total = sum(len(cs) for cs in shapes.values())
    for cs in shapes.values():
        try:
            # Guarded on the whole state Chief left (what it wrote, and what it
            # found and kept): a row answered since stays as it is now.
            left = {**cs[0]["before"], **cs[0]["after"]}
            put_back += len(_write(business_id, [c["id"] for c in cs], left, cs[0]["before"]))
        except _Unavailable:
            failed += len(cs)
    skipped = total - put_back - (failed - bad)
    if failed:
        # Stays undoable: asking again retries, and rows already back no longer pass the guard.
        return _fail(atype, f"only part of it went back: {put_back} rows put back, {failed} didn't save. "
                            "Ask again to finish.")
    sb_clients.sb_patch_as_service(f"/chief_undo_log?id=eq.{row['id']}", {
        "status": "undone", "undone_at": datetime.now(timezone.utc).isoformat(),
        "undo_result": f"put back {put_back}, skipped {skipped}"})
    result = f"Put back {put_back} bank rows the way they were before I filed them; they wait in To review again."
    if skipped:
        result += f" {skipped} had been answered since, so I left them as they are now."
    return {"type": atype, "result": result, "label": f"↩ Put back {put_back} bank rows", "nav": NAV}


# ─── Chief ────────────────────────────────────────────────────────────

TO_FILE_TOOL = {
    "name": "bank_to_file",
    "description": (
        "The bank rows still waiting for an answer (the To review queue), grouped by payee: each group's "
        "count, money in or out, total, dates, a sample of the bank's wording, any suggestion, and its payee key "
        "for file_bank_rows. Use it before filing ('put these in expense and revenue', 'categorize the "
        "transactions', 'what still needs a category'). Optional words or direction narrow it. Propose an "
        "answer per group and ask; never file from this alone."),
    "input_schema": {"type": "object", "properties": {
        "words": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "direction": {"type": "string", "enum": ["in", "out"]}}},
}


async def handle_bank_to_file(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(_to_file_sync, biz, action or {})


async def handle_file_bank_rows(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(file_rows, str(biz["id"]), action or {})


async def handle_undo_file_bank_rows(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo, str(biz["id"]), action or {})
