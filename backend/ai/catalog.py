"""Fixed model choices and pure integer billing."""
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Literal

ModelId = Literal['claude', 'gpt']


@dataclass(frozen=True)
class Usage:
    uncached_input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0

    @property
    def input_tokens(self):
        return self.uncached_input + self.cache_read + self.cache_write

    def __add__(self, other):
        return Usage(*(a + b for a, b in zip(self.values(), other.values())))

    def values(self):
        return self.uncached_input, self.cache_read, self.cache_write, self.output


@dataclass(frozen=True)
class ModelSpec:
    id: ModelId
    label: str
    provider: str
    model: str
    effort: str
    key_env: str
    prices: tuple[Decimal, Decimal, Decimal, Decimal] | None
    price_version: str


def prices(*values):
    return tuple(Decimal(str(v)) for v in values)


MODELS: dict[ModelId, ModelSpec] = {
    'claude': ModelSpec('claude', 'Claude', 'anthropic', 'claude-sonnet-5-5', 'medium',
                        'ANTHROPIC_API_KEY', prices(2, .2, 2.5, 10), '2026-10-31-contract'),
    'gpt': ModelSpec('gpt', 'GPT', 'openai', 'gpt-6.1-terra', 'medium',
                     'OPENAI_API_KEY', prices(1, .05, 0, 5), '2026-10-31-contract-unverified'),
}


def registry(raw: str | None = None) -> dict[ModelId, ModelSpec]:
    result = dict(MODELS)
    for key, override in json.loads(raw or '{}').items():
        spec = result[key]
        rate = override['prices']
        if rate is not None:
            if len(rate) != 4:
                raise ValueError('prices must contain uncached input, cache read, cache write, output')
            rate = prices(*rate)
            if any(not p.is_finite() or p < 0 for p in rate):
                raise ValueError('prices must be finite and nonnegative')
        result[key] = replace(spec, prices=rate, price_version=override['price_version'])
    return result


def cost_micro_usd(spec: ModelSpec, usage: Usage) -> int | None:
    if spec.prices is None:
        return None
    cost = sum((n * p for n, p in zip(usage.values(), spec.prices)), Decimal(0))
    return int(cost.quantize(Decimal(1), rounding=ROUND_HALF_UP))
