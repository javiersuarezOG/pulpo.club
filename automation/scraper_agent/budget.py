"""Anthropic spend cap for the scraper-agent loop.

A runaway loop — one that never converges and keeps asking the model for a
new patch — is the failure mode that turns "autonomous scraper repair" into a
surprise invoice. ``Budget`` is the hard stop: every model call is charged
against a per-run ceiling, and the loop checks ``exhausted()`` before each
iteration. Mirrors the spirit of ``automation/llm_cost_guard.py`` (which caps
the nightly enrichment spend) but is self-contained so the loop has no
dependency on the enrichment pipeline.

Prices are a cached snapshot — keep them in one clearly-marked place and let a
caller override per ``Budget`` instance if Anthropic pricing moves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Union

# ── pricing ──────────────────────────────────────────────────────────
# USD per 1,000,000 tokens, (input, output). Cached 2026-05-26 from the
# claude-api skill's model table. Update both columns together if Anthropic
# changes pricing; do not guess.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-opus-4-7":   (5.00, 25.00),
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (1.00,  5.00),
    # DeepSeek (OpenAI-compatible) — the provider Pulpo already pays for via
    # enrichment. Numbers match automation/llm_enrichment.py's constants.
    "deepseek-chat":     (0.27,  1.10),
}
# Unknown model → assume Opus-tier. Over-charging a mystery model is the safe
# direction for a *budget* guard: it trips the ceiling earlier, never later.
DEFAULT_PRICE_USD_PER_MTOK: tuple[float, float] = (5.00, 25.00)

# Cache economics (relative to base input price), per shared/prompt-caching.md.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


class BudgetExceeded(RuntimeError):
    """Raised by :meth:`Budget.check` when the per-run ceiling is reached."""


def _read(source: Union[Mapping, object], name: str) -> int:
    """Read a token field from an SDK usage object OR a plain dict, defaulting
    to 0. The Anthropic Python SDK exposes ``usage.input_tokens`` etc. as
    attributes; tests and replays pass dicts. Cache fields can be ``None``."""
    if isinstance(source, Mapping):
        value = source.get(name, 0)
    else:
        value = getattr(source, name, 0)
    return int(value or 0)


@dataclass
class Budget:
    """A per-run USD ceiling for model spend.

    ``charge_usage`` takes the ``usage`` block off a Messages API response
    (object or dict) and bills it; ``charge`` takes raw token counts. Both
    return the marginal cost so the loop can log per-iteration spend.
    """

    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    prices: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(PRICES_USD_PER_MTOK)
    )

    def price_for(self, model: str) -> tuple[float, float]:
        if model in self.prices:
            return self.prices[model]
        # A DeepSeek variant must NOT fall back to the Opus default — that
        # would over-charge a cheap model ~18x and trip the cap far too early.
        # Map any deepseek-* id to the deepseek-chat tier.
        if model.startswith("deepseek"):
            return self.prices.get("deepseek-chat", DEFAULT_PRICE_USD_PER_MTOK)
        return DEFAULT_PRICE_USD_PER_MTOK

    def cost_of(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> float:
        in_price, out_price = self.price_for(model)
        cost = (input_tokens / 1_000_000) * in_price
        cost += (cache_creation_input_tokens / 1_000_000) * in_price * CACHE_WRITE_MULTIPLIER
        cost += (cache_read_input_tokens / 1_000_000) * in_price * CACHE_READ_MULTIPLIER
        cost += (output_tokens / 1_000_000) * out_price
        return cost

    def charge(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> float:
        cost = self.cost_of(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )
        self.spent_usd += cost
        self.calls += 1
        return cost

    def charge_usage(self, model: str, usage: Union[Mapping, object]) -> float:
        """Bill the ``usage`` block from a Messages API response."""
        return self.charge(
            model,
            input_tokens=_read(usage, "input_tokens"),
            output_tokens=_read(usage, "output_tokens"),
            cache_creation_input_tokens=_read(usage, "cache_creation_input_tokens"),
            cache_read_input_tokens=_read(usage, "cache_read_input_tokens"),
        )

    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def exhausted(self) -> bool:
        return self.spent_usd >= self.limit_usd

    def check(self, *, headroom_usd: float = 0.0) -> None:
        """Raise :class:`BudgetExceeded` if spend has reached the ceiling.

        ``headroom_usd`` lets the loop refuse to *start* an iteration it
        likely can't afford — pass a rough per-iteration estimate so the loop
        stops before the call that would blow the budget, not after.
        """
        if self.spent_usd + headroom_usd >= self.limit_usd:
            raise BudgetExceeded(
                f"scraper-agent budget exhausted: spent ${self.spent_usd:.2f} "
                f"(+${headroom_usd:.2f} headroom) of ${self.limit_usd:.2f} "
                f"across {self.calls} call(s)"
            )

    def summary(self) -> str:
        return (
            f"spent ${self.spent_usd:.2f} / ${self.limit_usd:.2f} "
            f"({self.calls} call(s), ${self.remaining_usd():.2f} left)"
        )
