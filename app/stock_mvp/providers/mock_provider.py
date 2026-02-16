from __future__ import annotations

import csv
from datetime import date, timedelta

from app.stock_mvp.core.settings import SAMPLE_EVENTS_PATH, SAMPLE_STOCKS_PATH
from app.stock_mvp.models.schemas import StockEvent, StockSnapshot
from app.stock_mvp.providers.base import DataProvider


class MockDataProvider(DataProvider):
    def get_stock_snapshots(self) -> list[StockSnapshot]:
        rows: list[StockSnapshot] = []
        with SAMPLE_STOCKS_PATH.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    StockSnapshot(
                        symbol=row["symbol"].strip(),
                        name=row["name"].strip(),
                        exchange=row["exchange"].strip(),
                        sector=row["sector"].strip(),
                        market_cap_cr=float(row["market_cap_cr"]),
                        pe=float(row["pe"]),
                        profit_ttm_cr=float(row["profit_ttm_cr"]),
                        profit_prev_ttm_cr=float(row["profit_prev_ttm_cr"]),
                        profit_q1_cr=float(row["profit_q1_cr"]),
                        profit_q2_cr=float(row["profit_q2_cr"]),
                        profit_q3_cr=float(row["profit_q3_cr"]),
                        profit_q4_cr=float(row["profit_q4_cr"]),
                        promoter_holding_pct=float(row["promoter_holding_pct"]),
                        pledge_pct=float(row["pledge_pct"]),
                        hni_net_buying_cr=float(row["hni_net_buying_cr"]),
                        esm_flag=row["esm_flag"].strip().lower() == "true",
                        governance_flag=row["governance_flag"].strip().lower() == "true",
                    )
                )
        return rows

    def get_recent_events(self, lookback_days: int = 60) -> list[StockEvent]:
        cutoff = date.today() - timedelta(days=lookback_days)
        rows: list[StockEvent] = []

        with SAMPLE_EVENTS_PATH.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                event_date = date.fromisoformat(row["event_date"])
                if event_date < cutoff:
                    continue
                rows.append(
                    StockEvent(
                        symbol=row["symbol"].strip(),
                        event_type=row["event_type"].strip(),
                        event_date=event_date,
                        value_cr=float(row["value_cr"]),
                        headline=row["headline"].strip(),
                    )
                )
        return rows
