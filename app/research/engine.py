"""Generates explainable candidates without modifying executable source code."""

import hashlib
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from app.models.enums import StrategyState
from app.models.strategy import StrategySpec


class CandidateReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_version: str
    parent_strategy: str
    parameter_changes: dict[str, float | int]
    reason: str


class BoundedResearchEngine:
    """Creates specs from approved parameter grids; it cannot write application code."""

    def __init__(self, *, maximum_candidates: int = 50) -> None:
        if maximum_candidates <= 0:
            raise ValueError("maximum_candidates must be positive")
        self.maximum_candidates = maximum_candidates

    def generate_candidates(
        self,
        parent: StrategySpec,
        parameter_grid: Mapping[str, Sequence[float | int]],
    ) -> tuple[tuple[StrategySpec, CandidateReason], ...]:
        generated: list[tuple[StrategySpec, CandidateReason]] = []
        for parameter in sorted(parameter_grid):
            if parameter not in parent.parameters:
                raise ValueError(f"parameter is not approved by parent spec: {parameter}")
            for value in parameter_grid[parameter]:
                if len(generated) >= self.maximum_candidates:
                    return tuple(generated)
                parameters = dict(parent.parameters)
                old_value = parameters[parameter]
                parameters[parameter] = value
                change = {parameter: value}
                digest = hashlib.sha256(
                    f"{parent.version_key}|{parameter}|{value}".encode()
                ).hexdigest()[:8]
                reason_text = f"Bounded variation of {parameter}: {old_value} -> {value}"
                candidate = StrategySpec.model_validate(
                    {
                        **parent.model_dump(mode="python"),
                        "strategy_id": f"{parent.strategy_id}-candidate-{digest}",
                        "version": 1,
                        "parameters": parameters,
                        "creation_method": "bounded_parameter_search",
                        "creation_reason": reason_text,
                        "parent_strategy": parent.version_key,
                        "state": StrategyState.CREATED,
                    },
                )
                reason = CandidateReason(
                    candidate_version=candidate.version_key,
                    parent_strategy=parent.version_key,
                    parameter_changes=change,
                    reason=reason_text,
                )
                generated.append((candidate, reason))
        return tuple(generated)
