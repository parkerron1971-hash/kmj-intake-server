"""Closing the Embrace the Shift tables
(supabase/APPLY-2026-11-19-close-ets-policies.sql).

Read from production's catalog 2026-11-19: the ten ets_* tables have RLS on,
but every one carries an allow-all, a read-everything or a
"signed in is enough" policy, and `anon` holds SELECT/INSERT/UPDATE/DELETE on
all ten. The anon key ships in the public site's bundle, so anyone holding it
read, changed and deleted every inquiry, registration, engagement, email,
agent note, signature and session row, and so could any signed-in login.

Pins, as text (the behaviour itself is __tests__/ets_close_policies_db.mjs,
on a real Postgres):
  * the 25 policies production showed are dropped by their exact names, and
    nothing else is dropped but this file's own policies, each just before it
    is made (so it is safe to run twice); ets_public_read_events stays
  * what it adds: the owner through is_platform_owner() on all ten, TO
    authenticated; the public's reads and inserts TO anon, authenticated;
    never a literal true or a bare "signed in"; no policy loop
  * the confirmation function: SECURITY DEFINER, search_path pinned, SQL,
    stable, never a pattern match, a bounded reference, only the page's
    fields; callable by anon and authenticated only
  * the count triggers run as their owner; the views run as the caller
  * anon: nothing on the five staff tables, SELECT only on events, tiers and
    files, INSERT only on inquiries and registrations
  * one transaction, a lock timeout, a refusal on a database it was not
    written for, the schema reload, the checks before and after, a rollback
    that says it reopens the hole, the ledger row and the database check in CI

Names here are made up."""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = pathlib.Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

APPLY = ROOT / "supabase" / "APPLY-2026-11-19-close-ets-policies.sql"
ROLLBACK = ROOT / "supabase" / "ROLLBACK-2026-11-19-close-ets-policies.sql"

TABLES = ["ets_events", "ets_event_tiers", "ets_event_files", "ets_registrations", "ets_inquiries",
          "ets_engagements", "ets_emails", "ets_agent_log", "ets_signatures", "ets_sessions_log"]
STAFF = ["ets_engagements", "ets_emails", "ets_agent_log", "ets_signatures", "ets_sessions_log"]
PUBLIC_READS = ["ets_events", "ets_event_tiers", "ets_event_files"]
PUBLIC_INSERTS = ["ets_inquiries", "ets_registrations"]

# What pg_policies showed on production on 2026-11-19: (table, policy, command, USING / WITH CHECK as the
# rollback recreates it). All permissive, all TO public.
OPEN = "using (true) with check (true)"
SIGNED_IN = "using (auth.uid() is not null)"
PRODUCTION = [
    ("ets_events", "Allow all for anon", "all", OPEN),
    ("ets_events", "ets_auth_events", "all", SIGNED_IN),
    ("ets_event_tiers", "Allow all for anon", "all", OPEN),
    ("ets_event_tiers", "ets_auth_tiers", "all", SIGNED_IN),
    ("ets_event_tiers", "ets_public_read_tiers", "select", "using (is_visible = true)"),
    ("ets_event_files", "Allow all for anon", "all", OPEN),
    ("ets_event_files", "ets_auth_files", "all", SIGNED_IN),
    ("ets_event_files", "ets_public_read_files", "select", "using (true)"),
    ("ets_registrations", "Allow all for anon", "all", OPEN),
    ("ets_registrations", "ets_auth_registrations", "all", SIGNED_IN),
    ("ets_registrations", "ets_public_insert_registration", "insert", "with check (true)"),
    ("ets_registrations", "ets_public_read_own_registration", "select", "using (true)"),
    ("ets_inquiries", "ets_auth_inquiries", "all", SIGNED_IN),
    ("ets_inquiries", "ets_public_insert", "insert", "with check (true)"),
    ("ets_inquiries", "ets_public_read", "select", "using (true)"),
] + [
    row for t, x in [("ets_engagements", "engagements"), ("ets_emails", "emails"), ("ets_agent_log", "agent_log"),
                     ("ets_signatures", "signatures"), ("ets_sessions_log", "sessions")]
    for row in ((t, f"ets_auth_{x}", "all", SIGNED_IN), (t, f"ets_read_{x}", "select", "using (true)"))
]
KEPT = ("ets_events", "ets_public_read_events")

# What the file makes: (table, policy, command, roles).
ADDED = [(t, "ets_owner_all", "all", "authenticated") for t in TABLES] + [
    ("ets_event_tiers", "ets_public_read_live_tiers", "select", "anon, authenticated"),
    ("ets_event_files", "ets_public_read_live_files", "select", "anon, authenticated"),
    ("ets_inquiries", "ets_public_send_inquiry", "insert", "anon, authenticated"),
    ("ets_registrations", "ets_public_register", "insert", "anon, authenticated"),
]

# What the confirmation page shows, and so all the function may answer.
PAGE_KEYS = {"id", "first_name", "last_name", "email", "status", "amount_paid", "ets_events", "ets_event_tiers",
             "title", "event_date", "start_time", "end_time", "venue_name", "address", "city", "state", "format",
             "virtual_link", "confirmation_message", "timezone", "cover_image", "ets_event_files",
             "file_url", "is_cover", "name", "price"}
NEVER = {"phone", "organization", "notes", "stripe_session_id", "stripe_payment_intent", "checked_in",
         "checked_in_at", "created_at"}


def _code(path: pathlib.Path) -> str:
    """The SQL without its comments, lower case, one space between words."""
    text = path.read_text(encoding="utf-8")
    lines = [ln.split("--", 1)[0] for ln in text.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip().lower()


def _name(n: str) -> str:
    return f'"{n.lower()}"' if " " in n else n.lower()


def _policies(code: str):
    """(name, table, command, roles or '', body) for each CREATE POLICY."""
    out = []
    for m in re.finditer(r'create policy ("[^"]+"|\w+) on public\.(\w+) for (\w+) (.*?);(?= drop| create| alter| revoke| grant| do | commit|$)', code):
        name, table, cmd, rest = m.groups()
        roles = ""
        to = re.match(r"to ([\w, ]+?) (using|with check) (.*)$", rest)
        if to:
            roles, body = to.group(1), f"{to.group(2)} {to.group(3)}"
        else:
            body = rest
        out.append((name, table, cmd, roles, body))
    return out


def _function_body(code: str) -> str:
    start = code.index("create or replace function public.ets_registration_confirmation(p_ref text)")
    return code[start:code.index("$$;", start)]


# ─── The migration ────────────────────────────────────────────────────

def test_the_twenty_five_are_the_ones_production_showed():
    assert len(PRODUCTION) == 25 and len({(t, n) for t, n, _, _ in PRODUCTION}) == 25
    assert {t for t, _, _, _ in PRODUCTION} == set(TABLES)
    assert KEPT not in {(t, n) for t, n, _, _ in PRODUCTION}


def test_every_policy_production_showed_is_dropped_by_name_and_nothing_else_is():
    code = _code(APPLY)
    drops = re.findall(r'drop policy if exists ("[^"]+"|\w+) on public\.(\w+);', code)
    assert len(re.findall(r"\bdrop\b", code)) == len(drops), "every drop is a DROP POLICY IF EXISTS"
    dropped = {(t, n) for n, t in drops}
    want = {(t, _name(n)) for t, n, _, _ in PRODUCTION}
    own = {(t, n) for t, n, _, _ in ADDED}
    assert want <= dropped, sorted(want - dropped)
    assert dropped - want == own, sorted(dropped - want - own)
    for t, n, _, _ in PRODUCTION:
        assert code.count(f"drop policy if exists {_name(n)} on public.{t};") == 1, (t, n)
    assert "ets_public_read_events" not in code, "the events read stays as it is"


def test_what_it_adds_is_the_owner_and_the_public_and_never_an_open_door():
    code = _code(APPLY)
    assert "(true)" not in code and "using true" not in code and "check true" not in code
    assert "auth.uid() is not null" not in code
    made = _policies(code)
    assert len(made) == len(re.findall(r"create policy", code)) == len(ADDED)
    assert {(t, n, c, r) for n, t, c, r, _ in made} == set(ADDED)
    for name, table, cmd, roles, body in made:
        # Created right after its own drop, so a second run is the same.
        assert f"drop policy if exists {name} on public.{table}; create policy {name} on public.{table}" in code
        if name == "ets_owner_all":
            assert body == "using (public.is_platform_owner()) with check (public.is_platform_owner())", table
        else:
            assert "is_platform_owner" not in body, (table, name)   # anon may not call it
            assert ("using" if cmd == "select" else "with check") == body.split(" (")[0], (table, name)


def test_no_policy_can_loop():
    """docs/RLS_MODEL.md, the 42P17 rule: a policy that reads a table whose
    policy reads it back recurses. The graph of which table's policies read
    which other table (the kept events read reads none) has no cycle."""
    reads: dict = {t: set() for t in TABLES}
    for _, table, _, _, body in _policies(_code(APPLY)):
        reads[table] |= set(re.findall(r"(?:from|join) public\.(\w+)", body))
    assert reads["ets_events"] == set()
    assert reads["ets_event_tiers"] == {"ets_events"} and reads["ets_event_files"] == {"ets_events"}
    assert reads["ets_registrations"] == {"ets_events", "ets_event_tiers"}
    assert all(not reads[t] for t in STAFF + ["ets_inquiries"])

    def loops(t, seen=()):
        return t in seen or any(loops(r, seen + (t,)) for r in reads.get(t, ()))
    assert not any(loops(t) for t in TABLES)


def test_the_registration_rule_names_every_column_with_its_table():
    """Inside the subquery an unqualified event_id or status would be the
    tier's or the event's, and the rule would check the wrong row."""
    body = next(b for n, *_, b in _policies(_code(APPLY)) if n == "ets_public_register")
    for col in ("event_id", "tier_id", "status", "amount_paid", "checked_in", "checked_in_at", "stripe_session_id",
                "stripe_payment_intent", "notes"):
        for m in re.finditer(rf"(?<![\w.]){col}\b", body):
            raise AssertionError(f"unqualified {col} at …{body[max(0, m.start() - 30):m.end() + 10]}…")
    for need in ("e.status = 'published'", "t.is_visible is true", "ets_registrations.status = 'pending'",
                 "ets_registrations.status = 'confirmed' and (t.is_free is true or t.price = 0)",
                 "coalesce(ets_registrations.amount_paid, 0) = 0", "ets_registrations.amount_paid = t.price",
                 "ets_registrations.checked_in is not true", "ets_registrations.checked_in_at is null",
                 "ets_registrations.stripe_session_id is null", "ets_registrations.stripe_payment_intent is null",
                 "ets_registrations.notes is null"):
        assert need in body, need
    inquiry = next(b for n, *_, b in _policies(_code(APPLY)) if n == "ets_public_send_inquiry")
    for need in ("ets_inquiries.processed is not true", "ets_inquiries.processed_at is null",
                 "ets_inquiries.agent_notes is null", "ets_inquiries.lead_score::text = 'warm'",
                 "ets_inquiries.converted_to_engagement is not true"):
        assert need in inquiry, need


def test_the_confirmation_function_answers_one_registration_and_only_the_pages_fields():
    code = _code(APPLY)
    body = _function_body(code)
    assert body.startswith("create or replace function public.ets_registration_confirmation(p_ref text) returns jsonb "
                           "language sql stable security definer set search_path = public as $$")
    for pattern in (" like ", " ilike ", "similar to", "~~", "~*", "position(", "strpos(", "starts_with"):
        assert pattern not in body, pattern
    assert "p_ref is not null and char_length(p_ref) between 1 and 200" in body
    # By id only through the uuid's own text, cast only when it is one; by session only when exactly one has it.
    assert ("r.id = case when p_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
            "then p_ref::uuid end") in body
    assert "where r.stripe_session_id = p_ref having count(*) = 1" in body
    keys = set(re.findall(r"'([a-z_]+)',", body))
    assert keys == PAGE_KEYS, (sorted(keys - PAGE_KEYS), sorted(PAGE_KEYS - keys))
    answered = set(re.findall(r"\breg\.(\w+)", body))
    assert answered and not (answered & NEVER), "never answers a field the page does not show"
    assert "'virtual_link', case when reg.status = 'confirmed' then e.virtual_link end" in body
    assert ("revoke all on function public.ets_registration_confirmation(text) from public; "
            "grant execute on function public.ets_registration_confirmation(text) to anon, authenticated;") in code


def test_the_count_triggers_run_as_their_owner_and_the_views_as_the_caller():
    code = _code(APPLY)
    for fn in ("ets_update_registration_count", "ets_update_tier_sold_count"):
        assert f"alter function public.{fn}() security definer set search_path = public;" in code
    assert "create trigger" not in code and "create or replace function public.ets_update" not in code
    assert "execute format('alter view %s set (security_invoker = true)', v.rel);" in code
    assert "execute format('revoke all on %s from anon', v.rel);" in code
    assert "drop view" not in code


def test_anon_keeps_only_the_sites_reads_and_inserts():
    code = _code(APPLY)
    revoked = set()
    for group in re.findall(r"revoke all on ((?:public\.\w+(?:, )?)+) from anon;", code):
        revoked |= set(re.findall(r"public\.(\w+)", group))
    assert revoked == set(TABLES)
    grants = re.findall(r"grant (\w+) on ((?:public\.\w+(?:, )?)+) to (\w+);", code)
    assert [(p, sorted(re.findall(r"public\.(\w+)", ts)), who) for p, ts, who in grants] == [
        ("select", sorted(PUBLIC_READS), "anon"), ("insert", sorted(PUBLIC_INSERTS), "anon")]
    assert " to public" not in code
    # authenticated keeps its grants; only a materialized view (rows held) is taken from it.
    assert code.count("from authenticated") == 1
    assert "execute format('revoke all on %s from authenticated', v.rel);" in code


def test_one_transaction_that_refuses_a_database_it_was_not_written_for():
    text = APPLY.read_text(encoding="utf-8")
    code = _code(APPLY)
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.startswith("begin; set local lock_timeout = '5s'; do $$")
    assert code.endswith("commit; notify pgrst, 'reload schema';")
    guard = code[code.index("do $$"):code.index("$$;") + 3]
    assert code.index("$$;") < code.index("drop policy"), "the check runs before anything changes"
    for column in ("processed", "converted_to_engagement", "processed_at", "agent_notes", "lead_score", "checked_in",
                   "checked_in_at", "stripe_session_id", "stripe_payment_intent", "notes"):
        assert f"'{column}'" in guard, column
    assert "'ets_reg_count_trigger'" in guard and "'ets_tier_sold_trigger'" in guard
    assert "to_regprocedure('public.is_platform_owner()') is null" in guard
    assert guard.count("raise exception") == 2
    for word in ("create table", "alter table", "drop table", "truncate", "delete from", "update ", "insert into",
                 "create trigger", "drop function"):
        assert word not in code, word
    assert "-- Check before applying (read-only):" in text and "-- Check after (read-only):" in text
    assert "DEPLOY THE SITE FIRST" in text and "ROLLBACK-2026-11-19-close-ets-policies.sql" in text
    assert "close-public-reads" in text and "ets-realtime-signed-in" in text


def test_no_allow_all_policy_in_it():
    from test_close_allow_all_policies import _allow_all_in
    assert _allow_all_in(APPLY) == []
    assert len(_allow_all_in(ROLLBACK)) == 14, "the rollback really does recreate the open ones"


def test_the_rollback_recreates_each_dropped_policy_and_says_it_reopens_the_hole():
    text = ROLLBACK.read_text(encoding="utf-8")
    code = _code(ROLLBACK)
    assert "THIS REOPENS THE HOLE" in text.splitlines()[2]
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.startswith("begin; set local lock_timeout = '5s';")
    assert code.endswith("commit; notify pgrst, 'reload schema';")
    for t, n, cmd, body in PRODUCTION:
        made = re.search(rf"create policy {re.escape(_name(n))} on public\.{t} for (\w+) (.*?);", code)
        assert made, (t, n)
        assert made.groups() == (cmd, body), (t, n, made.groups())     # TO public, as it was
        assert f"drop policy if exists {_name(n)} on public.{t}; create policy {_name(n)} on public.{t}" in code
    for t, n, _, _ in ADDED:
        assert code.count(f"drop policy if exists {n} on public.{t};") == 1, (t, n)
    assert len(re.findall(r"create policy", code)) == 25
    granted = re.findall(r"grant select, insert, update, delete on ((?:public\.\w+(?:, )?)+) to anon;", code)
    assert len(granted) == 1 and set(re.findall(r"public\.(\w+)", granted[0])) == set(TABLES)
    for fn in ("ets_update_registration_count", "ets_update_tier_sold_count"):
        assert f"alter function public.{fn}() security invoker reset search_path;" in code
    assert "alter view %s reset (security_invoker)" in code
    # The function stays: the site's new build reads it.
    assert "drop function" not in code and "-- drop function if exists public.ets_registration_confirmation(text);" in text


def test_the_ledger_has_the_row_and_ci_runs_the_database_check():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(ln for ln in ledger.splitlines() if ln.startswith("| `supabase/APPLY-2026-11-19-close-ets-policies.sql`"))
    assert "| **NOT APPLIED" in row or "| **APPLIED" in row
    assert "DEPLOY THE SITE FIRST" in row and "REOPENS" in row and "ets_close_policies_db.mjs" in row
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("  test-db:"):ci.index("\n  test:\n")]
    assert "node __tests__/ets_close_policies_db.mjs" in job
    assert (HERE / "ets_close_policies_db.mjs").exists()
