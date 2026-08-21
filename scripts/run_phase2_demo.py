"""Generate the complete Phase 2 report from one immutable genuine-data snapshot."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backtesting import BacktestConfig, BacktestEngine, CostAssumptions
from app.data.snapshots import DatasetSnapshotStore
from app.portfolio import PortfolioBacktestConfig, PortfolioBacktestEngine
from app.research import Phase2BatchResearchEngine
from app.scoring import score_strategy
from app.strategies.reference import reference_strategies, strategy_from_spec
from app.validation import (
    ParameterSensitivityAnalyzer,
    QualificationEvidence,
    WalkForwardConfig,
    WalkForwardValidator,
    analyse_by_regime,
    classify_regimes,
    evaluate_paper_qualification,
    evaluate_price_perturbation,
)
from app.validation.splits import chronological_split
from scripts.phase2_common import resolve_universe, strategy_for_asset


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _neighbours(strategy_type: str) -> dict[str, tuple[float | int, ...]]:
    catalogue: dict[str, dict[str, tuple[float | int, ...]]] = {
        "moving_average_crossover": {"fast_window": (15, 25)},
        "momentum": {"lookback": (30, 50)},
        "mean_reversion": {"entry_z": (1.0, 1.5)},
        "breakout": {"lookback": (20, 40)},
    }
    return catalogue[strategy_type]


def _cost_stress_config(base: BacktestConfig) -> BacktestConfig:
    costs = base.costs
    return base.model_copy(
        update={
            "costs": CostAssumptions(
                commission_bps=costs.commission_bps * 2,
                fixed_fee=costs.fixed_fee * 2,
                minimum_commission=costs.minimum_commission * 2,
                spread_bps=costs.spread_bps * 2,
                slippage_bps=costs.slippage_bps * 2,
            )
        }
    )


def build_report(
    dataset_id: str,
    universe_name: str,
    *,
    snapshot_root: Path,
    random_seed: int,
) -> dict[str, Any]:
    store = DatasetSnapshotStore(snapshot_root)
    manifest = store.load_manifest(dataset_id)
    warnings = store.validate(dataset_id)
    universe = resolve_universe(universe_name)
    bars = {
        item.asset.symbol: store.load_bars(dataset_id, item.asset.symbol)
        for item in manifest.instruments
    }
    base_config = BacktestConfig(position_fraction=0.20)
    engine = BacktestEngine(base_config)
    stressed_engine = BacktestEngine(_cost_stress_config(base_config))
    rankings: list[dict[str, Any]] = []

    for instrument in manifest.instruments:
        symbol = instrument.asset.symbol
        instrument_bars = bars[symbol]
        _train, validation, holdout = chronological_split(instrument_bars)
        for reference in reference_strategies(symbol):
            spec = reference.spec.model_copy(
                update={
                    "asset_class": instrument.asset.asset_class,
                    "permitted_assets": (symbol,),
                }
            )
            strategy = strategy_from_spec(spec)
            strategy_type = str(spec.parameters["strategy_type"])
            sensitivity = ParameterSensitivityAnalyzer(engine).analyse(
                spec,
                validation,
                _neighbours(strategy_type),
                dataset_id=f"{dataset_id}:{symbol}:{spec.version_key}:sensitivity",
            )
            holdout_result = engine.run(
                strategy,
                holdout,
                dataset_id=f"{dataset_id}:{symbol}:{spec.version_key}:locked-holdout",
            )
            stressed = stressed_engine.run(
                strategy,
                holdout,
                dataset_id=f"{dataset_id}:{symbol}:{spec.version_key}:cost-stress",
            )
            walk_forward = WalkForwardValidator(
                engine,
                WalkForwardConfig(
                    train_bars=300,
                    validation_bars=100,
                    test_bars=100,
                    step_bars=100,
                ),
            ).validate(
                strategy,
                instrument_bars,
                dataset_id=f"{dataset_id}:{symbol}:{spec.version_key}:walk-forward",
            )
            perturbation = evaluate_price_perturbation(
                strategy,
                validation,
                engine,
                dataset_id=f"{dataset_id}:{symbol}:{spec.version_key}:perturbation",
                random_seed=random_seed,
            )
            score = score_strategy(
                holdout_result,
                parameter_stability=sensitivity.stability,
                out_of_sample_validated=True,
            )
            normal_return = holdout_result.metrics.total_return
            cost_ratio = (
                stressed.metrics.total_return / normal_return
                if normal_return > 0
                else (1.0 if stressed.metrics.total_return >= 0 else 0.0)
            )
            warnings_for_candidate = (
                () if perturbation.robust else ("failed deterministic price perturbation",)
            )
            qualification = evaluate_paper_qualification(
                QualificationEvidence(
                    score=score.score,
                    out_of_sample_bars=len(holdout),
                    trades=holdout_result.metrics.number_of_trades,
                    maximum_drawdown=holdout_result.metrics.maximum_drawdown,
                    cost_stress_ratio=max(min(cost_ratio, 1.0), 0.0),
                    parameter_stability=sensitivity.stability,
                    profitable_walk_forward_fraction=walk_forward.profitable_test_fraction,
                    benchmark_excess_return=holdout_result.benchmark.excess_return,
                    final_holdout_isolated=True,
                    critical_warnings=warnings_for_candidate,
                )
            )
            regimes = classify_regimes(holdout, lookback=20)
            rankings.append(
                {
                    "instrument": symbol,
                    "asset_class": instrument.asset.asset_class.value,
                    "strategy": spec.name,
                    "strategy_version": spec.version_key,
                    "score": score.score,
                    "lifecycle_state": score.state.value,
                    "paper_qualified": qualification.qualified,
                    "decision_reasons": qualification.reasons,
                    "holdout": {
                        "start": holdout[0].timestamp.isoformat(),
                        "end": holdout[-1].timestamp.isoformat(),
                        "bars": len(holdout),
                        "return": holdout_result.metrics.total_return,
                        "annualised_return": holdout_result.metrics.annualised_return,
                        "sharpe": holdout_result.metrics.sharpe_ratio,
                        "sortino": holdout_result.metrics.sortino_ratio,
                        "maximum_drawdown": holdout_result.metrics.maximum_drawdown,
                        "trades": holdout_result.metrics.number_of_trades,
                        "fees": holdout_result.metrics.fees_paid,
                        "slippage": holdout_result.metrics.slippage_cost,
                    },
                    "benchmark": holdout_result.benchmark.model_dump(mode="json"),
                    "validation": {
                        "parameter_stability": sensitivity.stability,
                        "walk_forward_profitable_fraction": (walk_forward.profitable_test_fraction),
                        "walk_forward_mean_test_return": walk_forward.mean_test_return,
                        "cost_stress_return": stressed.metrics.total_return,
                        "cost_stress_ratio": cost_ratio,
                        "perturbation": perturbation.model_dump(mode="json"),
                        "regime_performance": [
                            item.model_dump(mode="json")
                            for item in analyse_by_regime(holdout_result, regimes)
                        ],
                    },
                }
            )

    rankings.sort(key=lambda item: (-float(item["score"]), str(item["instrument"])))
    parent = strategy_for_asset(manifest.instruments[0].asset).spec.model_copy(
        update={"permitted_assets": tuple(item.asset.symbol for item in manifest.instruments)}
    )
    batch_engine = Phase2BatchResearchEngine(maximum_candidates=100)
    research_batch = batch_engine.run_selection(
        parent,
        {"fast_window": (10, 15, 20, 25), "slow_window": (40, 60, 80)},
        bars,
        dataset_id=dataset_id,
        universe_version=universe.version_key,
        random_seed=random_seed,
        backtest_config=base_config,
        retention_score=70,
        minimum_validation_trades=10,
        false_discovery_rate=0.05,
    )
    locked_holdout = batch_engine.evaluate_selected_holdout(
        research_batch, bars, backtest_config=base_config
    )
    strategies = {
        item.asset.symbol: strategy_for_asset(item.asset) for item in manifest.instruments
    }
    portfolio = PortfolioBacktestEngine(PortfolioBacktestConfig(starting_capital=100_000)).run(
        strategies,
        bars,
        dataset_id=dataset_id,
        universe=universe,
        adjustment_policy=manifest.adjustment_policy,
    )
    qualified = [
        f"{item['instrument']}:{item['strategy_version']}"
        for item in rankings
        if item["paper_qualified"]
    ]
    return {
        "report_version": "phase2-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_revision": _revision(),
        "safety": {
            "modes": ["BACKTEST", "PAPER"],
            "external_order_transmission": False,
            "live_money_trading": False,
        },
        "dataset": manifest.public_metadata(),
        "data_validation": {"valid": True, "warnings": warnings},
        "universe": universe.model_dump(mode="json"),
        "chronology": {
            "train_fraction": 0.60,
            "validation_fraction": 0.20,
            "final_holdout_fraction": 0.20,
            "candidate_selection_uses_final_holdout": False,
        },
        "reference_rankings": rankings,
        "research_batch": {
            "batch_id": research_batch.batch_id,
            "candidate_space_size": research_batch.candidate_space_size,
            "candidate_count": research_batch.candidate_count,
            "selected_for_locked_holdout": research_batch.selected_candidate_versions,
            "multiple_testing": research_batch.multiple_testing.model_dump(mode="json"),
            "candidate_decisions": [
                {
                    "candidate": item.candidate.version_key,
                    "selected": item.selected_for_holdout,
                    "score": item.mean_validation_score,
                    "reasons": item.reasons,
                }
                for item in research_batch.evaluations
            ],
            "locked_holdout_results": [item.model_dump(mode="json") for item in locked_holdout],
        },
        "portfolio": {
            "metrics": portfolio.metrics.model_dump(mode="json"),
            "benchmarks": [item.model_dump(mode="json") for item in portfolio.benchmarks],
            "strategy_attribution": [
                item.model_dump(mode="json") for item in portfolio.strategy_attribution
            ],
            "asset_attribution": [
                item.model_dump(mode="json") for item in portfolio.asset_attribution
            ],
            "asset_class_attribution": [
                item.model_dump(mode="json") for item in portfolio.asset_class_attribution
            ],
            "minimum_cash": min(point.cash for point in portfolio.equity_curve),
            "maximum_invested_weight": max(
                sum(point.position_weights.values()) for point in portfolio.equity_curve
            ),
        },
        "paper_qualified_strategies": qualified,
        "threshold_policy": (
            "Qualification thresholds were fixed before evaluation and not lowered."
        ),
        "disclaimer": (
            "Historical research and paper simulation do not guarantee future profitability."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--universe", default="phase2-demo-v1")
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--output", type=Path, default=Path("reports/phase2_demo_report.json"))
    arguments = parser.parse_args()
    report = build_report(
        arguments.dataset,
        arguments.universe,
        snapshot_root=arguments.snapshot_root,
        random_seed=arguments.seed,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(arguments.output),
                "dataset": arguments.dataset,
                "reference_evaluations": len(report["reference_rankings"]),
                "research_candidates": report["research_batch"]["candidate_count"],
                "paper_qualified": report["paper_qualified_strategies"],
                "portfolio_return": report["portfolio"]["metrics"]["total_return"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
