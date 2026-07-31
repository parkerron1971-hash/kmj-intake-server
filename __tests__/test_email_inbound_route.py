# __tests__/test_email_inbound_route.py
#
# Regression guard for the Arc 29 decorator drift: @router.post("/email/inbound")
# ended up attached to the _verify_resend_signature helper (inserted between the
# decorator and the handler), leaving inbound_email unrouted. Every Resend
# inbound webhook then 422'd in production and all inbound email was dropped.

from email_sender import router, inbound_email


def _route(path: str):
    matches = [r for r in router.routes if getattr(r, "path", None) == path]
    assert len(matches) == 1, f"expected exactly one route for {path}, got {len(matches)}"
    return matches[0]


def test_inbound_route_is_bound_to_the_handler():
    route = _route("/email/inbound")
    assert route.endpoint is inbound_email


def test_no_route_is_bound_to_a_private_helper():
    # A route whose endpoint starts with "_" means a decorator drifted onto
    # a helper def — the exact failure mode this file exists to catch.
    offenders = [
        (r.path, r.endpoint.__name__)
        for r in router.routes
        if getattr(r, "endpoint", None) is not None
        and r.endpoint.__name__.startswith("_")
    ]
    assert offenders == [], f"routes bound to private helpers: {offenders}"
