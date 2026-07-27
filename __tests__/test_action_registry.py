"""
test_action_registry.py — guards the action taxonomy against drift.

`action_registry` says what each Chief verb DOES: read / ui / write, and for
writes how reversible it is. Two surfaces will consume that — Chief autonomy
and an agent-facing MCP surface — and both fail CLOSED on a verb they don't
recognize.

Failing closed is the right default, but it is silent: add a verb to
ACTION_HANDLERS without classifying it and nothing breaks, it just quietly
never works from those surfaces, and nobody finds out for a month. This test
is what makes that loud. It is the same discipline as
`vertical_registry.KNOWN_GAPS` + `test_vertical_registry.py`: gaps are allowed,
*undeclared* gaps are not.

Note the registry is deliberately incomplete right now (S1.1 steps 3-4 are the
remaining classification work). These tests are green against that partial
state by design — they assert the registry and ACTION_HANDLERS describe the
same verb SET, not that every verb is classified.
"""
import action_registry as reg
import chief_of_staff as cos


# ── the drift guard ──────────────────────────────────────────────────

def test_every_action_handler_verb_is_accounted_for():
    """A verb added to Chief must be classified OR declared pending.

    This is the test that earns the file. Without it, a new verb silently
    inherits deny-by-default and quietly doesn't work from autonomy or an
    agent surface."""
    missing = sorted(set(cos.ACTION_HANDLERS) - reg.known_verbs())
    assert not missing, (
        f"{len(missing)} verb(s) in ACTION_HANDLERS with no entry in "
        f"action_registry: {missing}\n"
        f"Add each to REGISTRY (with a reason) or to UNCLASSIFIED (with a "
        f"note on why it's pending). Unclassified verbs fail closed — they "
        f"are not exposable and not autonomy-eligible — so leaving one out "
        f"breaks it silently instead of loudly.")


def test_registry_has_no_verbs_chief_lost():
    """The reverse drift: a verb renamed or removed from Chief must not linger
    here, or the taxonomy slowly describes a system that no longer exists."""
    stale = sorted(reg.known_verbs() - set(cos.ACTION_HANDLERS))
    assert not stale, (
        f"action_registry references verb(s) absent from ACTION_HANDLERS: "
        f"{stale}. Renamed or removed? Update the registry to match.")


def test_classified_and_unclassified_are_disjoint():
    """A verb is ruled on or it isn't. Both would make `known_verbs()` lie
    about coverage and hide a pending decision behind a real one."""
    overlap = sorted(reg.classified_verbs() & reg.unclassified_verbs())
    assert not overlap, (
        f"verb(s) both classified and listed pending: {overlap}. "
        f"Remove them from UNCLASSIFIED.")


# ── shape ────────────────────────────────────────────────────────────

def test_entries_are_well_formed():
    """Every entry carries a known effect and a reason; every write carries a
    valid reversibility class; nothing else does."""
    for verb, entry in sorted(reg.REGISTRY.items()):
        assert entry.get("effect") in reg.EFFECTS, (
            f"{verb}: effect must be one of {reg.EFFECTS}, got {entry.get('effect')!r}")
        assert entry.get("why", "").strip(), (
            f"{verb}: every classification needs a written reason — that reason "
            f"is the only reviewable artifact of a judgment call")
        if entry["effect"] == reg.WRITE:
            assert entry.get("reversibility") in reg.REVERSIBILITY_CLASSES, (
                f"{verb}: a write needs reversibility in "
                f"{reg.REVERSIBILITY_CLASSES}, got {entry.get('reversibility')!r}")
        else:
            assert "reversibility" not in entry, (
                f"{verb}: reversibility is meaningless for a "
                f"{entry['effect']} verb — remove it")


def test_unclassified_entries_carry_a_note():
    for verb, note in sorted(reg.UNCLASSIFIED.items()):
        assert isinstance(note, str) and note.strip(), (
            f"{verb}: pending verbs need a note saying why they're pending")


# ── the safety property everything else rests on ─────────────────────

def test_unknown_and_pending_verbs_are_denied():
    """Default-deny. An unclassified verb must behave exactly like class C.

    This is what makes a partial registry safe to ship, so it is asserted
    directly rather than assumed from the accessor implementations."""
    probes = ["definitely_not_a_verb", ""] + sorted(reg.unclassified_verbs())
    for verb in probes:
        assert reg.classification(verb) is None, f"{verb}: should be unknown"
        assert reg.effect(verb) is None, f"{verb}: should have no effect kind"
        assert reg.reversibility(verb) is None, f"{verb}: should have no class"
        assert not reg.is_read_only(verb), f"{verb}: must not read as read-only"
        assert not reg.may_expose_to_agent(verb), f"{verb}: must not be exposable"
        assert not reg.may_expose_to_agent(verb, allow_writes=True), (
            f"{verb}: must not be exposable even on a write-granted surface")
        assert not reg.is_autonomy_eligible(verb), f"{verb}: must not be autonomous"
        assert not reg.is_autonomy_eligible(verb, granted_scope=True), (
            f"{verb}: a granted scope must not rescue an unclassified verb")


def test_class_c_is_never_autonomous_or_exposable():
    """C is proposal-only forever — §2.4 calls it out as not a tuning knob."""
    c_verbs = [v for v in reg.REGISTRY if reg.reversibility(v) == "C"]
    assert c_verbs, "expected at least one class-C verb (delete_contact)"
    for verb in c_verbs:
        assert not reg.is_autonomy_eligible(verb), f"{verb}: C must never be autonomous"
        assert not reg.is_autonomy_eligible(verb, granted_scope=True), (
            f"{verb}: no scope grant may make a class-C verb autonomous")
        assert not reg.may_expose_to_agent(verb, allow_writes=True), (
            f"{verb}: C must never be agent-callable")


def test_ui_verbs_are_never_exposed():
    """UI directives drive the app surface. An off-app caller has no surface,
    so exposing them is noise at best and confusing at worst."""
    for verb in [v for v in reg.REGISTRY if reg.effect(v) == reg.UI]:
        assert not reg.may_expose_to_agent(verb)
        assert not reg.may_expose_to_agent(verb, allow_writes=True)
        assert not reg.is_autonomy_eligible(verb)


def test_reads_are_exposable_and_writes_are_not_by_default():
    """The open-on-read / closed-on-write rule, asserted rather than trusted."""
    reads = [v for v in reg.REGISTRY if reg.effect(v) == reg.READ]
    writes = [v for v in reg.REGISTRY if reg.effect(v) == reg.WRITE]
    assert reads and writes, "expected both reads and writes in the registry"
    for verb in reads:
        assert reg.may_expose_to_agent(verb), f"{verb}: a verified read should be exposable"
    for verb in writes:
        assert not reg.may_expose_to_agent(verb), (
            f"{verb}: writes must not be exposable on the default read-only surface")


def test_class_b_needs_a_granted_scope():
    """B is auto-eligible only WITH a scope; A without one. If a B verb ever
    reads as eligible bare, the distinction has collapsed. Bulk verbs are
    excluded — they answer to the rule below instead."""
    for verb in reg.REGISTRY:
        if reg.is_bulk(verb):
            continue
        rev = reg.reversibility(verb)
        if rev == "A":
            assert reg.is_autonomy_eligible(verb), f"{verb}: class A is auto-eligible"
        elif rev == "B":
            assert not reg.is_autonomy_eligible(verb), (
                f"{verb}: class B must NOT be autonomous without a granted scope")
            assert reg.is_autonomy_eligible(verb, granted_scope=True), (
                f"{verb}: class B should be autonomous once scoped")


def test_bulk_verbs_are_never_autonomous():
    """A bulk verb acts on a whole filtered set at once. The reversibility of
    one row says nothing about undoing forty, so bulk overrides class — even
    class A, and even with a scope granted."""
    bulk = [v for v in reg.REGISTRY if reg.is_bulk(v)]
    assert bulk, "expected at least one bulk verb (bulk_approve, bulk_dismiss, batch_email)"
    for verb in bulk:
        assert not reg.is_autonomy_eligible(verb), f"{verb}: bulk must never be autonomous"
        assert not reg.is_autonomy_eligible(verb, granted_scope=True), (
            f"{verb}: no scope grant may make a bulk verb autonomous")


def test_nothing_is_class_b_while_there_is_no_outbox():
    """§2.4 defines B as a send with a recall window. This system has no
    delayed-send outbox — every send is immediate — so nothing can honestly
    be B yet, and the outbound verbs sit at C instead.

    When an outbox ships, this test is the thing that should fail: that is
    the moment to walk the C entries whose note says "becomes B with an
    outbox" and move them. It is a reminder, not a prohibition."""
    b_verbs = [v for v in reg.REGISTRY if reg.reversibility(v) == "B"]
    assert not b_verbs, (
        f"{b_verbs} are class B — has a delayed-send outbox shipped? If so, good: "
        f"move every C entry noting 'becomes B with an outbox' and delete this test. "
        f"If not, B grants autonomy against a safety net that does not exist.")


# ── the invariant chief_action_reasoner only asks for in a comment ───

def test_remap_descriptions_are_all_registered_class_a():
    """The reasoner's hand-written source list must contain only class-A verbs.

    NOTE this asserts `_REMAP_DESCRIPTIONS`, the hand-edited dict — NOT the
    derived `SAFE_REMAP_ACTIONS`. Asserting the derived one would be vacuous:
    it is filtered to class A by construction, so it can never fail. The
    hand-edited dict is where a mistake actually enters, so that is what gets
    checked.

    This is the concrete drift risk the registry retires: the reasoner
    composes these verbs without asking the practitioner, so a verb quietly
    added while being class C is an autonomy escape. The runtime filter would
    now drop it, but silently — this test is what makes it loud, before merge."""
    import chief_action_reasoner as car

    not_in_chief = sorted(set(car._REMAP_DESCRIPTIONS) - set(cos.ACTION_HANDLERS))
    assert not not_in_chief, (
        f"_REMAP_DESCRIPTIONS references verb(s) Chief does not have: {not_in_chief}")

    offenders = {}
    for verb in sorted(car._REMAP_DESCRIPTIONS):
        rev = reg.reversibility(verb)
        if rev != "A" or reg.is_bulk(verb):
            offenders[verb] = ("bulk" if reg.is_bulk(verb) else rev
                               or ("unclassified" if verb in reg.UNCLASSIFIED
                                   else "missing from registry"))
    assert not offenders, (
        f"_REMAP_DESCRIPTIONS must contain only non-bulk class-A verbs — the "
        f"reasoner composes them without asking. Offenders: {offenders}")


def test_safe_remap_actions_is_derived_not_hand_held():
    """The allowlist the reasoner actually uses is the filtered view, and with
    the source list currently clean the two agree exactly. If they ever differ,
    the filter dropped something — which is the filter working, and the test
    above will name it."""
    import chief_action_reasoner as car

    assert set(car.SAFE_REMAP_ACTIONS) <= set(car._REMAP_DESCRIPTIONS), (
        "the derived allowlist must never exceed its source")
    for verb in car.SAFE_REMAP_ACTIONS:
        assert reg.reversibility(verb) == "A" and not reg.is_bulk(verb), (
            f"{verb}: reached the live allowlist without being non-bulk class A")


def test_a_non_class_a_verb_cannot_reach_the_allowlist(monkeypatch):
    """The filter, exercised rather than assumed. Smuggle a class-C verb into
    the source dict and rebuild: it must not come out the other side."""
    import chief_action_reasoner as car

    poisoned = dict(car._REMAP_DESCRIPTIONS)
    poisoned["send_sms"] = "smuggled — sends a text, class C"
    poisoned["bulk_approve"] = "smuggled — bulk send"
    monkeypatch.setattr(car, "_REMAP_DESCRIPTIONS", poisoned)

    rebuilt = car._safe_remap_actions()
    assert "send_sms" not in rebuilt, "a class-C verb reached the allowlist"
    assert "bulk_approve" not in rebuilt, "a bulk verb reached the allowlist"
    assert set(rebuilt) == set(car.SAFE_REMAP_ACTIONS), (
        "filtering should have removed exactly the smuggled verbs")


# ── coverage reporting (informational, never fails on progress) ──────

def test_coverage_is_self_consistent():
    cov = reg.coverage()
    assert cov["total"] == cov["classified"] + cov["unclassified"]
    assert cov["total"] == len(cos.ACTION_HANDLERS), (
        f"coverage total {cov['total']} != {len(cos.ACTION_HANDLERS)} handlers")
    assert cov["classified"] == cov["read"] + cov["ui"] + cov["A"] + cov["B"] + cov["C"]
