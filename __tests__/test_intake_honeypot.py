"""
test_intake_honeypot.py — THE LEAD ARC.

The intake honeypot was doing the opposite of its job.

IntakeFormBuilder derives a field's `name` from its label:

    label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')

The honeypot list was ("_hp", "website_url", "company_url", "fax").
Three of those four are names that transform PRODUCES: "Fax" -> 'fax',
"Website URL" -> 'website_url', "Company URL" -> 'company_url'. A
practitioner who added any of those fields had every submission
silently discarded with a 200 — no error, no row, nothing they could
see. Silence is what a working honeypot looks like, which is why this
could sit there indefinitely.

The names are collision-proof by construction now, and these tests
encode the transform so the next name added has to survive it.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import intake_endpoint  # noqa: E402


def builder_field_name(label: str) -> str:
    """The exact transform IntakeFormBuilder.tsx:542 applies. If that
    line changes, this is the test that has to be updated with it."""
    return re.sub(r"^_|_$", "",
                  re.sub(r"[^a-z0-9]+", "_", label.lower()))


def test_the_transform_matches_the_builder():
    """Guard the guard: if this drifts from the frontend, every
    assertion below is measuring the wrong thing."""
    assert builder_field_name("Full Name") == "full_name"
    assert builder_field_name("Fax") == "fax"
    assert builder_field_name("Website URL") == "website_url"
    assert builder_field_name("Company URL") == "company_url"
    assert builder_field_name("How did you hear about us?") == "how_did_you_hear_about_us"
    assert builder_field_name("  Notes  ") == "notes"


LABELS_A_PRACTITIONER_MIGHT_ACTUALLY_USE = [
    "Fax", "Fax Number", "Website URL", "Company URL", "Website",
    "Company Website", "Your URL", "Full Name", "Email Address",
    "Phone Number", "Organization", "Budget", "Timeline", "Message",
    "How did you hear about us?", "Preferred Date", "Notes",
    "sol hp", "Sol Hp", "_hp", "HP", "Honeypot",
]


def test_no_label_a_practitioner_could_type_becomes_a_honeypot():
    """THE defect. Every one of these is a field somebody would
    plausibly put on an intake form, and three of them used to mean
    'throw away every submission to this form, forever, silently.'"""
    collisions = [
        (label, builder_field_name(label))
        for label in LABELS_A_PRACTITIONER_MIGHT_ACTUALLY_USE
        if builder_field_name(label) in intake_endpoint.HONEYPOT_FIELDS
    ]
    assert not collisions, (
        f"these labels silently discard every submission: {collisions}")


def test_the_old_names_would_have_failed_that():
    """The negative control. Without it the test above could pass
    because the honeypot list is empty, which would be a different
    bug."""
    old = ("_hp", "website_url", "company_url", "fax")
    collisions = [
        label for label in LABELS_A_PRACTITIONER_MIGHT_ACTUALLY_USE
        if builder_field_name(label) in old
    ]
    assert len(collisions) >= 3, collisions


def test_the_honeypot_is_not_empty():
    """A honeypot with no names is not a fix, it is a removal."""
    assert intake_endpoint.HONEYPOT_FIELDS
    assert "sol-hp" in intake_endpoint.HONEYPOT_FIELDS


def test_every_honeypot_name_is_unreachable_by_construction():
    """Not 'no label in our list produces it' — no label CAN. The
    transform emits only [a-z0-9_] with no leading or trailing
    underscore, so a hyphen or a leading underscore is proof."""
    for name in intake_endpoint.HONEYPOT_FIELDS:
        reachable = re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", name)
        assert not reachable, (
            f"{name!r} is a name the builder's label transform can "
            f"produce — a real field could collide with it")


def test_embeds_already_in_the_wild_still_work():
    """`_hp` is what previously-generated snippets send, if any do.
    Dropping it would be a silent regression in the other direction."""
    assert "_hp" in intake_endpoint.HONEYPOT_FIELDS


def test_the_endpoint_reads_the_shared_tuple():
    """So the list cannot be narrowed here and left wide there."""
    import inspect
    src = inspect.getsource(intake_endpoint.submit_intake)
    assert "for hp in HONEYPOT_FIELDS:" in src


# ── behaviour: the trap catches bots, spares humans, and says so ──────

def _submit(data, form_business_id="biz-1"):
    import asyncio
    from unittest import mock
    calls, logs = [], []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path))
        if path.startswith("/intake_forms"):
            return [{"id": "form-1", "business_id": form_business_id,
                     "fields": [], "settings": {}, "form_type": "general",
                     "name": "Contact"}]
        if path.startswith("/businesses"):
            return [{"id": "biz-1", "name": "Co", "type": "general",
                     "voice_profile": {}}]
        if method == "POST":
            return [{"id": "c-1"}]
        return []

    req = type("R", (), {"headers": {}, "client": type("C", (), {"host": "1.2.3.4"})()})()
    body = intake_endpoint.IntakeSubmission(
        form_id="form-1", business_id="biz-1", data=data)

    import lead_identity
    import lead_scoring
    # The contact write goes through lead_identity now (one dedupe
    # rule, shared by all five doors), which uses sb_clients rather
    # than this module's supabase_request helper.
    resolution = lead_identity.Resolution(contact_id="c-1", created=True)
    with mock.patch.object(intake_endpoint, "supabase_request", side_effect=fake_sb), \
         mock.patch("lead_identity.resolve", return_value=resolution), \
         mock.patch.object(intake_endpoint, "get_supabase_url", return_value="https://x"), \
         mock.patch.object(intake_endpoint, "get_supabase_anon", return_value="k"), \
         mock.patch.object(intake_endpoint, "get_anthropic_key", return_value=""), \
         mock.patch.object(intake_endpoint, "_intake_rate_ok", return_value=True), \
         mock.patch.object(intake_endpoint.logger, "warning",
                           side_effect=lambda m, *a: logs.append(str(m))), \
         mock.patch("lead_scoring.score_and_store",
                    return_value=lead_scoring.LeadScore(score=50)):
        out = asyncio.run(intake_endpoint.submit_intake(body, req))
    return out, calls, logs


def test_a_filled_trap_drops_the_submission_and_writes_nothing():
    out, calls, logs = _submit({"name": "Bot", "sol-hp": "http://spam.example"})
    assert out == {"status": "ok", "contact_id": None, "queued": False}
    assert not [c for c in calls if c[0] == "POST"], "the bot got a row"
    assert any("honeypot" in m and "DROPPED" in m for m in logs), logs


def test_a_trip_names_the_form_so_it_can_be_diagnosed():
    """The failure mode is a human being thrown away in silence. The log
    line has to be enough to find WHICH form is doing it."""
    _, _, logs = _submit({"name": "Bot", "sol-hp": "x"})
    trip = [m for m in logs if "honeypot" in m][0]
    assert "form-1" in trip and "sol-hp" in trip


def test_an_empty_trap_lets_a_real_person_through():
    """The negative control: a trap that drops everyone would satisfy
    the two tests above."""
    out, calls, _ = _submit({"name": "Real Person", "email": "r@example.com",
                             "sol-hp": ""})
    assert out["success"] is True
    # lead_identity did the write; what this test cares about is
    # that the trap let them through at all.
    assert out["contact_id"] == "c-1"
