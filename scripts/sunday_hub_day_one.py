"""scripts/sunday_hub_day_one.py — the one Sunday hub's day-one list (M-7).

Read-only. For every church: each login (the owner, every active office
seat, every active ChurchSavvy team member) and the Sunday roles it will
hold the moment SUNDAY_HUB goes on, worked out by sunday_hub.standing from
what the church already gave it. Then the logins that see the Sunday pages
today (by their areas) and won't once the hub is on: nobody uses Church
Savvy yet, so they lose nothing in use, but Kevin reads this list before the
launch.

Run against production with the service role (writes nothing):
    railway run python scripts/sunday_hub_day_one.py
Prints names and roles only: no emails, phones or anything about money.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# The list is what the launch gives: worked out with the hub on (church_duties
# lists ministry_ops only then). This process only; nothing is written.
os.environ["SUNDAY_HUB"] = "on"

import sb_clients  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise SystemExit(f"Couldn't read {path.split('?')[0]}; nothing was changed. Try again.")
    return rows


def sees_sunday_today(biz: str, uid: str, seat: str) -> bool:
    """Whether the office menu shows this login the Sunday pages today: the
    whole church (areas None: the owner, admins, a login nothing places), or
    the Worship & media area among its areas."""
    import church_areas
    if seat in ("owner", "admin"):
        return True
    try:
        view = church_areas.view_for(biz, uid, seat)
    except Exception:
        return True
    areas = (view or {}).get("areas")
    return areas is None or "worship_media" in areas


def main() -> None:
    import church_follow_up
    import sunday_hub
    churches = [b for b in _get("/businesses?select=id,name,type,owner_id&order=name.asc&limit=1000")
                if church_follow_up.is_church(b)]
    losing: List[str] = []
    for b in churches:
        biz = str(b["id"])
        print(f"\n== {b.get('name') or biz}")
        logins: Dict[str, Dict[str, Any]] = {}
        if b.get("owner_id"):
            logins[str(b["owner_id"])] = {"name": "the owner", "seat": "owner"}
        for s in _get(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=user_id,role,name"
                      "&limit=200"):
            if s.get("user_id"):
                logins.setdefault(str(s["user_id"]), {"name": s.get("name") or "an office login",
                                                      "seat": s.get("role") or "member"})
        for t in _get(f"/worship_team?business_id=eq.{_q(biz)}&status=eq.active&select=user_id,name&limit=200"):
            if t.get("user_id"):
                logins.setdefault(str(t["user_id"]), {"name": t.get("name") or "a team member", "seat": None})
        for uid, who in logins.items():
            user = AuthedUser(id=uid, email="", role="authenticated")
            try:
                st = sunday_hub.standing(biz, user)
            except Exception as e:  # one login's read failing never stops the list
                print(f"  {who['name']:<28} couldn't be read: {e}")
                continue
            roles = ", ".join(sunday_hub.ROLE_LABEL[r] for r in st["roles"]) or "no Sunday role"
            leads = f" (leads {', '.join(t['name'] for t in st['leads'])})" if st["leads"] else ""
            reads = "reads Sunday" if st["reader"] else "NO Sunday pages"
            print(f"  {who['name']:<28} {who['seat'] or 'team only':<8} {roles}{leads}; {reads}")
            if not st["reader"] and who["seat"] and sees_sunday_today(biz, uid, who["seat"]):
                losing.append(f"{b.get('name') or biz}: {who['name']} ({who['seat']})")
    print("\n== Would lose the Sunday pages at launch (see them today, hold no Sunday role, duty or part)")
    for line in losing or ["nobody"]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
