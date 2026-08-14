"""
test_lead_identity.py — THE LEAD ARC PR 7.

Four doors used to give four different answers to "is this the same
person?":

  /intake/submit          no dedupe at all — every submission a new row
  /sites/…/contact-submit email ilike OR phone
  /concierge/…/lead       email ilike only
  booking widget          email=eq — case SENSITIVE at the database

One rule now. The tests are weighted toward the errors that are
expensive: merging two people is far worse than splitting one, so the
guard is generous about splitting and careful about merging.
"""
from __future__ import annotations

import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import lead_identity as li  # noqa: E402


def _db(rows_by_query=None, insert=None):
    """Fake PostgREST. `rows_by_query` maps a substring of the query to
    the rows it returns, so a test can say "the email lookup finds X and
    the phone lookup finds nothing"."""
    gets, posts = [], []

    def get(path):
        gets.append(path)
        for needle, rows in (rows_by_query or {}).items():
            if needle in path:
                return list(rows)
        return []

    def post(path, body, prefer="return=representation"):
        posts.append((path, body))
        return insert if insert is not None else [{"id": "new-1"}]

    import sb_clients
    return (mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get),
            mock.patch.object(sb_clients, "sb_post_as_service", side_effect=post),
            gets, posts)


# ═══════════════════════════════════════════════════════════════════════
# Matching
# ═══════════════════════════════════════════════════════════════════════

def test_the_same_person_is_matched_on_email():
    g, p, _, posts = _db({"email=ilike": [{"id": "c-1", "name": "Dana Reyes"}]})
    with g, p:
        r = li.resolve("biz-1", name="Dana Reyes", email="dana@x.com",
                       source="intake_form")
    assert r.contact_id == "c-1" and r.created is False
    assert r.matched_on == "email"
    assert not posts, "matched an existing contact and created another anyway"


def test_email_matching_ignores_case():
    """The booking door used `email=eq`, which is case SENSITIVE at the
    database — Dana@x.com was invisible to a booking for dana@x.com."""
    g, p, gets, _ = _db({"email=ilike": [{"id": "c-1", "name": "Dana"}]})
    with g, p:
        r = li.resolve("biz-1", name="Dana", email="DANA@X.COM")
    assert r.contact_id == "c-1"
    assert "dana%40x.com" in gets[0].lower()


def test_a_phone_only_visitor_is_matched():
    """The concierge matched on email alone, so somebody who left a
    phone number and no email became a new row every single time."""
    g, p, _, posts = _db({"phone=eq": [{"id": "c-2", "name": "Sam"}]})
    with g, p:
        r = li.resolve("biz-1", name="Sam", phone="(555) 010-2233")
    assert r.contact_id == "c-2" and r.matched_on == "phone"
    assert not posts


def test_phone_matching_normalizes_the_format():
    g, p, gets, _ = _db()
    with g, p:
        li.resolve("biz-1", name="Sam", phone="555-010-2233")
    phone_query = [q for q in gets if "phone=eq" in q][0]
    assert "%2B15550102233" in phone_query   # +15550102233, url-encoded


def test_an_underscore_in_an_email_is_not_a_wildcard():
    """`_` is a LIKE single-character wildcard. Unescaped, jo_n@x.com
    matches joan@x.com and two strangers are merged."""
    g, p, gets, _ = _db()
    with g, p:
        li.resolve("biz-1", name="Jon", email="jo_n@x.com")
    assert "%5C_" in gets[0], gets[0]        # backslash-escaped underscore


def test_matching_never_crosses_a_business():
    """The same human is legitimately a separate contact of two
    businesses. A cross-tenant match is a data leak, not a
    convenience."""
    g, p, gets, _ = _db()
    with g, p:
        li.resolve("biz-1", name="Dana", email="dana@x.com", phone="5550102233")
    assert all("business_id=eq.biz-1" in q for q in gets), gets


# ═══════════════════════════════════════════════════════════════════════
# The name guard — merging two people is the expensive error
# ═══════════════════════════════════════════════════════════════════════

def test_two_different_people_at_one_email_stay_separate():
    """Real row in production: a church list holds one household
    address. A false merge interleaves two people's history across
    seventeen foreign keys; a false split is a duplicate somebody can
    see and fix."""
    g, p, _, posts = _db({"email=ilike": [{"id": "c-1", "name": "Dana Reyes"}]})
    with g, p:
        r = li.resolve("biz-1", name="Marcus Okonkwo", email="house@x.com")
    assert r.created is True
    assert r.contact_id == "new-1"
    assert posts, "no new contact was created for a different person"


def test_a_shortened_name_is_still_the_same_person():
    """False splits are cheap but not free. 'Dana' coming back as
    'Dana Reyes' must not become a second lead."""
    g, p, _, posts = _db({"email=ilike": [{"id": "c-1", "name": "Dana"}]})
    with g, p:
        r = li.resolve("biz-1", name="Dana Reyes", email="dana@x.com")
    assert r.created is False and not posts


def test_an_honorific_carries_no_identity():
    """Without stripping titles, 'Pastor Dana' and 'Pastor Marcus' share
    a token and read as one person."""
    assert li.same_person("Pastor Dana Reyes", "Pastor Marcus Bell") is False
    assert li.same_person("Dr. Dana Reyes", "Dana Reyes") is True


def test_a_missing_name_never_blocks_a_match():
    assert li.same_person("", "Dana") is True
    assert li.same_person("Dana", None) is True


def test_name_tokens_drop_initials_and_noise():
    assert li.name_tokens("Rev. J. Marcus Bell") == {"marcus", "bell"}


# ═══════════════════════════════════════════════════════════════════════
# Creating
# ═══════════════════════════════════════════════════════════════════════

def test_a_new_person_is_created_with_the_arc_fields():
    g, p, _, posts = _db()
    with g, p:
        r = li.resolve("biz-1", name="Dana Reyes", email="Dana@X.com",
                       phone="555-010-2233", source="website_contact_form",
                       source_detail="/contact",
                       attribution={"utm_source": "google"})
    assert r.created is True
    body = posts[0][1]
    assert body["email"] == "dana@x.com", "email stored un-normalized"
    assert body["phone"] == "+15550102233"
    assert body["status"] == "lead"
    assert body["source"] == "website_contact_form"
    assert body["source_detail"] == "/contact"
    assert body["attribution"] == {"utm_source": "google"}


def test_a_nameless_submission_still_becomes_a_contact():
    """Losing a lead because a form did not ask for a name is worse
    than a row that says Unnamed."""
    g, p, _, posts = _db()
    with g, p:
        r = li.resolve("biz-1", name="", email="x@y.com")
    assert r.created is True
    assert posts[0][1]["name"] == "Unnamed"


def test_a_failed_insert_looks_again_before_giving_up():
    """A concurrent submission may have just created them. Dropping the
    lead because our own insert lost is the worst possible outcome."""
    import sb_clients
    state = {"created": False}

    def get(path):
        return [{"id": "c-race", "name": "Dana"}] if state["created"] else []

    def post(path, body, prefer="return=representation"):
        state["created"] = True      # somebody else won
        return None

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get), \
         mock.patch.object(sb_clients, "sb_post_as_service", side_effect=post):
        r = li.resolve("biz-1", name="Dana", email="dana@x.com")
    assert r.contact_id == "c-race" and r.created is False


def test_a_total_failure_reports_it_rather_than_inventing_an_id():
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service", return_value=[]), \
         mock.patch.object(sb_clients, "sb_post_as_service", return_value=None):
        r = li.resolve("biz-1", name="Dana", email="dana@x.com")
    assert r.contact_id is None and r.ok is False


def test_a_lookup_that_explodes_does_not_take_the_capture_with_it():
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service",
                           side_effect=RuntimeError("boom")), \
         mock.patch.object(sb_clients, "sb_post_as_service",
                           return_value=[{"id": "new-1"}]):
        r = li.resolve("biz-1", name="Dana", email="dana@x.com")
    assert r.contact_id == "new-1"


# ═══════════════════════════════════════════════════════════════════════
# Every door uses it — the whole point
# ═══════════════════════════════════════════════════════════════════════

DOORS = ("intake_endpoint.py", "public_site.py", "site_concierge.py",
         "booking_widget_router.py")


def test_all_four_doors_use_the_shared_rule():
    root = pathlib.Path(__file__).resolve().parent.parent
    for filename in DOORS:
        src = (root / filename).read_text(encoding="utf-8")
        assert "import lead_identity" in src, f"{filename} has its own rule"
        assert ("lead_identity.find(" in src
                or "lead_identity.resolve," in src), filename


def test_no_door_still_carries_its_own_contact_lookup():
    """The implementations are gone, not merely bypassed — a second copy
    left behind is the one that drifts.

    This sweep is how the FIFTH door was found: /public/booking/{slug}
    /submit lives in public_site rather than with the rest of the
    booking code, so it had its own case-sensitive lookup and had been
    missed by the scoring and attribution passes as well.

    Scoped to /contacts on purpose. business_customers has a real
    unique index on (business_id, lower(email)) and is entitled to its
    own lookup.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for filename in DOORS:
        for n, line in enumerate(
                (root / filename).read_text(encoding="utf-8").splitlines(), 1):
            if "/contacts?" not in line:
                continue
            if "email=ilike." in line or "&email=eq.{" in line:
                offenders.append(f"{filename}:{n}: {line.strip()}")
    assert not offenders, offenders


def test_the_fifth_door_scores_and_attributes_like_the_others():
    """It was missed by #574 and #580 because of where it lives."""
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "public_site.py").read_text(encoding="utf-8")
    booking = src.split("async def booking_submit")[1].split("\n@router")[0]
    assert "lead_identity.resolve" in booking
    assert "lead_attribution.capture" in booking
    assert "lead_scoring.score_in_background" in booking


def test_the_intake_door_no_longer_creates_unconditionally():
    """It was the only door with no dedupe at all — the same person
    enquiring twice produced two contacts, two AI scoring calls and two
    drafted replies."""
    import inspect

    import intake_endpoint
    src = inspect.getsource(intake_endpoint.submit_intake)
    assert "lead_identity.resolve" in src
    assert 'supabase_request(client, "POST", "/contacts"' not in src
