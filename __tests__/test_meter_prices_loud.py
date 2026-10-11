"""
test_meter_prices_loud.py — the meter never guesses quietly (2026-10-11).

Layer Two step 0a. Three ways spend could go uncounted or be counted low:

  * A model with no price row was priced at Sonnet-4 rates with no log
    line. An expensive model was under-booked, and nobody could see it.
    It is now priced at the top current Claude list price (Fable, $10/$50)
    and announced once on stdout, so the spend guard errs high until the
    row is added. Not the table's column maxima: those combine a
    per-character TTS row with a retired model's output rate into a price
    no model has, high enough to trip the platform cap.
  * Rows were missing for models in use: the default ElevenLabs voice
    (eleven_flash_v2_5), Kimi K3, GPT-5.4, Fable 5.1, Mythos 5.1.
  * 1-hour cache writes were priced at the 5-minute rate (1.25x, not 2x)
    on the sync path and in the route ledger. That covers every call
    metered at the llm_call seam.

Two direct provider calls never reached api_usage at all: the GPT-5.4
decoration validator and DALL-E. The spend guard reads api_usage only,
so it could not see them.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import api_usage_logger
from api_usage_logger import _compute_cost_cents, _price_for_model


# ── Unknown models: loud, once, and expensive ─────────────────────────

def test_an_unknown_model_is_priced_at_the_top_claude_rate(capsys):
    api_usage_logger._UNKNOWN_MODELS_SEEN.discard("mystery-model-9")
    assert _price_for_model("mystery-model-9") == (1000.0, 5000.0)
    # The ceiling is a real current price: the Fable row's own.
    assert api_usage_logger.MODEL_PRICING_CENTS["claude-fable-5"] == (1000.0, 5000.0)
    # Never the old silent Sonnet-4 fallback.
    assert _price_for_model("mystery-model-9") != (300.0, 1500.0)
    out = capsys.readouterr().out
    assert "[meter] UNKNOWN MODEL 'mystery-model-9'" in out


def test_the_warning_prints_once_per_model(capsys):
    api_usage_logger._UNKNOWN_MODELS_SEEN.discard("mystery-model-10")
    for _ in range(5):
        _price_for_model("mystery-model-10")
    assert capsys.readouterr().out.count("UNKNOWN MODEL 'mystery-model-10'") == 1


@pytest.mark.parametrize("empty", ["", None])
def test_an_empty_model_is_loud_and_expensive(empty, capsys):
    api_usage_logger._UNKNOWN_MODELS_SEEN.discard("<empty>")
    assert _price_for_model(empty) == api_usage_logger._most_expensive_rates()
    assert "UNKNOWN MODEL '<empty>'" in capsys.readouterr().out


def test_a_known_model_is_quiet(capsys):
    assert _price_for_model("claude-sonnet-5-5") == (200.0, 1000.0)
    assert capsys.readouterr().out == ""


# ── Rows for models in use ────────────────────────────────────────────

@pytest.mark.parametrize("model, prices", [
    ("eleven_flash_v2_5", (2500.0, 0.0)),    # same rate as eleven_turbo_v2_5
    ("kimi-k3", (300.0, 1500.0)),
    ("gpt-5.4", (250.0, 1500.0)),
    ("gpt-5.4-2026-03-05", (250.0, 1500.0)),  # dated ids match by prefix
    ("claude-fable-5-1", (1000.0, 5000.0)),
    ("claude-mythos-5-1", (1000.0, 5000.0)),
])
def test_models_in_use_have_their_own_rows(model, prices, capsys):
    assert _price_for_model(model) == prices
    assert "UNKNOWN" not in capsys.readouterr().out


def test_the_default_voice_model_is_priced_per_character():
    # 10,000 characters of Flash at $25 / 1M chars = 25 cents. Before the
    # row they fell through as Sonnet-4 input tokens: 3 cents.
    assert _compute_cost_cents("eleven_flash_v2_5", 10_000, 0) == pytest.approx(25.0)


# ── 1-hour cache writes on the sync path ──────────────────────────────

def test_the_sync_logger_prices_1h_writes_at_2x(monkeypatch):
    bodies = []
    monkeypatch.setattr(api_usage_logger, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(api_usage_logger, "SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setattr(api_usage_logger.httpx, "post",
                        lambda url, **kw: bodies.append(kw["json"]))
    # Sonnet 5 at $2/MTok: 10k 5-minute writes = 2.5c, 10k 1-hour = 4c.
    api_usage_logger.log_api_usage_sync(
        endpoint="llm:test", model="claude-sonnet-5", input_tokens=0, output_tokens=0,
        cache_creation_tokens=20_000, cache_creation_1h_tokens=10_000)
    assert bodies[0]["cost_cents"] == pytest.approx(6.5)


def test_the_seam_passes_the_1h_part_of_the_write(monkeypatch):
    import llm_call

    class _Resp:
        status_code = 200

        def json(self):
            return {"model": "claude-sonnet-5", "usage": {
                "input_tokens": 10, "output_tokens": 5,
                "cache_creation_input_tokens": 57_000,
                "cache_creation": {"ephemeral_5m_input_tokens": 12_000,
                                   "ephemeral_1h_input_tokens": 45_000}}}

    rows = []
    monkeypatch.setattr("api_usage_logger.log_api_usage_sync", lambda **kw: rows.append(kw))
    llm_call._meter(_Resp(), {}, "discovery", 0.0)
    assert rows[0]["cache_creation_tokens"] == 57_000
    assert rows[0]["cache_creation_1h_tokens"] == 45_000


def test_the_route_ledger_prices_1h_writes_at_2x():
    import route_ledger
    t = route_ledger.Tally()
    t.add("claude-sonnet-5", cache_write=20_000, cache_write_1h=10_000)
    assert t.cost_cents() == pytest.approx(6.5)
    # Without the breakdown a write keeps the 5-minute rate.
    t2 = route_ledger.Tally()
    t2.add("claude-sonnet-5", cache_write=20_000)
    assert t2.cost_cents() == pytest.approx(5.0)


def test_the_route_ledger_reads_the_breakdown_from_usage():
    import route_ledger
    t = route_ledger.Tally()
    token = route_ledger.TALLY.set(t)
    try:
        route_ledger.tally_usage("claude-sonnet-5", {
            "cache_creation_input_tokens": 20_000,
            "cache_creation": {"ephemeral_1h_input_tokens": 10_000}})
    finally:
        route_ledger.TALLY.reset(token)
    assert t.cost_cents() == pytest.approx(6.5)


def test_a_1h_count_never_exceeds_the_whole_write_in_the_ledger():
    import route_ledger
    t = route_ledger.Tally()
    t.add("claude-sonnet-5", cache_write=10_000, cache_write_1h=99_000)
    assert t.cost_cents() == pytest.approx(4.0)


# ── Direct provider calls reach api_usage ─────────────────────────────

def test_dalle_generations_are_metered_as_cost_rows(monkeypatch):
    from agents.slot_system import dalle_client
    rows = []
    monkeypatch.setattr("api_usage_logger.log_api_usage_sync", lambda **kw: rows.append(kw))
    monkeypatch.setattr(dalle_client, "_fetch_site_row", lambda bid: (None, {}))
    dalle_client._log_dalle_spend(business_id="biz-1", slot_name="hero", cost_usd=0.08)
    assert len(rows) == 1
    assert rows[0]["model"] == "dall-e-3"
    assert rows[0]["cost_cents_override"] == pytest.approx(8.0)
    assert rows[0]["business_id"] == "biz-1"
    # A cost row, not a priced action: no credits charged for it.
    assert rows[0]["units"] == 0


def test_the_gpt_validator_is_metered(monkeypatch):
    import studio_decoration_generator as sdg

    class _Resp:
        encoding = None

        def raise_for_status(self):
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(sdg.httpx, "post", lambda *a, **kw: _Resp())
    monkeypatch.setattr(sdg, "_decode_utf8_response", lambda r: {
        "model": "gpt-5.4-2026-03-05",
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 1_200, "completion_tokens": 300,
                  "prompt_tokens_details": {"cached_tokens": 200}}})
    rows = []
    monkeypatch.setattr("api_usage_logger.log_api_usage_sync", lambda **kw: rows.append(kw))
    assert sdg.call_gpt("check this") == "{}"
    assert rows[0]["endpoint"] == "/studio/decoration-validator"
    assert rows[0]["model"] == "gpt-5.4-2026-03-05"
    # OpenAI's prompt_tokens include the cached part; api_usage splits it out.
    assert rows[0]["input_tokens"] == 1_000
    assert rows[0]["cache_read_tokens"] == 200
    assert rows[0]["output_tokens"] == 300
    assert rows[0]["units"] == 0


def test_openai_metering_never_raises(monkeypatch, capsys):
    def boom(**kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", boom)
    api_usage_logger.meter_openai_usage("/x", {"usage": {}}, fallback_model="gpt-5.4")
    assert "not logged" in capsys.readouterr().out
