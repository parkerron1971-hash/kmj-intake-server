"""A scheduled post publishes only what a human approved.

The policy engine does not stop this: class C unattended is *recorded*,
not refused — a deliberate choice for verbs like recurring invoices,
where the practitioner set the recurrence up and the exposure is the
point. Publishing to a public Page is where that reasoning runs out. An
invoice reaches one client who expected it; a post reaches everyone and
cannot be unseen.

So the approval rides on the POST, and these pin the four ways it can
fail to cover what is about to go out.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import post_approval


def _post(**over):
    p = {
        "id": "post-1",
        "title": "Your website can publish news now",
        "body": "Two paragraphs of it.",
        "image_url": None,
    }
    p.update(over)
    return p


def _approved(post, page_id="PAGE_A", to_instagram=False):
    p = dict(post)
    p[post_approval.APPROVAL_KEY] = post_approval.build(
        p, user_id="u-1", page_id=page_id, to_instagram=to_instagram,
        when_iso="2026-08-30T12:00:00Z")
    return p


def _held(post, page_id="PAGE_A", to_instagram=False):
    return post_approval.refusal(post, page_id=page_id, to_instagram=to_instagram)


# ─── The four refusals ───────────────────────────────────────────────

def test_never_approved_is_held():
    assert "never approved" in (_held(_post()) or "")


def test_approved_post_goes():
    assert _held(_approved(_post())) is None


def test_editing_the_body_voids_the_approval():
    """Without the fingerprint, 'approved' would mean 'this row was
    approved once' — and rewriting the body afterwards would publish
    words nobody agreed to, under an approval that still looked valid."""
    p = _approved(_post())
    p["body"] = "Something else entirely."
    assert "edited after it was approved" in (_held(p) or "")


def test_editing_the_image_voids_it_too():
    p = _approved(_post())
    p["image_url"] = "https://example.com/other.png"
    assert "edited after it was approved" in (_held(p) or "")


def test_approval_does_not_transfer_to_another_page():
    """Approving a post for one Page is not approving it for whichever
    Page happens to resolve first at publish time."""
    p = _approved(_post(), page_id="PAGE_A")
    assert "different Page" in (_held(p, page_id="PAGE_B") or "")


def test_instagram_needs_its_own_approval():
    p = _approved(_post(), to_instagram=False)
    assert "Instagram was not part" in (_held(p, to_instagram=True) or "")
    assert _held(_approved(_post(), to_instagram=True), to_instagram=True) is None


# ─── What the fingerprint deliberately ignores ───────────────────────

def test_unrelated_fields_do_not_void_an_approval():
    """The fingerprint covers what a reader sees. If scheduling metadata
    or a counter voided it, people would be re-approving so often they
    would stop reading — which is the failure this is meant to prevent."""
    p = _approved(_post())
    p["scheduled_for"] = "2026-09-01T09:00:00Z"
    p["status"] = "queued"
    p["engagement"] = {"likes": 3}
    assert _held(p) is None


def test_whitespace_only_change_is_not_an_edit():
    p = _approved(_post())
    p["title"] = "  Your website can publish news now  "
    assert _held(p) is None


# ─── The seam the scheduler drives ───────────────────────────────────

def test_the_scheduler_marks_every_run_unattended():
    """The gate hangs on action['_unattended']. If the scheduler ever
    stops setting it, publish_post silently returns to posting whatever
    it is handed — so the assignment is pinned here, not just trusted."""
    import inspect
    import chief_scheduler
    src = inspect.getsource(chief_scheduler)
    assert 'action["_unattended"] = True' in src

    import chief_of_staff
    handler = inspect.getsource(chief_of_staff.handle_publish_post)
    assert '_unattended' in handler and "post_approval" in handler
    # And it is checked only after the Page is known, or it would be
    # comparing the approval against nothing.
    assert handler.index("page_token") < handler.index("post_approval")
