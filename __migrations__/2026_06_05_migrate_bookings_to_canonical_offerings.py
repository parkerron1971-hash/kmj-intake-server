"""
__migrations__/2026_06_05_migrate_bookings_to_canonical_offerings.py
================================================─────────────────────
Phase D.2.1 / Pass-A+ — Migrate any booking_calendar module that's
still on the pre-C.1.2 legacy `services` array -> canonical
`offerings` + `offering_ref` schema.

Triggered by Royal Barbers' hosted /book SlotPicker staying stuck in
"Pick a service above" empty state. Root cause: RB's Bookings module
service field is `type='select'` with agent_config.services hardcoded
(legacy), not `type='offering_ref'` reading from the offerings table
(canonical). Slot computation only iterates offerings, so empty
offerings -> empty available_slots -> SlotPicker can never activate.

Behavior:
  Detection: pick custom_modules rows where
    - archetype = 'booking_calendar'
    - the service field (resolved via archetype_params.color_field)
      has type != 'offering_ref'
    - agent_config.services is a non-empty array
    AND the business has no offerings already covering those services
    (idempotency guard — re-running on a migrated business is a no-op).

  Per business:
    1. For each entry in agent_config.services:
         - Skip if an offering with the same slug already exists
           (idempotent guard against partial prior runs).
         - Create an Offering: name, slug=derived, category='service',
           current_price, duration_min, is_active=True,
           show_price_to_customer=True (default — practitioner can
           tighten via OfferingsManager).
    2. PATCH the module's schema: change the service field's
         - type:                 'select'         -> 'offering_ref'
         - options:              [...]            -> None
         - offering_categories:  None             -> ['service']
    3. Preserve agent_config.services as
         agent_config._deprecated_services (audit trail), and stamp
         agent_config._migrated_to_offerings_at = iso8601 timestamp.

  Run modes:
    --dry-run (DEFAULT):  report what WOULD change; no writes.
    --apply:              write all changes; reports per-row.

Usage:
  railway run python __migrations__/2026_06_05_migrate_bookings_to_canonical_offerings.py
  railway run python __migrations__/2026_06_05_migrate_bookings_to_canonical_offerings.py --apply

Requires: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY env vars.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] migrate_bc: %(message)s",
)
logger = logging.getLogger("migrate_bookings_to_canonical_offerings")


_SLUG_BAD = re.compile(r"[^a-z0-9]+")
_SLUG_MULTI_DASH = re.compile(r"-{2,}")

DEFAULT_CATEGORY = "service"  # Barbershop / typical practitioner services
                              # ride under 'service'. 'session' would
                              # apply to coaching/therapy practices — but
                              # those are already on offering_ref per the
                              # survey, so 'service' is the safe default
                              # for any legacy migration target.


def _values_differ(a: Any, b: Any) -> bool:
    """True when two scalar values disagree, after coercing None and ''
    to None. Allows numeric comparison even if one side is int and the
    other is float (e.g. 30 vs 30.0)."""
    def _norm(v: Any) -> Any:
        if v is None or v == "":
            return None
        # Coerce numeric strings + ints for clean compare
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return _norm(a) != _norm(b)


def slug_from_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = _SLUG_BAD.sub("-", s)
    s = _SLUG_MULTI_DASH.sub("-", s)
    s = s.strip("-")
    return s or "service"


def find_service_field(
    schema: Dict[str, Any],
    archetype_params: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """Return (field_dict, field_index) for the field whose name matches
    archetype_params.color_field, or (None, None) if not found."""
    color_field = (archetype_params or {}).get("color_field")
    if not color_field:
        return None, None
    fields = (schema or {}).get("fields") or []
    for i, f in enumerate(fields):
        if (f or {}).get("name") == color_field:
            return f, i
    return None, None


def candidate_business(module: Dict[str, Any]) -> bool:
    """Return True if this booking_calendar module appears to need
    migration to canonical offerings. (archetype filter is applied at
    the query level; no need to re-check here.)"""
    bid = module.get("business_id", "")[:8]
    schema = module.get("schema") or {}
    ap = module.get("archetype_params") or {}
    svc_f, _ = find_service_field(schema, ap)
    if not svc_f:
        logger.debug(f"  reject {bid}: no service field (color_field={ap.get('color_field')})")
        return False
    if svc_f.get("type") == "offering_ref":
        logger.debug(f"  reject {bid}: already offering_ref")
        return False
    legacy_services = ((module.get("agent_config") or {}).get("services")) or []
    if not isinstance(legacy_services, list) or not legacy_services:
        logger.debug(f"  reject {bid}: legacy services empty/wrong-type ({type(legacy_services).__name__})")
        return False
    logger.debug(f"  accept {bid}: needs migration")
    return True


def plan_migration(
    module: Dict[str, Any],
    sb_clients,
) -> Dict[str, Any]:
    """Build a dry-run-able plan for one business+module. Returns:
      {
        business_id, module_id, module_name,
        offerings_to_create: [...],   # list of payload dicts
        offerings_skipped:    [...],  # already-exist slugs
        schema_field_patch:   {...},  # before/after of the service field
      }
    """
    business_id = module["business_id"]
    schema = module.get("schema") or {}
    ap = module.get("archetype_params") or {}
    svc_f, svc_idx = find_service_field(schema, ap)
    legacy_services = ((module.get("agent_config") or {}).get("services")) or []

    existing_offerings = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}"
        f"&select=slug,name,current_price,duration_min&is_active=eq.true"
    ) or []
    existing_by_slug: Dict[str, Dict[str, Any]] = {
        o["slug"]: o for o in existing_offerings if o.get("slug")
    }

    to_create: List[Dict[str, Any]] = []
    skipped: List[str] = []
    drift_warnings: List[Dict[str, Any]] = []
    null_fills: List[Dict[str, Any]] = []
    for svc in legacy_services:
        if not isinstance(svc, dict):
            continue
        raw_name = svc.get("name") or ""
        # Service entries in agent_config typically use snake_case names
        # ("haircut", "beard_trim"). Display these with a readable label.
        display = raw_name.replace("_", " ").title() if raw_name else ""
        slug = slug_from_name(raw_name or display)
        if slug in existing_by_slug:
            skipped.append(slug)
            existing = existing_by_slug[slug]
            legacy_price = svc.get("price")
            legacy_dur = svc.get("duration_min")
            existing_price = existing.get("current_price")
            existing_dur = existing.get("duration_min")

            # Null-fill plan: when existing field is null AND legacy has a
            # value, queue a backfill from the originating source. Never
            # overwrite a non-null existing value, even if legacy disagrees.
            patch: Dict[str, Any] = {}
            fills: List[Dict[str, Any]] = []
            if (existing_price in (None, "")) and (legacy_price not in (None, "")):
                patch["current_price"] = legacy_price
                fills.append({"field": "current_price", "value": legacy_price})
            if (existing_dur in (None, "")) and (legacy_dur not in (None, "")):
                patch["duration_min"] = legacy_dur
                fills.append({"field": "duration_min", "value": legacy_dur})
            if patch:
                null_fills.append({
                    "business_id": business_id,
                    "offering_slug": slug,
                    "offering_name": existing.get("name") or display,
                    "patch": patch,
                    "fills": fills,
                })

            # True drift: legacy disagrees with a NON-NULL existing value.
            # Warn-only; never auto-fix.
            price_drift = (
                existing_price not in (None, "")
                and _values_differ(legacy_price, existing_price)
            )
            dur_drift = (
                existing_dur not in (None, "")
                and _values_differ(legacy_dur, existing_dur)
            )
            if price_drift or dur_drift:
                drift_warnings.append({
                    "business_id": business_id,
                    "offering_slug": slug,
                    "offering_name": existing.get("name") or display,
                    "legacy_price": legacy_price,
                    "existing_price": existing_price,
                    "legacy_duration_min": legacy_dur,
                    "existing_duration_min": existing_dur,
                    "price_drift": price_drift,
                    "duration_drift": dur_drift,
                })
            continue
        to_create.append({
            "business_id": business_id,
            "name": display or slug,
            "slug": slug,
            "category": DEFAULT_CATEGORY,
            "current_price": svc.get("price"),
            "currency": "usd",
            "duration_min": svc.get("duration_min"),
            "show_price_to_customer": True,
            "is_active": True,
            "description": None,
        })

    schema_field_patch: Dict[str, Any] = {}
    if svc_f:
        before = dict(svc_f)
        after = dict(svc_f)
        after["type"] = "offering_ref"
        after["options"] = None
        after["offering_categories"] = [DEFAULT_CATEGORY]
        if before != after:
            schema_field_patch = {
                "field_index": svc_idx,
                "field_name": svc_f.get("name"),
                "before": before,
                "after": after,
            }

    return {
        "business_id": business_id,
        "module_id": module["id"],
        "module_name": module.get("name"),
        "offerings_to_create": to_create,
        "offerings_skipped": skipped,
        "schema_field_patch": schema_field_patch,
        "drift_warnings": drift_warnings,
        "null_fills": null_fills,
    }


def apply_migration(plan: Dict[str, Any], module: Dict[str, Any], sb_clients) -> None:
    """Execute the writes for one business+module plan."""
    bid = plan["business_id"]
    mid = plan["module_id"]

    # 1a. Null-fill existing offerings where legacy supplies the missing
    # field (current_price / duration_min). Never overwrites non-null.
    for nf in plan["null_fills"]:
        try:
            sb_clients.sb_patch_as_service(
                f"/offerings?business_id=eq.{bid}&slug=eq.{nf['offering_slug']}",
                nf["patch"],
            )
            fields_summary = ", ".join(f"{f['field']}={f['value']!r}" for f in nf["fills"])
            logger.info(f"    + null-fill: offering={nf['offering_name']!r} ({nf['offering_slug']}): {fields_summary}")
        except Exception as e:
            logger.warning(f"    ! null-fill failed: offering={nf['offering_slug']!r} err={e!s}")

    # 1b. Create offerings
    created_count = 0
    for payload in plan["offerings_to_create"]:
        try:
            created = sb_clients.sb_post_as_service("/offerings", payload)
            if isinstance(created, list) and created:
                created_count += 1
                logger.info(f"    + offering created: slug={payload['slug']!r} name={payload['name']!r}")
            else:
                logger.warning(f"    ! offering POST returned no row: slug={payload['slug']!r}")
        except Exception as e:
            logger.warning(f"    ! offering create failed: slug={payload['slug']!r} err={e!s}")

    # 2. PATCH module schema + agent_config (audit trail)
    if plan["schema_field_patch"]:
        sp = plan["schema_field_patch"]
        idx = sp["field_index"]
        new_fields = list((module.get("schema") or {}).get("fields") or [])
        if idx is not None and 0 <= idx < len(new_fields):
            new_fields[idx] = sp["after"]
            new_schema = dict(module.get("schema") or {})
            new_schema["fields"] = new_fields

            new_agent_config = dict(module.get("agent_config") or {})
            legacy = new_agent_config.pop("services", None)
            if legacy is not None:
                new_agent_config["_deprecated_services"] = legacy
                new_agent_config["_migrated_to_offerings_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )

            sb_clients.sb_patch_as_service(
                f"/custom_modules?id=eq.{mid}",
                {
                    "schema": new_schema,
                    "agent_config": new_agent_config,
                },
            )
            logger.info(f"    + schema patched: service field type 'select'->'offering_ref'")
            logger.info(f"    + agent_config.services -> _deprecated_services (audit trail)")

    logger.info(f"  DONE biz={bid[:8]}: {created_count} offerings created")


def main() -> int:
    import sb_clients

    apply_writes = "--apply" in sys.argv
    mode = "APPLY (writes will be made)" if apply_writes else "DRY-RUN (no writes)"
    logger.info(f"================================================")
    logger.info(f"  MODE: {mode}")
    logger.info(f"================================================")

    modules = sb_clients.sb_get_as_service(
        "/custom_modules?archetype=eq.booking_calendar"
        "&select=id,business_id,name,schema,agent_config,archetype_params"
    ) or []
    logger.info(f"booking_calendar modules in prod: {len(modules)}")

    # Diagnostic: report each module's classification
    for m in modules:
        bid = m["business_id"][:8]
        nm = m.get("name")
        ap = m.get("archetype_params") or {}
        schema = m.get("schema") or {}
        svc_f, _ = find_service_field(schema, ap)
        legacy = ((m.get("agent_config") or {}).get("services")) or []
        svc_type = (svc_f or {}).get("type")
        logger.info(
            f"  biz={bid} name={nm!r} color_field={ap.get('color_field')!r} "
            f"svc_field_found={bool(svc_f)} svc_type={svc_type!r} "
            f"legacy_services_count={len(legacy) if isinstance(legacy, list) else 'NOT_LIST'}"
        )

    candidates = [m for m in modules if candidate_business(m)]
    logger.info(f"candidates needing migration: {len(candidates)}")

    if not candidates:
        logger.info("nothing to migrate — every booking_calendar module is already canonical.")
        return 0

    plans: List[Dict[str, Any]] = []
    for m in candidates:
        plan = plan_migration(m, sb_clients)
        plans.append(plan)
        print()
        print(f"-- biz={plan['business_id'][:8]}  module={plan['module_name']!r}  --")
        if plan["offerings_to_create"]:
            print(f"  offerings TO CREATE ({len(plan['offerings_to_create'])}):")
            for p in plan["offerings_to_create"]:
                print(f"    name={p['name']!r:<22} slug={p['slug']!r:<22} "
                      f"price={p['current_price']!r:<6} duration_min={p['duration_min']!r}")
        if plan["offerings_skipped"]:
            print(f"  offerings ALREADY EXIST (skipped): {plan['offerings_skipped']}")
        if plan["null_fills"]:
            print(f"  NULL-FILLS ({len(plan['null_fills'])}):")
            for nf in plan["null_fills"]:
                fields_summary = ", ".join(f"{f['field']}={f['value']!r}" for f in nf["fills"])
                print(f"    NULL-FILL  offering={nf['offering_name']!r} ({nf['offering_slug']}): {fields_summary}")
        if plan["drift_warnings"]:
            print(f"  DRIFT WARNINGS ({len(plan['drift_warnings'])}):")
            for d in plan["drift_warnings"]:
                bits = []
                if d["price_drift"]:
                    bits.append(f"price: existing=${d['existing_price']!r}, legacy=${d['legacy_price']!r}")
                if d["duration_drift"]:
                    bits.append(f"duration_min: existing={d['existing_duration_min']!r}, legacy={d['legacy_duration_min']!r}")
                print(f"    DRIFT  offering={d['offering_name']!r} ({d['offering_slug']}): " + " | ".join(bits))
        if plan["schema_field_patch"]:
            sp = plan["schema_field_patch"]
            print(f"  schema PATCH: field[{sp['field_index']}] name={sp['field_name']!r}")
            print(f"    type: {sp['before'].get('type')!r} -> {sp['after'].get('type')!r}")
            print(f"    options: {sp['before'].get('options')!r} -> {sp['after'].get('options')!r}")
            print(f"    offering_categories: {sp['before'].get('offering_categories')!r} -> {sp['after'].get('offering_categories')!r}")
        else:
            print(f"  schema PATCH: (none — service field already canonical-shaped)")
        print(f"  agent_config: services -> _deprecated_services (audit trail) + "
              f"_migrated_to_offerings_at timestamp")

    # Cross-business null-fill summary — surfaces every null-fill in
    # one block.
    all_fills = [nf for p in plans for nf in p["null_fills"]]
    if all_fills:
        print()
        print(f"=== NULL-FILL SUMMARY ({len(all_fills)} fills across {len({n['business_id'] for n in all_fills})} business(es)) ===")
        for nf in all_fills:
            fields_summary = ", ".join(f"{f['field']}={f['value']!r}" for f in nf["fills"])
            print(f"  biz={nf['business_id'][:8]}  offering={nf['offering_name']!r} ({nf['offering_slug']}): {fields_summary}")
        print(f"=== end null-fill summary — fills only NULL fields from legacy source ===")

    # Cross-business drift summary — surfaces every drift warning in
    # one block so the user has a single place to rule on each.
    all_drift = [d for p in plans for d in p["drift_warnings"]]
    if all_drift:
        print()
        print(f"=== DRIFT SUMMARY ({len(all_drift)} warnings across {len({d['business_id'] for d in all_drift})} business(es)) ===")
        for d in all_drift:
            bits = []
            if d["price_drift"]:
                bits.append(f"price ${d['existing_price']!r} (offerings) vs ${d['legacy_price']!r} (legacy)")
            if d["duration_drift"]:
                bits.append(f"duration {d['existing_duration_min']!r}min (offerings) vs {d['legacy_duration_min']!r}min (legacy)")
            print(f"  biz={d['business_id'][:8]}  offering={d['offering_name']!r} ({d['offering_slug']}): " + " | ".join(bits))
        print(f"=== end drift summary — drift does NOT block migration; existing rows untouched ===")

    if not apply_writes:
        print()
        logger.info(f"DRY-RUN complete. Re-run with --apply to write {sum(len(p['offerings_to_create']) for p in plans)} offerings + {sum(1 for p in plans if p['schema_field_patch'])} schema patches.")
        if all_drift:
            logger.info(f"NOTE: {len(all_drift)} drift warnings detected — surface for ruling before apply if any look material.")
        return 0

    print()
    logger.info("APPLYING migrations now …")
    for m, plan in zip(candidates, plans):
        print()
        logger.info(f"applying biz={plan['business_id'][:8]} module={plan['module_name']!r}")
        apply_migration(plan, m, sb_clients)

    print()
    logger.info(f"APPLY complete. Migrated {len(plans)} module(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
