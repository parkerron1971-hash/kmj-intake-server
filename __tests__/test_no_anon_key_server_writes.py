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
_ANON_REF = re.compile(r"SUPABASE_ANON(_KEY)?\b|_supabase_anon\s*\(|anon_key\b")
_WINDOW = 20   # lines above a call — a headers dict sits well inside this


def test_no_anon_key_at_a_rest_write_call_site():
    """No mutating /rest/v1 call is made with the anon key in its headers.

    Scoped to the CALL SITE, not the file, and that distinction is the
    whole test. The first cut asked "does this file mention the anon key
    AND contain a mutating call AND mention /rest/v1" — which flagged
    marketing_pages and practitioner_profile_agent, two modules whose
    anon reference and whose POST are hundreds of lines and several
    unrelated services apart. A guard with false positives gets muted by
    exemptions until it guards nothing, so it has to be right about what
    it accuses.

    It kept one accusation when narrowed, and that one was true:
    public_site._sb_post wrote /events and /sessions with the anon key in
    both headers.
    """
    offenders = []
    for path, rel in _python_files():
        if rel in _EXEMPT:
            continue
        try:
            raw = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        lines = _code_only(raw).splitlines()
        for n, line in enumerate(lines):
            if not _MUTATING.search(line):
                continue
            window = "\n".join(lines[max(0, n - _WINDOW):n + 1])
            if "/rest/v1" in window and _ANON_REF.search(window):
                offenders.append(f"{rel}:{n + 1}")
    assert not offenders, (
        "mutating /rest/v1 call sites carrying the anon key — use "
        f"SUPABASE_SERVICE_ROLE_KEY (RLS_MODEL.md Rule 1): {offenders}")


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
