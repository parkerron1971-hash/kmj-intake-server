# __tests__/test_site_audit_fixes_0801.py
#
# The three verified bugs from the 2026-08-01 website-builder audit.
# Each test pins the FIX, not the implementation, so a future refactor
# is free to move code but not free to reintroduce the bug.

import inspect
import pathlib
import re

import public_site
import site_composer


# ─── 1. The residue purge must never sweep a key this function writes ──
#
# The purge (added 2026-07-22) listed page_spec + slot_concept, which
# render_and_persist writes ~60 lines earlier. Every full recompose
# wrote them and deleted them before the PATCH — breaking shuffle,
# killing catalog refresh, and re-rolling slot imagery every build.

def _persist_source() -> str:
    return inspect.getsource(site_composer.render_and_persist)


def test_purge_does_not_delete_page_spec_or_slot_concept():
    src = _persist_source()
    purge = re.search(r"for _dead in \((.*?)\):", src, re.S)
    assert purge, "residue purge loop not found — did it move?"
    swept = set(re.findall(r'"([a-z_]+)"', purge.group(1)))
    assert "page_spec" not in swept, (
        "page_spec is written by this same function — purging it breaks "
        "/composer/shuffle, refresh_if_composed, and the imagery fingerprint")
    assert "slot_concept" not in swept, (
        "slot_concept is written by this same function — purging it makes "
        "stored_concept_fp always empty, re-rolling paid imagery every build")


def test_purge_still_sweeps_the_actually_dead_keys():
    """The fix must not disarm the purge Kevin asked for."""
    src = _persist_source()
    purge = re.search(r"for _dead in \((.*?)\):", src, re.S)
    swept = set(re.findall(r'"([a-z_]+)"', purge.group(1)))
    for dead in ("design_brief", "design_recommendation", "enriched_brief",
                 "generated_decoration", "composer_cache", "sections"):
        assert dead in swept, f"{dead} should still be purged"


def test_no_restore_key_is_ever_purged():
    """_RESTORE_KEYS and the purge list must stay disjoint — a key that
    restore is supposed to bring back can't be one the purge deletes."""
    src = _persist_source()
    purge = re.search(r"for _dead in \((.*?)\):", src, re.S)
    swept = set(re.findall(r'"([a-z_]+)"', purge.group(1)))
    overlap = swept & set(site_composer._RESTORE_KEYS)
    assert not overlap, f"purged keys that restore expects back: {sorted(overlap)}"


# ─── 2. No duplicate routes on the composer router ────────────────────

def test_composer_router_has_no_duplicate_get_paths():
    seen = {}
    for r in site_composer.router.routes:
        for method in getattr(r, "methods", set()) or set():
            key = (method, r.path)
            assert key not in seen, (
                f"duplicate route {method} {r.path}: "
                f"{seen[key]} then {r.endpoint.__name__} — FastAPI matches in "
                f"registration order, so the second is dead code")
            seen[key] = r.endpoint.__name__


def test_both_spec_surfaces_are_reachable():
    paths = {r.path for r in site_composer.router.routes}
    assert "/composer/spec/{business_id}" in paths          # the Blueprint
    assert "/composer/composition/{business_id}" in paths   # what got built


# ─── 3. Site-config writers are owner-gated ───────────────────────────
#
# These took require_user only, so any signed-in user could write another
# business's site_config (custom_domain, offline, use_smart_sites) — and
# smart-preview had no auth at all while rendering their real content.

_MUST_BE_OWNER_GATED = (
    "save_smart_config_endpoint",
    "smart_preview_endpoint",
    "smart_disable_endpoint",
    "layout_override_endpoint",
    "generate_decoration_endpoint",
    "generate_design_rec_endpoint",
)


def test_site_config_writers_require_the_owner():
    for fn_name in _MUST_BE_OWNER_GATED:
        fn = getattr(public_site, fn_name)
        src = inspect.getsource(fn)
        assert "_require_business_owner(business_id, user)" in src, (
            f"{fn_name} writes or exposes another tenant's site data — "
            f"it must call _require_business_owner")


def test_owner_gated_endpoints_actually_take_a_user():
    """A gate is useless if the handler never receives the caller."""
    for fn_name in _MUST_BE_OWNER_GATED:
        sig = inspect.signature(getattr(public_site, fn_name))
        assert "user" in sig.parameters, f"{fn_name} has no user parameter"


# Endpoints under /sites/{business_id}/ that are PUBLIC ON PURPOSE.
# Adding to this set is a deliberate act — the sweep below fails on any
# new unauthenticated route until someone declares it here.
_INTENTIONALLY_PUBLIC = {
    # The website visitor's contact form. Anonymous by definition;
    # protected by IP rate-limiting (5/min) instead of auth, and it
    # captures the lead before the email leg so a Resend outage can't
    # lose it. See contact_submit_endpoint.
    "contact-submit",
}


# Either satisfies this sweep. business_access is the STRONGER of the
# two — it authenticates, binds the JWT for RLS, and then checks the
# caller's role on the business named in the path — so a route that has
# it does not also need require_user, and adding one back would be a
# downgrade dressed as belt-and-braces.
_AUTH_MARKERS = ("require_user", "business_access")


def test_no_site_write_endpoint_is_accidentally_public():
    """Sweep: every /sites/{business_id}/... POST either authenticates
    the caller or is explicitly declared public above. smart-preview
    shipped with neither — it rendered a tenant's real brand + content
    for anyone who knew a business_id."""
    src = pathlib.Path(public_site.__file__).read_text(encoding="utf-8")
    blocks = re.findall(
        r'@router\.post\("/sites/\{business_id\}/([^"]+)"\)\s*\n'
        r'async def (\w+)\((.*?)\):', src, re.S)
    assert blocks, "no /sites/{business_id} POST routes found — regex drifted?"
    for path, fn_name, params in blocks:
        if path in _INTENTIONALLY_PUBLIC:
            continue
        assert any(m in params for m in _AUTH_MARKERS), (
            f"POST /sites/{{business_id}}/{path} ({fn_name}) has no auth — "
            f"add Depends(business_access(...)) (preferred: it also checks "
            f"the caller's role on this business) or require_user, or "
            f"declare it in _INTENTIONALLY_PUBLIC with a reason")
