"""client-images: only the platform owner writes (APPLY-2026-11-20).

The bucket's two write policies checked only the bucket, so any signed-in
login of any business could upload into it or delete from it. Its only
writer is the owner-only Director page. These tests hold the SQL to that:
both write policies need the bucket AND is_platform_owner(), reads are not
touched, the rollback puts back exactly the 08-09 policies, and the app's
only writers are still behind the owner-only module.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPLY = ROOT / "supabase" / "APPLY-2026-11-20-client-images-owner-writes.sql"
ROLLBACK = ROOT / "supabase" / "ROLLBACK-2026-11-20-client-images-owner-writes.sql"
OLD = ROOT / "supabase" / "APPLY-2026-08-09-storage-write-lockdown.sql"


def _code(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines = [line.split("--", 1)[0] for line in text.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _policies(code: str):
    return re.findall(r'create policy "([^"]+)" on storage\.objects for (\w+) to (\w+) (using|with check) \((.*?)\);',
                      code)


def test_one_transaction_with_a_lock_timeout_and_a_safety_check_first():
    code = _code(APPLY)
    assert code.startswith("begin; set local lock_timeout = '5s'; do $$")
    assert code.endswith("commit;")
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    assert code.index("$$;") < code.index("drop policy"), "the check runs before anything changes"
    assert "to_regprocedure('public.is_platform_owner()') is null" in code


def test_both_writes_need_the_bucket_and_the_platform_owner():
    got = {name: (cmd, role, clause, body) for name, cmd, role, clause, body in _policies(_code(APPLY))}
    assert got == {
        "ets write: client-images insert": ("insert", "authenticated", "with check",
                                            "bucket_id = 'client-images' and public.is_platform_owner()"),
        "ets write: client-images delete": ("delete", "authenticated", "using",
                                            "bucket_id = 'client-images' and public.is_platform_owner()"),
    }


def test_each_policy_is_dropped_by_name_before_it_is_made_so_it_runs_twice():
    code = _code(APPLY)
    for name in ("ets write: client-images insert", "ets write: client-images delete"):
        drop = code.index(f'drop policy if exists "{name}" on storage.objects;')
        assert drop < code.index(f'create policy "{name}"')


def test_nothing_else_is_touched():
    code = _code(APPLY).lower()
    assert "allow public reads" not in code, "reads stay as they are"
    for word in ("update ", "delete from", "insert into", "truncate", "alter table", "grant ", "revoke ",
                 "create table", "drop table", "ets-event-files", "business-assets"):
        assert word not in code, word
    assert code.count("create policy") == 2 and code.count("drop policy") == 2


def test_the_rollback_puts_back_exactly_what_the_0809_file_made():
    back = {name: (cmd, role, clause, body) for name, cmd, role, clause, body in _policies(_code(ROLLBACK))}
    old = _code(OLD)
    for name, (cmd, role, clause, body) in back.items():
        assert "is_platform_owner" not in body
        made = re.search(rf'create policy "{re.escape(name)}" on storage\.objects for {cmd} to {role} '
                         rf'{clause} \(([^;]*?)\);', old)
        assert made and made.group(1) == body, name
    assert set(back) == {"ets write: client-images insert", "ets write: client-images delete"}
    assert "REOPENS" in ROLLBACK.read_text(encoding="utf-8")


def test_the_ledger_lists_it():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    assert "APPLY-2026-11-20-client-images-owner-writes.sql" in ledger
