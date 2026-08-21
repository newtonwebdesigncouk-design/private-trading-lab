"""Read model used by the local API and dashboard clients."""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backtesting import BacktestConfig, BacktestEngine
from app.backtesting.models import BacktestResult
from app.data.providers import StooqReadOnlyProvider, YahooReadOnlyProvider
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass, StrategyState, TradingMode
from app.scoring import StrategyScore, score_strategy
from app.strategies.reference import reference_strategies
from app.validation.regimes import classify_regimes


class LaboratoryService:
    def __init__(self) -> None:
        self.provider = SyntheticMarketDataProvider(seed=1729)
        self.asset = next(
            asset
            for asset in self.provider.supported_assets()
            if asset.asset_class is AssetClass.EQUITY
        )
        self.bars = self.provider.historical_data(
            self.asset,
            datetime(2022, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, 23, 59, tzinfo=UTC),
        )
        self.providers = (
            self.provider.provider_metadata(),
            YahooReadOnlyProvider().provider_metadata(),
            StooqReadOnlyProvider().provider_metadata(),
        )
        self.strategies = reference_strategies(self.asset.symbol)
        engine = BacktestEngine(BacktestConfig())
        self.results = tuple(
            engine.run(
                strategy,
                self.bars,
                dataset_id="synthetic-v2:seed-1729:2022-2024",
            )
            for strategy in self.strategies
        )
        self.scores: dict[str, StrategyScore] = {
            result.strategy.version_key: score_strategy(result) for result in self.results
        }
        self.phase2_demo_report = self._load_phase2_demo_report()
        self.phase3_replay_report = self._load_phase3_replay_report()

    @staticmethod
    def _load_phase2_demo_report() -> dict[str, Any] | None:
        report_path = Path(__file__).resolve().parents[2] / "reports" / "phase2_demo_report.json"
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _load_phase3_replay_report() -> dict[str, Any] | None:
        report_path = Path(__file__).resolve().parents[2] / "reports" / "phase3_replay_report.json"
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def phase3_forward_read_model(self, section: str) -> dict[str, object]:
        """Expose the committed replay demonstration without relabelling it as forward."""
        report = self.phase3_replay_report
        if report is None:
            return {
                "available": False,
                "provenance": "REPLAY",
                "reason": "The frozen Phase 3 replay report is not installed.",
            }
        value = report.get(section, {})
        payload = dict(value) if isinstance(value, dict) else {"items": value}
        return {
            "available": True,
            "provenance": "REPLAY",
            "genuine_forward_trials_started": report.get("genuine_forward_trials_started", 0),
            **payload,
        }

    def phase3_trial_detail(self, trial_id: str) -> dict[str, object] | None:
        report = self.phase3_replay_report
        if report is None:
            return None
        trials = report.get("trials", {})
        items = trials.get("items", []) if isinstance(trials, dict) else []
        return next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict) and item.get("trial_id") == trial_id
            ),
            None,
        )

    def active_dataset_id(self) -> str:
        if self.phase2_demo_report is not None:
            dataset = self.phase2_demo_report.get("dataset", {})
            dataset_id = dataset.get("dataset_id") if isinstance(dataset, dict) else None
            if isinstance(dataset_id, str):
                return dataset_id
        return "synthetic-v2:seed-1729:2022-2024"

    def phase2_demo_summary(self) -> dict[str, object]:
        """Return a compact, immutable read model of the frozen Phase 2 demonstration."""

        report = self.phase2_demo_report
        if report is None:
            return {
                "available": False,
                "reason": "The frozen Phase 2 demonstration report is not installed.",
            }
        dataset = report.get("dataset", {})
        portfolio = report.get("portfolio", {})
        research_batch = report.get("research_batch", {})
        rankings = report.get("reference_rankings", [])
        instruments = dataset.get("instruments", []) if isinstance(dataset, dict) else []
        compact_instruments = [
            {
                "asset": item.get("asset"),
                "rows": item.get("rows"),
                "actual_start": item.get("actual_start"),
                "actual_end": item.get("actual_end"),
                "diagnostics": item.get("diagnostics"),
            }
            for item in instruments
            if isinstance(item, dict)
        ]
        compact_rankings = [
            {
                key: item.get(key)
                for key in (
                    "strategy",
                    "strategy_version",
                    "instrument",
                    "asset_class",
                    "lifecycle_state",
                    "paper_qualified",
                    "score",
                    "decision_reasons",
                    "holdout",
                    "benchmark",
                )
            }
            for item in rankings
            if isinstance(item, dict)
        ]
        return {
            "available": True,
            "report_version": report.get("report_version"),
            "generated_at": report.get("generated_at"),
            "code_revision": report.get("code_revision"),
            "data_validation": report.get("data_validation"),
            "dataset": {
                "dataset_id": dataset.get("dataset_id") if isinstance(dataset, dict) else None,
                "provider": dataset.get("provider") if isinstance(dataset, dict) else None,
                "actual_start": dataset.get("actual_start") if isinstance(dataset, dict) else None,
                "actual_end": dataset.get("actual_end") if isinstance(dataset, dict) else None,
                "adjustment_policy": (
                    dataset.get("adjustment_policy") if isinstance(dataset, dict) else None
                ),
                "instruments": compact_instruments,
            },
            "portfolio": portfolio,
            "research_batch": {
                "batch_id": (
                    research_batch.get("batch_id") if isinstance(research_batch, dict) else None
                ),
                "candidate_count": (
                    research_batch.get("candidate_count") if isinstance(research_batch, dict) else 0
                ),
                "candidate_space_size": (
                    research_batch.get("candidate_space_size")
                    if isinstance(research_batch, dict)
                    else 0
                ),
                "candidate_decisions": (
                    research_batch.get("candidate_decisions", [])
                    if isinstance(research_batch, dict)
                    else []
                ),
                "selected_for_locked_holdout": (
                    research_batch.get("selected_for_locked_holdout", [])
                    if isinstance(research_batch, dict)
                    else []
                ),
                "multiple_testing": (
                    research_batch.get("multiple_testing", {})
                    if isinstance(research_batch, dict)
                    else {}
                ),
            },
            "reference_rankings": compact_rankings,
            "paper_qualified_strategies": report.get("paper_qualified_strategies", []),
            "safety": report.get("safety"),
            "threshold_policy": report.get("threshold_policy"),
            "universe": report.get("universe"),
            "disclaimer": report.get("disclaimer"),
        }

    def result_for(self, version_key: str) -> BacktestResult | None:
        return next(
            (result for result in self.results if result.strategy.version_key == version_key),
            None,
        )

    def run_reference_backtest(
        self,
        version_key: str,
        *,
        starting_capital: float,
    ) -> BacktestResult | None:
        strategy = next(
            (item for item in self.strategies if item.spec.version_key == version_key),
            None,
        )
        if strategy is None:
            return None
        return BacktestEngine(BacktestConfig(starting_capital=starting_capital)).run(
            strategy,
            self.bars,
            dataset_id="synthetic-v2:seed-1729:2022-2024",
        )

    def portfolio_summary(self) -> dict[str, object]:
        best = max(self.results, key=lambda result: self.scores[result.strategy.version_key].score)
        return {
            "mode": TradingMode.PAPER,
            "starting_capital": best.starting_capital,
            "current_simulated_equity": best.final_equity,
            "cash": best.equity_curve[-1].cash,
            "positions": int(best.equity_curve[-1].position_quantity > 0),
            "drawdown": best.metrics.maximum_drawdown,
            "performance": best.metrics.total_return,
            "note": "Demonstration simulation; no external order capability exists.",
        }

    def strategy_summary(self) -> dict[str, int]:
        states = Counter(score.state for score in self.scores.values())
        return {
            "total_strategies_created": len(self.results),
            **{state.value.lower(): states[state] for state in StrategyState},
        }

    def data_health(self) -> dict[str, object]:
        if self.phase2_demo_report is not None:
            dataset = self.phase2_demo_report.get("dataset", {})
            validation = self.phase2_demo_report.get("data_validation", {})
            instruments = dataset.get("instruments", []) if isinstance(dataset, dict) else []
            missing_data = {
                str(item.get("asset", {}).get("symbol", "unknown")): len(
                    item.get("diagnostics", {}).get("missing_expected_timestamps", [])
                )
                for item in instruments
                if isinstance(item, dict)
            }
            return {
                "providers": [provider.model_dump(mode="json") for provider in self.providers],
                "dataset_snapshots": [
                    {
                        "dataset_id": dataset.get("dataset_id"),
                        "provider": dataset.get("provider"),
                        "actual_start": dataset.get("actual_start"),
                        "actual_end": dataset.get("actual_end"),
                        "instrument_count": len(instruments),
                        "manifest_checksum": dataset.get("manifest_checksum"),
                    }
                ],
                "freshness": {"phase2_dataset": dataset.get("actual_end")},
                "validation_warnings": (
                    validation.get("warnings", []) if isinstance(validation, dict) else []
                ),
                "missing_data": missing_data,
                "note": "Frozen, content-addressed Phase 2 demonstration snapshot.",
            }
        return {
            "providers": [provider.model_dump(mode="json") for provider in self.providers],
            "dataset_snapshots": [],
            "freshness": {"demonstration_dataset": self.bars[-1].timestamp},
            "validation_warnings": [],
            "missing_data": {},
            "note": "Persistent manifests appear here when an owner snapshot store is configured.",
        }

    def research_batches(self) -> dict[str, object]:
        return {
            "items": [],
            "candidate_count": 0,
            "retained_count": 0,
            "rejected_count": 0,
            "multiple_testing_diagnostics": [],
            "holdout_locked": True,
        }

    def regime_summary(self) -> dict[str, object]:
        observations = classify_regimes(self.bars)
        return {
            "calculation_version": observations[0].calculation_version if observations else None,
            "items": [item.model_dump(mode="json") for item in observations[-20:]],
        }

    def portfolio_read_model(self) -> dict[str, object]:
        best = max(self.results, key=lambda result: self.scores[result.strategy.version_key].score)
        final = best.equity_curve[-1]
        return {
            "holdings": (
                [{"symbol": best.strategy.permitted_assets[0], "quantity": final.position_quantity}]
                if final.position_quantity
                else []
            ),
            "cash": final.cash,
            "equity_curve": [point.model_dump(mode="json") for point in best.equity_curve[-100:]],
            "drawdown": best.metrics.maximum_drawdown,
            "exposure": {"invested": best.metrics.exposure, "cash": 1 - best.metrics.exposure},
            "attribution": {"strategy": best.strategy.version_key},
            "benchmark_comparison": best.benchmark.model_dump(mode="json"),
        }

    def paper_read_model(self) -> dict[str, object]:
        return {
            "accounts": [],
            "last_cycle": None,
            "next_expected_cycle": None,
            "orders": [],
            "fills": [],
            "audit_events": [],
            "kill_switch_engaged": False,
            "external_order_transmission": False,
        }


service = LaboratoryService()
