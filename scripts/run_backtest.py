"""Run the fixed-seed Phase 1 reference-strategy laboratory report."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backtesting import BacktestConfig, BacktestEngine, CostAssumptions
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass, StrategyState
from app.scoring import score_strategy
from app.strategies.reference import reference_strategies
from app.validation.sensitivity import ParameterSensitivityAnalyzer
from app.validation.splits import chronological_split


def disposition(state: StrategyState) -> str:
    if state is StrategyState.PAPER_ELIGIBLE:
        return "PASSED FOR PAPER ELIGIBILITY"
    if state is StrategyState.REJECTED:
        return "FAILED"
    return "REQUIRES FURTHER VALIDATION"


def run() -> dict[str, Any]:
    seed = 1729
    dataset_id = "synthetic-v2:seed-1729:2018-2024"
    provider = SyntheticMarketDataProvider(seed=seed, cache_dir=Path("data/cache"))
    asset = next(
        asset for asset in provider.supported_assets() if asset.asset_class is AssetClass.EQUITY
    )
    bars = provider.historical_data(
        asset,
        datetime(2018, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, 23, 59, tzinfo=UTC),
    )
    config = BacktestConfig(
        starting_capital=100_000,
        position_fraction=0.20,
        costs=CostAssumptions(
            commission_bps=2.0,
            fixed_fee=0.25,
            minimum_commission=0.25,
            spread_bps=5.0,
            slippage_bps=3.0,
        ),
    )
    engine = BacktestEngine(config)
    sensitivity = ParameterSensitivityAnalyzer(engine)
    train_bars, validation_bars, test_bars = chronological_split(bars)
    neighbour_map: dict[str, dict[str, tuple[int | float, ...]]] = {
        "ma-crossover": {"fast_window": (18, 22)},
        "momentum": {"lookback": (35, 45)},
        "mean-reversion": {"window": (18, 22)},
        "breakout": {"lookback": (27, 33)},
    }
    rows: list[dict[str, Any]] = []
    for strategy in reference_strategies(asset.symbol):
        development_result = engine.run(strategy, train_bars, dataset_id=f"{dataset_id}:train")
        sensitivity_result = sensitivity.analyse(
            strategy.spec,
            validation_bars,
            neighbour_map[strategy.spec.strategy_id],
            dataset_id=f"{dataset_id}:validation-sensitivity",
        )
        result = engine.run(strategy, test_bars, dataset_id=f"{dataset_id}:out-of-sample-test")
        score = score_strategy(
            result,
            parameter_stability=sensitivity_result.stability,
            out_of_sample_validated=True,
        )
        rows.append(
            {
                "rank": 0,
                "strategy_version": strategy.spec.version_key,
                "name": strategy.spec.name,
                "score": score.score,
                "state": score.state.value,
                "disposition": disposition(score.state),
                "reasons": list(score.reasons),
                "metrics": result.metrics.model_dump(mode="json"),
                "benchmark": result.benchmark.model_dump(mode="json"),
                "costs": result.costs.model_dump(mode="json"),
                "parameter_stability": sensitivity_result.stability,
                "development_metrics": development_result.metrics.model_dump(mode="json"),
                "evaluation_scope": "chronological out-of-sample test split",
            }
        )
    rows.sort(key=lambda row: float(row["score"]), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return {
        "report_version": 1,
        "dataset_id": dataset_id,
        "random_seed": seed,
        "instrument": asset.model_dump(mode="json"),
        "bar_count": len(bars),
        "split_bar_counts": {
            "train": len(train_bars),
            "validation": len(validation_bars),
            "test": len(test_bars),
        },
        "execution_assumption": (
            "signals use closed bars; fills occur no earlier than next-bar open"
        ),
        "strategies": rows,
        "warning": "Reference strategies and synthetic results are not investment recommendations.",
    }


def main() -> None:
    report = run()
    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "backtest_report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("PRIVATE TRADING LAB - REPRODUCIBLE SYNTHETIC REPORT")
    dataset_line = (
        f"Dataset: {report['dataset_id']} | bars={report['bar_count']} | "
        f"seed={report['random_seed']}"
    )
    print(dataset_line)
    split = report["split_bar_counts"]
    print(
        f"Chronological split: train={split['train']} validation={split['validation']} "
        f"held-out test={split['test']}"
    )
    print("Ranked metrics below are from the held-out test split.")
    print("Costs are included in every result. Reference strategies are not recommendations.\n")
    for row in report["strategies"]:
        metrics = row["metrics"]
        benchmark = row["benchmark"]
        print(f"#{row['rank']} {row['name']} - {row['score']:.2f}/100 - {row['disposition']}")
        print(
            f"   return={metrics['total_return']:.2%}  sharpe={metrics['sharpe_ratio']:.2f}  "
            f"max_drawdown={metrics['maximum_drawdown']:.2%}  trades={metrics['number_of_trades']}"
        )
        print(
            f"   benchmark={benchmark['benchmark_return']:.2%}  "
            f"excess={benchmark['excess_return']:.2%}  fees={metrics['fees_paid']:.2f}  "
            f"slippage={metrics['slippage_cost']:.2f}"
        )
        print(
            f"   strategy_drawdown={metrics['maximum_drawdown']:.2%}  "
            f"benchmark_drawdown={benchmark['benchmark_drawdown']:.2%}  "
            f"parameter_stability={row['parameter_stability']:.0%}"
        )
        for reason in row["reasons"]:
            print(f"   - {reason}")
    print(f"\nMachine-readable report: {output.resolve()}")


if __name__ == "__main__":
    main()
