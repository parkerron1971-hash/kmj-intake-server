"""Closing the allow-all policies on twenty tenant tables
(supabase/APPLY-2026-11-18-close-allow-all-policies.sql).

Found 2026-11-18 reading pg_policies on production: each of these tables has
RLS on, a PERMISSIVE `USING (true)` policy TO public, and table privileges
for `anon`. The public anon key ships in the app bundle, so anyone holding
it read, changed and deleted every business's rows through PostgREST.

Pins:
  * the migration drops every one of the 26 allow-all policies production
    showed, by its exact name, and drops nothing else but the nine scoped
    policies it then creates (so it is safe to run twice)
  * what it adds goes through the SECURITY DEFINER helpers, TO authenticated,
    and is never an allow-all or an inline cross-table check
  * anon is revoked on the sixteen tables no browser reads, and not on the
    four the app reads signed in
  * one transaction, a lock timeout, the schema reload after the commit, the
    checks before and after, and a rollback that says it reopens the hole
  * the server paths that leaned on an allow-all policy now act as the
    server: a public site's products, Chief's learned patterns, the owner's
    practitioner profile
  * from here on, no new migration creates an allow-all policy without a
    written reason

Names here are made up."""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = pathlib.Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

APPLY = ROOT / "supabase" / "APPLY-2026-11-18-close-allow-all-policies.sql"
ROLLBACK = ROOT / "supabase" / "ROLLBACK-2026-11-18-close-allow-all-policies.sql"

# What pg_policies showed on production on 2026-11-18: (table, policy).
ALLOW_ALL = [
    ("business_expenses", "business_expenses_all"),
    ("chief_patterns", "patterns_all"),
    ("connector_action_log", "cal_all"),
    ("connectors", "connectors_all"),
    ("foundation_documents", "foundation_documents_all"),
    ("foundation_progress", "foundation_progress_all"),
    ("growth_milestones", "growth_ms_all"),
    ("growth_objectives", "growth_obj_all"),
    ("marketing_leads", "marketing_leads_all"),
    ("module_specs", "specs_all"),
    ("practitioner_profiles", "practitioner_profiles_all"),
    ("products", "products_all"),
    ("site_chat_history", "Allow all deletes on site_chat_history"),
    ("site_chat_history", "Allow all inserts on site_chat_history"),
    ("site_chat_history", "Allow all reads on site_chat_history"),
    ("site_chat_history", "Allow all updates on site_chat_history"),
    ("site_content_overrides", "Allow all deletes on site_content_overrides"),
    ("site_content_overrides", "Allow all inserts on site_content_overrides"),
    ("site_content_overrides", "Allow all reads on site_content_overrides"),
    ("site_content_overrides", "Allow all updates on site_content_overrides"),
    ("sms_bindings", "sms_bindings_all"),
    ("sms_keywords", "sms_keywords_all"),
    ("sms_opt_outs", "sms_opt_outs_all"),
    ("tasks", "tasks_all"),
    ("workflow_definitions", "wf_def_all"),
    ("workflow_runs", "wf_run_all"),
]
TABLES = sorted({t for t, _ in ALLOW_ALL})

# What the migration adds: (table, policy, command, helper).
ADDED = [
    ("growth_milestones", "business_owner_access", "all", "is_business_owner"),
    ("growth_objectives", "business_owner_access", "all", "is_business_owner"),
    ("module_specs", "business_owner_access", "all", "is_business_owner"),
    ("site_chat_history", "business_owner_access", "all", "is_business_owner"),
    ("connectors", "business_owner_read", "select", "is_business_owner"),
    ("sms_keywords", "business_owner_read", "select", "is_business_owner"),
    ("sms_opt_outs", "business_owner_read", "select", "is_business_owner"),
    ("sms_bindings", "business_owner_read", "select", "is_business_owner"),
    ("sms_bindings", "tenant_member_read", "select", "is_business_member"),
]
# The app reads these four with a signed-in login, so anon's grants stay and a
# lapsed session reads an empty list from the policies, not a permission error.
BROWSER_READS = {"tasks", "products", "business_expenses", "sms_bindings"}


def _code(path: pathlib.Path) -> str:
    """The SQL without its comments, lower case, one space between words."""
    text = path.read_text(encoding="utf-8")
    lines = [ln.split("--", 1)[0] for ln in text.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip().lower()


def _name(n: str) -> str:
    return f'"{n.lower()}"' if " " in n else n.lower()


# ─── The migration ────────────────────────────────────────────────────

def test_twenty_tables_and_twenty_six_policies_are_the_ones_production_showed():
    assert len(TABLES) == 20 and len(ALLOW_ALL) == 26 and len(set(ALLOW_ALL)) == 26


def test_every_allow_all_policy_is_dropped_by_name_and_nothing_else_is():
    code = _code(APPLY)
    drops = re.findall(r'drop policy if exists ("[^"]+"|\w+) on public\.(\w+);', code)
    assert len(re.findall(r"\bdrop\b", code)) == len(drops), "every drop is a DROP POLICY IF EXISTS"
    dropped = {(t, n) for n, t in drops}
    want = {(t, _name(n)) for t, n in ALLOW_ALL}
    own = {(t, n) for t, n, _, _ in ADDED}
    assert want <= dropped, sorted(want - dropped)
    assert dropped - want == own, sorted(dropped - want - own)
    for t, n in ALLOW_ALL:
        assert code.count(f"drop policy if exists {_name(n)} on public.{t};") == 1, (t, n)


def test_what_it_adds_goes_through_the_helpers_and_is_never_an_allow_all():
    code = _code(APPLY)
    assert "(true)" not in code and "using true" not in code and "check true" not in code
    made = re.findall(r"create policy (\w+) on public\.(\w+) for (\w+) to authenticated (.*?);", code)
    assert len(made) == len(re.findall(r"create policy", code)) == len(ADDED)
    got = set()
    for name, table, cmd, body in made:
        helper = re.search(r"using \(public\.(is_business_owner|is_business_member)\(business_id\)\)", body)
        assert helper, (table, name, body)
        if cmd == "all":
            assert f"with check (public.{helper.group(1)}(business_id))" in body, (table, name)
        else:
            assert cmd == "select" and "with check" not in body, (table, name)
        # Rule 2 (the 42P17 outage): no inline cross-table check.
        assert "select" not in body.replace("for select", "") and "exists" not in body, (table, name)
        # Created right after its own drop, so a second run is the same.
        assert f"drop policy if exists {name} on public.{table}; create policy {name} on public.{table}" in code
        got.add((table, name, cmd, helper.group(1)))
    assert got == set(ADDED)
    # No office login gets a write it did not have: the one seat policy added is a read.
    assert [a for a in ADDED if a[3] == "is_business_member"] == [
        ("sms_bindings", "tenant_member_read", "select", "is_business_member")]


def test_anon_is_revoked_on_the_sixteen_no_browser_reads_and_kept_on_the_four_it_does():
    code = _code(APPLY)
    revoked = set(re.findall(r"revoke all on public\.(\w+) from anon;", code))
    assert len(re.findall(r"\brevoke\b", code)) == len(revoked) == 16
    assert revoked == set(TABLES) - BROWSER_READS
    assert "grant " not in code


def test_one_transaction_with_a_lock_timeout_the_reload_after_and_both_checks():
    text = APPLY.read_text(encoding="utf-8")
    code = _code(APPLY)
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.startswith("begin; set local lock_timeout = '5s';")
    assert code.endswith("commit; notify pgrst, 'reload schema';")
    for word in ("create table", "alter table", "drop table", "truncate", "delete from", "update ", "insert into",
                 "security definer", "create function", "create or replace"):
        assert word not in code, word
    assert "-- Check before applying" in text and "-- Check after:" in text
    assert "DEPLOY THE SERVER FIRST" in text and "ROLLBACK-2026-11-18-close-allow-all-policies.sql" in text
    for t in TABLES:
        assert text.count(f"'{t}'") >= 2, t      # named in the check before and the check after


def test_the_rollback_recreates_each_dropped_policy_and_says_it_reopens_the_hole():
    text = ROLLBACK.read_text(encoding="utf-8")
    code = _code(ROLLBACK)
    assert "THIS REOPENS THE HOLE" in text.splitlines()[2]
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    for t, n in ALLOW_ALL:
        made = re.search(rf"create policy {re.escape(_name(n))} on public\.{t} for (\w+) (.*?);", code)
        assert made, (t, n)
        cmd, body = made.groups()
        assert " to " not in f" {body} ", (t, n)             # TO public, as it was
        if " " not in n:
            assert cmd == "all" and body == "using (true) with check (true)", (t, n)
        else:
            word = n.split()[2]
            assert (cmd, body) == {"deletes": ("delete", "using (true)"), "inserts": ("insert", "with check (true)"),
                                   "reads": ("select", "using (true)"),
                                   "updates": ("update", "using (true)")}[word], (t, n)
        assert code.count(f"drop policy if exists {_name(n)} on public.{t};") == 1
    granted = set(re.findall(r"grant select, insert, update, delete on public\.(\w+) to anon;", code))
    assert granted == set(TABLES) - BROWSER_READS
    # The scoped policies stay unless someone uncomments the last block.
    assert "business_owner_access" not in code and "business_owner_read" not in code


def test_the_ledger_has_the_row_and_the_older_files_say_not_to_run_them_again():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(ln for ln in ledger.splitlines() if "APPLY-2026-11-18-close-allow-all-policies.sql`" in ln
               and ln.startswith("| `supabase/APPLY-2026-11-18-close-allow-all-policies.sql`"))
    assert "| **NOT APPLIED" in row or "| **APPLIED" in row
    assert "DEPLOY THE SERVER FIRST" in row and "REOPENS" in row
    for old in ("sms-routing-migration.sql", "module-specs-migration.sql"):
        head = (ROOT / "supabase" / old).read_text(encoding="utf-8")[:400]
        assert "DO NOT RE-RUN THIS FILE" in head and "close-allow-all-policies" in head, old


# ─── No new allow-all policy without a written reason ─────────────────

# (file name, policy name): why a literal-true policy is right there.
ALLOW_ALL_WITH_A_REASON: dict = {}
SINCE = "2026-11-18"
_TRUE_POLICY = re.compile(
    r"create policy\s+(\"[^\"]+\"|\w+)\s+on\s+[\w.\"]+(?:(?!;).)*?"
    r"(?:using\s*\(\s*true\s*\)|with check\s*\(\s*true\s*\))", re.I | re.S)


def _dated(path: pathlib.Path) -> str:
    m = re.search(r"(20\d\d)[-_](\d\d)[-_](\d\d)", path.name)
    return "-".join(m.groups()) if m else ""


def _allow_all_in(path: pathlib.Path):
    sql = "\n".join(ln.split("--", 1)[0] for ln in path.read_text(encoding="utf-8", errors="replace").splitlines())
    return [m.group(1).strip('"') for m in _TRUE_POLICY.finditer(sql)]


def test_no_migration_from_today_on_creates_an_allow_all_policy_without_a_reason():
    """Postgres ORs permissive policies together, so one `USING (true)` cancels
    every scoped policy beside it (docs/RLS_MODEL.md, Rule 3). A new one needs
    its file and policy named in ALLOW_ALL_WITH_A_REASON, with why the table
    is public on purpose (a reference table with no business's rows in it)."""
    files = sorted(p for p in list((ROOT / "supabase").glob("APPLY-*.sql")) + list((ROOT / "__migrations__").glob("*.sql"))
                   if _dated(p) >= SINCE)
    assert any(p.name == APPLY.name for p in files)
    bad = [(p.name, n) for p in files for n in _allow_all_in(p) if (p.name, n) not in ALLOW_ALL_WITH_A_REASON]
    assert not bad, f"allow-all policies with no written reason: {bad}"
    for key, why in ALLOW_ALL_WITH_A_REASON.items():
        assert isinstance(why, str) and len(why) > 20, key


def test_the_allow_all_scan_sees_one_when_it_is_there(tmp_path):
    f = tmp_path / "APPLY-2026-12-01-example.sql"
    f.write_text('create policy "open_door" on public.widgets\n  for all using (true) with check (true);\n'
                 "create policy scoped on public.widgets for select using (public.is_business_member(business_id));\n"
                 "-- create policy commented on public.widgets for all using (true);\n", encoding="utf-8")
    assert _allow_all_in(f) == ["open_door"] and _dated(f) == "2026-12-01"
    # The files this migration cleans up after would have been caught.
    assert _allow_all_in(ROOT / "supabase" / "sms-routing-migration.sql") == [
        "sms_keywords_all", "sms_bindings_all", "sms_opt_outs_all"]
    assert _allow_all_in(ROLLBACK), "the rollback really does recreate them"


# ─── The server paths that leaned on an allow-all policy ──────────────

def test_a_public_sites_products_are_read_as_the_server_never_with_the_anon_key():
    src = (ROOT / "public_site.py").read_text(encoding="utf-8")
    anon_reads = re.findall(r"(?<![\w.])_sb\(\s*client,\s*f?[\"']/(\w+)", src)
    assert anon_reads, "the scan still finds the anon helper's calls"
    leaning = sorted(set(anon_reads) & set(TABLES))
    assert leaning == [], f"read with the anon key, which the migration closes: {leaning}"
    served = re.findall(r"_sb_service\(\s*client,\s*f\"/products\?([^\"]*)\"", src)
    assert len(served) >= 6
    for query in served:
        # Bounded to the one business the public slug resolved to, or to ids the page already holds.
        assert query.startswith(("business_id=eq.{biz_id}", "id=eq.{product_id}", "id=in.(")), query


def test_no_server_module_sends_the_anon_key_to_one_of_the_twenty_tables():
    """Every module that still builds anon headers, and the tables it names."""
    anon = re.compile(r"SUPABASE_ANON|sb_headers_anon|sb_as_anon|sb_get_as_anon|sb_patch_as_anon")
    # These build anon headers for something else and reach the twenty tables
    # only through helpers that pick the user's JWT or the service role.
    reviewed = {
        "public_site.py": "anon `_sb` reads business_sites/businesses only; pinned by the test above",
        "chief_of_staff.py": "`_supabase_anon` is unused by `_sb` (sb_as_current_context, service fallback)",
        "brand_engine.py": "`_sb_headers` is retained for old callers; `_sb_get`/`_sb_patch` are context-aware",
        "foundation_agent.py": "`_sb_headers` returns the user's JWT or the service role; `_sb_anon` is unused",
        "sms_service.py": "`_sb_anon` returns the service role key (2026-07-10)",
        "agents/director_agent/refine.py": "`_sb_headers` is unused; writes go through sb_*_current_context",
        "agents/override_system/override_storage.py": "`_sb_headers` is unused; writes go through sb_*_current_context",
        "sb_clients.py": "defines the helpers",
    }
    skip = {"__tests__", "node_modules", ".git", "research", "scripts", "docs", "video_worker", "worklog", "sites"}
    table = re.compile(r"[\"'/](%s)(?:\?|[\"'])" % "|".join(TABLES))
    found = {}
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = pathlib.Path(dirpath) / f
            text = p.read_text(encoding="utf-8", errors="replace")
            if anon.search(text) and table.search(text):
                found[p.relative_to(ROOT).as_posix()] = sorted(set(table.findall(text)))
    assert set(found) <= set(reviewed), f"a module with the anon key now names one of the twenty: {sorted(set(found) - set(reviewed))}"
    for name in ("agents/director_agent/refine.py", "agents/override_system/override_storage.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        assert "_sb_headers(" not in src.split("def _sb_headers", 1)[1].split("\n\n\n", 1)[1], name


def test_chiefs_patterns_are_written_as_the_server_and_pinned_to_the_business(monkeypatch):
    import chief_of_staff as cos
    as_user, as_server, reads = [], [], []

    async def user(client, method, path, body=None):
        as_user.append((method, path))
        return [{"id": "p1", "occurrences": 2, "pattern_value": {"a": 1}}] if "pattern_key=eq.seen" in path else []

    async def server(client, method, path, body=None):
        if method == "GET":
            reads.append(path)
            return [{"id": "p1", "occurrences": 2, "pattern_value": {"a": 1}}] if "pattern_key=eq.seen" in path else []
        as_server.append((method, path, body))
        return [{}]

    monkeypatch.setattr(cos, "_sb", user)
    monkeypatch.setattr(cos, "_sb_service", server)
    asyncio.run(cos._upsert_pattern(None, "biz-1", "habit", "seen", {"b": 2}, increment=True))
    asyncio.run(cos._upsert_pattern(None, "biz-1", "habit", "new", {"c": 3}))
    # The read and the write are both the server's, so they see the same row
    # whoever is signed in; each read is pinned to the chat's business.
    assert as_user == [] and len(reads) == 2 and all("business_id=eq.biz-1" in p for p in reads)
    (m1, p1, b1), (m2, p2, b2) = as_server
    assert (m1, p1) == ("PATCH", "/chief_patterns?id=eq.p1&business_id=eq.biz-1")
    assert b1["pattern_value"] == {"a": 1, "b": 2} and b1["occurrences"] == 3
    assert (m2, p2) == ("POST", "/chief_patterns") and b2["business_id"] == "biz-1" and b2["pattern_key"] == "new"


def test_the_owners_profile_is_read_as_the_server_whoever_is_signed_in(monkeypatch):
    import brand_engine as be
    import sb_clients
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: seen.append(path) or [{"owner_id": "o-1", "timezone": "America/Chicago"}])
    monkeypatch.setattr(sb_clients, "sb_get_current_context",
                        lambda *a, **k: pytest.fail("the owner's profile must not ride the caller's login"))
    token = sb_clients.set_user_jwt("an-office-logins-token")
    try:
        assert be._owner_profile("0a1b2c3d-0000-4000-8000-00000000000a")["timezone"] == "America/Chicago"
    finally:
        sb_clients.reset_user_jwt(token)
    assert seen == ["/practitioner_profiles?owner_id=eq.0a1b2c3d-0000-4000-8000-00000000000a&limit=1"]
    # Anything that is not an id never reaches the path.
    for bad in ("", None, "x&select=*", "a b", "eq.1,or=(owner_id.neq.1)", "o" * 65):
        assert be._owner_profile(bad) is None
    assert len(seen) == 1
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None)
    assert be._owner_profile("o-1") is None
    src = (ROOT / "brand_engine.py").read_text(encoding="utf-8")
    assert '_safe_get_one("practitioner_profiles"' not in src


def test_the_owners_timezone_read_is_the_servers_and_only_that_read(monkeypatch):
    import booking_rehearsal as br
    import chief_availability as ca
    import sb_clients
    seen = []

    async def service(client, method, path, body=None):
        seen.append((method, path))
        return [{"timezone": "America/Chicago"}]

    monkeypatch.setattr(sb_clients, "sb_as_service", service)
    good = "/practitioner_profiles?owner_id=eq.0a1b2c3d-0000-4000-8000-00000000000a&select=timezone&limit=1"
    assert asyncio.run(ca._owner_tz_get(None, "GET", good)) == [{"timezone": "America/Chicago"}]
    assert seen == [("GET", good)]
    for method, path, body in (("PATCH", good, None), ("GET", good, {"timezone": "x"}),
                               ("GET", "/businesses?id=eq.1&select=timezone&limit=1", None),
                               ("GET", "/practitioner_profiles?owner_id=eq.1&select=*&limit=1", None),
                               ("GET", "/practitioner_profiles?select=timezone&limit=1", None)):
        with pytest.raises(ValueError):
            asyncio.run(ca._owner_tz_get(None, method, path, body))
    assert len(seen) == 1
    assert br._owner_tz_get is ca._owner_tz_get
    for mod in (ca, br):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        call = src[src.index("/practitioner_profiles?owner_id=eq.{owner}"):]
        assert "read=_owner_tz_get" in call[:200], mod.__name__
