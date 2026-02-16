from __future__ import annotations

import logging
import threading
from typing import Any

from app.stock_mvp.core import db
from app.stock_mvp.core.rules import load_rules
from app.stock_mvp.models.schemas import StockSnapshot
from app.stock_mvp.providers.base import DataProvider
from app.stock_mvp.services.factories import build_provider
from app.stock_mvp.services.scoring import ScoreEngine
from app.stock_mvp.services import scan_status

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self, provider: DataProvider | None = None) -> None:
        self.provider = provider

    def run_scan_background(self, run_type: str = "manual") -> None:
        """Run scan in a background thread so the UI doesn't block."""
        t = threading.Thread(target=self._run_scan_safe, args=(run_type,), daemon=True)
        t.start()

    def _run_scan_safe(self, run_type: str) -> None:
        try:
            self.run_scan(run_type=run_type)
        except Exception as exc:
            logger.error("Background scan failed: %s", exc)
            scan_status.finish_scan(f"Scan failed: {exc}")

    def run_scan(self, run_type: str = "manual") -> dict[str, Any]:
        rules = load_rules()
        provider = self.provider or build_provider(rules)

        run_id = db.create_run(run_type=run_type, rules_snapshot=rules)

        try:
            lookback_days = int(rules.get("data_provider", {}).get("events_lookback_days", 90))

            scan_status.update_scan("fetching_data", 0, message="Loading stock data...")
            stocks = provider.get_stock_snapshots()

            scan_status.update_scan("fetching_events", 0, message="Fetching corporate events...")
            events = provider.get_recent_events(lookback_days=lookback_days)

            scan_status.update_scan("scoring", 0, message="Applying filters and scoring...")
            universe = self._apply_universe_filters(stocks, rules)
            passed = self._apply_quality_filters(universe, rules)

            scorer = ScoreEngine(rules)
            scored = scorer.score(passed, events)

            max_n = int(rules.get("ui", {}).get("max_recommendations_per_run", 25))
            top = scored[:max_n]

            rec_rows: list[dict[str, Any]] = []
            for idx, s in enumerate(top, start=1):
                rec_rows.append(
                    {
                        "rank": idx,
                        "symbol": s.symbol,
                        "name": s.name,
                        "exchange": s.exchange,
                        "sector": s.sector,
                        "market_cap_cr": s.market_cap_cr,
                        "pe": s.pe,
                        "final_score": s.final_score,
                        "score_breakdown": s.score_breakdown,
                        "reasons": s.reasons,
                        "event_count": s.event_count,
                        "metrics": s.metrics,
                    }
                )

            if rec_rows:
                db.insert_recommendations(run_id, rec_rows)

            summary = {
                "run_id": run_id,
                "run_type": run_type,
                "universe_size": len(stocks),
                "eligible_universe": len(universe),
                "passed_filters": len(passed),
                "recommended_count": len(rec_rows),
            }

            db.complete_run(run_id, summary)
            scan_status.finish_scan(f"Done — {len(rec_rows)} recommendations from {len(stocks)} stocks")

            return {
                "run": db.get_run(run_id),
                "recommendations": db.get_recommendations(run_id),
            }

        except Exception as exc:
            db.fail_run(run_id, str(exc))
            scan_status.finish_scan(f"Scan failed: {exc}")
            raise

    def _apply_universe_filters(self, stocks: list[StockSnapshot], rules: dict[str, Any]) -> list[StockSnapshot]:
        universe_rules = rules.get("universe", {})
        min_mc = float(universe_rules.get("min_market_cap_cr", 0))
        max_mc = float(universe_rules.get("max_market_cap_cr", 1e9))
        exchanges = set(universe_rules.get("exchanges", []))
        sectors_allowlist = set(universe_rules.get("sectors_allowlist", []))

        output: list[StockSnapshot] = []
        for s in stocks:
            if s.market_cap_cr < min_mc or s.market_cap_cr > max_mc:
                continue
            if exchanges and s.exchange not in exchanges:
                continue
            if sectors_allowlist and s.sector not in sectors_allowlist:
                continue
            output.append(s)
        return output

    def _apply_quality_filters(self, stocks: list[StockSnapshot], rules: dict[str, Any]) -> list[StockSnapshot]:
        filt = rules.get("filters", {})

        exclude_esm = bool(filt.get("exclude_esm", True))
        exclude_loss = bool(filt.get("exclude_loss_making", True))
        min_profit = float(filt.get("min_profit_ttm_cr", 0.0))
        min_yoy = float(filt.get("min_profit_yoy_growth_pct", -999))
        max_pe = float(filt.get("max_pe", 1e9))

        output: list[StockSnapshot] = []
        for s in stocks:
            if exclude_esm and s.esm_flag:
                continue
            if exclude_loss and s.profit_ttm_cr <= 0:
                continue
            if s.profit_ttm_cr < min_profit:
                continue

            if s.profit_prev_ttm_cr > 0:
                yoy = ((s.profit_ttm_cr - s.profit_prev_ttm_cr) / abs(s.profit_prev_ttm_cr)) * 100
            else:
                yoy = 100.0 if s.profit_ttm_cr > 0 else 0.0

            if yoy < min_yoy:
                continue
            if s.pe > max_pe:
                continue

            output.append(s)

        return output
