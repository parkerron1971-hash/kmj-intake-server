"""The server's columns of businesses stay the server's
(supabase/APPLY-2026-11-17-businesses-server-columns.sql).

Production gave the app's login UPDATE on all 30 columns of businesses, and
RLS lets an owner or an office admin update their own row, so a PATCH could
comp a plan, start a trial, point Stripe ids anywhere or (for an admin) take
ownership. The migration grants the app's logins UPDATE on the nine owner
columns only, takes INSERT away, and a trigger refuses the rest if a grant is
ever widened again. The database half runs on a real Postgres in
__tests__/businesses_server_columns_db.mjs; this file pins the lists to each
other and to every writer that runs with a user's login, the SQL's shape, and
the two server writers this PR changed (foundation_agent's badge, the signup
door's birth tier).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import sb_clients  # noqa: E402

ROOT = _here.parent
MIGRATION = ROOT / "supabase" / "APPLY-2026-11-17-businesses-server-columns.sql"

# public.businesses in production, read 2026-11-17 (information_schema).
PRODUCTION_COLUMNS = {
    "attribution", "brand_kit_draft", "brand_kit_draft_at", "brand_kit_history", "cancel_at_period_end",
    "cdi_vocabulary", "comp_tier", "created_at", "current_period_end", "entity_group_id", "id",
    "in_the_clear", "in_the_clear_at", "is_active", "is_sample", "name", "owner_id", "sample_of",
    "settings", "stripe_account_id", "stripe_customer_id", "stripe_subscription_id",
    "subscription_plan", "subscription_status", "tier", "trial_ends_at", "type", "updated_at",
    "use_composer", "voice_profile",
}
# The owner's to change: granted to authenticated.
OWNER_COLUMNS = {"name", "type", "settings", "voice_profile", "cdi_vocabulary",
                 "brand_kit_history", "brand_kit_draft", "brand_kit_draft_at", "updated_at"}
# The server's: refused to the app's logins by the trigger as well as the grants.
SERVER_COLUMNS = {"id", "owner_id", "created_at", "attribution", "comp_tier", "tier",
                  "subscription_status", "subscription_plan", "trial_ends_at", "current_period_end",
                  "cancel_at_period_end", "stripe_customer_id", "stripe_subscription_id",
                  "stripe_account_id", "in_the_clear", "in_the_clear_at", "is_active",
                  "entity_group_id", "use_composer"}
# Not granted either; businesses_guard_sample (2026-11-15) already refuses them.
SAMPLE_COLUMNS = {"is_sample", "sample_of"}
# What the app's logins send to the row (solutionist-studio module-system,
# 2026-11-17): BusinessIdentityEditor (name, type), AboutMeReview and
# VoiceToneEditor (voice_profile), lib/businessSettings (settings, through
# merge_business_settings or its fallback PATCH). It never inserts a business.
APP_COLUMNS = {"name", "type", "voice_profile", "settings"}


def _sql() -> str:
    """The file's statements, comments stripped."""
    return "\n".join(line.split("--", 1)[0] for line in MIGRATION.read_text(encoding="utf-8").splitlines())


def _guard() -> str:
    sql = _sql().lower()
    body = sql[sql.index("create or replace function public.businesses_guard_server_columns("):]
    return body[:body.index("$$;") + 3]


# ─── 1. one classification ───────────────────────────────────────────

def test_every_production_column_is_classified_once():
    assert OWNER_COLUMNS | SERVER_COLUMNS | SAMPLE_COLUMNS == PRODUCTION_COLUMNS
    assert len(OWNER_COLUMNS) + len(SERVER_COLUMNS) + len(SAMPLE_COLUMNS) == len(PRODUCTION_COLUMNS) == 30


def test_the_grant_is_the_owner_columns():
    m = re.search(r"grant update \(([^)]*)\)\s+on public\.businesses to authenticated;", _sql().lower())
    assert m, "the column grant"
    assert {c.strip() for c in m.group(1).split(",")} == OWNER_COLUMNS
    assert "revoke insert, update on public.businesses from anon, authenticated;" in _sql().lower()
    # Nothing else is granted to the app's logins on this table.
    assert len(re.findall(r"\bgrant\b", _sql().lower())) == 1


def test_the_guard_names_every_server_column_and_only_those():
    fn = _guard()
    named = set(re.findall(r"when new\.(\w+)(?:::jsonb)?\s+is distinct from old\.(\w+)(?:::jsonb)?\s+then '(\w+)'", fn))
    assert {a for a, b, c in named} == SERVER_COLUMNS
    assert all(a == b == c for a, b, c in named)


def test_the_app_writes_only_owner_columns():
    assert APP_COLUMNS <= OWNER_COLUMNS


# ─── 2. every writer that runs with a user's login ────────────────────

_WRITERS = {"_sb", "_sb_patch", "be_patch", "_sb_post"}


def _user_login_business_writes():
    """(file, line, top-level keys) for every write to /businesses through a
    helper that forwards the user's login when one is bound: Chief's `_sb`
    inside a chat, brand_engine's `_sb_patch` (and creative_expression's
    be_patch, which is it), foundation_agent's `_sb_patch` unless it says
    as_server=True. keys is None when the body isn't a literal dict."""
    out = []
    for path in list(ROOT.glob("*.py")) + list(ROOT.glob("agents/**/*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "/businesses" not in text or not re.search(r"\b(_sb|_sb_patch|be_patch|_sb_post)\(", text):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name not in _WRITERS:
                continue
            args = list(node.args)
            if args and isinstance(args[0], ast.Name) and args[0].id == "client":
                args = args[1:]
            method = None
            if args and isinstance(args[0], ast.Constant) and args[0].value in ("GET", "PATCH", "POST", "DELETE"):
                method, args = args[0].value, args[1:]
            if not args or (name == "_sb" and method not in ("PATCH", "POST")):
                continue
            p = args[0]
            if isinstance(p, ast.Constant):
                head = p.value
            elif isinstance(p, ast.JoinedStr) and p.values and isinstance(p.values[0], ast.Constant):
                head = p.values[0].value
            elif isinstance(p, ast.Call) and getattr(p.func, "id", None) == "_draft_path":
                head = "/businesses?"          # brand_engine's draft writers
            else:
                head = ""
            if not (isinstance(head, str) and head.startswith("/businesses")):
                continue
            if any(k.arg == "as_server" and isinstance(k.value, ast.Constant) and k.value.value
                   for k in node.keywords):
                continue
            body = args[1] if len(args) > 1 else None
            keys = ({k.value for k in body.keys if isinstance(k, ast.Constant)}
                    if isinstance(body, ast.Dict) and all(isinstance(k, ast.Constant) for k in body.keys)
                    else None)
            out.append((path.relative_to(ROOT).as_posix(), node.lineno, keys))
    return out


def test_no_user_login_writer_names_a_server_column():
    """A write to businesses with the user's login that names anything but an
    owner column is refused by the database after the migration (42501).
    Whoever adds one writes that column as the server instead, or (if it
    really is the owner's) grants it in a migration and adds it to
    OWNER_COLUMNS."""
    writes = _user_login_business_writes()
    assert writes, "the scan found nothing: it has gone blind"
    for file, line, keys in writes:
        assert keys is not None, f"{file}:{line}: a user-login businesses write whose keys can't be read"
        assert keys <= OWNER_COLUMNS, f"{file}:{line}: {sorted(keys - OWNER_COLUMNS)}"


def test_the_user_login_writers_are_the_known_ones():
    found = {}
    for file, _line, _keys in _user_login_business_writes():
        found[file] = found.get(file, 0) + 1
    # settings (Chief's actions), voice_profile (update_voice_profile),
    # settings + brand_kit_history + updated_at and the draft (brand_engine).
    assert found == {"brand_engine.py": 5, "business_track_actions.py": 1, "chief_grow_actions.py": 6,
                     "chief_of_staff.py": 4, "chief_offering_actions.py": 2, "chief_strategy_actions.py": 1,
                     "agents/composer/creative_expression.py": 1}, found


def test_brand_engines_draft_path_is_the_businesses_row():
    import brand_engine
    assert brand_engine._draft_path("b").startswith("/businesses?id=eq.b")


# ─── 3. the SQL ───────────────────────────────────────────────────────

def test_the_guard_holds_only_the_apps_logins_and_reads_no_table():
    fn = _guard()
    assert "security definer" not in fn                     # current_user must be the caller
    assert "if current_user not in ('anon', 'authenticated') then\n    return new;" in fn
    assert "if tg_op = 'insert' then" in fn and "errcode = '42501'" in fn
    assert fn.count("raise exception") == 2
    code = re.sub(r"'(?:[^']|'')*'", "''", fn).replace("distinct from", "")
    assert not re.search(r"\b(from|join)\b", code)          # no table read: no 42P17 risk
    assert re.search(r"before insert or update on public\.businesses\s+for each row", _sql().lower())


def test_the_migration_is_safe_to_run_twice_and_its_rollback_is_commented_out():
    sql = _sql().lower()
    assert sql.count("create or replace function") == 1
    assert "drop trigger if exists businesses_guard_server_columns on public.businesses;" in sql
    assert "set local lock_timeout = '5s';" in sql and "begin;" in sql and "commit;" in sql
    assert "notify pgrst, 'reload schema';" in sql
    assert "alter table" not in sql and "delete from" not in sql and "update public." not in sql
    assert "security definer" not in sql
    text = MIGRATION.read_text(encoding="utf-8")
    tail = text[text.index("-- Rollback"):]
    assert "drop trigger if exists businesses_guard_server_columns" in tail
    assert "grant insert, update on public.businesses to anon, authenticated;" in tail
    assert all(line.startswith("--") for line in tail.splitlines() if line.strip())


def test_the_ledger_names_it_not_applied():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(line for line in ledger.splitlines() if "APPLY-2026-11-17-businesses-server-columns.sql" in line)
    assert "NOT APPLIED" in row


def test_the_rls_doc_says_how_to_add_a_column():
    doc = (ROOT / "docs" / "RLS_MODEL.md").read_text(encoding="utf-8")
    assert "APPLY-2026-11-17-businesses-server-columns.sql" in doc
    assert "grant update (" in doc.lower()


def test_ci_runs_the_database_check():
    assert "node __tests__/businesses_server_columns_db.mjs" in (
        ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


# ─── 4. the badge is the server's ─────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self._data, self.status_code = data, 200
        self.text = "x"

    def json(self):
        return self._data


class _Client:
    """httpx.AsyncClient as _recompute_in_the_clear meets it."""

    def __init__(self, phases_done, flagged):
        self.phases_done, self.flagged, self.calls = phases_done, flagged, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, timeout=None):
        self.calls.append(("get", url, headers))
        if "/foundation_progress" in url:
            return _Resp([{"phase": p, "status": "complete"} for p in self.phases_done])
        return _Resp([{"in_the_clear": self.flagged}])

    async def patch(self, url, headers=None, content=None, timeout=None):
        self.calls.append(("patch", url, headers, content))
        return _Resp([{}])


@pytest.mark.parametrize("phases_done,flagged,expect", [
    ([1, 2, 3, 4, 5, 6, 7], False, True),
    ([1, 2, 3], True, False),
])
def test_in_the_clear_is_written_as_the_server_even_inside_a_users_request(monkeypatch, phases_done, flagged, expect):
    import json

    import foundation_agent
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("SUPABASE_ANON", "anon-key")
    client = _Client(phases_done, flagged)
    monkeypatch.setattr(foundation_agent.httpx, "AsyncClient", lambda *a, **k: client)
    token = sb_clients.set_user_jwt("the-users-jwt")
    try:
        asyncio.run(foundation_agent._recompute_in_the_clear("biz-1"))
    finally:
        sb_clients.reset_user_jwt(token)
    patches = [c for c in client.calls if c[0] == "patch"]
    assert len(patches) == 1
    assert json.loads(patches[0][3])["in_the_clear"] is expect
    assert all(c[2]["Authorization"] == "Bearer service-key" for c in client.calls)


def test_in_the_clear_unchanged_writes_nothing(monkeypatch):
    import foundation_agent
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    client = _Client([1, 2, 3, 4, 5, 6, 7], True)
    monkeypatch.setattr(foundation_agent.httpx, "AsyncClient", lambda *a, **k: client)
    asyncio.run(foundation_agent._recompute_in_the_clear("biz-1"))
    assert [c[0] for c in client.calls] == ["get", "get"]


def test_the_wizards_own_writes_still_follow_the_login(monkeypatch):
    """Only the badge moved to the server: a phase row is still written with
    the user's login when one is bound (RLS decides whose)."""
    import foundation_agent
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("SUPABASE_ANON", "anon-key")
    token = sb_clients.set_user_jwt("the-users-jwt")
    try:
        assert foundation_agent._sb_headers()["Authorization"] == "Bearer the-users-jwt"
        assert foundation_agent._sb_headers(as_server=True)["Authorization"] == "Bearer service-key"
    finally:
        sb_clients.reset_user_jwt(token)


# ─── 5. the signup door's birth tier ──────────────────────────────────

@pytest.fixture
def fake(monkeypatch):
    from test_i2_gl_sync import FakeSB
    fb = FakeSB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    for k in ("BILLING_ENFORCE", "LAUNCH_INVITE_ONLY", "STRIPE_PRICE_ID_STARTER"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _u(uid):
    return type("U", (), {"id": uid, "email": None})()


@pytest.mark.parametrize("sent", [None, "starter", "practice", "church_large"])
def test_a_new_business_is_born_on_the_servers_tier_whatever_the_app_sends(fake, sent):
    import launch_access as la
    out = la.create_business(la.CreateBusinessBody(name="New", type="coach", tier=sent), _u("owner-1"))
    assert out["ok"]
    rows = fake.rows("businesses")
    assert len(rows) == 1 and rows[0]["tier"] == la.BIRTH_TIER == "starter"
    assert rows[0]["owner_id"] == "owner-1"
    for col in ("comp_tier", "subscription_status", "subscription_plan", "trial_ends_at",
                "stripe_customer_id", "stripe_subscription_id", "stripe_account_id"):
        assert not rows[0].get(col), col


def test_the_signup_door_never_copies_the_clients_tier():
    import inspect

    import launch_access as la
    src = inspect.getsource(la.create_business)
    assert '"tier": BIRTH_TIER' in src and "body.tier" not in src
