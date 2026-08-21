"""Transactional persistence for immutable trials and idempotent forward PAPER cycles."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.tables import (
    ForwardAuditEventRow,
    ForwardBenchmarkSnapshotRow,
    ForwardCycleLeaseRow,
    ForwardCycleRow,
    ForwardDataQualityEventRow,
    ForwardDegradationEventRow,
    ForwardEvidenceManifestRow,
    ForwardFillRow,
    ForwardLifecycleDecisionRow,
    ForwardObservationRow,
    ForwardOrderRow,
    ForwardPortfolioRow,
    ForwardPortfolioSnapshotRow,
    ForwardSignalRow,
    ForwardTrialRow,
)
from app.forward.models import (
    ForwardCycleResult,
    ForwardDataQualityEvent,
    ForwardEvidenceManifest,
    ForwardFill,
    ForwardLifecycleDecision,
    ForwardObservation,
    ForwardPerformance,
    ForwardPortfolioSnapshot,
    ForwardPortfolioState,
    ForwardSignal,
    ForwardTrial,
    ForwardTrialManifest,
    canonical_hash,
)
from app.models.enums import (
    ForwardCycleStatus,
    ForwardTrialState,
    ObservationProvenance,
    OrderStatus,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ForwardRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_trial(self, manifest: ForwardTrialManifest) -> ForwardTrial:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            if session.get(ForwardTrialRow, manifest.trial_id) is not None:
                raise ValueError("forward trial manifest is immutable and already exists")
            session.add(
                ForwardTrialRow(
                    trial_id=manifest.trial_id,
                    portfolio_id=manifest.portfolio_id,
                    strategy_version=manifest.strategy.version_key,
                    configuration_fingerprint=manifest.configuration_fingerprint,
                    provenance=manifest.provenance.value,
                    state=ForwardTrialState.READY_FOR_FORWARD.value,
                    manifest=manifest.model_dump(mode="json"),
                    failed_evaluations=0,
                    started_at=manifest.start_timestamp,
                    latest_observation_at=None,
                    created_at=manifest.created_at,
                    updated_at=now,
                )
            )
        return self.get_trial(manifest.trial_id)

    @staticmethod
    def _trial_from_row(row: ForwardTrialRow) -> ForwardTrial:
        manifest = ForwardTrialManifest.model_validate(row.manifest)
        if manifest.configuration_fingerprint != row.configuration_fingerprint:
            raise ValueError("persisted forward trial fingerprint mismatch")
        if manifest.provenance.value != row.provenance:
            raise ValueError("persisted forward trial provenance mismatch")
        return ForwardTrial(
            manifest=manifest,
            state=ForwardTrialState(row.state),
            started_at=_aware(row.started_at),
            updated_at=_aware(row.updated_at),
            failed_evaluations=row.failed_evaluations,
            latest_observation_at=(
                _aware(row.latest_observation_at) if row.latest_observation_at else None
            ),
        )

    def get_trial(self, trial_id: str) -> ForwardTrial:
        with self._sessions() as session:
            row = session.get(ForwardTrialRow, trial_id)
            if row is None:
                raise KeyError(f"forward trial not found: {trial_id}")
            return self._trial_from_row(row)

    def list_trials(
        self,
        *,
        provenance: ObservationProvenance | None = None,
        states: Sequence[ForwardTrialState] | None = None,
        portfolio_id: str | None = None,
    ) -> tuple[ForwardTrial, ...]:
        with self._sessions() as session:
            statement = select(ForwardTrialRow)
            if provenance is not None:
                statement = statement.where(ForwardTrialRow.provenance == provenance.value)
            if states:
                statement = statement.where(
                    ForwardTrialRow.state.in_([item.value for item in states])
                )
            if portfolio_id is not None:
                statement = statement.where(ForwardTrialRow.portfolio_id == portfolio_id)
            rows = session.scalars(statement.order_by(ForwardTrialRow.trial_id)).all()
            return tuple(self._trial_from_row(row) for row in rows)

    def save_evidence_manifest(self, manifest: ForwardEvidenceManifest) -> None:
        with self._sessions.begin() as session:
            existing = session.get(ForwardEvidenceManifestRow, manifest.manifest_id)
            if existing is not None:
                if existing.manifest != manifest.model_dump(mode="json"):
                    raise ValueError("forward evidence manifest identity collision")
                return
            session.add(
                ForwardEvidenceManifestRow(
                    manifest_id=manifest.manifest_id,
                    stream_id=manifest.stream_id,
                    sequence=manifest.sequence,
                    provenance=manifest.provenance.value,
                    manifest=manifest.model_dump(mode="json"),
                    created_at=manifest.fetched_at,
                )
            )

    def acquire_lease(
        self,
        lease_key: str,
        owner: str,
        *,
        now: datetime,
        ttl: timedelta,
        cycle_id: str | None = None,
    ) -> bool:
        if ttl <= timedelta(0):
            raise ValueError("forward cycle lease TTL must be positive")
        with self._sessions.begin() as session:
            row = session.get(ForwardCycleLeaseRow, lease_key)
            if row is not None:
                expires = _aware(row.expires_at) if row.expires_at else None
                if row.owner not in {None, owner} and expires is not None and expires > now:
                    return False
                row.owner = owner
                row.acquired_at = now
                row.expires_at = now + ttl
                row.cycle_id = cycle_id
            else:
                session.add(
                    ForwardCycleLeaseRow(
                        lease_key=lease_key,
                        owner=owner,
                        acquired_at=now,
                        expires_at=now + ttl,
                        cycle_id=cycle_id,
                    )
                )
        return True

    def release_lease(self, lease_key: str, owner: str, *, now: datetime) -> None:
        with self._sessions.begin() as session:
            row = session.get(ForwardCycleLeaseRow, lease_key)
            if row is None or row.owner != owner:
                return
            row.owner = None
            row.expires_at = now
            row.cycle_id = None

    def lease_status(self, lease_key: str) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(ForwardCycleLeaseRow, lease_key)
            if row is None:
                return None
            return {
                "lease_key": row.lease_key,
                "owner": row.owner,
                "acquired_at": _aware(row.acquired_at) if row.acquired_at else None,
                "expires_at": _aware(row.expires_at) if row.expires_at else None,
                "cycle_id": row.cycle_id,
            }

    def begin_cycle(
        self,
        *,
        cycle_id: str,
        portfolio_id: str,
        evidence_manifest_id: str,
        provenance: ObservationProvenance,
        market_timestamp: datetime,
        lease_owner: str,
    ) -> bool:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(ForwardCycleRow, cycle_id)
            if row is not None:
                if row.status in {
                    ForwardCycleStatus.COMPLETED.value,
                    ForwardCycleStatus.BLOCKED.value,
                }:
                    return False
                row.status = ForwardCycleStatus.IN_PROGRESS.value
                row.retry_count += 1
                row.error = None
                row.lease_owner = lease_owner
                row.started_at = now
                return True
            session.add(
                ForwardCycleRow(
                    cycle_id=cycle_id,
                    portfolio_id=portfolio_id,
                    evidence_manifest_id=evidence_manifest_id,
                    provenance=provenance.value,
                    market_timestamp=market_timestamp,
                    status=ForwardCycleStatus.IN_PROGRESS.value,
                    lease_owner=lease_owner,
                    retry_count=0,
                    payload={},
                    started_at=now,
                )
            )
        return True

    def ensure_portfolio(
        self,
        state: ForwardPortfolioState,
        manifests: Sequence[ForwardTrialManifest],
    ) -> ForwardPortfolioState:
        fingerprint = canonical_hash(sorted(item.configuration_fingerprint for item in manifests))
        provenances = {item.provenance for item in manifests}
        if len(provenances) != 1:
            raise ValueError("replay and genuine trials cannot share a portfolio")
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.get(ForwardPortfolioRow, state.portfolio_id)
            if row is None:
                session.add(
                    ForwardPortfolioRow(
                        portfolio_id=state.portfolio_id,
                        policy_fingerprint=fingerprint,
                        provenance=next(iter(provenances)).value,
                        state=state.model_dump(mode="json"),
                        created_at=now,
                        updated_at=now,
                    )
                )
                return state
            if row.policy_fingerprint != fingerprint:
                raise ValueError("material portfolio/trial change requires a new portfolio ID")
            if row.provenance != next(iter(provenances)).value:
                raise ValueError("portfolio provenance cannot be changed")
            return ForwardPortfolioState.model_validate(row.state)

    def load_portfolio(self, portfolio_id: str) -> ForwardPortfolioState:
        with self._sessions() as session:
            row = session.get(ForwardPortfolioRow, portfolio_id)
            if row is None:
                raise KeyError(f"forward portfolio not found: {portfolio_id}")
            return ForwardPortfolioState.model_validate(row.state)

    def observations(self, trial_id: str) -> tuple[ForwardObservation, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardObservationRow)
                .where(ForwardObservationRow.trial_id == trial_id)
                .order_by(ForwardObservationRow.timestamp, ForwardObservationRow.observation_id)
            ).all()
            return tuple(ForwardObservation.model_validate(row.payload) for row in rows)

    def signals(self, trial_id: str) -> tuple[ForwardSignal, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardSignalRow)
                .where(ForwardSignalRow.trial_id == trial_id)
                .order_by(ForwardSignalRow.timestamp, ForwardSignalRow.signal_id)
            ).all()
            return tuple(ForwardSignal.model_validate(row.payload) for row in rows)

    def fills(self, trial_id: str) -> tuple[ForwardFill, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardFillRow)
                .where(ForwardFillRow.trial_id == trial_id)
                .order_by(ForwardFillRow.filled_at, ForwardFillRow.fill_id)
            ).all()
            return tuple(ForwardFill.model_validate(row.payload) for row in rows)

    def portfolio_snapshots(self, portfolio_id: str) -> tuple[ForwardPortfolioSnapshot, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardPortfolioSnapshotRow)
                .where(ForwardPortfolioSnapshotRow.portfolio_id == portfolio_id)
                .order_by(
                    ForwardPortfolioSnapshotRow.timestamp,
                    ForwardPortfolioSnapshotRow.snapshot_id,
                )
            ).all()
            return tuple(ForwardPortfolioSnapshot.model_validate(row.payload) for row in rows)

    def performances(self, trial_id: str) -> tuple[ForwardPerformance, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardBenchmarkSnapshotRow)
                .where(ForwardBenchmarkSnapshotRow.trial_id == trial_id)
                .order_by(
                    ForwardBenchmarkSnapshotRow.timestamp,
                    ForwardBenchmarkSnapshotRow.snapshot_id,
                )
            ).all()
            return tuple(ForwardPerformance.model_validate(row.performance) for row in rows)

    def unresolved_data_quality_count(self, trial_id: str) -> int:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardDataQualityEventRow).where(
                    ForwardDataQualityEventRow.trial_id == trial_id,
                    ForwardDataQualityEventRow.resolved.is_(False),
                )
            ).all()
            return len(rows)

    def complete_cycle(
        self,
        result: ForwardCycleResult,
        state: ForwardPortfolioState,
        performance: Mapping[str, ForwardPerformance],
    ) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            cycle = session.get(ForwardCycleRow, result.cycle_id)
            portfolio = session.get(ForwardPortfolioRow, result.portfolio_id)
            if cycle is None or portfolio is None:
                raise RuntimeError("forward cycle or portfolio persistence state is missing")
            if cycle.status != ForwardCycleStatus.IN_PROGRESS.value:
                raise RuntimeError("forward cycle is not in progress")
            evidence = session.get(ForwardEvidenceManifestRow, result.evidence_manifest_id)
            if evidence is None:
                raise RuntimeError("forward evidence manifest was not persisted")
            if evidence.provenance != result.provenance.value:
                raise ValueError("cycle/evidence provenance mismatch")

            for observation in result.observations:
                trial_row = session.get(ForwardTrialRow, observation.trial_id)
                if trial_row is None:
                    raise RuntimeError("forward observation trial is missing")
                manifest = ForwardTrialManifest.model_validate(trial_row.manifest)
                if observation.provenance is not manifest.provenance:
                    raise ValueError("replay and genuine forward observations cannot mix")
                if observation.bar.timestamp < manifest.start_timestamp:
                    raise ValueError("pre-start bar cannot be persisted as forward evidence")
                existing = session.get(ForwardObservationRow, observation.observation_id)
                if existing is None:
                    session.add(
                        ForwardObservationRow(
                            observation_id=observation.observation_id,
                            trial_id=observation.trial_id,
                            cycle_id=observation.cycle_id,
                            evidence_manifest_id=observation.evidence_manifest_id,
                            provenance=observation.provenance.value,
                            symbol=observation.bar.asset.symbol,
                            timestamp=observation.bar.timestamp,
                            payload=observation.model_dump(mode="json"),
                        )
                    )
                latest = trial_row.latest_observation_at
                if latest is None or observation.bar.timestamp > _aware(latest):
                    trial_row.latest_observation_at = observation.bar.timestamp

            for signal in result.signals:
                if session.get(ForwardSignalRow, signal.signal_id) is None:
                    session.add(
                        ForwardSignalRow(
                            signal_id=signal.signal_id,
                            trial_id=signal.trial_id,
                            cycle_id=signal.cycle_id,
                            timestamp=signal.timestamp,
                            payload=signal.model_dump(mode="json"),
                        )
                    )
            for wrapped in result.orders:
                order = wrapped.order
                if session.get(ForwardOrderRow, order.order_id) is None:
                    session.add(
                        ForwardOrderRow(
                            order_id=order.order_id,
                            trial_id=wrapped.trial_id,
                            cycle_id=result.cycle_id,
                            status=OrderStatus.PENDING.value,
                            payload=wrapped.model_dump(mode="json"),
                            created_at=order.decision_timestamp,
                        )
                    )
            for fill_wrapper in result.fills:
                fill = fill_wrapper.fill
                fill_id = (
                    "forward-fill-" + canonical_hash(fill_wrapper.model_dump(mode="json"))[:24]
                )
                if session.get(ForwardFillRow, fill_id) is None:
                    session.add(
                        ForwardFillRow(
                            fill_id=fill_id,
                            order_id=fill.order_id,
                            trial_id=fill_wrapper.trial_id,
                            cycle_id=result.cycle_id,
                            payload=fill_wrapper.model_dump(mode="json"),
                            filled_at=fill.timestamp,
                        )
                    )
                order_row = session.get(ForwardOrderRow, fill.order_id)
                if order_row is not None:
                    order_row.status = OrderStatus.FILLED.value

            if result.snapshot is not None:
                snapshot_id = (
                    "forward-portfolio-snapshot-"
                    + canonical_hash(result.snapshot.model_dump(mode="json"))[:24]
                )
                if session.get(ForwardPortfolioSnapshotRow, snapshot_id) is None:
                    session.add(
                        ForwardPortfolioSnapshotRow(
                            snapshot_id=snapshot_id,
                            portfolio_id=result.portfolio_id,
                            cycle_id=result.cycle_id,
                            provenance=result.provenance.value,
                            timestamp=result.snapshot.timestamp,
                            payload=result.snapshot.model_dump(mode="json"),
                        )
                    )
            for trial_id, item in performance.items():
                snapshot_id = f"forward-benchmark-{result.cycle_id}-{trial_id}"
                if session.get(ForwardBenchmarkSnapshotRow, snapshot_id) is None:
                    session.add(
                        ForwardBenchmarkSnapshotRow(
                            snapshot_id=snapshot_id,
                            trial_id=trial_id,
                            cycle_id=result.cycle_id,
                            timestamp=result.timestamp,
                            performance=item.model_dump(mode="json"),
                        )
                    )
            for diagnostic in result.degradation:
                event_id = f"forward-degradation-{result.cycle_id}-{diagnostic.trial_id}"
                if session.get(ForwardDegradationEventRow, event_id) is None:
                    session.add(
                        ForwardDegradationEventRow(
                            event_id=event_id,
                            trial_id=diagnostic.trial_id,
                            cycle_id=result.cycle_id,
                            timestamp=diagnostic.timestamp,
                            severity=diagnostic.severity.value,
                            payload=diagnostic.model_dump(mode="json"),
                        )
                    )
            for event in result.data_quality:
                self._add_data_quality(session, event)
            observed_trials = {item.trial_id for item in result.observations}
            for trial_id in observed_trials:
                unresolved = session.scalars(
                    select(ForwardDataQualityEventRow).where(
                        ForwardDataQualityEventRow.trial_id == trial_id,
                        ForwardDataQualityEventRow.resolved.is_(False),
                    )
                ).all()
                for row in unresolved:
                    row.resolved = True
                    event = ForwardDataQualityEvent.model_validate(row.payload)
                    row.payload = event.model_copy(update={"resolved": True}).model_dump(
                        mode="json"
                    )
                if unresolved:
                    resolution_id = f"forward-audit-data-resolved-{result.cycle_id}-{trial_id}"
                    if session.get(ForwardAuditEventRow, resolution_id) is None:
                        session.add(
                            ForwardAuditEventRow(
                                event_id=resolution_id,
                                cycle_id=result.cycle_id,
                                trial_id=trial_id,
                                event_type="FORWARD_DATA_QUALITY_RESOLVED",
                                occurred_at=result.timestamp,
                                payload={"resolved_events": len(unresolved)},
                            )
                        )
            for decision in result.lifecycle_decisions:
                self._add_lifecycle_decision(session, decision)
            for trial_id, reasons in result.risk_rejections.items():
                event_id = (
                    "forward-audit-"
                    + canonical_hash(
                        {"cycle": result.cycle_id, "trial": trial_id, "reasons": reasons}
                    )[:24]
                )
                if session.get(ForwardAuditEventRow, event_id) is None:
                    session.add(
                        ForwardAuditEventRow(
                            event_id=event_id,
                            cycle_id=result.cycle_id,
                            trial_id=trial_id,
                            event_type="FORWARD_RISK_REJECTION",
                            occurred_at=result.timestamp,
                            payload={"reasons": list(reasons)},
                        )
                    )
            completion_id = f"forward-audit-complete-{result.cycle_id}"
            if session.get(ForwardAuditEventRow, completion_id) is None:
                session.add(
                    ForwardAuditEventRow(
                        event_id=completion_id,
                        cycle_id=result.cycle_id,
                        trial_id=None,
                        event_type="FORWARD_CYCLE_COMPLETED",
                        occurred_at=result.timestamp,
                        payload={
                            "provenance": result.provenance.value,
                            "observations": len(result.observations),
                            "orders": len(result.orders),
                            "fills": len(result.fills),
                            "external_order_transmission": False,
                        },
                    )
                )
            portfolio.state = state.model_dump(mode="json")
            portfolio.updated_at = now
            cycle.status = result.status.value
            cycle.payload = {
                "observations": len(result.observations),
                "signals": len(result.signals),
                "orders": len(result.orders),
                "fills": len(result.fills),
                "equity": result.snapshot.equity if result.snapshot else None,
            }
            cycle.completed_at = now

    @staticmethod
    def _add_lifecycle_decision(session: Session, decision: ForwardLifecycleDecision) -> None:
        if session.get(ForwardLifecycleDecisionRow, decision.decision_id) is None:
            session.add(
                ForwardLifecycleDecisionRow(
                    decision_id=decision.decision_id,
                    trial_id=decision.trial_id,
                    cycle_id=decision.cycle_id,
                    previous_state=decision.previous_state.value,
                    new_state=decision.new_state.value,
                    rule_id=decision.rule_id,
                    timestamp=decision.timestamp,
                    payload=decision.model_dump(mode="json"),
                )
            )
        row = session.get(ForwardTrialRow, decision.trial_id)
        if row is None:
            raise RuntimeError("lifecycle trial is missing")
        row.state = decision.new_state.value
        if decision.new_state is ForwardTrialState.FAILED_FORWARD:
            row.failed_evaluations = row.failed_evaluations + 1
        elif decision.new_state is not ForwardTrialState.RETIRED:
            row.failed_evaluations = 0
        row.updated_at = decision.timestamp

    @staticmethod
    def _add_data_quality(session: Session, event: ForwardDataQualityEvent) -> None:
        if session.get(ForwardDataQualityEventRow, event.event_id) is None:
            session.add(
                ForwardDataQualityEventRow(
                    event_id=event.event_id,
                    cycle_id=event.cycle_id,
                    trial_id=event.trial_id,
                    timestamp=event.timestamp,
                    severity=event.severity,
                    resolved=event.resolved,
                    payload=event.model_dump(mode="json"),
                )
            )

    def fail_cycle(self, cycle_id: str, error: str) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            cycle = session.get(ForwardCycleRow, cycle_id)
            if cycle is None:
                raise RuntimeError("forward cycle persistence state is missing")
            cycle.status = ForwardCycleStatus.FAILED.value
            cycle.error = error
            cycle.completed_at = now
            event_id = f"forward-audit-failed-{cycle_id}-{cycle.retry_count}"
            if session.get(ForwardAuditEventRow, event_id) is None:
                session.add(
                    ForwardAuditEventRow(
                        event_id=event_id,
                        cycle_id=cycle_id,
                        trial_id=None,
                        event_type="FORWARD_CYCLE_FAILED",
                        occurred_at=now,
                        payload={"error": error},
                    )
                )

    def record_data_quality_block(
        self,
        *,
        portfolio_id: str,
        trials: Sequence[ForwardTrial],
        provenance: ObservationProvenance,
        timestamp: datetime,
        lease_owner: str,
        detail: str,
    ) -> ForwardCycleResult:
        identity = {
            "portfolio_id": portfolio_id,
            "trials": sorted(item.manifest.trial_id for item in trials),
            "provenance": provenance.value,
            "timestamp": timestamp.isoformat(),
            "detail": detail,
        }
        cycle_id = f"forward-cycle-blocked-{canonical_hash(identity)[:24]}"
        events: list[ForwardDataQualityEvent] = []
        decisions: list[ForwardLifecycleDecision] = []
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            existing = session.get(ForwardCycleRow, cycle_id)
            if existing is not None:
                return ForwardCycleResult(
                    cycle_id=cycle_id,
                    portfolio_id=portfolio_id,
                    evidence_manifest_id="NO_SAFE_EVIDENCE",
                    provenance=provenance,
                    status=ForwardCycleStatus.DUPLICATE,
                    processed=False,
                    timestamp=timestamp,
                    error=detail,
                )
            session.add(
                ForwardCycleRow(
                    cycle_id=cycle_id,
                    portfolio_id=portfolio_id,
                    evidence_manifest_id="NO_SAFE_EVIDENCE",
                    provenance=provenance.value,
                    market_timestamp=timestamp,
                    status=ForwardCycleStatus.BLOCKED.value,
                    lease_owner=lease_owner,
                    retry_count=0,
                    error=detail,
                    payload={"data_quality_block": detail, "orders": 0, "fills": 0},
                    started_at=now,
                    completed_at=now,
                )
            )
            for trial in trials:
                event = ForwardDataQualityEvent(
                    event_id=(
                        "forward-data-quality-"
                        + canonical_hash({"cycle": cycle_id, "trial": trial.manifest.trial_id})[:24]
                    ),
                    cycle_id=cycle_id,
                    trial_id=trial.manifest.trial_id,
                    timestamp=timestamp,
                    event_type="UNSAFE_FORWARD_DATA",
                    severity="PAUSE",
                    detail=detail,
                )
                events.append(event)
                self._add_data_quality(session, event)
                decision = ForwardLifecycleDecision(
                    decision_id=(
                        "forward-decision-"
                        + canonical_hash(
                            {
                                "cycle": cycle_id,
                                "trial": trial.manifest.trial_id,
                                "state": "PAUSED_DATA_QUALITY",
                            }
                        )[:24]
                    ),
                    trial_id=trial.manifest.trial_id,
                    cycle_id=cycle_id,
                    timestamp=timestamp,
                    previous_state=trial.state,
                    new_state=ForwardTrialState.PAUSED_DATA_QUALITY,
                    rule_id="CURRENT_DATA_FAIL_CLOSED",
                    reasons=(detail,),
                    evidence={
                        "orders": 0,
                        "fills": 0,
                        "external_order_transmission": False,
                    },
                )
                decisions.append(decision)
                self._add_lifecycle_decision(session, decision)
            audit_id = f"forward-audit-blocked-{cycle_id}"
            session.add(
                ForwardAuditEventRow(
                    event_id=audit_id,
                    cycle_id=cycle_id,
                    trial_id=None,
                    event_type="FORWARD_CYCLE_BLOCKED_DATA_QUALITY",
                    occurred_at=timestamp,
                    payload={
                        "detail": detail,
                        "external_order_transmission": False,
                    },
                )
            )
        return ForwardCycleResult(
            cycle_id=cycle_id,
            portfolio_id=portfolio_id,
            evidence_manifest_id="NO_SAFE_EVIDENCE",
            provenance=provenance,
            status=ForwardCycleStatus.BLOCKED,
            processed=True,
            timestamp=timestamp,
            lifecycle_decisions=tuple(decisions),
            data_quality=tuple(events),
            error=detail,
        )

    def cycles(self, portfolio_id: str | None = None) -> tuple[dict[str, object], ...]:
        with self._sessions() as session:
            statement = select(ForwardCycleRow)
            if portfolio_id is not None:
                statement = statement.where(ForwardCycleRow.portfolio_id == portfolio_id)
            rows = session.scalars(
                statement.order_by(ForwardCycleRow.started_at, ForwardCycleRow.cycle_id)
            ).all()
            return tuple(
                {
                    "cycle_id": row.cycle_id,
                    "portfolio_id": row.portfolio_id,
                    "evidence_manifest_id": row.evidence_manifest_id,
                    "provenance": row.provenance,
                    "market_timestamp": _aware(row.market_timestamp),
                    "status": row.status,
                    "retry_count": row.retry_count,
                    "error": row.error,
                    "payload": row.payload,
                    "started_at": _aware(row.started_at),
                    "completed_at": _aware(row.completed_at) if row.completed_at else None,
                }
                for row in rows
            )

    def lifecycle_decisions(
        self, trial_id: str | None = None
    ) -> tuple[ForwardLifecycleDecision, ...]:
        with self._sessions() as session:
            statement = select(ForwardLifecycleDecisionRow)
            if trial_id is not None:
                statement = statement.where(ForwardLifecycleDecisionRow.trial_id == trial_id)
            rows = session.scalars(
                statement.order_by(
                    ForwardLifecycleDecisionRow.timestamp,
                    ForwardLifecycleDecisionRow.decision_id,
                )
            ).all()
            return tuple(ForwardLifecycleDecision.model_validate(row.payload) for row in rows)

    def data_quality_events(self) -> tuple[ForwardDataQualityEvent, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ForwardDataQualityEventRow).order_by(
                    ForwardDataQualityEventRow.timestamp,
                    ForwardDataQualityEventRow.event_id,
                )
            ).all()
            return tuple(ForwardDataQualityEvent.model_validate(row.payload) for row in rows)
