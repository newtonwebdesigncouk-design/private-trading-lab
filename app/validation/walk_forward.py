"""Rolling train/validate/test evaluation with separately stored results."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting import BacktestEngine, BacktestResult
from app.models.market import MarketBar
from app.strategies.base import Strategy


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_bars: int = Field(default=180, ge=2)
    validation_bars: int = Field(default=60, ge=2)
    test_bars: int = Field(default=60, ge=2)
    step_bars: int = Field(default=60, ge=1)


class WalkForwardFold(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold: int
    train: BacktestResult
    validation: BacktestResult
    test: BacktestResult


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_version: str
    folds: tuple[WalkForwardFold, ...]
    mean_test_return: float
    profitable_test_fraction: float


class WalkForwardValidator:
    def __init__(self, engine: BacktestEngine, config: WalkForwardConfig | None = None) -> None:
        self.engine = engine
        self.config = config or WalkForwardConfig()

    def validate(
        self, strategy: Strategy, bars: Sequence[MarketBar], *, dataset_id: str
    ) -> WalkForwardResult:
        window = self.config.train_bars + self.config.validation_bars + self.config.test_bars
        folds: list[WalkForwardFold] = []
        for fold, start in enumerate(range(0, len(bars) - window + 1, self.config.step_bars), 1):
            train_end = start + self.config.train_bars
            validation_end = train_end + self.config.validation_bars
            test_end = validation_end + self.config.test_bars
            train = self.engine.run(
                strategy, bars[start:train_end], dataset_id=f"{dataset_id}:fold-{fold}:train"
            )
            validation = self.engine.run(
                strategy,
                bars[train_end:validation_end],
                dataset_id=f"{dataset_id}:fold-{fold}:validation",
            )
            test = self.engine.run(
                strategy,
                bars[validation_end:test_end],
                dataset_id=f"{dataset_id}:fold-{fold}:test",
            )
            folds.append(WalkForwardFold(fold=fold, train=train, validation=validation, test=test))
        if not folds:
            raise ValueError("insufficient bars for one walk-forward window")
        test_returns = [fold.test.metrics.total_return for fold in folds]
        return WalkForwardResult(
            strategy_version=strategy.spec.version_key,
            folds=tuple(folds),
            mean_test_return=sum(test_returns) / len(test_returns),
            profitable_test_fraction=sum(value > 0 for value in test_returns) / len(test_returns),
        )
