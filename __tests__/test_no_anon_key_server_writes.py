"""Server code does not WRITE to Postgres with the anon key.

docs/RLS_MODEL.md Rule 1: the backend accesses the database with
SUPABASE_SERVICE_ROLE_KEY. The anon key is public — it ships in the
frontend bundle — and "any server path using the anon key on a
tenant-scoped table breaks the moment its permissive policy is removed.
This is exactly what bit us."

It bit us a second time, more quietly. `kmj_intake_automation` wrote
every lead into public.leads with the anon key, and that single call site
is why the table could not have RLS switched on at all: enabling it
would have killed the insert, because anon would no longer satisfy any
policy. So the anon-key write did not merely violate the rule — it was
the reason the rule could not be enforced on that table. The table sat
readable by anyone holding the public key, carrying named prospects and
internal qualification notes, from launch until 2026-09-01.

A rule that is only in a document gets violated in a file nobody
re-reads. This is the version that fails the build.

WHY A SOURCE SCAN AND NOT A RUNTIME CHECK. The write happened inside a
best-effort try/except that only printed on exception, so a 401 from a
revoked grant looked exactly like success. There is no runtime signal to
assert on. The thing that is checkable is the shape of the code, so that
is what is checked.

WHAT IS DELIBERATELY STILL ALLOWED. Reaching for the anon key is correct
in two places and both are exempted by name below: `ledger_unlock`
re-proves a password against Supabase Auth (an auth call, not a table
write, and it MUST be the anon key — that is the endpoint's contract),
and the composer's post_processor reads with it. The rule is about
WRITES to PostgREST tables, not about the key existing.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Auth calls and reads that legitimately use the public key. Add to this
# only with a reason, and never for something that writes a table.
_EXEMPT = {
    "ledger_unlock.py",            # /auth/v1/token — anon key is the contract
    "agents/composer/post_processor.py",
}

_ANON_NAMES = ("SUPABASE_ANON", "SUPABASE_ANON_KEY")


def _code_only(src: str) -> str:
    """Source with `#` comments removed.

    Necessary, and the first run of this file proved why: the commit that
    fixed the leads writer also explained itself in a comment naming
    SUPABASE_ANON_KEY, and the scan dutifully failed the fix for
    mentioning the thing it had just removed. A guard that cannot tell
    code from prose about code punishes writing the prose, which is the
    opposite of what this repo wants.

    Comment lines are BLANKED, not removed. Dropping them shifts every
    line number below, so the first version of this guard reported
    public_site.py:1138 — a string replace, in a function about HTML —
    for a call that actually lives 14 lines further down. A guard that
    names the wrong line sends the reader somewhere innocent and teaches
    them the guard is noise.
    """
    out = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append("")
            continue
        # Trailing comment, ignoring a `#` inside a quoted string.
        in_s = in_d = False
        cut = None
        for idx, ch in enumerate(line):
            if ch == "'" and not in_d:
                in_s = not in_s
            elif ch == '"' and not in_s:
                in_d = not in_d
            elif ch == "#" and not in_s and not in_d:
                cut = idx
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def _python_files():
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs
                   if d not in {".git", "__pycache__", "node_modules",
                                "__tests__", ".venv", "venv"}]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                yield path, os.path.relpath(path, REPO).replace("\\", "/")


# A mutating HTTP call, and an anon-key reference. Both have to appear in
# the same small window for the pair to mean anything.
_MUTATING = re.compile(r"\.(post|patch|put|delete)\s*\(")
_ENV_ANON = re.compile(r"SUPABASE_ANON(_KEY)?\b")
_WINDOW = 20   # lines above a call — a headers dict sits well inside this

# Helper functions whose NAME suggests the anon key. Whether they actually
# return it is a separate question, and the whole reason _anon_helpers()
# exists — see below.
_HELPER_DEF = re.compile(r"^def (_sb_anon|_supabase_anon)\s*\(", re.M)
_ANY_DEF = re.compile(r"^def ([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.M)


def _anon_helpers(src: str) -> set:
    """Which anon-NAMED helpers in this file genuinely return the anon key.

    THE TRAP THIS ENCODES, which cost a real correction in PR #768: a
    module can define `_sb_anon()` that returns
    SUPABASE_SERVICE_ROLE_KEY. `business_profile_agent` does exactly
    that — the name is a leftover from its migration off the anon key.
    A reviewer grepped for the name, saw the file, and filed a claim that
    the module was unmigrated. It wasn't. The correction is a commit on
    main.

    A guard that keyed on the name alone would repeat that accusation
    every build, forever, about a module that is already correct — and
    the fix would be an exemption entry, which is how a guard rots into
    a list of things it has agreed not to look at.

    So the name is a candidate and the BODY is the evidence. Any mention
    of the service-role key in the helper's body means it is not an anon
    call site: `sms_service` returns service-role with an anon fallback
    (deliberate, so a half-configured env limps visibly rather than
    failing dark), and that is service-role-preferring, not a violation.

    THE SECOND INDIRECTION, and the reason the first version of this
    guard passed while three modules were plainly writing with the anon
    key. Nobody puts `_sb_anon()` next to their `.post()`. They write
    `_sb_headers()` once at the top of the file and call it four hundred
    lines later, so a window around the call site sees a helper name and
    nothing incriminating. The chain has to be followed:

        _sb_anon()  ->  _sb_headers()  ->  client.post(headers=...)

    So this returns BOTH kinds of name: helpers that yield the key, and
    the header builders that embed one.
    """
    anon = set()
    lines = src.splitlines()

    def _body_of(match_start):
        start = src[:match_start].count("\n")
        body = []
        for line in lines[start + 1:start + 30]:
            if line and not line[0].isspace() and not line.startswith(")"):
                break
            body.append(line)
        return "\n".join(body)

    for m in _HELPER_DEF.finditer(src):
        body_text = _body_of(m.start())
        if "SUPABASE_SERVICE_ROLE_KEY" in body_text:
            continue          # service-role, whatever it is called
        if _ENV_ANON.search(body_text):
            anon.add(m.group(1))

    # Header builders that embed one of those (or the env var directly).
    for m in _ANY_DEF.finditer(src):
        name = m.group(1)
        if name in anon:
            continue
        body_text = _body_of(m.start())
        if "apikey" not in body_text:
            continue
        if "SUPABASE_SERVICE_ROLE_KEY" in body_text:
            continue
        if _ENV_ANON.search(body_text) or any(
                re.search(rf"\b{re.escape(h)}\s*\(", body_text) for h in anon):
            anon.add(name)
    return anon


def test_no_anon_key_at_a_rest_write_call_site():
    """No mutating /rest/v1 call is made with the anon key in its headers.

    Scoped to the CALL SITE, not the file, and that distinction is the
    whole test — a guard with false positives gets muted by exemptions
    until it guards nothing, so it has to be right about what it accuses.

    CORRECTION, 2026-09-01. An earlier version of this docstring called
    marketing_pages and practitioner_profile_agent false positives whose
    "anon reference and POST are hundreds of lines apart." That was
    wrong, and wrong in the direction that matters: BOTH were real.
    marketing_pages builds its anon key twelve lines above a POST to
    marketing_leads — the table lead_admin reads — and
    practitioner_profile_agent reaches its POST through _sb_headers().
    The dismissal came from a narrow grep that happened to show neither.

    So the guard was right twice and its author talked it out of both.
    That is the actual failure mode of a check like this: not that it
    cries wolf, but that a plausible story about why a hit is spurious
    is always available and costs nothing to believe. A hit gets
    dismissed only by reading the call site.
    """
    offenders = []
    for path, rel in _python_files():
        if rel in _EXEMPT:
            continue
        try:
            raw = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        code = _code_only(raw)
        # An anon reference in THIS file: the env var directly, or a
        # locally-defined helper whose body proves it returns the anon key.
        helpers = _anon_helpers(code)
        pattern = "|".join([r"SUPABASE_ANON(_KEY)?\b"]
                           + [rf"{re.escape(h)}\s*\(" for h in helpers])
        anon_ref = re.compile(pattern)

        lines = code.splitlines()
        for n, line in enumerate(lines):
            if not _MUTATING.search(line):
                continue
            # SYMMETRIC. A multi-line call puts its headers= argument
            # BELOW the .post( line:
            #     r = await client.post(f"{_sb_url()}/rest/v1{path}",
            #                           headers=_sb_headers(), ...)
            # A backwards-only window read three real violations as clean
            # — foundation_agent's two writes and one of
            # practitioner_profile_agent's — for no reason but line order.
            window = "\n".join(lines[max(0, n - _WINDOW):n + _WINDOW])
            if "/rest/v1" in window and anon_ref.search(window):
                offenders.append(f"{rel}:{n + 1}")
    assert not offenders, (
        "mutating /rest/v1 call sites carrying the anon key — use "
        f"SUPABASE_SERVICE_ROLE_KEY (RLS_MODEL.md Rule 1): {offenders}")


def test_the_helper_resolver_reads_bodies_not_names():
    """Pin the #768 trap directly, so nobody 'simplifies' the resolver
    back into a name match.

    business_profile_agent._sb_anon returns SUPABASE_SERVICE_ROLE_KEY.
    sms_service._sb_anon prefers service-role with an anon fallback.
    Neither is an anon call site; both are named as if they were.
    """
    def helpers_of(rel):
        src = _code_only(open(os.path.join(REPO, rel),
                              encoding="utf-8", errors="ignore").read())
        return _anon_helpers(src)

    assert "_sb_anon" not in helpers_of("business_profile_agent.py"), \
        "business_profile_agent._sb_anon returns the SERVICE ROLE key (#768)"
    assert "_sb_anon" not in helpers_of("sms_service.py"), \
        "sms_service._sb_anon prefers service-role with an anon fallback"
    # And the resolver still SEES a genuine one, or it proves nothing.
    assert "_sb_anon" in helpers_of("agents/director_agent/refine.py")


def test_the_leads_writer_uses_service_role():
    """The specific regression. Pinned by name because this one call site
    is what kept RLS off public.leads."""
    src = _code_only(open(os.path.join(REPO, "kmj_intake_automation.py"),
                          encoding="utf-8", errors="ignore").read())
    i = src.find("/rest/v1/leads")
    assert i > 0, "the leads write moved — re-point this test, don't delete it"
    window = src[max(0, i - 1500):i]
    assert "SUPABASE_SERVICE_ROLE_KEY" in window, \
        "the leads write must use the service-role key"
    assert "SUPABASE_ANON_KEY" not in window, \
        "the leads write is reaching for the anon key again"


def test_migration_locks_both_advisor_tables():
    """The migration is the other half of the fix: the code change stops
    writing with anon, and this switches RLS on. Shipping one without the
    other leaves either a broken insert or an open table."""
    path = os.path.join(REPO, "supabase",
                        "APPLY-2026-09-01-rls-advisor-errors.sql")
    sql = open(path, encoding="utf-8", errors="ignore").read().lower()
    for table in ("public.leads", "public.discovery_submissions"):
        assert f"alter table {table}" in sql and "enable row level security" in sql, table
        assert f"revoke all on {table}" in sql, table


def test_migration_flips_every_definer_view():
    """All eight the linter named, or the finding is only partly closed."""
    path = os.path.join(REPO, "supabase",
                        "APPLY-2026-09-01-rls-advisor-errors.sql")
    sql = open(path, encoding="utf-8", errors="ignore").read().lower()
    for view in ("ets_pending_agent_actions", "ets_event_summary",
                 "v_approval_queue", "v_contact_health", "v_business_stats",
                 "api_usage_summary_30d", "trust_client_balances",
                 "trust_reconciliation_state"):
        assert f"alter view public.{view}" in sql, view
    assert sql.count("security_invoker = true") >= 8
