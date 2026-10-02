import pytest

from api_usage_logger import _compute_cost_cents


def test_sonnet5_prices_new_usage_at_permanent_rate_with_cache():
    # 10k fresh input = 2 cents, 1k output = 1 cent,
    # 20k cache reads = .4 cents, 4k cache writes = 1 cent.
    assert _compute_cost_cents('claude-sonnet-5', 10_000, 1_000,
                              cache_read_tokens=20_000, cache_creation_tokens=4_000) == pytest.approx(4.4)


def test_sonnet4_and_opus_prices_are_unchanged():
    assert _compute_cost_cents('claude-sonnet-4-5-20250929', 10_000, 1_000) == pytest.approx(4.5)
    assert _compute_cost_cents('claude-opus-4-8', 10_000, 1_000) == pytest.approx(7.5)
