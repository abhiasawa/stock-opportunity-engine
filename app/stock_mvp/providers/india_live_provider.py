from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yfinance as yf

from app.stock_mvp.core import db
from app.stock_mvp.core.settings import BASE_DIR
from app.stock_mvp.models.schemas import StockEvent, StockSnapshot
from app.stock_mvp.providers.base import DataProvider
from app.stock_mvp.services import scan_status

logger = logging.getLogger(__name__)


class NSEAnnouncementsClient:
    BASE_WEB = "https://www.nseindia.com"
    API_ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements"

    def __init__(self, timeout_sec: int = 12):
        self.timeout_sec = timeout_sec
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.nseindia.com/",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _bootstrap(self) -> None:
        try:
            self.session.get(self.BASE_WEB, timeout=self.timeout_sec)
        except requests.RequestException:
            return

    def fetch_events(self, symbol: str, lookback_days: int = 90) -> list[StockEvent]:
        self._bootstrap()
        params = {"index": "equities", "symbol": symbol}

        try:
            resp = self.session.get(self.API_ANNOUNCEMENTS, params=params, timeout=self.timeout_sec)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return []

        if not isinstance(payload, list):
            return []

        cutoff = date.today() - timedelta(days=lookback_days)
        out: list[StockEvent] = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            text = self._pick_text(item)
            if not text:
                continue

            event_type = self._classify_event_type(text)
            if not event_type:
                continue

            d = self._pick_date(item)
            if d < cutoff:
                continue

            out.append(
                StockEvent(
                    symbol=symbol,
                    event_type=event_type,
                    event_date=d,
                    value_cr=self._extract_value_cr(text),
                    headline=text[:220],
                )
            )

        return out

    @staticmethod
    def _pick_text(item: dict[str, Any]) -> str:
        for key in ("desc", "subject", "sm_name", "headline", "attchmntText"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                return re.sub(r"\s+", " ", v.strip())
        return ""

    @staticmethod
    def _pick_date(item: dict[str, Any]) -> date:
        for key in ("an_dt", "an_date", "date", "dt"):
            raw = item.get(key)
            if not raw:
                continue
            if isinstance(raw, (int, float)):
                try:
                    return datetime.utcfromtimestamp(raw).date()
                except (ValueError, OSError):
                    continue
            if isinstance(raw, str):
                raw = raw.strip()
                for fmt in (
                    "%Y-%m-%d",
                    "%d-%m-%Y",
                    "%d/%m/%Y",
                    "%d-%b-%Y",
                    "%d-%b-%Y %H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                ):
                    try:
                        return datetime.strptime(raw, fmt).date()
                    except ValueError:
                        continue
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
                except ValueError:
                    continue
        return date.today()

    @staticmethod
    def _classify_event_type(text: str) -> str | None:
        t = text.lower()
        rules = [
            ("preferential_allotment", ["preferential", "allotment", "warrant"]),
            ("capacity_expansion", ["capacity expansion", "expand capacity", "commissioned"]),
            ("new_plant", ["new plant", "plant commissioned", "factory commenced"]),
            ("acquisition", ["acquisition", "acquire", "takeover"]),
            ("partnership", ["partnership", "mou", "joint venture", "collaborat"]),
            ("subsidiary_launch", ["subsidiary", "incorporated", "wholly owned"]),
            ("large_order", ["order", "order book", "contract awarded", "work order"]),
        ]
        for event_type, needles in rules:
            if any(k in t for k in needles):
                return event_type
        return None

    @staticmethod
    def _extract_value_cr(text: str) -> float:
        t = text.lower().replace(",", "")
        m_cr = re.search(r"(\d+(?:\.\d+)?)\s*(?:crore|cr)\b", t)
        if m_cr:
            return float(m_cr.group(1))

        m_lakh = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)\b", t)
        if m_lakh:
            return float(m_lakh.group(1)) / 100.0

        return 0.0


class IndiaLiveProvider(DataProvider):
    """
    Optimized provider that:
    1. Caches fundamentals (quarterly profits, sector, metrics) for ~90 days
    2. Uses yf.download() for batch price fetch (single HTTP call for all symbols)
    3. Only calls slow per-symbol yf.Ticker().info for uncached/stale entries
    """

    CACHE_MAX_AGE_DAYS = 90

    def __init__(
        self,
        symbols_file: str,
        max_symbols: int = 25,
        timeout_sec: int = 12,
        nse_events_enabled: bool = True,
    ) -> None:
        self.symbols_file = Path(symbols_file)
        if not self.symbols_file.is_absolute():
            self.symbols_file = (BASE_DIR / self.symbols_file).resolve()
        self.max_symbols = max_symbols
        self.timeout_sec = timeout_sec
        self.nse_events_enabled = nse_events_enabled
        self.nse_client = NSEAnnouncementsClient(timeout_sec=timeout_sec)

    def get_stock_snapshots(self) -> list[StockSnapshot]:
        symbols = self._load_symbols()
        if not symbols:
            return []

        scan_status.start_scan(len(symbols))

        # Phase 1: Check cache — identify which symbols need full fetch
        cached = db.get_cached_fundamentals(symbols, max_age_days=self.CACHE_MAX_AGE_DAYS)
        cached_symbols = set(cached.keys())
        stale_symbols = [s for s in symbols if s not in cached_symbols]

        logger.info(
            "Cache status: %d cached, %d stale/missing (of %d total)",
            len(cached_symbols),
            len(stale_symbols),
            len(symbols),
        )

        if stale_symbols:
            scan_status.update_scan(
                "fetching_fundamentals", 0,
                message=f"Fetching fundamentals for {len(stale_symbols)} new stocks...",
            )

        # Phase 2: Full fetch for stale/missing symbols (slow, per-symbol)
        new_cache_entries: list[dict[str, Any]] = []
        for i, symbol in enumerate(stale_symbols, 1):
            scan_status.update_scan(
                "fetching_fundamentals", i, symbol=symbol,
                message=f"Fetching {symbol} ({i}/{len(stale_symbols)})",
            )
            entry = self._fetch_fundamentals(symbol)
            if entry is not None:
                cached[symbol] = entry
                new_cache_entries.append(entry)
            # Persist in batches of 20 to avoid losing progress on crash
            if len(new_cache_entries) % 20 == 0 and new_cache_entries:
                db.upsert_fundamentals_cache(new_cache_entries[-20:])

        # Phase 3: Persist remaining newly fetched fundamentals to cache
        if new_cache_entries:
            db.upsert_fundamentals_cache(new_cache_entries)
            logger.info("Cached %d new/updated fundamentals", len(new_cache_entries))

        # Phase 4: Batch fetch live prices (single API call)
        scan_status.update_scan(
            "fetching_prices", len(stale_symbols),
            message=f"Batch fetching live prices for {len(symbols)} symbols...",
        )
        live_prices = self._batch_fetch_prices(symbols)

        # Phase 5: Merge cached fundamentals + live prices → StockSnapshots
        out: list[StockSnapshot] = []
        for symbol in symbols:
            fund = cached.get(symbol)
            if fund is None:
                continue

            # Update current_price with live data if available
            metrics = dict(fund.get("metrics", {}))
            if symbol in live_prices:
                metrics["current_price"] = live_prices[symbol]

            out.append(
                StockSnapshot(
                    symbol=fund["symbol"],
                    name=fund["name"],
                    exchange=fund["exchange"],
                    sector=fund["sector"],
                    market_cap_cr=fund["market_cap_cr"],
                    pe=fund["pe"],
                    profit_ttm_cr=fund["profit_ttm_cr"],
                    profit_prev_ttm_cr=fund["profit_prev_ttm_cr"],
                    profit_q1_cr=fund["profit_q1_cr"],
                    profit_q2_cr=fund["profit_q2_cr"],
                    profit_q3_cr=fund["profit_q3_cr"],
                    profit_q4_cr=fund["profit_q4_cr"],
                    promoter_holding_pct=fund["promoter_holding_pct"],
                    pledge_pct=fund["pledge_pct"],
                    hni_net_buying_cr=fund["hni_net_buying_cr"],
                    esm_flag=False,
                    governance_flag=False,
                    metrics=metrics,
                )
            )

        return out

    def get_recent_events(self, lookback_days: int = 60) -> list[StockEvent]:
        if not self.nse_events_enabled:
            return []

        symbols = self._load_symbols()
        out: list[StockEvent] = []
        for symbol in symbols:
            out.extend(self.nse_client.fetch_events(symbol=symbol, lookback_days=lookback_days))
        return out

    def _load_symbols(self) -> list[str]:
        symbols: list[str] = []
        with self.symbols_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw = (row.get("symbol") or "").strip().upper()
                if raw:
                    symbols.append(raw)
        if self.max_symbols > 0:
            return symbols[: self.max_symbols]
        return symbols

    def _fetch_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        """Full per-symbol fetch via yf.Ticker().info — slow but comprehensive."""
        yahoo_symbol = self._to_yahoo_symbol(symbol)

        try:
            ticker = yf.Ticker(yahoo_symbol)
            info = ticker.info or {}
        except Exception:
            return None

        market_cap = float(info.get("marketCap") or 0.0)
        if market_cap <= 0:
            try:
                fi = ticker.fast_info
                market_cap = float(getattr(fi, "market_cap", 0.0) or 0.0)
            except Exception:
                market_cap = 0.0

        pe = float(info.get("trailingPE") or info.get("forwardPE") or 0.0)

        q_values = self._extract_quarterly_net_income(ticker)
        if len(q_values) < 4:
            net_income = float(info.get("netIncomeToCommon") or 0.0)
            if net_income <= 0:
                return None
            q_values = [net_income / 4.0] * 4

        q1, q2, q3, q4 = q_values[-4:]
        profit_ttm = sum([q1, q2, q3, q4])

        prev = self._extract_previous_four_quarters(ticker)
        if len(prev) == 4:
            profit_prev_ttm = sum(prev)
        else:
            profit_prev_ttm = max(1.0, profit_ttm * 0.8)

        exchange = "NSE" if yahoo_symbol.endswith(".NS") else "BSE"
        name = str(info.get("longName") or info.get("shortName") or symbol)
        sector = str(info.get("sector") or "Unknown")

        promoter_holding_pct = float(info.get("heldPercentInsiders") or 0.0) * 100.0
        pledge_pct = 0.0
        hni_net_buying_cr = 0.0

        inr_to_cr = 1e7

        current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
        book_value = float(info.get("bookValue") or 0.0)
        price_to_book = float(info.get("priceToBook") or 0.0)
        dividend_yield = float(info.get("dividendYield") or 0.0) * 100.0
        roe = float(info.get("returnOnEquity") or 0.0) * 100.0
        total_revenue = float(info.get("totalRevenue") or 0.0)
        total_debt = float(info.get("totalDebt") or 0.0)
        operating_income = float(info.get("operatingIncome") or info.get("ebitda") or 0.0)
        total_equity = float(info.get("totalStockholderEquity") or 0.0)
        high_52w = float(info.get("fiftyTwoWeekHigh") or 0.0)
        low_52w = float(info.get("fiftyTwoWeekLow") or 0.0)

        capital_employed = total_equity + total_debt
        ebit = float(info.get("ebit") or operating_income or 0.0)
        roce = (ebit / capital_employed * 100.0) if capital_employed > 0 else 0.0

        metrics = {
            "current_price": round(current_price, 2),
            "book_value": round(book_value, 2),
            "price_to_book": round(price_to_book, 2),
            "dividend_yield": round(dividend_yield, 2),
            "roe": round(roe, 2),
            "roce": round(roce, 2),
            "sales_cr": round(total_revenue / inr_to_cr, 2) if total_revenue else 0.0,
            "net_worth_cr": round(total_equity / inr_to_cr, 2) if total_equity else 0.0,
            "debt_cr": round(total_debt / inr_to_cr, 2) if total_debt else 0.0,
            "operating_profit_cr": round(operating_income / inr_to_cr, 2) if operating_income else 0.0,
            "promoter_holding_pct": round(promoter_holding_pct, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
        }

        return {
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "sector": sector,
            "market_cap_cr": market_cap / inr_to_cr if market_cap else 0.0,
            "pe": pe,
            "profit_ttm_cr": profit_ttm / inr_to_cr,
            "profit_prev_ttm_cr": profit_prev_ttm / inr_to_cr,
            "profit_q1_cr": q1 / inr_to_cr,
            "profit_q2_cr": q2 / inr_to_cr,
            "profit_q3_cr": q3 / inr_to_cr,
            "profit_q4_cr": q4 / inr_to_cr,
            "promoter_holding_pct": promoter_holding_pct,
            "pledge_pct": pledge_pct,
            "hni_net_buying_cr": hni_net_buying_cr,
            "metrics": metrics,
        }

    def _batch_fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        """Batch fetch live prices for all symbols in a single yf.download() call."""
        yahoo_symbols = [self._to_yahoo_symbol(s) for s in symbols]
        nse_to_original = {self._to_yahoo_symbol(s): s for s in symbols}

        try:
            df = yf.download(
                yahoo_symbols,
                period="1d",
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("Batch price fetch failed: %s", exc)
            return {}

        prices: dict[str, float] = {}

        if df is None or df.empty:
            return prices

        # yf.download returns different column structures for single vs multiple symbols
        if len(yahoo_symbols) == 1:
            # Single symbol: columns are just ["Open", "High", "Low", "Close", ...]
            ys = yahoo_symbols[0]
            original = nse_to_original.get(ys, ys.replace(".NS", "").replace(".BO", ""))
            try:
                close_val = df["Close"].iloc[-1]
                if close_val and float(close_val) > 0:
                    prices[original] = round(float(close_val), 2)
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        else:
            # Multiple symbols: MultiIndex columns like ("Close", "RELIANCE.NS")
            try:
                close_df = df["Close"]
            except KeyError:
                return prices

            for ys in yahoo_symbols:
                original = nse_to_original.get(ys, ys.replace(".NS", "").replace(".BO", ""))
                try:
                    val = close_df[ys].iloc[-1]
                    if val and float(val) > 0:
                        prices[original] = round(float(val), 2)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue

        logger.info("Batch fetched prices for %d / %d symbols", len(prices), len(symbols))
        return prices

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol
        return f"{symbol}.NS"

    @staticmethod
    def _extract_quarterly_net_income(ticker: yf.Ticker) -> list[float]:
        try:
            qdf = ticker.quarterly_income_stmt
        except Exception:
            return []

        if qdf is None or qdf.empty:
            return []

        row_names = [
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income Including Noncontrolling Interests",
        ]

        row = None
        for r in row_names:
            if r in qdf.index:
                row = qdf.loc[r]
                break

        if row is None:
            return []

        values: list[tuple[datetime, float]] = []
        for dt_obj, val in row.items():
            if val is None:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if isinstance(dt_obj, datetime):
                d = dt_obj
            else:
                try:
                    d = datetime.fromisoformat(str(dt_obj))
                except ValueError:
                    d = datetime.utcnow()
            values.append((d, v))

        if not values:
            return []

        values.sort(key=lambda x: x[0])
        return [v for _, v in values]

    @classmethod
    def _extract_previous_four_quarters(cls, ticker: yf.Ticker) -> list[float]:
        vals = cls._extract_quarterly_net_income(ticker)
        if len(vals) < 8:
            return []
        return vals[-8:-4]
