"""Feed 1b — the curated vertical playbook and the retrieval that reads it."""
from __future__ import annotations

import re
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import vertical_context as vctx
import vertical_knowledge as vk
import vertical_playbook as vpb
import vertical_registry as reg


# ─── Coverage ────────────────────────────────────────────────────────


def test_every_vertical_has_a_shelf_except_custom():
    """'custom' is absent deliberately — the registry marks it
    "intentionally GENERIC — triggers Chief interactive discovery", so a
    playbook for it would mean inventing the trade."""
    missing = [v for v in reg.canonical_keys()
               if v != "custom" and v not in vpb.PLAYBOOK]
    assert not missing, f"verticals with no curated knowledge: {missing}"

    assert "custom" not in vpb.PLAYBOOK
    assert vpb.entries_for("custom") == []
    assert vpb.entries_for("florist") == []


def test_shelves_resolve_aliases():
    assert vpb.entries_for("church") == vpb.PLAYBOOK["ministry"]
    assert vpb.entries_for("agency") == vpb.PLAYBOOK["creative"]
    assert vpb.entries_for("plumber") == vpb.PLAYBOOK["contractor"]


def test_entries_are_well_formed():
    for vertical, rows in vpb.PLAYBOOK.items():
        assert rows, f"{vertical} has an empty shelf"
        seen = set()
        for row in rows:
            assert row.get("kind"), f"{vertical} has an entry with no kind"
            content = row.get("content") or ""
            assert content, f"{vertical} has an entry with no content"
            assert content not in seen, f"{vertical} repeats an entry"
            seen.add(content)
            # Each row is retrieved on its own and must stand alone inside
            # the shared 700-char budget; one long row would crowd out
            # everything else that matched.
            assert len(content) <= 320, (
                f"{vertical} entry is {len(content)} chars — too long to "
                f"share the retrieval budget")


# ─── The discipline that keeps this corpus honest ────────────────────


_PERCENT = re.compile(r"\d+\s*(?:%|percent)")
_MONEY = re.compile(r"[$£€]\s?\d")


def test_no_entry_invents_a_benchmark_number():
    """The module forbids fabricated statistics, and this is what makes the
    ban real rather than aspirational.

    Nobody here measured a typical no-show rate or an average ticket. A
    made-up figure reads as authoritative BECAUSE it is specific — Chief
    would repeat it to a practitioner who would act on it. Where the useful
    thing is a number, an entry names which number to watch and what it
    would mean, and leaves the value to the business's own data."""
    for vertical, rows in vpb.PLAYBOOK.items():
        for row in rows:
            content = row["content"]
            assert not _PERCENT.search(content), (
                f"{vertical} entry states a percentage — no benchmark here "
                f"was measured: {content[:80]}")
            assert not _MONEY.search(content), (
                f"{vertical} entry states a currency figure: {content[:80]}")


def test_therapist_shelf_stays_out_of_clinical_scope():
    """The therapist vertical launched with clinical records out of scope.
    This corpus is retrieved straight into the Chief prompt, so it would be
    the natural seam for clinical language to re-enter."""
    blob = " ".join(r["content"] for r in vpb.PLAYBOOK["therapist"]).lower()
    for forbidden in ("diagnosis", "progress note", "clinical note",
                      "session content", "treatment plan", "symptom"):
        assert forbidden not in blob, (
            f"therapist playbook must not mention '{forbidden}'")


# ─── Projection into rows ────────────────────────────────────────────


def test_curate_tick_writes_curated_rows(monkeypatch):
    written = []
    monkeypatch.setattr(vk, "_enabled", lambda: True)
    monkeypatch.setattr(vk, "list_for_vertical", lambda v, **kw: [])
    monkeypatch.setattr(vk, "upsert",
                        lambda v, k, c, **kw: written.append((v, kw.get("source"))) or True)

    out = vpb.curate_tick(["ministry"])
    assert out["written"] == len(vpb.PLAYBOOK["ministry"])
    assert out["failed"] == 0
    assert {s for _, s in written} == {vk.SOURCE_CURATED}, (
        "curated rows must not be written as 'seed' — seeds are filtered "
        "out of retrieval, so they would land on a shelf nothing reads")


def test_curate_tick_skips_what_is_already_there(monkeypatch):
    """Diff-first. upsert embeds BEFORE it writes, so a blind re-run would
    pay for every embedding again to produce zero rows."""
    rows = vpb.PLAYBOOK["coach"]
    monkeypatch.setattr(vk, "_enabled", lambda: True)
    monkeypatch.setattr(vk, "list_for_vertical",
                        lambda v, **kw: [{"content": rows[0]["content"]}])
    calls = []
    monkeypatch.setattr(vk, "upsert",
                        lambda v, k, c, **kw: calls.append(c) or True)

    out = vpb.curate_tick(["coach"])
    assert out["skipped"] == 1
    assert out["written"] == len(rows) - 1
    assert rows[0]["content"] not in calls


def test_curate_tick_survives_one_bad_shelf(monkeypatch):
    """A malformed shelf costs that shelf and nothing else — otherwise the
    run fails silently AND partially, the worst of both."""
    monkeypatch.setattr(vk, "_enabled", lambda: True)

    def boom(v, **kw):
        if v == "broken":
            raise RuntimeError("nope")
        return []
    monkeypatch.setattr(vk, "list_for_vertical", boom)
    monkeypatch.setattr(vk, "upsert", lambda *a, **kw: True)
    monkeypatch.setattr(vpb, "PLAYBOOK",
                        {"coach": vpb.PLAYBOOK["coach"], "broken": [{"kind": "x", "content": "y"}]})

    out = vpb.curate_tick(["coach", "broken"])
    assert out["failed"] == 1
    assert out["written"] == len(vpb.PLAYBOOK["coach"])


def test_curate_tick_is_a_no_op_when_the_store_is_off(monkeypatch):
    monkeypatch.setattr(vk, "_enabled", lambda: False)
    monkeypatch.setattr(vk, "upsert",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("wrote anyway")))
    assert vpb.curate_tick(["coach"])["written"] == 0


# ─── Retrieval ───────────────────────────────────────────────────────


def _rows(*specs):
    return [{"content": c, "source": s} for c, s in specs]


def test_curated_rows_now_reach_the_prompt(monkeypatch):
    """The point of the whole change. Before it, retrieval filtered to
    source='learned' and there were zero learned rows — so this block was
    always empty no matter what the shelf held."""
    monkeypatch.setattr(vk, "match", lambda *a, **kw: _rows(
        ("A bid that isn't followed up loses to whoever did.", "curated")))
    block = vctx.build_vertical_learned_block({"type": "contractor"}, "slow month")
    assert "HOW THIS TRADE WORKS" in block
    assert "isn't followed up" in block


def test_seed_rows_are_still_excluded(monkeypatch):
    """Seeds are a projection of the profiles already in the static block.
    Surfacing them would make the prompt say everything twice."""
    monkeypatch.setattr(vk, "match", lambda *a, **kw: _rows(
        ("Voice hallmark: uses 'Client' and 'Matter' consistently", "seed")))
    assert vctx.build_vertical_learned_block({"type": "lawyer"}, "anything") == ""


def test_curated_and_learned_are_labelled_separately(monkeypatch):
    """"Several businesses like yours do this" and "this is how the trade
    works" are different claims. Under one heading the weaker would borrow
    the other's authority."""
    monkeypatch.setattr(vk, "match", lambda *a, **kw: _rows(
        ("Rebooking happens in the chair or it doesn't happen.", "curated"),
        ("Reminder proposals get accepted more than discount proposals.", "learned")))
    block = vctx.build_vertical_learned_block({"type": "personal_services"}, "retention")

    assert "HOW THIS TRADE WORKS" in block
    assert "WHAT WORKS FOR BUSINESSES LIKE THIS" in block
    assert block.index("HOW THIS TRADE WORKS") < block.index("Rebooking")
    # The learned line must sit under the learned heading, not the curated one.
    assert (block.index("WHAT WORKS FOR BUSINESSES LIKE THIS")
            < block.index("Reminder proposals"))


def test_both_sources_share_one_budget(monkeypatch):
    """Adding the curated shelf must not double what this block costs every
    turn — one budget across both, not one each."""
    long_row = "x" * 300
    monkeypatch.setattr(vk, "match", lambda *a, **kw: _rows(
        (long_row, "curated"), (long_row, "curated"),
        (long_row, "learned"), (long_row, "learned")))
    block = vctx.build_vertical_learned_block({"type": "coach"}, "anything")
    assert block.count(long_row) == 2, "budget should stop after ~700 chars"


def test_retrieval_failure_still_returns_empty(monkeypatch):
    """Fails open. The prompt has worked without this block for a year."""
    def boom(*a, **kw):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(vk, "match", boom)
    assert vctx.build_vertical_learned_block({"type": "coach"}, "anything") == ""
