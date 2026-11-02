"""
chief_reconcile.py — "reconcile all the transactions you can", and undo.

Kevin, 2026-10-30: "chief should be able to do pretty much all that i can do
upon request except things that require my permission. so that way is
someone say reconcile all the transaction it can and allow me to check what
it done if I want." Then: "pick the best options".

reconcile_books does, in one batch, only what is CLEAR:

    payout ........ a deposit that matches a Stripe payout (the same matcher
                    the bank sync runs on its own: plaid_reconciliation)
    sent .......... a payment out that matches a Stripe transfer we sent
    own transfer .. money that left one of the business's own accounts and
                    landed in another, the same amount within days, and BOTH
                    sides say transfer. money_kind='transfer' on both legs;
                    the deposit leg is settled with the reason
    no payout ..... a deposit that can't be a Stripe payout (no Stripe
                    account, or nothing in it says Stripe): settled as
                    'ignored' with the reason written on the row, which is
                    what the Reconciliation screen's Ignore does

Everything else is left alone and listed: a deposit that says Stripe but
matched nothing, rows past the per-run cap. Nothing here decides what money
IS: a PayPal deposit the bank calls a transfer is not counted as income, and
whether it is giving is the owner's answer, so the result asks rather than
relabels.

CHECK WHAT IT DID. The result is a card listing every row changed and why,
and it records each row's values from before. undo_reconcile_books puts one
batch back (the newest, or a batch_id), row by row, and skips any row that
someone changed since, so an undo never overwrites a later decision. undo_last
reaches it too, for a day; asked by name, for RECONCILE_UNDO_DAYS.

Who may: the owner, or a church's Admin seat (the treasurer), the same gate
as the Reconciliation screen's writes (plaid_router._require_money_writer,
the church money wall included), as the person
talking. Bulk, so it never runs unprompted (policy_engine). Same switch as
the bank search: CHIEF_BANK_SEARCH.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("chief_reconcile")

# Deposits sent to the Stripe matcher per run (one Stripe call each).
DEPOSIT_CAP = 200
_PAGE = 1000
_ROW_CAP = 5000
RECONCILE_UNDO_DAYS = 30
CARD_ROWS = 60
_CHUNK = 40

_FIELDS = ("reconciliation_status", "reconciled_to_payout_id", "reconciled_to_transfer_id",
           "reconciled_payout_amount", "reconciled_payout_date", "manual_match_reason",
           "ignored_at", "money_kind")
_ROW_SELECT = ("transaction_id,account_id,amount,date,name,merchant_name,business_id,"
               "plaid_category_primary,plaid_category_detail,reconciliation_status,"
               "reconciled_to_payout_id,reconciled_to_transfer_id,reconciled_payout_amount,"
               "reconciled_payout_date,manual_match_reason,ignored_at")
_TRANSFER_WORDS = re.compile(r"\b(transfer|xfer|trnsfr|tfr)\b", re.I)
_STRIPE = re.compile(r"stripe", re.I)

WHAT = {
    "payout": "Matched to a Stripe payout",
    "sent": "Matched to a Stripe transfer you sent",
    "own_transfer": "A move between your own accounts",
    "no_payout": "Not a Stripe payout: nothing to match",
}

COLUMNS = [
    {"key": "date", "label": "Date", "kind": "date"},
    {"key": "description", "label": "Description", "kind": "text"},
    {"key": "amount", "label": "Amount", "kind": "money"},
    {"key": "what", "label": "What I did", "kind": "text"},
]


class _Unavailable(Exception):
    """A read came back as a failure, not as nothing."""


# ─── Pure: what to change ─────────────────────────────────────────────

def _amt(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(t: Dict[str, Any]) -> str:
    return f"{t.get('name') or ''} {t.get('merchant_name') or ''}"


def says_transfer(t: Dict[str, Any]) -> bool:
    primary = str(t.get("plaid_category_primary") or "").upper()
    side = "TRANSFER_IN" if _amt(t) < 0 else "TRANSFER_OUT"
    return primary.startswith(side) or bool(_TRANSFER_WORDS.search(_text(t)))


def _before(t: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: t.get(k) for k in keys}


def _change(kind: str, t: Dict[str, Any], after: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    name = (t.get("merchant_name") or t.get("name") or "(no description)").strip()
    return {
        "id": t["transaction_id"],
        "kind": kind,
        "before": _before(t, after.keys()),
        "after": after,
        # The business's view: money in positive, money out negative.
        "row": {"id": t["transaction_id"], "date": str(t.get("date") or "")[:10],
                "description": name[:80], "amount": round(-_amt(t), 2),
                "what": (WHAT[kind] + (f" ({note})" if note else ""))[:120]},
    }


def plan(deposits: List[Dict[str, Any]], outs: List[Dict[str, Any]], *,
         match: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
         has_stripe: bool, kinds_supported: bool,
         pair: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
         account_label: Callable[[Optional[str]], str],
         today: Optional[date] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(changes, left). `deposits` are unmatched money in, newest first,
    already capped; `outs` are money out with no answer yet, for pairing
    and for the sent-transfer matcher (`match` decides)."""
    stamp = (today or date.today()).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    changes: List[Dict[str, Any]] = []
    left: List[Dict[str, Any]] = []
    settled: set = set()

    for t in deposits + outs:
        patch = match(t)
        if patch:
            kind = "payout" if _amt(t) < 0 else "sent"
            changes.append(_change(kind, t, dict(patch)))
            settled.add(t["transaction_id"])

    if kinds_supported:
        rest = [t for t in deposits + outs
                if t["transaction_id"] not in settled and not t.get("money_kind")]
        for p in pair(rest):
            o, i = p["out"], p["in"]
            if not (says_transfer(o) and says_transfer(i)):
                continue
            changes.append(_change("own_transfer", o, {"money_kind": "transfer"},
                                   f"to {account_label(i.get('account_id'))}"))
            reason = (f"Chief, {stamp}: moved from {account_label(o.get('account_id'))} "
                      f"on {str(o.get('date') or '')[:10]}")
            changes.append(_change("own_transfer", i, {
                "money_kind": "transfer", "reconciliation_status": "ignored",
                "ignored_at": now, "manual_match_reason": reason[:200]},
                f"from {account_label(o.get('account_id'))}"))
            settled.update((o["transaction_id"], i["transaction_id"]))

    for t in deposits:
        if t["transaction_id"] in settled:
            continue
        if _STRIPE.search(_text(t)):
            left.append({**t, "_why": "says Stripe, but no payout matched"})
            continue
        why = ("no Stripe account is connected, so there's no payout to match" if not has_stripe
               else "not a Stripe payout, so there's nothing to match")
        changes.append(_change("no_payout", t, {
            "reconciliation_status": "ignored", "ignored_at": now,
            "manual_match_reason": f"Chief, {stamp}: {why}"[:200]}))
    return changes, left


def not_counted_as_income(changes: List[Dict[str, Any]], by_id: Dict[str, Dict[str, Any]]) -> int:
    """Deposits settled as 'nothing to match' that the books don't count as
    income (the bank calls them transfers: PayPal, Zelle, Venmo...)."""
    import bank_money
    n = 0
    for c in changes:
        t = by_id.get(c["id"])
        if c["kind"] == "no_payout" and t and not bank_money.is_income(t) and not bank_money.kind(t):
            n += 1
    return n


# ─── Reading and writing ──────────────────────────────────────────────

def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise _Unavailable(path.split("?")[0])
    return rows


def _read_all(path: str, cap: int = _ROW_CAP) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    while True:
        page = _get(f"{path}&limit={_PAGE}&offset={len(rows)}")
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > cap:
            raise _Unavailable(path.split("?")[0] + " (over the row cap)")


def _guard(values: Dict[str, Any]) -> str:
    """PostgREST filters that hold only while the row still has `values`
    on the fields this batch touches."""
    parts = []
    for k in ("reconciliation_status", "money_kind"):
        if k not in values:
            continue
        v = values[k]
        parts.append(f"{k}=is.null" if v is None else f"{k}=eq.{v}")
    return "&".join(parts)


def _patch(business_id: str, tid: str, guard: Dict[str, Any], body: Dict[str, Any]) -> Optional[bool]:
    """True: written. False: the row changed under us (nothing matched).
    None: the write failed."""
    path = f"/plaid_transactions?business_id=eq.{business_id}&transaction_id=eq.{tid}"
    g = _guard(guard)
    if g:
        path += "&" + g
    res = sb_clients.sb_patch_as_service(
        path, {**body, "updated_at": datetime.now(timezone.utc).isoformat()})
    if res is None:
        return None
    return bool(res) if isinstance(res, list) else True


def _owner(business_id: str) -> Optional[str]:
    """None when the person talking may change the bank rows; else why not."""
    from chief_of_staff import _TURN_USER_ID
    user_id = _TURN_USER_ID.get()
    if not user_id:
        return "Reconciling is done only for a signed-in person who keeps the books."
    from fastapi import HTTPException
    import plaid_router
    try:
        plaid_router._require_money_writer(business_id, SimpleNamespace(id=user_id))
    except HTTPException as e:
        if e.status_code == 403 and not isinstance(e.detail, dict):
            return ("Only the owner, or a church's Admin, can reconcile the books, the same as on the "
                    "Reconciliation screen.")
        detail = e.detail.get("message") if isinstance(e.detail, dict) else e.detail
        return str(detail or "This login can't change the bank rows.")
    return None


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    logger.info(f"{atype} failed: {msg}")
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True,
            "nav": {"tab": "operate", "sub": "bookkeeping"}}


def _sent_matcher(business_id: str) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """try_match_transaction, called only where a match is possible: every
    deposit when Stripe is connected, and only the payments out whose amount
    equals a paid Stripe transfer (each attempt is a lookup)."""
    import plaid_reconciliation as pr
    has_stripe = bool(pr.stripe_account_for_business(business_id))
    sent = _get(f"/outbound_transfers?business_id=eq.{business_id}&status=eq.paid"
                f"&select=amount&limit=1000")
    sent_cents = {int(round(float(s.get("amount") or 0) * 100)) for s in sent}

    def match(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        a = _amt(t)
        if a < 0 and not has_stripe:
            return None
        if a > 0 and int(round(a * 100)) not in sent_cents:
            return None
        return pr.try_match_transaction({**t, "business_id": business_id})
    match.has_stripe = has_stripe  # type: ignore[attr-defined]
    return match


def reconcile(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import chief_transactions
    import bank_money
    import bookkeeping_overview as bo
    atype = "reconcile_books"
    if not chief_transactions.switched_on(business_id):
        return _fail(atype, "Reconciling from chat isn't switched on for this business yet. "
                            "Bookkeeping → Reconciliation does it on screen.")
    refused = _owner(business_id)
    if refused:
        return _fail(atype, refused)
    try:
        accts = _get(f"/plaid_accounts?business_id=eq.{business_id}&deleted_at=is.null"
                     f"&included_in_bookkeeping=eq.true"
                     f"&select=account_id,name,official_name,mask,type,is_trust_account")
        accts = [a for a in accts if a.get("account_id") and not a.get("is_trust_account")]
        if not accts:
            return {"type": atype, "label": "Nothing to reconcile",
                    "result": "No bank account is in the books yet, so there's nothing to reconcile.",
                    "nav": {"tab": "operate", "sub": "bookkeeping"}}
        by_acct = {a["account_id"]: a for a in accts}
        scope = (f"business_id=eq.{business_id}&account_id=in.({','.join(by_acct)})"
                 f"&pending=eq.false&excluded_from_books=eq.false&reconciliation_status=eq.unmatched")
        kinds = bank_money.supported()
        select = _ROW_SELECT + bank_money.cols()
        all_deposits = _read_all(f"/plaid_transactions?{scope}&amount=lt.0"
                                 f"&select={select}&order=date.desc,transaction_id.asc")
        # A deposit matched to recorded gifts (giving_deposits.py) is answered.
        all_deposits = [t for t in all_deposits if t.get("money_kind") not in bank_money.MATCHED_ONLY]
        deposits = all_deposits[:DEPOSIT_CAP]
        outs: List[Dict[str, Any]] = []
        if deposits:
            dates = [str(t.get("date") or "")[:10] for t in deposits if t.get("date")]
            lo = (date.fromisoformat(min(dates)) - timedelta(days=bo.TRANSFER_WINDOW_DAYS)).isoformat()
            hi = (date.fromisoformat(max(dates)) + timedelta(days=bo.TRANSFER_WINDOW_DAYS)).isoformat()
            outs = _read_all(f"/plaid_transactions?{scope}&amount=gt.0&date=gte.{lo}&date=lte.{hi}"
                             + ("&money_kind=is.null" if kinds else "")
                             + f"&select={select}&order=date.desc,transaction_id.asc")
        match = _sent_matcher(business_id)
    except _Unavailable as e:
        logger.warning(f"[chief_reconcile] read failed: {e}")
        return _fail(atype, "the bank rows couldn't be read just now, so nothing was changed. Try again.")

    changes, left = plan(
        deposits, outs, match=match, has_stripe=match.has_stripe, kinds_supported=kinds,  # type: ignore[attr-defined]
        pair=lambda rows: bo.find_transfer_pairs(rows, by_acct),
        account_label=lambda aid: bo.account_label(by_acct.get(aid)))

    done: List[Dict[str, Any]] = []
    moved, failed = 0, 0
    for c in changes:
        ok = _patch(business_id, c["id"], c["before"], c["after"])
        if ok:
            done.append(c)
        elif ok is False:
            moved += 1
        else:
            failed += 1

    by_id = {t["transaction_id"]: t for t in deposits + outs}
    return summarize(done, left, moved=moved, failed=failed,
                     over_cap=max(0, len(all_deposits) - len(deposits)),
                     not_income=not_counted_as_income(done, by_id))


def summarize(done: List[Dict[str, Any]], left: List[Dict[str, Any]], *, moved: int, failed: int,
              over_cap: int, not_income: int) -> Dict[str, Any]:
    counts = {k: sum(1 for c in done if c["kind"] == k) for k in WHAT}
    bits = []
    if counts["payout"]:
        bits.append(f"{counts['payout']} matched to Stripe payouts")
    if counts["sent"]:
        bits.append(f"{counts['sent']} matched to Stripe transfers you sent")
    if counts["own_transfer"]:
        bits.append(f"{counts['own_transfer'] // 2} moves between your own accounts "
                    f"({counts['own_transfer']} rows)")
    if counts["no_payout"]:
        bits.append(f"{counts['no_payout']} deposits marked 'nothing to match' (not Stripe payouts)")
    if done:
        result = f"Reconciled {len(done)} bank rows: " + "; ".join(bits) + "."
    else:
        result = "Nothing was clear enough to reconcile, so nothing changed."
    if left:
        result += f" Left for you: {len(left)} (" + "; ".join(
            sorted({t['_why'] for t in left})) + ")."
    if over_cap:
        result += f" {over_cap} older unmatched deposits weren't looked at this time; ask again for them."
    if moved:
        result += f" {moved} changed while I worked and were left as they are."
    if failed:
        result += f" {failed} didn't save; nothing else was affected. Ask again to retry them."
    if done:
        result += " Every change is listed and can be undone as one batch."

    rows = [c["row"] for c in done[:CARD_ROWS]]
    note = ("Say what the result says, in plain words, and that the card lists every change. "
            "Offer undo (undo_reconcile_books) without pushing it.")
    if not_income:
        note += (f" {not_income} of the deposits marked 'nothing to match' are ones the bank calls "
                 "transfers (PayPal, Zelle and the like), so the books don't count them as income. "
                 "Ask whether they're giving or income; don't relabel them yourself.")
    out: Dict[str, Any] = {
        # The verb, not show_view: the answer check reads a result's effect
        # from its type, and as show_view (a read) "I reconciled 49 bank
        # rows" had no write receipt and was withheld (2026-10-30, live).
        # `display: table` is what tells the app to draw the card.
        "type": "reconcile_books",
        "display": "table",
        "view": "reconciled",
        "filter": "batch",
        "title": "What I reconciled",
        "form": "list",
        "date_key": "date",
        "columns": COLUMNS,
        "rows": rows,
        "summary": {"count": len(done)},
        "limit_reached": len(done) > len(rows),
        "result": result,
        "label": (f"🏦 Reconciled {len(done)} bank rows" if done else "🏦 Nothing to reconcile")[:120],
        "speak": result,
        "note_for_chief": note,
        "counts": counts,
        "left": [{"date": str(t.get("date") or "")[:10],
                  "description": (t.get("merchant_name") or t.get("name") or "")[:80],
                  "amount": round(-_amt(t), 2), "why": t["_why"]} for t in left[:20]],
        "nav": {"tab": "operate", "sub": "bookkeeping"},
    }
    if done:
        out["batch_id"] = uuid.uuid4().hex
        out["changes"] = [{"id": c["id"], "kind": c["kind"], "before": c["before"], "after": c["after"]}
                          for c in done]
    if failed and not done:
        out["failed"] = True
        out["result"] = "Failed: " + result
    return out


# ─── Undo ─────────────────────────────────────────────────────────────

def _batch(business_id: str, batch_id: Optional[str]) -> Optional[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=RECONCILE_UNDO_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = _get(f"/chief_undo_log?business_id=eq.{business_id}&action_type=eq.reconcile_books"
                f"&status=eq.undoable&created_at=gte.{since}&order=created_at.desc&limit=50"
                f"&select=id,result_json,created_at")
    for r in rows:
        res = r.get("result_json") or {}
        if not isinstance(res, dict) or not res.get("changes"):
            continue
        if batch_id is None or res.get("batch_id") == batch_id:
            return r
    return None


def undo(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    import chief_transactions
    atype = "undo_reconcile_books"
    if not chief_transactions.switched_on(business_id):
        return _fail(atype, "Reconciling from chat isn't switched on for this business yet.")
    refused = _owner(business_id)
    if refused:
        return _fail(atype, refused)
    batch_id = str(action.get("batch_id") or "").strip() or None
    if batch_id and not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        return _fail(atype, "that isn't a reconcile batch I recorded")
    try:
        row = _batch(business_id, batch_id)
    except _Unavailable:
        return _fail(atype, "the record of what I reconciled couldn't be read just now; nothing changed")
    if not row:
        return _fail(atype, f"there's no reconcile batch of mine from the last {RECONCILE_UNDO_DAYS} days "
                            "left to undo. Single rows can be unmatched on the Reconciliation screen.")
    changes = row["result_json"]["changes"]
    put_back, skipped, failed = 0, 0, 0
    for c in changes:
        if not isinstance(c, dict) or not isinstance(c.get("before"), dict) \
                or not isinstance(c.get("after"), dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(c.get("id"))):
            failed += 1
            continue
        before = {k: v for k, v in c["before"].items() if k in _FIELDS}
        after = {k: v for k, v in c["after"].items() if k in _FIELDS}
        ok = _patch(business_id, c["id"], after, before)
        if ok:
            put_back += 1
        elif ok is False:
            skipped += 1
        else:
            failed += 1
    if failed:
        # The batch stays undoable: asking again retries these, and the rows
        # already put back no longer pass the guard, so they're skipped.
        return _fail(atype, f"only part of it went back: {put_back} rows put back, {failed} didn't "
                            "save. Ask again to finish.")
    sb_clients.sb_patch_as_service(f"/chief_undo_log?id=eq.{row['id']}", {
        "status": "undone", "undone_at": datetime.now(timezone.utc).isoformat(),
        "undo_result": f"put back {put_back}, skipped {skipped}"})
    result = f"Put back {put_back} bank rows the way they were before I reconciled them."
    if skipped:
        result += f" {skipped} had been changed since, so I left them as they are now."
    return {"type": atype, "result": result, "label": f"↩ Put back {put_back} bank rows",
            "nav": {"tab": "operate", "sub": "bookkeeping"}}


async def handle_reconcile_books(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(reconcile, str(biz["id"]), action or {})


async def handle_undo_reconcile_books(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo, str(biz["id"]), action or {})
