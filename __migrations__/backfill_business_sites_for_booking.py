"""
__migrations__/backfill_business_sites_for_booking.py
─────────────────────────────────────────────────────
Phase D.2.1 — One-shot backfill: ensure every business has a
business_sites row so that every business has a slug + URL identity
for the hosted booking page.

Idempotent. Touches ONLY businesses that don't already have a row.
Existing rows (status='published', 'draft', etc. — the MySite-backed
ones) are left untouched per Kevin's stop condition.

Run via:  python __migrations__/backfill_business_sites_for_booking.py
Requires: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY env vars
          (Railway env is fine; pull with `railway run python ...`)

Behavior:
  - For every business in `businesses` with no matching row in
    `business_sites`, derive a slug from `businesses.name` (kebab-case)
    and insert {slug, business_id, status='booking_only',
    html_content=NULL, site_config={}, hero_composer_module=NULL}.
  - Collision-resolved: if the desired slug is taken, append `-2`,
    `-3`, etc.
  - Logs every row created. Reports totals.
"""
from __future__ import annotations

import os
import sys
import logging

# Allow `python __migrations__/...` to find sibling modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] backfill: %(message)s",
)
logger = logging.getLogger("backfill_business_sites")


def main() -> int:
    import sb_clients
    from business_sites_helpers import ensure_business_site

    biz_rows = sb_clients.sb_get_as_service(
        "/businesses?select=id,name&order=created_at.asc"
    ) or []
    if not isinstance(biz_rows, list):
        logger.error(f"unexpected businesses response: {biz_rows!r}")
        return 1

    created = 0
    already = 0
    for b in biz_rows:
        try:
            site, was_created = ensure_business_site(b)
            if was_created:
                logger.info(
                    f"  created  biz={b['id'][:8]}  "
                    f"name={b.get('name')!r:<35}  slug={site['slug']!r}"
                )
                created += 1
            else:
                logger.info(
                    f"  exists   biz={b['id'][:8]}  "
                    f"name={b.get('name')!r:<35}  slug={site.get('slug')!r}"
                )
                already += 1
        except Exception as e:
            logger.warning(
                f"  FAILED   biz={b['id'][:8]}  "
                f"name={b.get('name')!r}  err={e!s}"
            )

    print()
    print(f"Backfill summary: {created} created · {already} already existed "
          f"· {len(biz_rows)} businesses total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
