"""
vertical_registry.py — the CANONICAL list of verticals + who supports each.

The reconciliation spine for the five historically-divergent vertical maps:
  1. onboarding picker      (frontend OnboardingFlow.tsx BUSINESS_TYPES)
  2. DB CHECK constraint    (businesses.type allowed values)
  3. Chief intelligence     (vertical_intelligence.VERTICAL_INTELLIGENCE)
  4. terminology            (vertical_terminology.VERTICAL_TERMS + dictionary.ts)
  5. module blueprint seed  (business-type-module-blueprint-seed.sql)

Each subsystem still OWNS its own data — this module doesn't replace them.
It records the single canonical set + per-vertical coverage, so:
  - there is ONE place to see "what verticals exist and how complete each is",
  - the drift test (test_vertical_registry.py) asserts the importable
    Python maps agree with this registry and flags new drift, and
  - `family` routes through vertical_family.py (the accounting/compliance
    shape), keeping that classifier and this registry consistent.

Coverage flags are the TRUTH we intend; `KNOWN_GAPS` records the ones that
are deliberately or not-yet filled (with the arc that will close them), so
the test passes today while the gaps stay visible instead of silent.
"""
from __future__ import annotations

from typing import Dict, List

import vertical_family


# Canonical verticals, in the order a picker would show them. `aliases`
# are legacy/synonym strings that must resolve to this same vertical.
# Aliases for the accounting families (lawyer/ministry/nonprofit) mirror
# vertical_family.py's synonym sets, so resolve() and family_of() agree.
CANONICAL: Dict[str, Dict] = {
    "coach":              {"label": "Coach",               "aliases": ["coaching"]},
    "consultant":         {"label": "Consultant",          "aliases": ["consulting"]},
    "creative":           {"label": "Creative / Agency",   "aliases": ["agency"]},
    "course_creator":     {"label": "Course Creator",      "aliases": ["course"]},
    "financial_educator": {"label": "Financial Educator",  "aliases": ["educator"]},
    "fitness_wellness":   {"label": "Fitness / Wellness",  "aliases": ["fitness", "wellness", "trainer"]},
    "service_provider":   {"label": "Service Provider",    "aliases": ["service", "freelance"]},
    # Private practice mental health. Launched with clinical records OUT OF
    # SCOPE (vertical_scope.py) — scheduling, billing and admin only, so the
    # platform never becomes a HIPAA business associate. Not a permanent
    # limitation; a narrowed launch pending a BAA posture.
    "therapist":          {"label": "Therapist / Counselor",
                           "aliases": ["therapy", "therapists", "counselor", "counsellor",
                                       "counseling", "counselling", "psychotherapist",
                                       "psychotherapy", "mental_health", "lmft", "lcsw",
                                       "lpc", "psychologist"]},
    "personal_services":  {"label": "Personal Services",   "aliases": []},
    # Trades. Distinct from service_provider (the deliberate generic
    # baseline) because the work has a shape service_provider does not
    # model: a JOB at a site, quoted before it starts, with materials and
    # labor billed separately and a deposit taken up front. Aliases cover
    # the trades that self-describe by craft rather than by "contractor".
    "contractor":         {"label": "Contractor / Trades",
                           "aliases": ["contracting", "general_contractor", "trades",
                                       "tradesman", "handyman", "builder", "remodeler",
                                       "plumber", "plumbing", "electrician", "electrical",
                                       "hvac", "roofer", "roofing", "landscaper",
                                       "landscaping", "painter", "painting",
                                       "carpenter", "carpentry", "flooring",
                                       "construction"]},
    "lawyer":             {"label": "Lawyer / Law Firm",
                           "aliases": ["law", "law_firm", "law_practice", "lawyers",
                                       "attorney", "attorneys", "legal", "legal_services"]},
    "ministry":           {"label": "Ministry / Church",
                           "aliases": ["church", "churches", "pastor", "parachurch",
                                       "faith", "faith_based", "religious", "religious_org",
                                       "synagogue", "mosque", "temple", "congregation", "ministries"]},
    "nonprofit":          {"label": "Nonprofit",
                           "aliases": ["non_profit", "not_for_profit", "nonprofit_org"]},
    # Selling PRODUCTS rather than time. Distinct from every vertical above
    # because the unit is an ORDER that must be picked, packed and shipped:
    # stock can run out, a carrier owns the delivery date, sales tax is
    # collected on behalf of a state, and a return is a routine cost rather
    # than a failure. None of the service verticals model any of that.
    # `business_type_archetypes` has carried an 'ecommerce' row for a long
    # time, so businesses could already be STAMPED this — they just had no
    # profile, no dictionary and no playbook behind the stamp.
    "ecommerce":          {"label": "E-commerce / Online Store",
                           "aliases": ["e_commerce", "ecom", "online_store", "store",
                                       "retail", "dtc", "merch", "dropshipping",
                                       "print_on_demand"]},
    # Recurring software revenue. Distinct because the money is subscribed
    # rather than sold once: an annual plan is paid up front and earned
    # monthly, churn is decided long before the renewal, and usage — not
    # billing — is the leading indicator. A SaaS business modelled as a
    # consultancy reads its own numbers wrong.
    "saas":               {"label": "SaaS / Software",
                           "aliases": ["software", "software_company", "saas_company",
                                       "micro_saas", "app", "platform"]},
    "custom":             {"label": "Something else",      "aliases": ["other", "general"]},
}

# Subsystems whose coverage we track per vertical.
SUBSYSTEMS = ("onboarding", "constraint", "intel", "terminology", "blueprint")

# What's intentionally or not-yet covered, with the reason/arc. The drift
# test treats these as allowed absences; everything else must be present.
# Keep this list SHRINKING — each closed gap is deleted here.
KNOWN_GAPS: Dict[str, Dict[str, str]] = {
    # lawyer CLOSED 2026-07-14 (Leg 3): added to onboarding picker + a
    # matter/engagement/trust module blueprint (APPLY-2026-07-14-lawyer-
    # blueprint.sql) + smart-sites touch. Now first-class end-to-end.
    # nonprofit CLOSED 2026-07-14: intel (Leg 1), then onboarding picker +
    # module blueprint (APPLY-2026-07-14-nonprofit-blueprint.sql) + smart-
    # sites touch + type_steer.
    #   CORRECTION 2026-08-11: "first-class end-to-end" was NOT true when it
    #   was written. The blueprint FILE existed; its rows were never applied.
    #   business_type_module_blueprint held 0 nonprofit rows for four weeks,
    #   so a nonprofit signup was provisioned nothing at all — while this
    #   comment said the vertical was closed. Applied 2026-08-11 (5 rows:
    #   donors, programs, grants, events, volunteers) and VERIFIED against
    #   the live DB, the way the personal_services note below already did.
    #   Writing a migration is not applying it, and a closure note that
    #   cites a file has only checked that the file exists.
    # personal_services CLOSED 2026-07-25: both recorded gaps had gone stale.
    # onboarding — solutionist-studio#218 adds it to BUSINESS_TYPES (canonical
    # position, CDI warm-community), so it is a picker card, not an admin stamp.
    # blueprint — business_type_module_blueprint already carries five bespoke
    # rows (Appointments / Clients with formulas+sensitivities / Service Menu
    # with fixed AND quote-required modes / Payments with duration-gated
    # deposits / Staff with commission+booth-rent), verified against the live
    # DB — not the generic set. Now first-class end-to-end.
    # service_provider + custom are intentionally the GENERIC baseline for
    # Chief intelligence (a deliberate catch-all voice, not a missing profile).
    "service_provider": {
        "intel": "intentionally GENERIC baseline voice",
    },
    "custom": {
        "intel":     "intentionally GENERIC — triggers Chief interactive discovery",
        "blueprint": "intentionally no rows — triggers Chief interactive discovery",
    },
}


def canonical_keys() -> List[str]:
    return list(CANONICAL.keys())


def alias_to_canonical() -> Dict[str, str]:
    """Flat map of every alias (and canonical key) → canonical key."""
    out: Dict[str, str] = {}
    for key, meta in CANONICAL.items():
        out[key] = key
        for a in meta.get("aliases", []):
            out[a] = key
    return out


def resolve(business_type: str) -> str:
    """Canonical key for any type string (via alias table), or 'custom'."""
    bt = (business_type or "").lower().strip().replace("-", "_").replace(" ", "_")
    return alias_to_canonical().get(bt, "custom")


def family_of(business_type: str) -> str:
    """Accounting/compliance family — delegates to vertical_family so the
    two stay consistent."""
    return vertical_family.family_of(business_type)
