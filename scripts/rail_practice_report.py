"""The rail's practice record, per shelf (chief_rail.summarize). Read-only.

Prints counts, shares and timings from chief_rail_practice: how many records
questions each shelf took, how many it proved, how often Chief said the same
thing, why the rest were declined, and what Chief's turns on them cost.
No answers, names or ids.

Run:  railway run python -X utf8 scripts/rail_practice_report.py [days]
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chief_rail  # noqa: E402
import sb_clients  # noqa: E402


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    rows = sb_clients.sb_get_as_service(
        f"/{chief_rail.TABLE}?created_at=gte.{quote(since, safe='')}&order=created_at.desc&limit=5000"
        "&select=shelf,form,took,decline_reason,proof,outcome,chief_cost_cents,rail_ms,chief_ms")
    if not isinstance(rows, list):
        print("chief_rail_practice unreadable: is supabase/APPLY-2026-10-16-chief-rail-practice.sql applied?")
        return
    print(f"rail practice, last {days} days: {len(rows)} records questions")
    print(json.dumps(chief_rail.summarize(rows), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
