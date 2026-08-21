"""Auditable reference strategies; these are not investment recommendations."""

import math
from collections.abc import Sequence

from app.indicators import highest, mean, momentum
from app.models.enums import AssetClass
from app.models.market import MarketBar
from app.models.strategy import IndicatorSpec, StrategySpec
from app.strategies.base import Strategy


class MovingAverageCrossover(Strategy):
    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        closes = self._closes(available_history)
        fast = mean(closes, int(self.spec.parameters["fast_window"]))
        slow = mean(closes, int(self.spec.parameters["slow_window"]))
        return 1.0 if fast is not None and slow is not None and fast > slow else 0.0


class MomentumStrategy(Strategy):
    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        value = momentum(self._closes(available_history), int(self.spec.parameters["lookback"]))
        threshold = float(self.spec.parameters["threshold"])
        return 1.0 if value is not None and value > threshold else 0.0


class MeanReversionStrategy(Strategy):
    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        closes = self._closes(available_history)
        window = int(self.spec.parameters["window"])
        entry = float(self.spec.parameters["entry_z"])
        exit_level = float(self.spec.parameters["exit_z"])
        active = False
        if len(closes) < window:
            return 0.0
        rolling_sum = sum(closes[:window])
        rolling_square_sum = sum(value * value for value in closes[:window])
        for end in range(window, len(closes) + 1):
            average = rolling_sum / window
            variance = max(rolling_square_sum / window - average * average, 0.0)
            deviation = math.sqrt(variance)
            value = (closes[end - 1] - average) / deviation if deviation else 0.0
            if value < -entry:
                active = True
            elif value > exit_level:
                active = False
            if end < len(closes):
                outgoing = closes[end - window]
                incoming = closes[end]
                rolling_sum += incoming - outgoing
                rolling_square_sum += incoming * incoming - outgoing * outgoing
        return 1.0 if active else 0.0


class BreakoutStrategy(Strategy):
    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        closes = self._closes(available_history)
        prior_high = highest(closes, int(self.spec.parameters["lookback"]), exclude_current=True)
        if prior_high is None:
            return 0.0
        return 1.0 if closes[-1] > prior_high else 0.0


STRATEGY_TYPES: dict[str, type[Strategy]] = {
    "moving_average_crossover": MovingAverageCrossover,
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
}


def strategy_from_spec(spec: StrategySpec) -> Strategy:
    strategy_type = str(spec.parameters.get("strategy_type", ""))
    try:
        return STRATEGY_TYPES[strategy_type](spec)
    except KeyError as exc:
        raise ValueError(f"unknown reference strategy type: {strategy_type}") from exc


def reference_strategies(symbol: str = "SYNTH_EQ") -> tuple[Strategy, ...]:
    common = {
        "asset_class": AssetClass.EQUITY,
        "permitted_assets": (symbol,),
        "timeframe": "1d",
        "position_sizing_method": "fractional_equity",
    }
    specs = (
        StrategySpec(
            strategy_id="ma-crossover",
            version=1,
            name="Moving Average Crossover",
            description="Long when the fast moving average exceeds the slow moving average.",
            indicators=(
                IndicatorSpec(name="simple_moving_average", parameters={"window": 20}),
                IndicatorSpec(name="simple_moving_average", parameters={"window": 60}),
            ),
            entry_conditions=("20-day average > 60-day average",),
            exit_conditions=("20-day average <= 60-day average",),
            parameters={
                "strategy_type": "moving_average_crossover",
                "fast_window": 20,
                "slow_window": 60,
            },
            **common,
        ),
        StrategySpec(
            strategy_id="momentum",
            version=1,
            name="Momentum",
            description="Long when trailing return exceeds a fixed threshold.",
            indicators=(IndicatorSpec(name="momentum", parameters={"lookback": 40}),),
            entry_conditions=("40-day momentum > 2%",),
            exit_conditions=("40-day momentum <= 2%",),
            parameters={"strategy_type": "momentum", "lookback": 40, "threshold": 0.02},
            **common,
        ),
        StrategySpec(
            strategy_id="mean-reversion",
            version=1,
            name="Mean Reversion",
            description="Long after a negative z-score excursion; exit on mean recovery.",
            indicators=(IndicatorSpec(name="zscore", parameters={"window": 20}),),
            entry_conditions=("20-day z-score < -1.25",),
            exit_conditions=("20-day z-score > 0",),
            parameters={
                "strategy_type": "mean_reversion",
                "window": 20,
                "entry_z": 1.25,
                "exit_z": 0.0,
            },
            **common,
        ),
        StrategySpec(
            strategy_id="breakout",
            version=1,
            name="Breakout",
            description="Long on a close above the prior channel high.",
            indicators=(IndicatorSpec(name="highest_close", parameters={"lookback": 30}),),
            entry_conditions=("close > prior 30-day highest close",),
            exit_conditions=("close no longer exceeds prior channel high",),
            parameters={"strategy_type": "breakout", "lookback": 30},
            **common,
        ),
    )
    return tuple(strategy_from_spec(spec) for spec in specs)
