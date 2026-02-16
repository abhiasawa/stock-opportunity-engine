from __future__ import annotations

from typing import Any

from app.stock_mvp.providers.base import DataProvider
from app.stock_mvp.providers.india_live_provider import IndiaLiveProvider
from app.stock_mvp.providers.mock_provider import MockDataProvider


def build_provider(rules: dict[str, Any]) -> DataProvider:
    provider_cfg = rules.get("data_provider", {})
    provider_type = str(provider_cfg.get("type", "mock")).strip().lower()

    if provider_type == "india_live":
        return IndiaLiveProvider(
            symbols_file=provider_cfg.get("symbols_file", "data/universe_symbols.csv"),
            max_symbols=int(provider_cfg.get("max_symbols", 500)),
            timeout_sec=int(provider_cfg.get("requests_timeout_sec", 15)),
            nse_events_enabled=bool(provider_cfg.get("nse_events_enabled", True)),
        )

    return MockDataProvider()
