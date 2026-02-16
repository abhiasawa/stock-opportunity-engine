from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.stock_mvp.models.schemas import ScoredStock, StockEvent, StockSnapshot
from app.stock_mvp.utils.math_utils import clamp


class ScoreEngine:
    def __init__(self, rules: dict[str, Any]):
        self.rules = rules
        self.weights = rules["weights"]
        self.event_weights = rules["event_weights"]

    def score(self, stocks: list[StockSnapshot], events: list[StockEvent]) -> list[ScoredStock]:
        events_by_symbol: dict[str, list[StockEvent]] = defaultdict(list)
        for e in events:
            events_by_symbol[e.symbol].append(e)

        scored: list[ScoredStock] = []
        for stock in stocks:
            symbol_events = events_by_symbol.get(stock.symbol, [])

            profit_score, profit_reasons = self._profit_trend_score(stock)
            valuation_score, valuation_reasons = self._valuation_score(stock)
            event_score, event_reasons = self._future_event_score(stock, symbol_events)
            quality_score, quality_reasons = self._quality_score(stock)
            risk_penalty, risk_reasons = self._risk_penalty(stock)

            positive_weight_sum = (
                float(self.weights["profit_trend"])
                + float(self.weights["valuation"])
                + float(self.weights["future_events"])
                + float(self.weights["quality"])
            )

            weighted_positive = (
                profit_score * float(self.weights["profit_trend"])
                + valuation_score * float(self.weights["valuation"])
                + event_score * float(self.weights["future_events"])
                + quality_score * float(self.weights["quality"])
            ) / positive_weight_sum

            weighted_risk = risk_penalty * (float(self.weights["risk"]) / 100.0)
            final_score = clamp(weighted_positive - weighted_risk, 0.0, 100.0)

            reasons = [
                *profit_reasons,
                *valuation_reasons,
                *event_reasons,
                *quality_reasons,
                *risk_reasons,
            ]

            scored.append(
                ScoredStock(
                    symbol=stock.symbol,
                    name=stock.name,
                    exchange=stock.exchange,
                    sector=stock.sector,
                    market_cap_cr=stock.market_cap_cr,
                    pe=stock.pe,
                    final_score=round(final_score, 2),
                    score_breakdown={
                        "profit_trend": round(profit_score, 2),
                        "valuation": round(valuation_score, 2),
                        "future_events": round(event_score, 2),
                        "quality": round(quality_score, 2),
                        "risk_penalty": round(risk_penalty, 2),
                    },
                    reasons=reasons[:10],
                    event_count=len(symbol_events),
                    metrics=stock.metrics,
                )
            )

        return sorted(scored, key=lambda x: x.final_score, reverse=True)

    def _profit_trend_score(self, stock: StockSnapshot) -> tuple[float, list[str]]:
        reasons: list[str] = []

        if stock.profit_prev_ttm_cr <= 0:
            yoy_growth_pct = 100.0 if stock.profit_ttm_cr > 0 else 0.0
        else:
            yoy_growth_pct = ((stock.profit_ttm_cr - stock.profit_prev_ttm_cr) / abs(stock.profit_prev_ttm_cr)) * 100

        q = [stock.profit_q1_cr, stock.profit_q2_cr, stock.profit_q3_cr, stock.profit_q4_cr]
        increasing_steps = sum(1 for i in range(1, len(q)) if q[i] >= q[i - 1])
        consistency_score = (increasing_steps / 3.0) * 100.0

        growth_score = clamp(yoy_growth_pct, -50, 100)
        growth_score_normalized = ((growth_score + 50.0) / 150.0) * 100.0

        score = clamp((0.7 * growth_score_normalized) + (0.3 * consistency_score), 0.0, 100.0)

        reasons.append(f"Profit YoY growth: {yoy_growth_pct:.1f}%")
        reasons.append(f"Quarterly trend consistency: {increasing_steps}/3")
        return score, reasons

    def _valuation_score(self, stock: StockSnapshot) -> tuple[float, list[str]]:
        reasons: list[str] = []
        max_pe = float(self.rules["filters"].get("max_pe", 40))

        if stock.pe <= 0:
            score = 100.0
        elif stock.pe <= 20:
            score = 100.0
        elif stock.pe <= max_pe:
            score = clamp(100.0 - ((stock.pe - 20.0) / max(1.0, (max_pe - 20.0))) * 40.0, 45.0, 100.0)
        else:
            score = clamp(45.0 - ((stock.pe - max_pe) * 2.0), 0.0, 45.0)

        reasons.append(f"PE: {stock.pe:.1f} (max configured: {max_pe:.1f})")
        return score, reasons

    def _future_event_score(self, stock: StockSnapshot, events: list[StockEvent]) -> tuple[float, list[str]]:
        reasons: list[str] = []
        if not events:
            return 0.0, ["No recent qualifying events"]

        raw = 0.0
        top_events: list[str] = []

        for e in events:
            base = float(self.event_weights.get(e.event_type, 0))
            if base <= 0:
                continue
            age_days = max(0, (date.today() - e.event_date).days)
            recency = clamp(1.0 - (age_days / 90.0), 0.35, 1.0)
            raw += base * recency
            top_events.append(f"{e.event_type} ({e.event_date.isoformat()})")

        score = clamp(raw, 0.0, 100.0)
        if top_events:
            reasons.append("Recent events: " + ", ".join(top_events[:3]))
        return score, reasons

    def _quality_score(self, stock: StockSnapshot) -> tuple[float, list[str]]:
        reasons: list[str] = []

        promoter_score = clamp((stock.promoter_holding_pct / 75.0) * 100.0, 0.0, 100.0)
        hni_score = clamp((stock.hni_net_buying_cr / 20.0) * 100.0, 0.0, 100.0)
        pledge_penalty = clamp((stock.pledge_pct / 50.0) * 100.0, 0.0, 100.0)

        score = clamp((0.55 * promoter_score) + (0.45 * hni_score) - (0.35 * pledge_penalty), 0.0, 100.0)

        reasons.append(f"Promoter holding: {stock.promoter_holding_pct:.1f}%")
        reasons.append(f"HNI net buying: {stock.hni_net_buying_cr:.1f} cr")
        if stock.pledge_pct > 0:
            reasons.append(f"Pledge: {stock.pledge_pct:.1f}%")

        return score, reasons

    def _risk_penalty(self, stock: StockSnapshot) -> tuple[float, list[str]]:
        reasons: list[str] = []
        penalty = 0.0

        if stock.esm_flag:
            penalty += 50.0
            reasons.append("Risk: ESM/ASM-like flag present")

        if stock.governance_flag:
            penalty += 35.0
            reasons.append("Risk: governance red flag")

        max_pledge = float(self.rules["filters"].get("max_pledge_pct", 40))
        if stock.pledge_pct > max_pledge:
            penalty += 25.0
            reasons.append(f"Risk: pledge above threshold ({stock.pledge_pct:.1f}% > {max_pledge:.1f}%)")

        if stock.profit_prev_ttm_cr > 0:
            yoy_growth_pct = ((stock.profit_ttm_cr - stock.profit_prev_ttm_cr) / abs(stock.profit_prev_ttm_cr)) * 100
            if yoy_growth_pct < -30:
                penalty += 30.0
                reasons.append(f"Risk: sharp profit drop ({yoy_growth_pct:.1f}%)")

        return clamp(penalty, 0.0, 100.0), reasons
