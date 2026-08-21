"""Seeded price perturbations for testing dependence on exact observations."""

import random
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting import BacktestEngine
from app.models.market import MarketBar
from app.strategies.base import Strategy


class PerturbationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_version: str
    random_seed: int
    maximum_price_noise_bps: float
    base_return: float
    perturbed_return: float
    return_ratio: float = Field(ge=-10, le=10)
    robust: bool


def evaluate_price_perturbation(
    strategy: Strategy,
    bars: Sequence[MarketBar],
    engine: BacktestEngine,
    *,
    dataset_id: str,
    random_seed: int,
    maximum_price_noise_bps: float = 5.0,
    minimum_return_ratio: float = 0.75,
) -> PerturbationResult:
    if maximum_price_noise_bps < 0:
        raise ValueError("maximum_price_noise_bps cannot be negative")
    random_source = random.Random(random_seed)
    perturbed: list[MarketBar] = []
    for bar in bars:
        factor = 1 + random_source.uniform(
            -maximum_price_noise_bps / 10_000, maximum_price_noise_bps / 10_000
        )
        perturbed.append(
            bar.model_copy(
                update={
                    "open": bar.open * factor,
                    "high": bar.high * factor,
                    "low": bar.low * factor,
                    "close": bar.close * factor,
                    "adjusted_close": (
                        bar.adjusted_close * factor if bar.adjusted_close is not None else None
                    ),
                }
            )
        )
    base = engine.run(strategy, bars, dataset_id=f"{dataset_id}:base")
    changed = engine.run(strategy, perturbed, dataset_id=f"{dataset_id}:perturbed")
    ratio = (
        changed.metrics.total_return / base.metrics.total_return
        if base.metrics.total_return > 0
        else (1.0 if changed.metrics.total_return >= 0 else -1.0)
    )
    ratio = max(min(ratio, 10.0), -10.0)
    return PerturbationResult(
        strategy_version=strategy.spec.version_key,
        random_seed=random_seed,
        maximum_price_noise_bps=maximum_price_noise_bps,
        base_return=base.metrics.total_return,
        perturbed_return=changed.metrics.total_return,
        return_ratio=ratio,
        robust=ratio >= minimum_return_ratio,
    )
