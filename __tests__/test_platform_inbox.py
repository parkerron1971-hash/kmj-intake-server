# __tests__/test_platform_inbox.py
#
# The Mission Control inbox: mail addressed to the platform itself
# (kevin@/support@/... at INBOUND_EMAIL_DOMAIN) routes to platform_emails
# instead of dying as unknown_sender. These tests pin the address matcher
# and the /platform/inbox route surface.

from unittest import mock

from email_sender import _match_platform_address, _platform_local_parts


DOMAIN_ENV = {"INBOUND_EMAIL_DOMAIN": "mysolutionist.app"}


def test_named_address_matches_at_the_inbound_domain():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["kevin@mysolutionist.app"]) == "kevin@mysolutionist.app"
        assert _match_platform_address(["support@mysolutionist.app"]) == "support@mysolutionist.app"


def test_wrong_domain_does_not_match_when_domain_configured():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["kevin@othersite.com"]) is None


def test_reply_plus_addresses_never_match():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["reply+abc12345+def67890@mysolutionist.app"]) is None


def test_unknown_local_part_does_not_match():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["randomperson@mysolutionist.app"]) is None


def test_first_platform_recipient_wins_among_many():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        got = _match_platform_address(
            ["someone@gmail.com", "hello@mysolutionist.app", "kevin@mysolutionist.app"])
        assert got == "hello@mysolutionist.app"


def test_env_override_replaces_the_default_list():
    with mock.patch.dict(
        "os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": "ceo, press"}
    ):
        assert _platform_local_parts() == ["ceo", "press"]
        assert _match_platform_address(["ceo@mysolutionist.app"]) == "ceo@mysolutionist.app"
        # kevin is not in the overridden list
        assert _match_platform_address(["kevin@mysolutionist.app"]) is None


def test_unconfigured_domain_matches_on_local_part_alone():
    # A deploy that lost INBOUND_EMAIL_DOMAIN should still route rather
    # than drop.
    with mock.patch.dict("os.environ", {"INBOUND_EMAIL_DOMAIN": ""}):
        assert _match_platform_address(["support@anything.example"]) == "support@anything.example"


def test_platform_inbox_routes_exist_and_are_owner_gated():
    from platform_console import router

    by_path = {}
    for r in router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))

    assert "GET" in by_path.get("/platform/inbox", set())
    assert "GET" in by_path.get("/platform/inbox/{email_id}", set())
    assert "DELETE" in by_path.get("/platform/inbox/{email_id}", set())

    # Every inbox endpoint must carry the require_owner dependency —
    # this inbox is the platform owner's mail and nobody else's.
    from lead_admin import require_owner
    for r in router.routes:
        if not r.path.startswith("/platform/inbox"):
            continue
        deps = [d.call for d in r.dependant.dependencies]
        assert require_owner in deps, f"{r.path} is missing require_owner"
