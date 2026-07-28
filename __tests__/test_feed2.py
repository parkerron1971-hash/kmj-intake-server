"""
Feed 2 — cross-account vertical learning.

LAYER_TWO_ARCHITECTURE.md §6 calls this the moat: what one salon teaches
Chief, the next salon should already know. It is also the single riskiest
thing in the codebase, because it is the ONLY path by which one tenant's
usage reaches another tenant — every other read in the system is
business_id-scoped.

So these tests are weighted toward the defences, not the feature. The
happy path is a handful of assertions; the privacy design gets the rest.

What they defend:
  • k-anonymity is enforced on the EVIDENCE, before the model sees it,
  • contribution is per-business, honoured, and revocable,
  • the model is never handed a message body,
  • scrubbing strips identifiers even from the fields that do get used,
  • a row cannot carry the business it came from,
  • every layer fails open — no key, no table, no evidence → no writes and
    no change to the prompt.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import vertical_distill as vd
import vertical_knowledge as vk
import vertical_context as vctx


# ─── consent ─────────────────────────────────────────────────────────

def test_contribution_is_on_by_default():
    """Kevin's ruling 2026-07-27: on by default, with an off switch. A
    business that has never seen the setting still contributes."""
    assert vd.contributes({"id": "b1"})
    assert vd.contributes({"id": "b1", "settings": {}})
    assert vd.contributes({"id": "b1", "settings": {"unrelated": 1}})


def test_contribution_can_be_switched_off():
    assert not vd.contributes({"settings": {"feed2": {"contribute": False}}})
    assert not vd.contributes({"settings": {"feed2_contribute": False}})


def test_explicit_true_still_contributes():
    assert vd.contributes({"settings": {"feed2": {"contribute": True}}})


def test_malformed_settings_do_not_crash_the_scan():
    """A bad settings blob must not take the job down — it falls back to
    the default rather than raising."""
    for junk in ("not-a-dict", 42, None, [1, 2, 3]):
        assert vd.contributes({"settings": junk}) is True


def test_non_contributors_are_excluded_from_the_scan(monkeypatch):
    """The toggle has to bite where it matters — in the grouping that
    decides whose data is gathered at all."""
    rows = [
        {"id": "in-1", "type": "coach", "settings": {}},
        {"id": "in-2", "type": "coach", "settings": {"feed2": {"contribute": True}}},
        {"id": "OUT", "type": "coach", "settings": {"feed2": {"contribute": False}}},
    ]
    monkeypatch.setattr(vd.sb_clients, "sb_get_as_service", lambda p: rows)
    groups = vd._businesses_by_vertical()
    assert set(groups.get("coach", [])) == {"in-1", "in-2"}
    assert "OUT" not in groups.get("coach", [])


# ─── k-anonymity: the primary control ────────────────────────────────

def test_k_anonymity_drops_anything_below_the_floor():
    buckets = {
        "seen at one business":   {"b1"},
        "seen at two":            {"b1", "b2"},
        "seen at three":          {"b1", "b2", "b3"},
        "seen at four":           {"b1", "b2", "b3", "b4"},
    }
    kept = {k["signal"] for k in vd._k_anonymous(buckets)}
    assert kept == {"seen at three", "seen at four"}


def test_k_anonymity_counts_businesses_not_occurrences():
    """One chatty business must not clear the floor on its own. The bucket
    is a SET of business ids precisely so repetition cannot substitute for
    breadth."""
    buckets = {"one business, forty times": {"b1"}}
    assert vd._k_anonymous(buckets) == []


def test_floor_is_at_least_three():
    """Below three, 'several businesses do this' stops being true."""
    assert vd.MIN_BUSINESSES >= 3


def test_a_vertical_with_too_few_businesses_is_skipped(monkeypatch):
    monkeypatch.setattr(vd, "_businesses_by_vertical",
                        lambda: {"coach": ["b1", "b2"]})
    monkeypatch.setattr(vd, "_enabled", lambda: True)
    called = []
    monkeypatch.setattr(vd, "_gather", lambda ids: called.append(ids) or {})
    out = vd.run_for_vertical("coach")
    assert out["written"] == 0
    assert "only 2" in (out["skipped"] or "")
    assert not called, "evidence must not even be gathered below the floor"


def test_distillation_is_skipped_when_no_signal_clears_the_floor(monkeypatch):
    monkeypatch.setattr(vd, "_enabled", lambda: True)
    monkeypatch.setattr(vd, "_businesses_by_vertical",
                        lambda: {"coach": ["b1", "b2", "b3", "b4"]})
    monkeypatch.setattr(vd, "_gather", lambda ids: {
        "situations": {"only one business does this": {"b1"}},
        "corrections": {}, "proposals": {}})
    distilled = []
    monkeypatch.setattr(vd, "_distil", lambda v, e: distilled.append(e) or [])
    out = vd.run_for_vertical("coach")
    assert out["written"] == 0
    assert "k-anonymity" in (out["skipped"] or "")
    assert not distilled, "the model must never be called with sub-floor evidence"


# ─── the model never sees a message body ─────────────────────────────

def test_gather_never_selects_a_template_body(monkeypatch):
    """chief_templates.body holds real messages that were sent to real
    customers. It is the richest-looking source and the most dangerous one,
    so the query must not ask for it.

    Asserted against the select= clauses actually issued at runtime, not
    against the module source — the source also contains the word 'body' in
    the comment explaining why it is absent, and a test that reads prose
    tests nothing."""
    selects = []

    def _fake_get(path):
        if "select=" in path:
            selects.append(path.split("select=")[1].split("&")[0])
        return []

    monkeypatch.setattr(vd.sb_clients, "sb_get_as_service", _fake_get)
    vd._gather(["b1", "b2", "b3"])

    assert selects, "expected the gatherer to issue queries"
    for clause in selects:
        cols = {c.strip() for c in clause.split(",")}
        assert "body" not in cols, f"a query selected `body`: {clause}"


def test_gather_requests_only_structural_columns(monkeypatch):
    seen = []

    def _fake_get(path):
        seen.append(path)
        return []

    monkeypatch.setattr(vd.sb_clients, "sb_get_as_service", _fake_get)
    vd._gather(["b1", "b2", "b3"])

    joined = " ".join(seen)
    for forbidden in ("contacts", "email", "phone", "amount", "select=*"):
        assert forbidden not in joined, (
            f"gatherer reached for {forbidden!r}: {joined}")


# ─── scrubbing ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,gone", [
    ("email sarah@acme.com about it", "sarah@acme.com"),
    ("call 555-123-4567 back", "555-123-4567"),
    ("invoice for $1,250.00 sent", "$1,250.00"),
    ("see https://acme.com/x/y", "https://acme.com/x/y"),
    ("booked for 03/14/2026", "03/14/2026"),
    ("account 998877665544", "998877665544"),
])
def test_scrub_strips_identifiers(raw, gone):
    assert gone not in vd._scrub(raw)


def test_scrub_keeps_the_shape_of_the_sentence():
    out = vd._scrub("email sarah@acme.com about the $400 invoice")
    assert "[email]" in out and "[amount]" in out
    assert "invoice" in out, "scrubbing should not destroy the useful words"


def test_scrub_is_bounded():
    assert len(vd._scrub("x" * 5000)) <= 180


def test_distilled_output_is_scrubbed_again(monkeypatch):
    """Belt and braces: even if the model echoes an identifier back, it is
    scrubbed on the way out, not just on the way in."""
    class _Resp:
        status_code = 200
        def json(self):
            return {"content": [{"text":
                    '{"patterns":[{"content":"Coaches often email '
                    'sarah@acme.com after a session ends","confidence":0.7}]}'}]}

    monkeypatch.setattr(vd.llm_call, "post_with", lambda c, p, **k: _Resp())
    out = vd._distil("coach", [{"signal": "s", "businesses": 4}])
    assert out and "sarah@acme.com" not in out[0]["content"]
    assert "[email]" in out[0]["content"]


# ─── the row cannot carry its origin ─────────────────────────────────

def test_written_rows_have_no_business_id(monkeypatch):
    posted = {}

    def _fake_post(path, body, prefer=None):
        posted.update(body)
        return {}

    monkeypatch.setattr(vk.sb_clients, "sb_post_as_service", _fake_post)
    monkeypatch.setattr(vk.chief_memory_semantic, "embed", lambda t: None)
    assert vk.upsert("coach", vk.KIND_PATTERN, "a pattern about coaching",
                     source=vk.SOURCE_LEARNED, evidence_count=4)
    assert "business_id" not in posted
    assert posted["vertical"] == "coach"
    assert posted["source"] == "learned"


def _ddl_without_comments(sql: str) -> str:
    """SQL with `-- …` comments stripped. The migration deliberately says
    'DELIBERATELY NO business_id' in a comment, so a naive substring check
    would assert against the sentence promising the thing rather than the
    thing."""
    return "\n".join(line.split("--")[0] for line in sql.splitlines())


def test_migration_declares_no_business_id_column():
    """Defence 2 is structural — the column does not exist, so provenance
    cannot be reconstructed from a row even by a future careless writer."""
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-27-vertical-knowledge.sql").read_text(encoding="utf-8")
    ddl = _ddl_without_comments(sql)
    table = ddl.split("CREATE TABLE IF NOT EXISTS public.vertical_knowledge")[1].split(");")[0]
    assert "business_id" not in table, "vertical_knowledge must not have a business_id column"


def test_match_rpc_is_not_business_scoped():
    """The RPC takes a vertical, not a business — knowledge here belongs to
    the category. Asserted so a future 'fix' cannot quietly re-scope it."""
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-27-vertical-knowledge.sql").read_text(encoding="utf-8")
    fn = _ddl_without_comments(sql).split(
        "FUNCTION public.match_vertical_knowledge")[1].split("$$")[0]
    assert "p_vertical text" in fn
    assert "p_business_id" not in fn


# ─── retrieval into the prompt ───────────────────────────────────────

def test_learned_block_is_empty_when_nothing_is_learned(monkeypatch):
    """The prompt must be byte-identical to today's when Feed 2 has
    nothing — that is what makes this safe to ship before it has data."""
    monkeypatch.setattr(vk, "match", lambda *a, **k: [])
    assert vctx.build_vertical_learned_block({"type": "coach"}, "how's my week") == ""


def test_learned_block_never_raises(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(vk, "match", _boom)
    assert vctx.build_vertical_learned_block({"type": "coach"}, "anything") == ""


def test_learned_block_only_surfaces_learned_rows(monkeypatch):
    """Seeded knowledge is already in the static vertical block. Repeating
    it here would spend tokens saying the same thing twice."""
    monkeypatch.setattr(vk, "match", lambda *a, **k: [
        {"content": "SEEDED voice hallmark", "source": "seed"},
        {"content": "LEARNED pattern about rebooking", "source": "learned"},
    ])
    block = vctx.build_vertical_learned_block({"type": "coach"}, "rebooking")
    assert "LEARNED pattern about rebooking" in block
    assert "SEEDED" not in block


def test_learned_block_is_token_budgeted(monkeypatch):
    monkeypatch.setattr(vk, "match", lambda *a, **k: [
        {"content": "x" * 400, "source": "learned"} for _ in range(20)])
    block = vctx.build_vertical_learned_block({"type": "coach"}, "q")
    assert len(block) < vctx.LEARNED_BLOCK_MAX_CHARS + 400


def test_learned_block_frames_patterns_as_priors_not_rules(monkeypatch):
    """Chief must weigh these against the business's own history, not obey
    them. The framing is the only thing stopping a category tendency from
    overriding what this particular practitioner actually does."""
    monkeypatch.setattr(vk, "match", lambda *a, **k: [
        {"content": "Evening reminders get more replies", "source": "learned"}])
    block = vctx.build_vertical_learned_block({"type": "coach"}, "reminders")
    lowered = block.lower()
    assert "not rules" in lowered
    assert "own history" in lowered or "always win" in lowered


def test_learned_block_needs_both_a_vertical_and_a_question():
    assert vctx.build_vertical_learned_block({}, "q") == ""
    assert vctx.build_vertical_learned_block({"type": "coach"}, "") == ""
    assert vctx.build_vertical_learned_block(None, "q") == ""


# ─── kill switches and fail-open ─────────────────────────────────────

def test_feed2_kill_switch(monkeypatch):
    monkeypatch.setenv("FEED2", "off")
    assert not vd._enabled()
    assert vd.tick() == {"skipped": "disabled"}


def test_vertical_knowledge_kill_switch(monkeypatch):
    monkeypatch.setenv("VERTICAL_KNOWLEDGE", "off")
    assert not vk._enabled()
    assert vk.match("coach", "anything") == []
    assert vk.upsert("coach", "pattern", "x") is False
    assert vk.list_for_vertical("coach") == []


def test_distil_returns_empty_on_a_bad_model_reply(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"content": [{"text": "I'm afraid I can't do that"}]}
    monkeypatch.setattr(vd.llm_call, "post_with", lambda c, p, **k: _Resp())
    assert vd._distil("coach", [{"signal": "s", "businesses": 5}]) == []


def test_distil_returns_empty_when_the_model_errors(monkeypatch):
    class _Resp:
        status_code = 500
        text = "boom"
    monkeypatch.setattr(vd.llm_call, "post_with", lambda c, p, **k: _Resp())
    assert vd._distil("coach", [{"signal": "s", "businesses": 5}]) == []


def test_distil_with_no_evidence_makes_no_model_call(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("model must not be called with no evidence")
    monkeypatch.setattr(vd.llm_call, "post_with", _boom)
    assert vd._distil("coach", []) == []


def test_upsert_reports_failure_honestly(monkeypatch):
    """`written` counts must not flatter — a failed write returns False."""
    def _boom(*a, **k):
        raise RuntimeError("table missing")
    monkeypatch.setattr(vk.sb_clients, "sb_post_as_service", _boom)
    monkeypatch.setattr(vk.chief_memory_semantic, "embed", lambda t: None)
    assert vk.upsert("coach", "pattern", "something") is False


# ─── evidence_count is a floor, not a boast ──────────────────────────

def test_evidence_count_records_the_weakest_signal(monkeypatch):
    monkeypatch.setattr(vd, "_enabled", lambda: True)
    monkeypatch.setattr(vd, "_businesses_by_vertical",
                        lambda: {"coach": ["b1", "b2", "b3", "b4", "b5"]})
    monkeypatch.setattr(vd, "_gather", lambda ids: {
        "situations": {"widely seen": {"b1", "b2", "b3", "b4", "b5"}},
        "corrections": {"just cleared the floor": {"b1", "b2", "b3"}},
        "proposals": {}})
    monkeypatch.setattr(vd, "_distil", lambda v, e: [
        {"content": "a distilled pattern about coaching", "confidence": 0.8}])
    captured = {}
    monkeypatch.setattr(vk, "upsert",
                        lambda *a, **k: captured.update(k) or True)
    out = vd.run_for_vertical("coach")
    assert out["written"] == 1
    assert captured["evidence_count"] == 3, (
        "evidence_count should be the weakest supporting signal, not the strongest")


# ─── Feed 1 seeding ──────────────────────────────────────────────────

def test_seed_tick_skips_content_already_present(monkeypatch):
    """The reason this is schedulable: `upsert` embeds BEFORE it writes, so
    a blind re-run would pay for every embedding again to produce nothing.
    Diffing first makes the steady state one cheap read per vertical."""
    monkeypatch.setattr(vk, "_enabled", lambda: True)
    monkeypatch.setattr(vk, "list_for_vertical",
                        lambda v, source=None, limit=200: [
                            {"content": "Voice hallmark: already here"}])
    monkeypatch.setattr(vk, "_seed_rows_for", lambda v: [
        {"kind": "voice", "content": "Voice hallmark: already here"},
        {"kind": "voice", "content": "Voice hallmark: brand new"},
    ])
    embedded = []
    monkeypatch.setattr(vk.chief_memory_semantic, "embed",
                        lambda t: embedded.append(t) or None)
    monkeypatch.setattr(vk.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: {})

    out = vk.seed_tick(["coach"])
    assert out["written"] == 1 and out["skipped"] == 1
    assert embedded == ["Voice hallmark: brand new"], (
        "an already-present seed must not be re-embedded")


def test_seed_tick_is_idempotent(monkeypatch):
    """Second run over an unchanged profile writes nothing at all."""
    monkeypatch.setattr(vk, "_enabled", lambda: True)
    rows = [{"kind": "voice", "content": "Voice hallmark: warm"}]
    monkeypatch.setattr(vk, "_seed_rows_for", lambda v: rows)
    monkeypatch.setattr(vk, "list_for_vertical",
                        lambda v, source=None, limit=200: [
                            {"content": r["content"]} for r in rows])
    monkeypatch.setattr(vk.chief_memory_semantic, "embed",
                        lambda t: pytest.fail("should not embed on a no-op run"))
    out = vk.seed_tick(["coach"])
    assert out["written"] == 0 and out["skipped"] == 1
    assert out["verticals"] == 1 and out["failed"] == 0


def test_one_bad_vertical_does_not_stop_the_others(monkeypatch):
    """Without a per-vertical guard, a malformed profile raises, the
    remaining verticals never seed, and the scheduler wrapper swallows it —
    failing silently AND partially. A bad vertical must cost that vertical
    and nothing else."""
    monkeypatch.setattr(vk, "_enabled", lambda: True)
    monkeypatch.setattr(vk, "list_for_vertical", lambda v, source=None, limit=200: [])
    monkeypatch.setattr(vk.chief_memory_semantic, "embed", lambda t: None)
    monkeypatch.setattr(vk.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: {})

    def _rows(vertical):
        if vertical == "broken":
            raise ValueError("malformed profile")
        return [{"kind": "voice", "content": f"Voice hallmark for {vertical}"}]

    monkeypatch.setattr(vk, "_seed_rows_for", _rows)

    out = vk.seed_tick(["coach", "broken", "lawyer"])
    assert out["failed"] == 1
    assert out["written"] == 2, "the healthy verticals must still seed"


def test_seed_tick_reports_failures_rather_than_hiding_them():
    """`failed` is in the return shape so a partial run is visible to
    whoever reads the job's output, not just to the log."""
    import inspect
    assert '"failed"' in inspect.getsource(vk.seed_tick)


def test_min_businesses_is_documented_as_load_bearing():
    """The product UI promises client data never leaves the account. For
    names that promise rests on this floor, not on scrubbing — so the
    constant carries a warning saying so. If this test fails, someone
    removed the explanation of why the number cannot be lowered."""
    import inspect
    src = inspect.getsource(vd)
    head = src[:src.index("MIN_BUSINESSES = 3")]
    assert "never leave your account" in head, (
        "the link between MIN_BUSINESSES and the UI promise must stay documented")
