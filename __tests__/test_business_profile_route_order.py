"""Route-order guard for business_profile_router (2026-09-01).

What broke: `POST /profile/{business_id}` was declared ABOVE
`POST /profile/seed-from-onboarding`. Starlette matches routes in
declaration order, so every onboarding seed call was handed to the
upsert handler with business_id="seed-from-onboarding"; its owner check
asked PostgREST for `id=eq.seed-from-onboarding`, got a 400 (not a
uuid), read that as "no rows", and answered 404 "business not found".
The client treats the seed as non-fatal, so nothing surfaced — and no
business created since July had a profile row, a blueprint module set,
or a vertical autopilot.

The guard is a rubric, not a list: every route whose path has no
parameter must be the FIRST full match for its own path and method.
"""

from starlette.routing import Match

import business_profile_router as m


def _first_full_match(method: str, path: str):
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "path_params": {}}
    for route in m.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


def test_seed_from_onboarding_reaches_its_own_handler():
    route = _first_full_match("POST", "/business-profile/profile/seed-from-onboarding")
    assert route is not None
    assert route.endpoint is m.seed_from_onboarding, (
        f"POST /business-profile/profile/seed-from-onboarding is captured by {route.path}"
    )


def test_no_literal_route_is_shadowed_by_a_parameter_route():
    shadowed = []
    for route in m.router.routes:
        if "{" in route.path:
            continue
        for method in route.methods or ():
            hit = _first_full_match(method, route.path)
            if hit is not route:
                shadowed.append(f"{method} {route.path} -> {hit.path if hit else None}")
    assert not shadowed, "literal routes captured by an earlier parameter route: " + "; ".join(shadowed)
