"""The SMS endpoints check WHOSE business it is.

WHY THIS FILE EXISTS
  `require_user` proves the caller is signed in. It says nothing about
  which business they signed in to. Six practitioner endpoints across
  sms_service and sms_routing took `business_id` straight out of the
  request and trusted it:

    POST /sms/send                 text anyone AS any business
    GET  /sms/conversation/{b}/{c} read any business's SMS thread, bodies
    POST /sms/session-reminder     send a reminder as any business
    GET  /sms/keyword              read any business's inbound keyword
    POST /sms/keyword              set the keyword of a business not yours
    POST /sms/broadcast            text up to 500 of another practitioner's
                                   contacts, under that practitioner's name

  `email_sender.send_email` already carries the fix and a comment
  describing exactly this attack on the email side. SMS never got the
  sweep — because `ownership_sweep.PUBLIC_BY_DESIGN` exempted both
  modules as "inbound webhooks". SMS's webhooks are in twilio_sms.py,
  which is signature-validated; these are session endpoints, and the
  exemption is why the ratchet never made a sound about them.

  So this file tests the guard, and test_business_access_ratchet tests
  that the exemption stays gone.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import ownership_sweep
import sms_routing
import sms_service

# (module, handler, the minimum role its business check demands)
GUARDED = [
    (sms_service, "send_sms", "member"),
    (sms_service, "get_conversation", "viewer"),
    (sms_service, "send_session_reminder", "member"),
    (sms_routing, "get_keyword", "viewer"),
    (sms_routing, "set_keyword", "admin"),
    (sms_routing, "broadcast", "admin"),
]


def _source(mod, fn):
    import inspect
    return inspect.getsource(getattr(mod, fn))


@pytest.mark.parametrize("mod,fn,role", GUARDED,
                         ids=[f"{m.__name__}.{f}" for m, f, _ in GUARDED])
def test_the_handler_resolves_the_callers_relationship_to_the_business(mod, fn, role):
    src = _source(mod, fn)
    assert "assert_access" in src, (
        f"{mod.__name__}.{fn} takes a business id and does not check it")
    assert f'"{role}"' in src, (
        f"{mod.__name__}.{fn} should demand at least {role!r}")


@pytest.mark.parametrize("mod,fn,role", GUARDED,
                         ids=[f"{m.__name__}.{f}" for m, f, _ in GUARDED])
def test_the_check_runs_before_the_work(mod, fn, role):
    """A check that runs after the send is not a check.

    Ordering is the whole property here: broadcast in particular walks a
    contact list and texts every row, so an authorisation that landed
    below the loop would refuse a caller who had already spent the
    practitioner's carrier reputation."""
    src = _source(mod, fn)
    gate = src.index("assert_access")
    for marker in ("httpx.AsyncClient()", "_sb_get(", "_sb_post(",
                   "send_sms_core("):
        at = src.find(marker)
        if at != -1:
            assert gate < at, (
                f"{mod.__name__}.{fn}: assert_access runs after {marker}")


def test_the_bulk_one_is_not_merely_member():
    """/sms/broadcast reaches up to 500 people at once under the
    practitioner's brand. Its docstring calls business_id scoping "what
    makes cross-contamination structurally impossible" — which was true
    of the QUERY and false of the authorisation, because the id was the
    caller's to choose."""
    src = _source(sms_routing, "broadcast")
    assert '"admin"' in src and '"member"' not in src


def test_sms_is_no_longer_exempt_from_the_ownership_sweep():
    """The exemption is what hid all six. It described these modules as
    inbound webhooks; the webhooks live in twilio_sms.py."""
    assert "sms_service" not in ownership_sweep.PUBLIC_BY_DESIGN
    assert "sms_routing" not in ownership_sweep.PUBLIC_BY_DESIGN


def test_no_sms_handler_is_reported_unguarded():
    rows = ownership_sweep.sweep()["unguarded"]
    sms = sorted(f"{r['module']}.{r['fn']}" for r in rows
                 if r["module"] in ("sms_service", "sms_routing"))
    assert not sms, f"still unguarded: {sms}"


def test_the_public_opt_in_page_stays_public():
    """/api/sms/opt-in takes no business id and backs the crawlable /sms
    page an A2P reviewer verifies. Guarding it would break the thing it
    exists for — this pins that the sweep's own rule (only handlers that
    TAKE a business id) is what keeps it out, not an exemption."""
    import inspect
    src = inspect.getsource(sms_routing.sms_opt_in)
    assert "business_id" not in src
    assert "require_user" not in src


# ─── the sweep measures the repository ────────────────────────────────

def test_the_sweep_ignores_dot_directories():
    """Found the hard way: a real ownership fix landed on sms_service.py
    and the sweep kept reporting the handler unguarded, because rglob was
    reading a months-old copy of that file out of an untracked
    .claude-wt-ctx/ snapshot directory and the duplicate won.

    A ratchet computed against files nobody ships fails in the dangerous
    direction — it hides a fix, so the next person concludes the guard
    does not work and removes it."""
    files = list(ownership_sweep._source_files())
    assert files, "the sweep found no files at all"
    for f in files:
        parts = f.relative_to(ownership_sweep.ROOT).parts[:-1]
        assert not any(p.startswith(".") for p in parts), (
            f"sweep is reading {f} out of a dot-directory")


def test_no_top_level_module_is_parsed_from_two_places():
    """The symptom the dot-directory rule cures.

    The sweep keys a module by FILE STEM, and nested packages share stems
    legitimately (a dozen `__init__.py`, several `router.py`) — so a bare
    duplicate count is noise. The invariant that actually matters is
    narrower: every router that lives at the top level must be parsed
    from the top level and nowhere else. A second copy of `sms_service.py`
    anywhere in the tree is the failure, because whichever the walk
    reaches last is the one the ratchet reports on.
    """
    top = {f.stem for f in ownership_sweep.ROOT.glob("*.py")}
    seen = {}
    for f in ownership_sweep._source_files():
        if f.stem in top:
            seen.setdefault(f.stem, []).append(
                f.relative_to(ownership_sweep.ROOT).as_posix())
    shadowed = {k: v for k, v in seen.items() if len(v) > 1}
    assert not shadowed, (
        f"top-level modules parsed from more than one path: {shadowed}. "
        f"The sweep is measuring something other than the repository.")


def test_the_sms_modules_specifically_are_read_from_the_repo():
    """The concrete instance, pinned by name: these two are what the
    stale copy shadowed, and they are what the fix above had to reach."""
    for stem in ("sms_service", "sms_routing"):
        paths = [f.relative_to(ownership_sweep.ROOT).as_posix()
                 for f in ownership_sweep._source_files() if f.stem == stem]
        assert paths == [f"{stem}.py"], f"{stem} parsed from {paths}"
