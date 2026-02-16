from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class StockSnapshot(BaseModel):
    symbol: str
    name: str
    exchange: str
    sector: str
    market_cap_cr: float
    pe: float
    profit_ttm_cr: float
    profit_prev_ttm_cr: float
    profit_q1_cr: float
    profit_q2_cr: float
    profit_q3_cr: float
    profit_q4_cr: float
    promoter_holding_pct: float
    pledge_pct: float
    hni_net_buying_cr: float
    esm_flag: bool
    governance_flag: bool
    metrics: dict[str, float] = {}


class StockEvent(BaseModel):
    symbol: str
    event_type: str
    event_date: date
    value_cr: float
    headline: str


class ScoredStock(BaseModel):
    symbol: str
    name: str
    exchange: str
    sector: str
    market_cap_cr: float
    pe: float
    final_score: float
    score_breakdown: dict[str, float]
    reasons: list[str]
    event_count: int
    metrics: dict[str, float] = {}
