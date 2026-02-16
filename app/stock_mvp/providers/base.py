from __future__ import annotations

from abc import ABC, abstractmethod

from app.stock_mvp.models.schemas import StockEvent, StockSnapshot


class DataProvider(ABC):
    @abstractmethod
    def get_stock_snapshots(self) -> list[StockSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def get_recent_events(self, lookback_days: int = 60) -> list[StockEvent]:
        raise NotImplementedError
