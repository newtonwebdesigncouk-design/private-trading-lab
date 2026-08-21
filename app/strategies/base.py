"""Strategy interface: requests exposure but never creates or submits orders."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.models.market import MarketBar
from app.models.strategy import StrategySpec


class Strategy(ABC):
    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec

    @abstractmethod
    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        """Return long-only target exposure [0, 1] using closed bars only."""

    def _closes(self, available_history: Sequence[MarketBar]) -> list[float]:
        return [bar.effective_close for bar in available_history]
