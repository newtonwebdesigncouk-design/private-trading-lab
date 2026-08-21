"""Portfolio-of-strategies experiments restricted to already validated components."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.analytics import maximum_drawdown, periodic_returns, sharpe_ratio
from app.backtesting.models import BacktestResult
from app.models.enums import StrategyState


class ValidatedStrategyComponent(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_version: str
    lifecycle_state: StrategyState
    weight: float = Field(gt=0, le=0.50)


class StrategyPortfolioExperiment(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    components: tuple[ValidatedStrategyComponent, ...]

    @model_validator(mode="after")
    def require_validated_components(self) -> "StrategyPortfolioExperiment":
        allowed = {StrategyState.PAPER_ELIGIBLE, StrategyState.QUALIFIED}
        if any(component.lifecycle_state not in allowed for component in self.components):
            raise ValueError("every component must pass its independent validation gate")
        if sum(component.weight for component in self.components) > 1:
            raise ValueError("strategy portfolio weights cannot exceed one")
        return self


class StrategyPortfolioResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment: StrategyPortfolioExperiment
    total_return: float
    sharpe_ratio: float
    maximum_drawdown: float
    component_return_attribution: dict[str, float]


def combine_validated_strategies(
    experiment: StrategyPortfolioExperiment,
    results: Mapping[str, BacktestResult],
    *,
    annual_periods: int = 252,
) -> StrategyPortfolioResult:
    if any(component.strategy_version not in results for component in experiment.components):
        raise ValueError("a result is required for every validated strategy component")
    lengths = {
        len(results[component.strategy_version].equity_curve) for component in experiment.components
    }
    if len(lengths) != 1:
        raise ValueError("component equity curves must be aligned")
    count = lengths.pop()
    component_returns: dict[str, Sequence[float]] = {}
    attribution: dict[str, float] = {}
    for component in experiment.components:
        result = results[component.strategy_version]
        returns = periodic_returns([point.equity for point in result.equity_curve])
        component_returns[component.strategy_version] = returns
        attribution[component.strategy_version] = component.weight * result.metrics.total_return
    cash_weight = 1 - sum(component.weight for component in experiment.components)
    del cash_weight
    combined_returns = [
        sum(
            component.weight * component_returns[component.strategy_version][index]
            for component in experiment.components
        )
        for index in range(count - 1)
    ]
    values = [1.0]
    for value in combined_returns:
        values.append(values[-1] * (1 + value))
    return StrategyPortfolioResult(
        experiment=experiment,
        total_return=values[-1] - 1,
        sharpe_ratio=sharpe_ratio(combined_returns, annual_periods),
        maximum_drawdown=maximum_drawdown(values),
        component_return_attribution=attribution,
    )
