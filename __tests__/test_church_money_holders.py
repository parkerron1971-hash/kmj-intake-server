"""Giving as its own tick, the database half (step three of "One sheet per
person", piece 2 of 7): supabase/APPLY-2026-11-18-church-money-holders.sql,
its rollback, and the two closed reads in church_money_holders.py. Kevin,
2026-11-18: "yes build with C".

What the file does on a real Postgres (nobody's answer changes with no
holder; what each tick opens; only the owner's word) is
__tests__/church_money_holders_db.mjs, run by CI's database checks. This file
pins the things that one cannot see:

  * the file's shape: one transaction, a lock timeout, safe to run twice,
    nothing dropped that it does not make again, and it touches none of the
    objects it promises to leave alone
  * the copied text really is the copy: the base is the 2026-09-29 body, the
    walled list is the 2026-09-29 list, the nine tables are the 2026-09-29
    nine, and the rollback's two bodies are their files' own
  * every function has a fixed search_path; the ones a policy reads are
    SECURITY DEFINER; the two the server runs are the server's alone
  * the two new tables are server-only and carry no policy
  * the rollback undoes each object the apply adds and leaves the tables
  * the ledger, the export decision and CI know about it
  * the server's reads: a read that fails, a table that is not there, a seat
    that ended, a tick given to another seat, or an id that is not an id is
    "no holder", and nothing here raises

People and churches here are made up."""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import account_lifecycle  # noqa: E402
import church_money_holders as mh  # noqa: E402
import sb_clients  # noqa: E402

APPLY = ROOT / "supabase" / "APPLY-2026-11-18-church-money-holders.sql"
ROLLBACK = ROOT / "supabase" / "ROLLBACK-2026-11-18-church-money-holders.sql"
READINESS = ROOT / "supabase" / "APPLY-2026-09-29-ministry-readiness.sql"
GIFT_ROWS = ROOT / "supabase" / "APPLY-2026-10-27-church-keys-gift-rows.sql"

TABLES = ("church_money_holders", "church_money_asks")
POLICY_FUNCTIONS = ("ministry_finance_base", "ministry_finance_walled", "church_money_tick",
                    "ministry_finance_access", "ministry_giving_access", "ministry_finance_write_guard",
                    "ministry_finance_bank_guard")
SERVER_FUNCTIONS = ("church_money_grant", "church_money_answer")
NEW_FUNCTIONS = tuple(f for f in POLICY_FUNCTIONS if f not in ("ministry_finance_access", "ministry_giving_access")
                      ) + SERVER_FUNCTIONS
NEW_POLICIES = ("ministry_financial_write_insert", "ministry_financial_write_update",
                "ministry_financial_write_delete", "church_money_bank")
# What the file promises not to touch.
LEFT_ALONE_FUNCTIONS = ("ministry_finance_guard", "church_giving_open", "protect_gift_classification",
                        "is_business_writer", "is_business_member")
LEFT_ALONE_POLICIES = ("ministry_financial_privacy", "gift_row_privacy", "church_giving_bank",
                       "ministry_financial_events", "ministry_financial_notifications", "tenant_writer_write",
                       "tenant_member_read")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(sql: str) -> str:
    """The statements without their comments, lower case."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).lower()


def _body(sql: str, name: str) -> str:
    """One function's body, spaces folded."""
    start = sql.index(f"create or replace function public.{name}(")
    a = sql.index("as $$", start) + 5
    return re.sub(r"\s+", " ", sql[a:sql.index("$$", a)]).strip()


def _head(sql: str, name: str) -> str:
    """One function's header: from its name to its body."""
    start = sql.index(f"create or replace function public.{name}(")
    return re.sub(r"\s+", " ", sql[start:sql.index("as $$", start)]).lower()


def _array(sql: str, first: str) -> list:
    """The text[] literal that starts with `first`."""
    m = re.search(r"array\[(%s[^\]]*)\]" % re.escape("'" + first + "'"), sql)
    assert m, first
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _type_list(sql: str, after: str) -> list:
    """The business types of the wall, from the function named `after`."""
    start = sql.index(f"create or replace function public.{after}(")
    m = re.search(r"\(('ministry','ministries'[^)]*)\)", sql[start:])
    assert m, after
    return re.findall(r"'([a-z_]+)'", m.group(1))


# ─── The file's shape ─────────────────────────────────────────────────

def test_it_is_one_transaction_with_a_lock_timeout_and_tells_postgrest_after():
    code = _code(_read(APPLY))
    assert len(re.findall(r"^\s*begin;", code, re.M)) == 1 and len(re.findall(r"^\s*commit;", code, re.M)) == 1
    assert code.index("begin;") < code.index("set local lock_timeout = '5s';") < code.index("create table")
    assert code.index("commit;") < code.index("notify pgrst, 'reload schema';")
    # Nothing a statement could do after the commit but the notify.
    assert code[code.index("commit;") + len("commit;"):].strip() == "notify pgrst, 'reload schema';"
    # The SQL editor runs it: no psql meta-commands.
    assert not re.search(r"^\s*\\", _read(APPLY), re.M)


def test_it_is_safe_to_run_twice():
    code = _code(_read(APPLY))
    assert len(re.findall(r"create table (?!if not exists)", code)) == 0
    assert len(re.findall(r"create (?:unique )?index (?!if not exists)", code)) == 0
    assert len(re.findall(r"create function", code)) == 0, "every function is create or replace"
    # Each constraint is added behind its own pg_constraint check.
    for name in re.findall(r"add constraint (\w+)", code):
        assert f"where conname = '{name}'" in code, name
    # Each policy it makes it first removes, in the same statement block.
    for name in NEW_POLICIES:
        assert code.count(f"drop policy if exists {name} on public.%i") == 1, name
        assert code.count(f"create policy {name} on public.%i") == 1, name
        assert code.index(f"drop policy if exists {name} ") < code.index(f"create policy {name} ")


def test_nothing_is_dropped_that_it_does_not_make_again():
    code = _code(_read(APPLY))
    drops = re.findall(r"\bdrop\s+(\w+)(?:\s+if\s+exists)?\s+([\w.]+)", code)
    assert drops and all(kind == "policy" for kind, _ in drops), drops
    assert sorted({name for _, name in drops}) == sorted(NEW_POLICIES)
    for word in ("drop table", "drop function", "drop trigger", "drop index", "truncate", "alter policy"):
        assert word not in code, word
    # The file deletes no row when it runs: the one `delete` is inside the
    # server's own function (taking a tick away), and nowhere else.
    assert code.count("delete from") == 1
    assert "delete from public.church_money_holders where business_id = p_business and user_id = p_user;" in re.sub(
        r"\s+", " ", _body(_read(APPLY), "church_money_grant"))
    # No existing table is altered: only the two new ones.
    for table in re.findall(r"alter table (?:public\.)?(\w+)", code):
        assert table in TABLES, table


def test_it_leaves_alone_what_it_says_it_leaves_alone():
    code = _code(_read(APPLY))
    for name in LEFT_ALONE_FUNCTIONS:
        assert f"function public.{name}(" not in code, name
    for name in LEFT_ALONE_POLICIES:
        assert f"policy {name} " not in code and f"policy if exists {name} " not in code, name
    assert "create trigger" not in code
    # Every policy it adds only narrows.
    for line in re.findall(r"create policy [^;]+", code):
        assert " as restrictive " in line and " to authenticated " in line, line
    assert " as permissive " not in code and "using (true)" not in code and "using(true)" not in code


# ─── The copies are copies ────────────────────────────────────────────

def test_the_base_is_the_september_body_word_for_word():
    apply, old = _read(APPLY), _read(READINESS)
    assert _body(apply, "ministry_finance_base") == _body(old, "ministry_finance_access")
    assert _head(apply, "ministry_finance_base") == _head(old, "ministry_finance_access").replace(
        "ministry_finance_access", "ministry_finance_base")


def test_the_wall_stands_in_front_of_the_same_businesses_and_tables():
    apply, old = _read(APPLY), _read(READINESS)
    assert _type_list(apply, "ministry_finance_walled") == _type_list(old, "ministry_finance_guard")
    assert len(_type_list(apply, "ministry_finance_walled")) == 18
    # The same fold of the type's spelling.
    fold = "lower(regexp_replace(trim(coalesce(b.type,'')), '[-[:space:]]+', '_', 'g'))"
    assert fold in _body(apply, "ministry_finance_walled") and fold in _body(old, "ministry_finance_guard")
    nine = _array(old, "invoices")
    assert len(nine) == 9 and _array(apply, "invoices") == nine
    assert _array(apply, "plaid_transactions") == ["plaid_transactions", "plaid_accounts"]
    assert _array(_read(GIFT_ROWS), "plaid_transactions") == ["plaid_transactions", "plaid_accounts"]


def test_the_replaced_functions_say_what_the_header_says():
    apply = _read(APPLY)
    assert _body(apply, "ministry_finance_access") == (
        "select public.ministry_finance_base(b_id) or public.church_money_tick(b_id, 'any');")
    giving = _body(apply, "ministry_giving_access")
    assert giving == ("select (public.ministry_finance_base(b_id) or public.church_money_tick(b_id, 'who_gave')) "
                      "and public.church_giving_open(b_id);")
    # Giving never takes the widened access: any holder would see who gave.
    assert "ministry_finance_access" not in giving
    # Same names and arguments as the functions they replace (create or
    # replace cannot rename an argument).
    assert "public.ministry_finance_access(b_id uuid) returns boolean" in _head(apply, "ministry_finance_access")
    assert "public.ministry_giving_access(b_id uuid) returns boolean" in _head(apply, "ministry_giving_access")
    write, bank = _body(apply, "ministry_finance_write_guard"), _body(apply, "ministry_finance_bank_guard")
    assert "church_money_tick(b_id, 'work')" in write and "'any'" not in write and "'bank'" not in write
    assert "church_money_tick(b_id, 'bank')" in bank and "'any'" not in bank and "'work'" not in bank
    for guard in (write, bank):
        assert guard.startswith("select exists(select 1 from businesses b where b.id=b_id) and (not "
                                "public.ministry_finance_walled(b_id) or public.ministry_finance_base(b_id) or ")


def test_the_tick_counts_only_on_the_active_seat_it_was_given_to():
    tick = _body(_read(APPLY), "church_money_tick")
    assert "from church_money_holders h" in tick
    assert "join business_users u on u.id=h.seat_id and u.business_id=h.business_id and u.user_id=h.user_id" in tick
    assert "u.status='active'" in tick
    assert "h.business_id=b_id and h.user_id=auth.uid()" in tick
    assert "when 'work' then h.level in ('work','lead') and u.role in ('member','manager','admin')" in tick
    assert "when 'any' then true" in tick and "when 'who_gave' then h.who_gave" in tick
    assert "when 'bank' then h.bank" in tick and "else false end" in tick


# ─── The functions ────────────────────────────────────────────────────

def test_every_function_has_a_fixed_search_path_and_the_right_rights():
    apply = _read(APPLY)
    code = _code(apply)
    made = re.findall(r"create or replace function public\.(\w+)\(", code)
    assert sorted(made) == sorted(POLICY_FUNCTIONS + SERVER_FUNCTIONS)
    for name in POLICY_FUNCTIONS:
        head = _head(apply, name)
        assert "security definer" in head and "set search_path=public" in head and " stable " in head, name
        assert "language sql" in head, name
    for name in SERVER_FUNCTIONS:
        head = _head(apply, name)
        assert "set search_path=public" in head and "security definer" not in head, name
    # Policy functions read only these four tables: none has a policy that
    # calls them back (docs/RLS_MODEL.md, the 42P17 rule).
    for name in POLICY_FUNCTIONS:
        read = set(re.findall(r"(?:from|join)\s+(\w+)", _body(apply, name)))
        assert read <= {"businesses", "business_users", "business_collaborators", "church_money_holders"}, (name, read)
    flat = re.sub(r"\s+", " ", code)
    assert ("revoke all on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid), "
            "public.church_money_answer(uuid, boolean, uuid) from public, anon, authenticated;") in flat
    assert ("grant execute on function public.church_money_grant(uuid, uuid, text, boolean, boolean, uuid, uuid), "
            "public.church_money_answer(uuid, boolean, uuid) to service_role;") in flat
    assert ("revoke all on function public.ministry_finance_base(uuid), public.ministry_finance_walled(uuid), "
            "public.church_money_tick(uuid, text) from public, anon, authenticated;") in flat
    assert ("revoke all on function public.ministry_finance_write_guard(uuid), "
            "public.ministry_finance_bank_guard(uuid) from public, anon;") in flat
    # Nothing is ever granted to the signed-out role.
    assert not re.search(r"grant [^;]* to [^;]*\banon\b", flat)


def test_only_the_owner_makes_a_holder():
    apply = _read(APPLY)
    grant, answer = _body(apply, "church_money_grant"), _body(apply, "church_money_answer")
    owner_check = "if v_owner is null or p_by is null or v_owner <> p_by then raise exception"
    assert owner_check in grant and owner_check in answer
    assert "select b.owner_id into v_owner from public.businesses b where b.id = p_business;" in grant
    assert "select b.owner_id into v_owner from public.businesses b where b.id = a.business_id;" in answer
    # The owner check comes before the first write in each.
    assert grant.index(owner_check) < grant.index("delete from") < grant.index("insert into")
    assert answer.index(owner_check) < answer.index("church_money_grant(") < answer.index("update public.church_money_asks")
    assert "for update" in answer and "a.status <> 'asked'" in answer and "a.expires_at <= now()" in answer
    assert "a.asked_by = a.user_id" in answer
    assert "v_role = 'viewer' and p_level <> 'see'" in grant and "u.status = 'active'" in grant
    assert "not public.ministry_finance_walled(p_business)" in grant


# ─── The tables ───────────────────────────────────────────────────────

def test_the_two_tables_are_the_servers_alone_and_the_export_knows_them():
    code = _code(_read(APPLY))
    for table in TABLES:
        assert code.count(f"create table if not exists public.{table}(") == 1
        assert f"alter table public.{table} enable row level security;" in code
        assert f"revoke all on public.{table} from public, anon, authenticated;" in code
        assert f"grant all on public.{table} to service_role;" in code
        assert f"on public.{table} " not in "\n".join(re.findall(r"create policy [^;]+", code)), table
        # Excluded from the export, with a reason; never both.
        assert table in account_lifecycle.EXPORT_EXCLUDED and table not in account_lifecycle.BUSINESS_CHILD_TABLES
        assert len(account_lifecycle.EXPORT_EXCLUDED[table]) > 60
    assert code.count("references public.businesses(id) on delete cascade") == 2
    assert "seat_id uuid not null references public.business_users(id) on delete cascade" in code
    assert "primary key (business_id, user_id)" in code
    assert ("create unique index if not exists church_money_asks_one_open on public.church_money_asks(business_id, "
            "user_id) where status = 'asked';") in re.sub(r"\s+", " ", code)
    assert "check (level in ('see', 'work', 'lead'))" in code
    assert "check (status in ('asked', 'approved', 'declined', 'expired', 'withdrawn'))" in re.sub(r"\s+", " ", code)
    assert "check (asked_by <> user_id)" in code
    assert "interval '7 days'" in code


# ─── The rollback ─────────────────────────────────────────────────────

def test_the_rollback_restores_each_object_the_apply_replaces_and_removes_each_it_adds():
    back, code = _read(ROLLBACK), _code(_read(ROLLBACK))
    assert len(re.findall(r"^\s*begin;", code, re.M)) == 1 and len(re.findall(r"^\s*commit;", code, re.M)) == 1
    assert "set local lock_timeout = '5s';" in code
    assert _body(back, "ministry_finance_access") == _body(_read(READINESS), "ministry_finance_access")
    assert _head(back, "ministry_finance_access") == _head(_read(READINESS), "ministry_finance_access")
    assert _body(back, "ministry_giving_access") == _body(_read(GIFT_ROWS), "ministry_giving_access")
    assert _head(back, "ministry_giving_access") == _head(_read(GIFT_ROWS), "ministry_giving_access")
    assert sorted(re.findall(r"create or replace function public\.(\w+)\(", code)) == [
        "ministry_finance_access", "ministry_giving_access"]
    for name in NEW_POLICIES:
        assert f"drop policy if exists {name} on public.%i" in code, name
    for name in NEW_FUNCTIONS:
        assert f"drop function if exists public.{name}(" in code, name
    assert sorted(re.findall(r"drop function if exists public\.(\w+)\(", code)) == sorted(NEW_FUNCTIONS)
    # The policies go before the guards they call; the two bodies are put
    # back before what they used to call is dropped.
    assert code.index("drop policy if exists") < code.index("create or replace function") < code.index("drop function")
    # The tables stay, the rows with them; dropping them is a comment.
    assert "drop table" not in code and "delete from" not in code and "create policy" not in code
    assert "-- drop table if exists public.church_money_holders;" in back
    assert "delete from public.church_money_holders;" in back          # the instant stop, said
    assert _array(back, "invoices") == _array(_read(APPLY), "invoices")
    for name in LEFT_ALONE_POLICIES + LEFT_ALONE_FUNCTIONS:
        assert f"policy if exists {name} " not in code and f"function if exists public.{name}(" not in code, name


# ─── The ledger and CI ────────────────────────────────────────────────

def test_the_ledger_and_ci_know_about_it():
    ledger = _read(ROOT / "docs" / "MIGRATIONS.md")
    rows = [ln for ln in ledger.splitlines() if ln.startswith("| `supabase/APPLY-2026-11-18-church-money-holders.sql`")]
    assert len(rows) == 1
    assert "| **NOT APPLIED** |" in rows[0] or "| **APPLIED 20" in rows[0]
    assert "ROLLBACK-2026-11-18-church-money-holders.sql" in rows[0]
    ci = _read(ROOT / ".github" / "workflows" / "ci.yml")
    assert "node __tests__/church_money_holders_db.mjs" in ci
    assert (ROOT / "__tests__" / "church_money_holders_db.mjs").exists()


# ─── The server's reads: closed ───────────────────────────────────────

BIZ = "11111111-1111-4111-8111-111111111111"
USER = "00000000-0000-4000-8000-000000000005"
SEAT = "aaaaaaaa-0000-4000-8000-000000000005"
OWNER = "00000000-0000-4000-8000-000000000001"
ASK = "bbbbbbbb-0000-4000-8000-000000000001"


def _holder(**over):
    return {"business_id": BIZ, "user_id": USER, "seat_id": SEAT, "level": "work", "who_gave": True, "bank": False,
            "granted_by": OWNER, "granted_at": "2026-11-18T15:00:00+00:00", "ask_id": None, **over}


def _seat(**over):
    return {"id": SEAT, "role": "member", "status": "active", **over}


class Reads:
    """sb_get_as_service, answering from two lists and keeping the paths."""

    def __init__(self, holders=None, seats=None, asks=None):
        self.holders, self.seats, self.asks, self.paths = holders, seats, asks, []

    def __call__(self, path, *a, **k):
        self.paths.append(path)
        if path.startswith(f"/{mh.HOLDERS}?"):
            return self.holders
        if path.startswith("/business_users?"):
            return self.seats
        if path.startswith(f"/{mh.ASKS}?"):
            return self.asks
        raise AssertionError(f"an unexpected read: {path}")


@pytest.fixture
def reads(monkeypatch):
    def use(**kw):
        fake = Reads(**kw)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
        return fake
    return use


def test_a_holder_on_their_active_seat_is_read_as_the_database_reads_them(reads):
    fake = reads(holders=[_holder()], seats=[_seat()])
    got = mh.money_holder(BIZ, USER)
    assert got == {"level": "work", "can_work": True, "who_gave": True, "bank": False, "seat_role": "member",
                   "granted_by": OWNER, "granted_at": "2026-11-18T15:00:00+00:00", "ask_id": None}
    # The seat read asks for THAT seat row, this church, this person, active.
    seat_read = fake.paths[1]
    for part in (f"id=eq.{SEAT}", f"business_id=eq.{BIZ}", f"user_id=eq.{USER}", "status=eq.active"):
        assert part in seat_read, part
    for part in (f"business_id=eq.{BIZ}", f"user_id=eq.{USER}"):
        assert part in fake.paths[0], part


@pytest.mark.parametrize("level, role, can_work", [
    ("see", "manager", False), ("work", "viewer", False), ("lead", "viewer", False), ("work", "member", True),
    ("lead", "manager", True), ("work", "admin", True), ("work", None, False), ("work", "owner", False),
])
def test_work_is_work_only_on_a_seat_that_may_write(reads, level, role, can_work):
    reads(holders=[_holder(level=level)], seats=[_seat(role=role)])
    got = mh.money_holder(BIZ, USER)
    assert got["level"] == level and got["can_work"] is can_work


@pytest.mark.parametrize("why, holders, seats", [
    ("no row", [], [_seat()]),
    ("the holders read failed (or the table is not there yet)", None, [_seat()]),
    ("the holders read answered something that is not rows", {"message": "relation does not exist"}, [_seat()]),
    ("the seat read failed", [_holder()], None),
    ("the seat it was given to is no longer active", [_holder()], []),
    ("the seat row is another seat", [_holder()], [_seat(id="cccccccc-0000-4000-8000-000000000009")]),
    ("the seat row says revoked", [_holder()], [_seat(status="revoked")]),
    ("a level nobody gave", [_holder(level="everything")], [_seat()]),
    ("no seat on the row", [_holder(seat_id=None)], [_seat()]),
    ("a row for another person", [_holder(user_id=OWNER)], [_seat()]),
    ("a row for another church", [_holder(business_id="22222222-2222-4222-8222-222222222222")], [_seat()]),
    ("a row that is not a row", ["x"], [_seat()]),
    ("a seat that is not a row", [_holder()], ["x"]),
])
def test_anything_short_of_a_holder_on_their_active_seat_is_no_holder(reads, why, holders, seats):
    reads(holders=holders, seats=seats)
    assert mh.money_holder(BIZ, USER) is None, why


def test_a_read_that_raises_is_no_holder_and_never_reaches_a_route(monkeypatch):
    def boom(path, *a, **k):
        raise RuntimeError("the database did not answer")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert mh.money_holder(BIZ, USER) is None
    assert mh.open_ask(BIZ, USER) is None


@pytest.mark.parametrize("biz, user", [
    (None, USER), (BIZ, None), ("", ""), ("not-a-uuid", USER), (BIZ, f"{USER}&user_id=neq.x"),
    (f"{BIZ}#", USER), (BIZ, "*"), (BIZ, f"{USER} "[:-1] + "x"), (123, USER),
])
def test_an_id_that_is_not_an_id_is_no_holder_without_a_read(reads, biz, user):
    fake = reads(holders=[_holder()], seats=[_seat()], asks=[])
    assert mh.money_holder(biz, user) is None
    assert mh.open_ask(biz, user) is None
    assert fake.paths == []


def test_truth_is_true_and_nothing_else(reads):
    reads(holders=[_holder(who_gave="yes", bank=1)], seats=[_seat()])
    got = mh.money_holder(BIZ, USER)
    assert got["who_gave"] is False and got["bank"] is False


NOW = dt.datetime(2026, 11, 18, 16, 0, tzinfo=dt.timezone.utc)


def _ask(**over):
    return {"id": ASK, "business_id": BIZ, "user_id": USER, "asked_by": OWNER.replace("1", "2", 1),
            "wants": {"level": "work", "who_gave": True}, "status": "asked",
            "asked_at": "2026-11-18T15:00:00+00:00", "expires_at": "2026-11-25T15:00:00+00:00",
            "reminded_at": None, **over}


def test_an_open_ask_is_read_and_opens_nothing(reads):
    fake = reads(asks=[_ask()])
    got = mh.open_ask(BIZ, USER, now=NOW)
    assert got["id"] == ASK and got["wants"] == {"level": "work", "who_gave": True, "bank": False}
    assert got["expires_at"] == "2026-11-25T15:00:00+00:00"
    assert "status=eq.asked" in fake.paths[0] and f"user_id=eq.{USER}" in fake.paths[0]
    # An ask is never a holder.
    reads(holders=[], seats=[_seat()], asks=[_ask()])
    assert mh.money_holder(BIZ, USER) is None


@pytest.mark.parametrize("why, asks", [
    ("none", []),
    ("the read failed", None),
    ("it ran out", [_ask(expires_at="2026-11-18T15:59:59+00:00")]),
    ("it runs out this second", [_ask(expires_at="2026-11-18T16:00:00+00:00")]),
    ("no end written", [_ask(expires_at=None)]),
    ("an end that is not a time", [_ask(expires_at="soon")]),
    ("already answered", [_ask(status="approved")]),
    ("for another person", [_ask(user_id=OWNER)]),
    ("for another church", [_ask(business_id="22222222-2222-4222-8222-222222222222")]),
    ("wants nothing this file knows", [_ask(wants={"level": "owner"})]),
    ("wants is not an object", [_ask(wants="work")]),
    ("not a row", ["x"]),
])
def test_anything_short_of_an_open_ask_is_none(reads, why, asks):
    reads(asks=asks)
    assert mh.open_ask(BIZ, USER, now=NOW) is None, why


def test_a_time_with_no_zone_is_read_as_utc(reads):
    reads(asks=[_ask(expires_at="2026-11-18T16:00:01")])
    assert mh.open_ask(BIZ, USER, now=NOW) is not None
    reads(asks=[_ask(expires_at="2026-11-18T16:00:01Z")])
    assert mh.open_ask(BIZ, USER, now=NOW) is not None


def test_this_file_decides_nothing_and_no_door_reads_it_yet():
    """The tick is not wired into any decision in this PR: the money gate's
    table does not name it, and nothing but this test imports the module."""
    import church_money_gate
    gate = _read(ROOT / "church_money_gate.py")
    assert "church_money_holders" not in gate and "money_holder(" not in gate
    assert not hasattr(church_money_gate, "money_holder")
    users = [p.name for p in ROOT.glob("*.py")
             if p.name != "church_money_holders.py" and re.search(r"\bchurch_money_holders\b", _read(p))
             and p.name != "account_lifecycle.py"]
    assert users == [], users
    src = _read(ROOT / "church_money_holders.py")
    assert "HTTPException" not in src and "sb_post" not in src and "sb_patch" not in src and "sb_delete" not in src
    assert "sb_get_as_service" in src and "SUPABASE_ANON" not in src
