from dataclasses import replace
import pytest
from .ai.catalog import MODELS, Usage, cost_micro_usd, registry


@pytest.mark.parametrize('model,usage,expected', [
    ('claude', Usage(1000, 2000, 3000, 4000), 49900),
    ('gpt', Usage(1000, 2000, 0, 4000), 21100),
    ('claude', Usage(), 0),
    ('gpt', Usage(0, 10, 0, 0), 1),
])
def test_cost_literal(model, usage, expected):
    assert cost_micro_usd(MODELS[model], usage) == expected


def test_unpriced_and_override():
    assert cost_micro_usd(replace(MODELS['gpt'], prices=None), Usage(10)) is None
    table = registry('{"gpt":{"prices":[2,1,0,10],"price_version":"custom"}}')
    assert cost_micro_usd(table['gpt'], Usage(100, 50, 0, 10)) == 350
    assert table['gpt'].price_version == 'custom'
    assert MODELS['gpt'].price_version == '2026-10-31-contract-unverified'
    assert registry('{"claude":{"prices":null,"price_version":"unknown"}}')['claude'].prices is None


def test_usage_addition_preserves_cache_subsets():
    value = Usage(10, 20, 30, 40) + Usage(1, 2, 3, 4)
    assert value == Usage(11, 22, 33, 44)
    assert value.input_tokens == 66
