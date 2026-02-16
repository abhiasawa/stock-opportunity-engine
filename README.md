# Stock Opportunity Engine

Rule-driven stock screener for the Indian stock market. Scans NSE/BSE stocks, scores them on profit trends, valuation, corporate events, and quality metrics, and presents ranked recommendations in a clean Screener.in-inspired web UI.

## Features

- **Live data** via Yahoo Finance (`yfinance`) for 429+ NSE stocks
- **Fundamentals caching** — quarterly data cached for 90 days, only live prices fetched on repeat scans
- **Batch price fetch** — single `yf.download()` call for all symbols
- **NSE corporate announcements** — classifies events (orders, expansions, acquisitions) for event scoring
- **Explainable scoring** — weighted breakdown: Profit Trend (35%), Valuation (20%), Events (25%), Quality (10%), Risk (10%)
- **Expandable metrics** — click any stock row to see ROE, ROCE, Book Value, Debt, Sales, and more
- **Screener.in links** — every stock symbol hyperlinks to its Screener.in page
- **Visual rule editor** — 6-tab form UI for filters, weights, schedules (no YAML editing required)
- **Scheduled scans** — configurable cron for daily full scans and intraday event scans
- **Run history** — browse past scan results with full scoring details

## Tech Stack

- **Backend**: FastAPI, SQLite, APScheduler
- **Data**: yfinance, NSE Announcements API
- **Frontend**: Jinja2 templates, vanilla CSS (Screener.in-inspired light theme)
- **Config**: YAML-based rules (`config/rules.yaml`)

## Project Layout

```
app/stock_mvp/
  main.py                  # FastAPI app + routes
  services/
    pipeline.py            # Scan orchestration
    scoring.py             # 5-factor scoring engine
    scheduler.py           # APScheduler cron jobs
  providers/
    india_live_provider.py # Yahoo Finance + NSE events + caching
    mock_provider.py       # CSV-based mock provider for testing
  core/
    db.py                  # SQLite (runs, recommendations, cache)
    rules.py               # YAML rule loading/validation
    settings.py            # Path constants
  templates/               # Jinja2 HTML templates
  static/style.css         # Screener-inspired light theme
config/rules.yaml          # Editable rules, weights, schedules
data/universe_symbols.csv  # 429 NSE stock symbols
```

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
uvicorn app.stock_mvp.main:app --reload --port 8000

# 4. Open in browser
open http://127.0.0.1:8000
```

## Usage

1. Open the **Dashboard** at `http://127.0.0.1:8000`
2. Click **Run Scan** to trigger a stock scan
3. View ranked recommendations with score breakdowns
4. Click any stock row to expand detailed financial metrics
5. Click the stock symbol to open its Screener.in page
6. Go to **Rules** to adjust filters, weights, and schedules via the visual editor

## Configuration

All settings are in `config/rules.yaml`:

| Section | Key Settings |
|---------|-------------|
| `data_provider` | Provider type, symbol file, timeout, events lookback |
| `universe` | Market cap range, exchange filter, sector allowlist |
| `filters` | Min profit, max PE, exclude ESM/loss-making stocks |
| `weights` | Scoring weights for each factor (must sum to 100) |
| `event_weights` | Points per event type (orders, expansions, etc.) |
| `schedules` | Cron expressions for full scan and event scan |
| `ui` | Max recommendations per run |

## How Caching Works

- **First scan**: Fetches full fundamentals per-symbol via `yf.Ticker().info` (slow, ~1-2s per stock)
- **Subsequent scans**: Reads fundamentals from SQLite cache, only fetches live prices via batch `yf.download()` (fast, single API call for all symbols)
- **Cache expiry**: 90 days — quarterly data is re-fetched automatically when stale

## Notes

- This is a recommendation/screening tool, not an auto-trading system
- Always manually review recommendations before making investment decisions
- Yahoo Finance rate limits may slow down the first scan; subsequent scans use cached data
