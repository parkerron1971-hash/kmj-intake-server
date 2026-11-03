"""The reports a church needs that a business doesn't (Kevin, 2026-11-03).

Step 4 of the reports plan (https://claude.ai/artifact/78TtG5ZPRio233qhiBi8nS):

  Funds            — each giving fund: given (gifts to it), spent (bank
                     payments placed on the year fund with the same name,
                     Kevin's pick "A"), left. Year funds no giving fund
                     matches are listed on their own with what was spent.
  Giving by fund   — the period's gifts by fund and by how they were given,
  and by way         added to Giving & income.
  Givers / one     — the people who gave in a year, and one person's gifts
  person's giving    by date, fund and way: the church's statement.

Reads only. Gifts come from giving_records.read_gifts (paged, never short);
year funds from funds.py (paged), only where its switch is on.
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import reports_engine


def _norm(name: Any) -> str:
    """A fund's matching key: 'Youth Fund', 'youth', ' YOUTH ' are one fund."""
    n = " ".join(str(name or "").lower().split())
    if n.endswith(" fund"):
        n = n[: -len(" fund")]
    return n or "general"


def _net(g: Dict[str, Any]) -> float:
    amt = float(g.get("total") or 0)
    rc = g.get("refund_amount_cents")
    if rc and float(rc) > 0:
        amt -= float(rc) / 100.0
    return round(amt, 2)


def _fund_of(g: Dict[str, Any]) -> str:
    return (str(g.get("gift_fund") or "").strip()) or "General"


def _gifts(biz: str, start: _date, end: _date, contact_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from giving_records import read_gifts
    return read_gifts(biz, start.isoformat(), (end + timedelta(days=1)).isoformat(), contact_id=contact_id)


def _window(period: str, custom_from: Optional[str], custom_to: Optional[str]) -> Tuple[_date, _date]:
    return reports_engine.period_bounds(period, custom_from, custom_to)


# ─── Funds ────────────────────────────────────────────────────────────

def _configured(biz: str) -> List[str]:
    import sb_clients
    from giving_router import configured_funds
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=settings&limit=1") or []
    settings = (rows[0].get("settings") if rows else None) or {}
    return configured_funds((settings.get("giving") or {}) if isinstance(settings, dict) else {})


def _year_fund_spending(biz: str, start: _date, end: _date) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """name key -> {name, spent, payments} for bank payments placed on year
    funds in the window. (…, False) where year funds are switched off."""
    import funds
    if not funds.switched_on(biz):
        return {}, False
    rows = funds.list_funds(biz)
    out: Dict[str, Dict[str, Any]] = {}
    if not rows:
        return out, True
    for item in funds.items_for(biz, [r["id"] for r in rows]):
        if item.get("direction") != "out":
            continue
        d = str(item.get("entry_date") or "")[:10]
        if not (start.isoformat() <= d <= end.isoformat()):
            continue
        fund = next((r for r in rows if r["id"] == item.get("fund_id")), None)
        if not fund:
            continue
        k = _norm(fund.get("name"))
        e = out.setdefault(k, {"name": fund.get("name"), "spent": 0.0, "payments": 0})
        e["spent"] = round(e["spent"] + float(item.get("amount") or 0), 2)
        e["payments"] += 1
    return out, True


def funds_report(biz: str, period: str = "this_year", custom_from: Optional[str] = None,
                 custom_to: Optional[str] = None) -> Dict[str, Any]:
    from giving_router import is_designated
    start, end = _window(period, custom_from, custom_to)
    funds_by_key: Dict[str, Dict[str, Any]] = {}
    for name in _configured(biz):
        funds_by_key.setdefault(_norm(name), {"fund": name, "given": 0.0, "gifts": 0})
    for g in _gifts(biz, start, end):
        amt = _net(g)
        if amt <= 0:
            continue
        name = _fund_of(g)
        f = funds_by_key.setdefault(_norm(name), {"fund": name, "given": 0.0, "gifts": 0})
        f["given"] = round(f["given"] + amt, 2)
        f["gifts"] += 1
    spending, year_funds_on = _year_fund_spending(biz, start, end)

    rows: List[Dict[str, Any]] = []
    for k, f in funds_by_key.items():
        sp = spending.get(k)
        rows.append({**f, "designated": is_designated(f["fund"]),
                     "spent": sp["spent"] if sp else None,
                     "left": round(f["given"] - sp["spent"], 2) if sp else None,
                     "year_fund": sp["name"] if sp else None})
    rows.sort(key=lambda r: (r["designated"], -r["given"], r["fund"].lower()))
    others = [{"fund": v["name"], "spent": v["spent"], "payments": v["payments"]}
              for k, v in sorted(spending.items()) if k not in funds_by_key]
    return {
        "ok": True, "report": "funds", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "funds": rows,
        "other_funds": others,
        "year_funds_on": year_funds_on,
        "total_given": round(sum(r["given"] for r in rows), 2),
        "total_spent": round(sum(r["spent"] or 0 for r in rows) + sum(o["spent"] for o in others), 2),
        "note": ("Given is the gifts to each fund. Spent is the bank payments placed on the fund "
                 "with the same name in Bookkeeping, Funds; name a fund there like the giving "
                 "fund to see what's left. Tithes and offerings are the general fund."),
    }


# ─── Giving & income: by fund and by way ──────────────────────────────

def by_fund_and_way(biz: str, start: _date, end: _date) -> Dict[str, Any]:
    from giving_ways import method_label
    by_fund: Dict[str, Dict[str, Any]] = {}
    by_way: Dict[str, float] = {}
    for g in _gifts(biz, start, end):
        amt = _net(g)
        if amt <= 0:
            continue
        name = _fund_of(g)
        f = by_fund.setdefault(_norm(name), {"fund": name, "amount": 0.0})
        f["amount"] = round(f["amount"] + amt, 2)
        way = method_label(g.get("payment_method"))
        by_way[way] = round(by_way.get(way, 0.0) + amt, 2)
    return {
        "by_fund": sorted(by_fund.values(), key=lambda x: -x["amount"]),
        "by_way": [{"way": k, "amount": v} for k, v in sorted(by_way.items(), key=lambda kv: -kv[1])],
    }


# ─── Givers, and one person's giving ──────────────────────────────────

def givers(biz: str, year: int) -> Dict[str, Any]:
    people: Dict[str, Dict[str, Any]] = {}
    for g in _gifts(biz, _date(year, 1, 1), _date(year, 12, 31)):
        cid = g.get("contact_id")
        if not cid or _net(g) <= 0:
            continue
        c = (g.get("contacts") or {}) or {}
        p = people.setdefault(str(cid), {"contact_id": cid, "name": c.get("name") or "(no name on record)",
                                         "gifts": 0, "total": 0.0})
        p["gifts"] += 1
        p["total"] = round(p["total"] + _net(g), 2)
    return {"ok": True, "year": year,
            "givers": sorted(people.values(), key=lambda p: (p["name"] or "").lower())}


def giver_history(biz: str, contact_id: str, year: int) -> Dict[str, Any]:
    from giving_ways import method_label
    gifts = _gifts(biz, _date(year, 1, 1), _date(year, 12, 31), contact_id=contact_id)
    rows, by_fund, total = [], {}, 0.0
    name = ""
    for g in sorted(gifts, key=lambda x: str(x.get("paid_at") or "")):
        amt = _net(g)
        if amt <= 0:
            continue
        name = name or ((g.get("contacts") or {}) or {}).get("name") or ""
        fund = _fund_of(g)
        rows.append({"date": str(g.get("paid_at") or "")[:10], "fund": fund,
                     "way": method_label(g.get("payment_method")), "amount": amt,
                     "refunded": bool(g.get("refund_amount_cents"))})
        by_fund[fund] = round(by_fund.get(fund, 0.0) + amt, 2)
        total = round(total + amt, 2)
    return {"ok": True, "year": year, "contact_id": contact_id, "name": name,
            "gifts": rows, "total": total,
            "by_fund": [{"fund": k, "amount": v} for k, v in sorted(by_fund.items(), key=lambda kv: -kv[1])]}
