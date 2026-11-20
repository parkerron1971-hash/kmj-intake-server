"""The server's keys in businesses.settings stay the server's, and a settings
write names only its own keys (business_settings.py,
supabase/APPLY-2026-11-17-settings-server-keys.sql).

The first paying church lost settings.founding_church on 2026-11-16 to a
whole-object write from a copy read before the place was written. The
database half (the guard trigger and merge_business_settings on a real
Postgres) is __tests__/settings_server_keys_db.mjs; this file pins the lists
to each other and to the code, the SQL's shape, the server's merge and its
fallback, and the writers that now name one key.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import business_settings as bs  # noqa: E402
import sb_clients  # noqa: E402

ROOT = _here.parent
MIGRATION = ROOT / "supabase" / "APPLY-2026-11-17-settings-server-keys.sql"
BIZ = "c4a0c4a0-0000-4000-8000-0000000000aa"


def _sql() -> str:
    """The file's statements, comments stripped."""
    return "\n".join(line.split("--", 1)[0] for line in MIGRATION.read_text(encoding="utf-8").splitlines())


def _fn(name: str) -> str:
    sql = _sql().lower()
    body = sql[sql.index(f"create or replace function public.{name}("):]
    return body[:body.index("$$;") + 3]


def _array(fn: str) -> list:
    return re.findall(r"'([a-z_]+)'", _fn(fn).split("array[", 1)[1].split("]", 1)[0])


# ─── 1. one list, in Python and in SQL ───────────────────────────────

PAYROLL_MIGRATION = ROOT / "supabase" / "APPLY-2026-11-19-payroll-deposits.sql"


def test_the_sql_list_is_the_python_list():
    assert sorted(_array("business_settings_server_keys")) == sorted(bs.SERVER_KEYS)
    assert len(bs.SERVER_KEYS) == len(set(bs.SERVER_KEYS)) == 45
    # The payroll file writes the same list when this file is already in (it
    # added "payroll" on 2026-11-19; guest_calls joined both on 2026-11-20),
    # so either order ends with all 45.
    payroll = "\n".join(ln.split("--", 1)[0] for ln in PAYROLL_MIGRATION.read_text(encoding="utf-8").splitlines())
    body = payroll[payroll.index("create or replace function public.business_settings_server_keys()"):]
    listed = re.findall(r"'([a-z_]+)'", body.split("array[", 1)[1].split("]", 1)[0])
    assert sorted(listed) == sorted(bs.SERVER_KEYS) and "payroll" in listed and "guest_calls" in listed
    assert set(_array("business_settings_birth_keys")) == set(bs.BIRTH_KEYS) == {"churchsavvy_only"}
    assert bs.BIRTH_KEYS <= set(bs.SERVER_KEYS)


def test_every_key_the_server_names_in_code_is_on_the_list():
    import church_billing
    import church_founding
    import church_leaders_note
    import church_over
    import church_serving
    import church_team_week
    import church_texts
    import email_sender
    import lifecycle_emails
    import no_card_trial
    import sample_church
    import site_publish
    for key in (church_founding.FOUNDING, no_card_trial.MARKER, sample_church.SETTINGS_KEY,
                church_billing.MOVE, church_billing.EXTRA_LOGINS, church_billing.EXTRA_STORAGE,
                lifecycle_emails.SETTINGS_KEY,
                church_texts.SETTINGS_KEY, church_leaders_note.KEY, church_team_week.KEY,
                church_serving.SETTINGS_KEY, email_sender.EMAIL_DOMAIN_SETTINGS_KEY,
                site_publish.SETTING_KEY, church_over.OWNER_PERSON_KEY,
                "computer", "stripe", "chief_insights", "chief_playbook", "maturity",
                "churchsavvy_only", "platform_books", "autonomy"):
        assert bs.server_owned(key), key


# The keys the app writes itself, straight to the row (solutionist-studio,
# every PATCH of /businesses?id=eq. and the one supabase-js update; the
# inventory is in worklog/2026-11-17-settings-server-keys.md), and the ones
# it sends when it makes a business. On the server's list, the app's own
# write of one would be kept out without a word.
APP_KEYS = {
    "autopilot", "period_lock_mode", "period_close_two_signature", "financial",
    "nurture_thresholds", "nurture_auto_run", "session_prep_window_hours", "contract_min_lead_score",
    "payment_overdue_days", "payment_trend_threshold_pct", "nurture_auto_min_health",
    "nurture_auto_cooldown_hours", "payment_auto_max_reminders", "sms_alerts", "feed2",
    "notifications", "practitioner_name", "avatar_url", "chief_preferences", "next_steps",
    "saved_filters", "content_calendar", "website_content", "email_templates_v2",
    "email_templates", "funder_profile", "get_found", "goals", "public_listing",
    "grant_boilerplate", "boards", "strategy", "payments", "payment_providers", "link_page",
    "media_library", "checklist_dismissed", "dashboard", "print_materials", "branding",
    "revenue_allocator", "store", "tour_done_v1", "theme", "rooms_visited",
    # sent at birth (OnboardingFlow, ChurchSavvyApp)
    "priority_agents", "custom_type", "track",
}
# Written by the server with the user's login (Chief's _sb inside a chat
# forwards the practitioner's JWT; brand_engine's _sb_patch does too), so the
# guard would hold them as if the app had sent them.
USER_LOGIN_KEYS = {"goals", "content_calendar", "website_content", "store", "events_public",
                   "track", "business_track_done", "brand_kit", "email_templates_v2"}


def test_no_key_the_app_or_a_user_login_writes_is_the_servers():
    assert not (APP_KEYS & set(bs.SERVER_KEYS))
    assert not (USER_LOGIN_KEYS & set(bs.SERVER_KEYS))


def test_the_user_login_settings_writers_are_the_known_ones():
    """A new `_sb(client, "PATCH", "/businesses...` settings write runs as
    the user inside a chat and is held by the guard: whoever adds one checks
    its keys against SERVER_KEYS (or writes it with business_settings.merge)
    and adds it here."""
    found = {}
    for path in ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        n = len(re.findall(r"""_sb\(\s*client,\s*["']PATCH["'],\s*f["']/businesses\?id=eq\.[^\n]*(?:\n[^\n]*)?\{["']settings["']""", text))
        if n:
            found[path.name] = n
    # business_track_done; goals, content_calendar, website_content; website_content,
    # email_templates_v2; events_public, store; track: none of them the server's.
    assert found == {"business_track_actions.py": 1, "chief_grow_actions.py": 6, "chief_of_staff.py": 3,
                     "chief_offering_actions.py": 2, "chief_strategy_actions.py": 1}, found


# ─── 2. the SQL ───────────────────────────────────────────────────────

def test_the_guard_holds_only_the_apps_logins_and_reads_no_table():
    fn = _fn("businesses_guard_server_settings")
    assert "security definer" not in fn                     # current_user must be the caller
    assert "if current_user not in ('anon', 'authenticated') then\n    return new;" in fn
    assert "(incoming - public.business_settings_server_keys()) || kept" in fn
    assert "old.settings -> k" in fn and "business_settings_birth_keys()" in fn
    code = re.sub(r"'(?:[^']|'')*'", "''", fn).replace("distinct from", "")
    assert not re.search(r"\b(from|join)\b", code)          # no table read: no 42P17 risk
    assert re.search(r"before insert or update of settings on public\.businesses\s+for each row", _sql().lower())


def test_the_merge_is_one_update_and_refuses_a_server_key_to_the_app():
    fn = _fn("merge_business_settings")
    assert "security invoker" in fn and "security definer" not in fn
    assert "update public.businesses" in fn and fn.count("update ") == 1
    assert "set settings = public.business_settings_merge_at(settings, p_under, p_set, p_drop)" in fn
    assert "if current_user in ('anon', 'authenticated') then" in fn and "errcode = '42501'" in fn
    sql = _sql().lower()
    for sig in ("merge_business_settings(uuid, jsonb, text[], text[])",
                "business_settings_merge_at(jsonb, text[], jsonb, text[])"):
        assert f"revoke all on function public.{sig} from public, anon;" in sql
        assert f"grant execute on function public.{sig} to authenticated, service_role;" in sql
    assert "security definer" not in sql


def test_the_migration_is_safe_to_run_twice_and_its_rollback_is_commented_out():
    sql = _sql().lower()
    assert sql.count("create or replace function") == 5
    assert "drop trigger if exists businesses_guard_server_settings on public.businesses;" in sql
    assert "set local lock_timeout = '5s';" in sql and "begin;" in sql and "commit;" in sql
    assert "alter table" not in sql and "delete from" not in sql
    text = MIGRATION.read_text(encoding="utf-8")
    tail = text[text.index("-- Rollback"):]
    assert "drop trigger if exists businesses_guard_server_settings" in tail
    assert all(line.startswith("--") for line in tail.splitlines() if line.strip())


def test_the_ledger_names_it_not_applied():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(line for line in ledger.splitlines() if "APPLY-2026-11-17-settings-server-keys.sql" in line)
    assert "NOT APPLIED" in row


def test_ci_runs_the_database_check():
    assert "node __tests__/settings_server_keys_db.mjs" in (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


# ─── 3. the server's merge ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh():
    bs._missing["until"] = 0.0
    yield
    bs._missing["until"] = 0.0
    sb_clients._LAST.error = None          # the fakes below set it; no later test may read it


class _DB:
    """PostgREST as merge() meets it: the function, or its absence."""

    def __init__(self, settings, rpc=True, refuse=None):
        self.settings, self.rpc, self.refuse, self.calls = dict(settings), rpc, refuse, []

    def post(self, path, body, prefer="return=representation", redact=False):
        self.calls.append(("post", path, body))
        if self.refuse:
            sb_clients._LAST.error = self.refuse
            return None
        if not self.rpc:
            sb_clients._LAST.error = {"status": 404, "code": "PGRST202", "message": "Could not find the function"}
            return None
        sb_clients._LAST.error = None
        self.settings = bs.merge_at(self.settings, body["p_under"], body["p_set"], body["p_drop"])
        return dict(self.settings)

    def get(self, path, redact=False):
        self.calls.append(("get", path))
        return [{"settings": dict(self.settings)}]

    def patch(self, path, body):
        self.calls.append(("patch", path, body))
        self.settings = dict(body["settings"])
        return [{}]


def _install(monkeypatch, db):
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    return db


def test_merge_sends_only_the_keys_it_names(monkeypatch):
    db = _install(monkeypatch, _DB({"giving": {"on": True}, "rooms_visited": {"home": "t"}}))
    out = bs.merge(BIZ, {"founding_church": {"n": 1}})
    assert out == {"giving": {"on": True}, "rooms_visited": {"home": "t"}, "founding_church": {"n": 1}}
    [(verb, path, body)] = db.calls
    assert (verb, path) == ("post", "/rpc/merge_business_settings")
    assert body == {"p_business": BIZ, "p_set": {"founding_church": {"n": 1}}, "p_drop": [], "p_under": []}
    assert bs.merge(BIZ, drop=["rooms_visited"]) == {"giving": {"on": True}, "founding_church": {"n": 1}}
    assert bs.merge(BIZ, {"welcome_at": "t1"}, under=["lifecycle_emails"])["lifecycle_emails"] == {"welcome_at": "t1"}
    assert not [c for c in db.calls if c[0] != "post"]       # never a read, never the whole object


def test_until_the_migration_it_writes_from_a_fresh_read_and_says_so(monkeypatch, capsys):
    db = _install(monkeypatch, _DB({"giving": {"on": True}}, rpc=False))
    assert bs.merge(BIZ, {"church_move": {"state": "paid"}}) == {"giving": {"on": True}, "church_move": {"state": "paid"}}
    assert [c[0] for c in db.calls] == ["post", "get", "patch"]
    assert db.calls[2][2] == {"settings": {"giving": {"on": True}, "church_move": {"state": "paid"}}}
    assert "APPLY-2026-11-17-settings-server-keys.sql" in capsys.readouterr().out
    # It doesn't ask again for a while: the next write goes straight to the fallback.
    db.calls.clear()
    bs.merge(BIZ, drop=["church_move"])
    assert [c[0] for c in db.calls] == ["get", "patch"] and db.settings == {"giving": {"on": True}}


def test_a_refused_merge_is_not_retried_the_old_way(monkeypatch):
    db = _install(monkeypatch, _DB({}, refuse={"status": 400, "code": "22023", "message": "p_set must be"}))
    assert bs.merge(BIZ, {"a": 1}) is None
    assert [c[0] for c in db.calls] == ["post"]


def test_no_row_is_none_and_nothing_to_write_is_a_bug(monkeypatch):
    def post(path, body, prefer=None, redact=False):
        sb_clients._LAST.error = None
        return None                                          # the function's null: no such row
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    assert bs.merge(BIZ, {"a": 1}) is None
    assert bs.merge("", {"a": 1}) is None
    with pytest.raises(ValueError):
        bs.merge(BIZ)
    with pytest.raises(ValueError):
        bs.merge(BIZ, {"": 1})


def test_merge_at_is_the_databases_rule():
    assert bs.merge_at({"a": 1, "b": {"x": 1, "y": 1}}, ["b"], {"z": 2}, ["x"]) == {"a": 1, "b": {"y": 1, "z": 2}}
    assert bs.merge_at(None, [], {"a": 1}, []) == {"a": 1}
    assert bs.merge_at({"a": {"b": "no"}}, ["a", "b"], {"c": 1}, []) == {"a": {"b": {"c": 1}}}
    assert bs.merge_at({"a": 1, "b": 2}, [], {}, ["a", "missing"]) == {"b": 2}
    doc = {"a": {"x": 1}}
    bs.merge_at(doc, ["a"], {"y": 2}, [])
    assert doc == {"a": {"x": 1}}                            # the input is never changed


def test_amerge_runs_off_the_loop(monkeypatch):
    db = _install(monkeypatch, _DB({"k": 1}))
    assert asyncio.run(bs.amerge(BIZ, {"j": 2})) == {"k": 1, "j": 2}
    assert asyncio.run(bs.amerge(BIZ, drop=["k"])) == {"j": 2}
    assert len(db.calls) == 2


# ─── 4. a new business is born without the server's keys ─────────────

FORGED = {"founding_church": {"n": 1}, "extra_logins": 40, "no_card_trial": {"started_at": "x"},
          "computer": {"spend_limit_cents": 10 ** 9}, "lifecycle_emails": {"welcome_at": "t"},
          "platform_books": True, "autonomy": {"client_facing_autonomy": "enabled", "acknowledged_at": "t"}}


def test_the_signup_door_keeps_the_apps_keys_and_drops_the_servers():
    import launch_access
    sent = {"practitioner_name": "Pastor Sam", "priority_agents": ["intake"], "custom_type": None,
            "track": "purpose", "churchsavvy_only": True, **FORGED}
    assert launch_access.birth_settings(sent, "ministry") == {
        "practitioner_name": "Pastor Sam", "priority_agents": ["intake"], "custom_type": None,
        "track": "purpose", "churchsavvy_only": True}
    # A regulated practice gets the regulated default, never one it sent.
    born = launch_access.birth_settings(sent, "law firm")
    assert born["autonomy"] == {"client_facing_autonomy": "disabled", "disabled_reason": "regulated_vertical_default",
                                "acknowledgment_required": True, "acknowledged_at": None}
    assert bs.for_new_business(None) == {} and bs.for_new_business(["x"]) == {}


def test_create_business_and_import_use_the_birth_settings():
    import inspect

    import account_lifecycle
    import launch_access
    create = inspect.getsource(launch_access.create_business)
    assert "settings = birth_settings(body.settings, btype)" in create
    assert "dict(body.settings" not in create
    imp = inspect.getsource(account_lifecycle.import_account)
    assert "launch_access.birth_settings(src_biz.get(\"settings\")" in imp
    assert '"settings": settings}' in imp and 'src_biz.get("settings") or {}}' not in imp


# ─── 5. the writers that now name their key ───────────────────────────

@pytest.fixture
def merges(monkeypatch):
    from settings_merge_fake import install
    row = {"id": BIZ, "settings": {"other": "kept"}}
    calls = install(monkeypatch, lambda bid: row if bid == BIZ else None)
    for name in ("sb_patch_as_service",):
        monkeypatch.setattr(sb_clients, name, lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a whole-object settings write")))
    return row, calls


def test_the_cron_markers_send_only_their_own_key(merges):
    import chief_insights
    import chief_playbook
    row, calls = merges
    stale = {"id": BIZ, "settings": {"other": "a copy from before the model call"}}
    chief_insights._mark_run(stale, 3)
    chief_playbook._mark_run(stale, 2, "fp")
    assert [sorted(c["set"]) for c in calls] == [["chief_insights"], ["chief_playbook"]]
    assert row["settings"]["other"] == "kept"
    assert row["settings"]["chief_insights"]["last_count"] == 3 and row["settings"]["chief_playbook"]["fingerprint"] == "fp"


def test_maturity_and_the_email_domain_send_only_their_own_key(merges):
    import email_domain_monitor
    import email_domains_router
    import maturity_engine
    row, calls = merges
    assert maturity_engine._write_cache(BIZ, {"stage": "idea"}) is True
    assert email_domain_monitor._write_cfg({"id": BIZ, "settings": {}}, {"domain": "a.org"}) is True
    assert email_domains_router._write_settings({"id": BIZ, "settings": {}}, {"domain": "b.org"})["email_domain"] == {"domain": "b.org"}
    email_domains_router._write_settings({"id": BIZ}, None)
    assert [(sorted(c["set"]), c["drop"]) for c in calls] == [
        (["maturity"], []), (["email_domain"], []), (["email_domain"], []), ([], ["email_domain"])]
    assert row["settings"] == {"other": "kept", "maturity": {"stage": "idea"}}


def test_a_connect_account_update_writes_inside_settings_stripe(merges, monkeypatch):
    import stripe_connect_router as scr
    row, calls = merges
    row["settings"]["stripe"] = {"account_note": "kept"}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, redact=False: [{"id": BIZ}])
    scr._handle_account_updated({"id": "acct_1", "charges_enabled": True, "payouts_enabled": False,
                                 "details_submitted": True})
    [call] = calls
    assert call["under"] == ["stripe"] and sorted(call["set"]) == [
        "charges_enabled", "details_submitted", "last_account_event_at", "payouts_enabled"]
    assert row["settings"]["stripe"]["account_note"] == "kept" and row["settings"]["stripe"]["charges_enabled"] is True
    assert row["settings"]["other"] == "kept"


def test_a_lifecycle_stamp_writes_inside_lifecycle_emails(merges):
    import lifecycle_emails
    row, calls = merges
    row["settings"]["lifecycle_emails"] = {"welcome_at": "t0"}
    lifecycle_emails._stamp(BIZ, "trial_ending_at")
    [call] = calls
    assert call["under"] == ["lifecycle_emails"] and list(call["set"]) == ["trial_ending_at"]
    assert row["settings"]["lifecycle_emails"]["welcome_at"] == "t0"
    assert row["settings"]["lifecycle_emails"]["trial_ending_at"]


def test_the_converted_writers_never_write_the_whole_object_again():
    """The writers this change moved to business_settings.merge: none of them
    sends {"settings": ...} to /businesses any more."""
    import inspect

    import chief_insights
    import chief_playbook
    import church_billing
    import email_domain_monitor
    import email_domains_router
    import lifecycle_emails
    import maturity_engine
    import no_card_trial
    import stripe_connect_router
    for fn in (church_billing._merge_setting, lifecycle_emails._stamp, chief_insights._mark_run,
               chief_playbook._mark_run, maturity_engine._write_cache, email_domain_monitor._write_cfg,
               email_domains_router._write_settings, stripe_connect_router._handle_account_updated,
               no_card_trial.verify_phone_code):
        src = inspect.getsource(fn)
        assert "business_settings" in src, fn.__name__
        assert not re.search(r"""\{["']settings["']\s*:""", src), fn.__name__
