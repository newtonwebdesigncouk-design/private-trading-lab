"""Corporate-action policies with explicit dividend double-counting protection."""

from collections.abc import Sequence

from app.data.models import CorporateAction
from app.models.enums import AdjustmentPolicy, CorporateActionType
from app.models.market import MarketBar


def apply_adjustment_policy(
    bars: Sequence[MarketBar],
    actions: Sequence[CorporateAction],
    policy: AdjustmentPolicy,
) -> tuple[MarketBar, ...]:
    actions_by_timestamp: dict[object, list[CorporateAction]] = {}
    for action in actions:
        actions_by_timestamp.setdefault(action.effective_timestamp, []).append(action)

    prepared: list[MarketBar] = []
    for bar in bars:
        relevant = actions_by_timestamp.get(bar.timestamp, [])
        cash_dividend = sum(
            action.cash_amount or 0.0
            for action in relevant
            if action.action_type is CorporateActionType.CASH_DIVIDEND
        )
        if policy is AdjustmentPolicy.TOTAL_RETURN_ADJUSTED:
            if bar.adjusted_close is None:
                raise ValueError("total-return-adjusted policy requires adjusted_close")
            prepared.append(bar.model_copy(update={"dividend": 0.0}))
        elif policy in {
            AdjustmentPolicy.UNADJUSTED_WITH_ACTIONS,
            AdjustmentPolicy.SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS,
        }:
            prepared.append(bar.model_copy(update={"dividend": cash_dividend}))
        else:  # pragma: no cover - closed enum protects this branch
            raise ValueError(f"unsupported adjustment policy: {policy}")
    return tuple(prepared)


def split_ratio_at(actions: Sequence[CorporateAction], bar: MarketBar) -> float:
    ratio = 1.0
    for action in actions:
        if (
            action.asset == bar.asset
            and action.effective_timestamp == bar.timestamp
            and action.action_type is CorporateActionType.STOCK_SPLIT
        ):
            ratio *= action.split_ratio or 1.0
    return ratio
