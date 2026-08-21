"""Nearby-parameter testing to flag narrow performance peaks."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting import BacktestEngine
from app.models.market import MarketBar
from app.models.strategy import StrategySpec
from app.strategies.reference import strategy_from_spec


class SensitivityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameter: str
    value: float | int
    total_return: float
    sharpe_ratio: float


class SensitivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_version: str
    points: tuple[SensitivityPoint, ...]
    stability: float = Field(ge=0, le=1)
    fragile: bool


class ParameterSensitivityAnalyzer:
    def __init__(self, engine: BacktestEngine) -> None:
        self.engine = engine

    def analyse(
        self,
        base: StrategySpec,
        bars: Sequence[MarketBar],
        neighbours: Mapping[str, Sequence[float | int]],
        *,
        dataset_id: str,
    ) -> SensitivityResult:
        base_result = self.engine.run(strategy_from_spec(base), bars, dataset_id=dataset_id)
        points: list[SensitivityPoint] = []
        stable = 0
        for parameter, values in neighbours.items():
            for value in values:
                parameters = dict(base.parameters)
                parameters[parameter] = value
                candidate = base.derive(
                    parameters=parameters,
                    reason=f"Sensitivity test: {parameter}={value}",
                    creation_method="parameter_sensitivity",
                )
                result = self.engine.run(
                    strategy_from_spec(candidate),
                    bars,
                    dataset_id=f"{dataset_id}:{parameter}={value}",
                )
                points.append(
                    SensitivityPoint(
                        parameter=parameter,
                        value=value,
                        total_return=result.metrics.total_return,
                        sharpe_ratio=result.metrics.sharpe_ratio,
                    )
                )
                same_direction = (result.metrics.total_return >= 0) == (
                    base_result.metrics.total_return >= 0
                )
                return_gap = abs(result.metrics.total_return - base_result.metrics.total_return)
                if same_direction and return_gap <= 0.10:
                    stable += 1
        stability = stable / len(points) if points else 1.0
        return SensitivityResult(
            strategy_version=base.version_key,
            points=tuple(points),
            stability=stability,
            fragile=stability < 0.60,
        )
