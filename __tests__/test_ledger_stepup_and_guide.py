"""Three things, one arc: step-up on the ledger, the guide reaching the
auditor it was built for, and Chief able to ask for it in words.

The through-line is the same rule the ledger has had since Stage 4: the
software finds and filters; the human concludes. Every layer added here
keeps the model on the finding side of that line, and does so by not
handing it the data rather than by asking it nicely.
"""
from __future__ import annotations

import os
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

os.environ.setdefault("AUDITOR_LINK_SECRET", "unit-test-secret")

_AUDIT_SRC = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
_PORTAL_SRC = (_here.parent / "auditor_portal.py").read_text(encoding="utf-8")
_UNLOCK_SRC = (_here.parent / "ledger_unlock.py").read_text(encoding="utf-8")


def _req(token: str = ""):
    return type("R", (), {"headers": {"X-Ledger-Unlock": token} if token else {}})()


# ─── 1. Step-up ──────────────────────────────────────────────────────

def test_an_unlock_proves_one_specific_person():
    """Bound to the user, so one signed-in person's unlock cannot be
    replayed by another."""
    import ledger_unlock
    tok = ledger_unlock.mint("user-a")["token"]
    assert ledger_unlock.verify(tok, "user-a") is True
    assert ledger_unlock.verify(tok, "user-b") is False


def test_an_unlock_expires():
    import time
    import ledger_unlock
    tok = ledger_unlock.mint("user-a")["token"]
    assert ledger_unlock.verify(tok, "user-a") is True
    real = time.time
    time.time = lambda: real() + ledger_unlock.UNLOCK_TTL_SECONDS + 5
    try:
        assert ledger_unlock.verify(tok, "user-a") is False
    finally:
        time.time = real


def test_a_forged_or_absent_unlock_is_refused():
    import ledger_unlock
    for bad in ("", "nonsense", "a.b", "....."):
        assert ledger_unlock.verify(bad, "user-a") is False


def test_an_unlock_cannot_be_used_as_an_auditor_link_or_session():
    """Same key, three credential types. Without distinct HMAC domains
    one would verify as another — the lesson the auditor-session work
    already paid for, applied to the third."""
    import auditor_links
    import ledger_unlock
    tok = ledger_unlock.mint("user-a")["token"]
    assert auditor_links.verify(tok) is None
    assert auditor_links.resolve_session(tok) is None


def test_the_lock_is_machine_readable():
    """The frontend must tell "unlock me" apart from "you may never read
    this". Showing a password box to someone who will never be let in is
    its own small cruelty; showing "access denied" to someone who just
    needs to type their password is worse."""
    from fastapi import HTTPException
    import ledger_unlock
    with pytest.raises(HTTPException) as e:
        ledger_unlock.require_unlock(_req(), "user-a")
    assert e.value.status_code == 403
    assert e.value.detail["code"] == "ledger_locked"


def test_a_valid_unlock_passes_the_gate():
    import ledger_unlock
    tok = ledger_unlock.mint("user-a")["token"]
    ledger_unlock.require_unlock(_req(tok), "user-a")   # must not raise


def test_every_authenticated_ledger_surface_is_gated():
    """Read, verify, export and navigate are all the ledger. Gating some
    of them would just mean the export is the way in."""
    for marker in ('@router.get("")', '@router.get("/verify")',
                   '@router.get("/export")', '@router.post("/navigate")'):
        section = _AUDIT_SRC.split(marker)[1].split("\n@router")[0]
        assert "ledger_unlock.require_unlock(" in section, f"{marker} is not gated"


def test_minting_and_redaction_are_gated_but_revocation_is_not():
    """Revocation only ever REDUCES access, and it is what you reach for
    when a link has leaked. A password prompt between a practice and
    cutting off a live auditor is a control that hurts the person it
    exists to protect."""
    mint = _PORTAL_SRC.split("def mint_link(")[1].split("\n@router")[0]
    redact = _PORTAL_SRC.split("def redact_subject(")[1].split("\n@router")[0]
    revoke = _PORTAL_SRC.split("def revoke_link(")[1].split("\n@router")[0]
    assert "require_unlock(" in mint
    assert "require_unlock(" in redact
    assert "require_unlock(" not in revoke
    assert "DELIBERATELY no step-up" in revoke, "the exemption must say why"


def test_the_password_check_fails_closed_on_an_outage():
    """A transport failure must not read as a successful unlock."""
    check = _UNLOCK_SRC.split("async def check_password(")[1].split("\ndef ")[0]
    assert "raise HTTPException(503" in check
    assert "grant_type" in check, "the password is re-proved against Supabase"


def test_the_unlock_attempt_is_recorded_either_way():
    body = _AUDIT_SRC.split("async def unlock_ledger(")[1].split("\n@router")[0]
    assert 'verb="ledger:unlocked"' in body
    assert 'verb="ledger:unlock_failed"' in body
    assert "_require_ledger_read(" in body, \
        "someone who may not read this ledger must not get a password oracle"
    assert 'allow_strict("ledger_unlock"' in body


def test_step_up_does_not_pretend_to_narrow_the_audience():
    """The read gate still admits viewers and accountants. Step-up puts
    a prompt in front of that audience; it does not shrink it, and
    saying otherwise would be false comfort."""
    head = " ".join(_UNLOCK_SRC.split('"""')[1].split())
    assert "does not narrow" in head
    assert "not a second factor" in head


# ─── 2. The guide reaches the auditor ────────────────────────────────

def test_the_auditor_can_finally_use_the_navigator():
    """It existed only behind require_user — the one audience it was
    designed for could not reach it."""
    assert '@router.post("/public/audit/view/navigate")' in _PORTAL_SRC
    body = _PORTAL_SRC.split("def auditor_navigate(")[1].split("\n@router")[0]
    assert "_session(request)" in body
    assert "audit_log.run_navigation(" in body


def test_the_auditors_navigator_is_metered_per_link():
    """It spends money per call and the caller is an outsider, so the
    budget is keyed to the LINK — an IP bucket is theirs to vary free."""
    body = _PORTAL_SRC.split("def auditor_navigate(")[1].split("\n@router")[0]
    assert 'rate_limit.allow("ledger_nav", ctx["jti"])' in body


def test_the_signed_window_clamps_the_model():
    """THE security property. The filter comes from free text an
    outsider typed. Without the clamp, "everything from last year" on a
    link scoped to one quarter would widen the link, and the model would
    have become the access-control decision."""
    fn = _AUDIT_SRC.split("def run_navigation(")[1].split("@router.post")[0]
    assert "max(since, ws)" in fn, "a later start must win"
    assert "min(until, we)" in fn, "an earlier end must win"
    body = _PORTAL_SRC.split("def auditor_navigate(")[1].split("\n@router")[0]
    assert "window_start=ctx" in body and "window_end=ctx" in body


def test_the_window_narrows_and_never_widens():
    """Exercised, not just read: a filter asking for the whole year
    against a link scoped to one quarter comes back as the quarter."""
    import audit_log
    captured = {}

    real = audit_log.ledger_entries
    audit_log.ledger_entries = lambda biz, **kw: captured.update(kw) or []
    real_nav = sys.modules.get("ledger_navigator")
    import ledger_navigator
    real_resolve = ledger_navigator.resolve
    ledger_navigator.resolve = lambda q: {
        "filter": {"since": "2026-01-01T00:00:00Z", "until": "2026-12-31T00:00:00Z"},
        "description": "the whole year"}
    try:
        audit_log.run_navigation(
            "b1", "everything from last year",
            actor_type="agent", actor_id="auditor:x", authorized_by="auditor_link",
            window_start="2026-04-01T00:00:00Z", window_end="2026-06-30T00:00:00Z")
    finally:
        audit_log.ledger_entries = real
        ledger_navigator.resolve = real_resolve
        if real_nav is not None:
            sys.modules["ledger_navigator"] = real_nav
    assert captured["since"] == "2026-04-01T00:00:00Z", "start clamped forward"
    assert captured["until"] == "2026-06-30T00:00:00Z", "end clamped back"


def test_the_portal_renders_rows_without_innerhtml():
    """Verbs, actor names and subject ids are practitioner-controlled
    text. The server escapes them on first render; putting them back
    through innerHTML would hand an auditor's browser to whoever could
    get a string into a ledger row."""
    # Strip the comments first — one of them says "never innerHTML", and
    # matching prose instead of code is how a test passes while the
    # thing it guards is broken.
    script = _PORTAL_SRC.split("<script>")[1].split("</script>")[0]
    code = " ".join(l for l in script.splitlines()
                    if not l.strip().startswith("//"))
    assert "innerHTML" not in code
    assert "textContent" in code


def test_the_portal_shows_the_filter_description_not_a_verdict():
    script = _PORTAL_SRC.split("<script>")[1].split("</script>")[0]
    assert "j.description" in script
    assert "j.summary" not in script and "verdict" not in script


# ─── 3. Chief can ask, but is never told what it means ───────────────

def test_chief_has_the_verb_and_it_is_classified():
    import action_registry
    import chief_of_staff
    assert "search_ledger" in chief_of_staff.ACTION_HANDLERS
    assert action_registry.effect("search_ledger") == action_registry.READ


def test_chief_is_never_handed_the_rows():
    """THE line. Give Chief the rows and it becomes the thing that says
    "nothing unusual happened there" — the conclusion the reader has to
    reach alone, and the one a ledger exists to stop software producing
    on someone's behalf."""
    src = (_here.parent / "chief_of_staff.py").read_text(encoding="utf-8")
    body = src.split("async def handle_search_ledger(")[1].split("\nasync def ")[0]
    assert '"entries"' not in body, "row contents must not reach Chief's context"
    assert '"count": count' in body
    assert '"description": desc' in body


def test_chief_returns_the_shape_the_app_needs():
    """Every handler returns result + label or the surface blanks."""
    src = (_here.parent / "chief_of_staff.py").read_text(encoding="utf-8")
    body = src.split("async def handle_search_ledger(")[1].split("\nasync def ")[0]
    assert '"result":' in body and '"label":' in body
    assert '"nav": {"tab": "operate", "sub": "history"' in body


def test_the_ledger_verb_never_reaches_the_agent_surface():
    """Exposure is DERIVED — any verb classified `read` lands on the MCP
    surface automatically, which is how a surface widens with nobody
    deciding to widen it. The count tripwire caught this one. Marked
    sensitive: a long-lived agent token must not be the way around the
    step-up just added for humans."""
    import action_registry
    assert action_registry.is_sensitive("search_ledger") is True
    assert action_registry.may_expose_to_agent("search_ledger") is False
    assert action_registry.may_expose_to_agent("search_ledger", allow_writes=True) is False


def test_the_sentence_describes_what_was_applied_not_what_was_asked():
    """Found by driving the live portal, not by a unit test.

    On a link scoped to January, "everything from the last two years"
    returned zero rows under the sentence "Showing everything recorded
    since 2022-07-01". The clamp was right; the sentence was a lie, and
    an auditor would reasonably read "nothing happened in two years"
    from a search that in fact covered one month. A narrowing the reader
    cannot see is the exact failure this surface exists to prevent.
    """
    import audit_log
    import ledger_navigator

    real_entries = audit_log.ledger_entries
    real_resolve = ledger_navigator.resolve
    audit_log.ledger_entries = lambda biz, **kw: []
    ledger_navigator.resolve = lambda q: {
        "filter": {"since": "2022-07-01T00:00:00Z"},
        "description": "Showing everything recorded since 2022-07-01, most recent first."}
    try:
        out = audit_log.run_navigation(
            "b1", "everything from the last two years",
            actor_type="agent", actor_id="auditor:x",
            authorized_by="auditor_link",
            window_start="2026-01-01T00:00:00Z",
            window_end="2026-01-31T00:00:00Z")
    finally:
        audit_log.ledger_entries = real_entries
        ledger_navigator.resolve = real_resolve

    assert "2022" not in out["description"], \
        "the sentence must not claim a range the search did not cover"
    assert "2026-01-01" in out["description"] and "2026-01-31" in out["description"]
    assert "narrowed" in out["description"], "the narrowing must be said out loud"


def test_an_unclamped_search_keeps_its_original_sentence():
    """No window, no narrowing, no extra caveat to explain away."""
    import audit_log
    import ledger_navigator
    real_entries = audit_log.ledger_entries
    real_resolve = ledger_navigator.resolve
    audit_log.ledger_entries = lambda biz, **kw: []
    ledger_navigator.resolve = lambda q: {
        "filter": {"since": "2026-07-01T00:00:00Z"}, "description": "SENTINEL"}
    try:
        out = audit_log.run_navigation(
            "b1", "july", actor_type="user", actor_id="u1",
            authorized_by="ledger_read")
    finally:
        audit_log.ledger_entries = real_entries
        ledger_navigator.resolve = real_resolve
    assert out["description"] == "SENTINEL"


def test_audit_honours_every_filter_the_navigator_can_produce():
    """Found auditing the seam: the navigator emits `actor` and
    `subject_id`, but GET /audit — where a reader LANDS after Chief
    resolves a question — silently dropped both. Chief counted rows with
    the actor applied, the panel re-fetched without it, and "3 records by
    chief" opened onto every actor's rows with nothing on screen
    admitting the constraint had gone.
    """
    import inspect
    import audit_log
    sig = set(inspect.signature(audit_log.read_audit).parameters)
    emitted = {"since", "until", "verb", "failed_only",
               "include_db", "limit", "actor", "subject_id"}
    assert emitted <= sig, f"/audit cannot express: {sorted(emitted - sig)}"


def test_both_readers_share_one_post_filter_implementation():
    src = (_here.parent / "audit_log.py").read_text(encoding="utf-8")
    assert src.count("def apply_post_filters(") == 1
    for caller in ("def read_audit(", "def run_navigation("):
        body = src.split(caller)[1].split("\n@router")[0]
        assert "apply_post_filters(" in body, f"{caller} must use the shared filter"


def test_the_actor_filter_actually_narrows():
    import audit_log
    rows = [
        {"id": "1", "actor_type": "chief", "actor_id": "chief"},
        {"id": "2", "actor_type": "user", "actor_id": "u1"},
    ]
    assert [r["id"] for r in audit_log.apply_post_filters(rows, "chief", None)] == ["1"]
    assert len(audit_log.apply_post_filters(rows, None, None)) == 2


def test_the_subject_filter_matches_refs_and_legacy_targets():
    import audit_log
    rows = [
        {"id": "1", "subject_refs": [{"type": "contacts", "id": "c-abc"}], "target_id": None},
        {"id": "2", "subject_refs": [], "target_id": "c-abc"},
        {"id": "3", "subject_refs": [], "target_id": "other"},
    ]
    got = [r["id"] for r in audit_log.apply_post_filters(rows, None, "c-abc")]
    assert got == ["1", "2"]
