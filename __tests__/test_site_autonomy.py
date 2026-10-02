"""The dial, and the line it is not allowed to cross.

Kevin's ruling: the site feed may publish on a schedule without a
per-post approval; social never may. The point of these is not that the
setting works — it is that the setting *cannot be made to reach social*,
including by a later caller who passes the wrong verb in good faith.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_registry
import site_publish


# ─── The line ────────────────────────────────────────────────────────

def test_the_dial_governs_the_site_verb_only():
    assert site_publish.GOVERNS == frozenset({"publish_to_site"})


def test_social_is_never_exempt_even_with_the_dial_on():
    """The check is verb-first. A caller passing publish_post through
    the same door inherits nothing."""
    on = {site_publish.SETTING_KEY: site_publish.AUTO_SITE}
    assert site_publish.exempt_from_approval("publish_post", on) is False
    assert site_publish.exempt_from_approval("send_email", on) is False
    assert site_publish.exempt_from_approval("bulk_approve", on) is False


def test_the_site_verb_is_exempt_only_when_the_dial_is_on():
    on = {site_publish.SETTING_KEY: site_publish.AUTO_SITE}
    off = {site_publish.SETTING_KEY: site_publish.APPROVE_ALL}
    assert site_publish.exempt_from_approval("publish_to_site", on) is True
    assert site_publish.exempt_from_approval("publish_to_site", off) is False


# ─── Failing closed ──────────────────────────────────────────────────

def test_an_unset_dial_reads_as_approve_all():
    assert site_publish.setting({}) == site_publish.APPROVE_ALL
    assert site_publish.setting(None) == site_publish.APPROVE_ALL


def test_a_nonsense_value_reads_as_approve_all():
    """A dial that fails open is a dial that publishes on the day
    someone fat-fingers a row."""
    for junk in ("auto", "AUTO_SITE", "true", True, 1, {"on": True}, ""):
        assert site_publish.setting({site_publish.SETTING_KEY: junk}) \
            == site_publish.APPROVE_ALL, junk


# ─── The verb's own classification ───────────────────────────────────

def test_publish_to_site_is_registered_and_irreversible():
    """Class C even though it is our own server: it is public the moment
    it lands, and search may index it before anyone reads it twice. The
    dial is an explicit exemption from C's unattended rule, not a claim
    that the verb is harmless."""
    cls = action_registry.classification("publish_to_site")
    assert cls, "publish_to_site must be in the registry or the gate fails open"
    assert cls.get("reversibility") == "C"
    assert not action_registry.is_autonomy_eligible("publish_to_site")


def test_the_handler_consults_the_dial_and_the_gate():
    import inspect
    import chief_of_staff
    src = inspect.getsource(chief_of_staff.handle_publish_to_site)
    assert "_unattended" in src
    assert "exempt_from_approval" in src
    assert "post_approval" in src
    # The exemption is ANDed with the unattended check, never replaces it.
    assert "not site_publish.exempt_from_approval" in src
