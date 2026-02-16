# Stock Opportunity Engine (MVP)

Rule-driven stock opportunity scanner for Indian micro/small/mid-cap workflows.

## What this MVP does
- Runs scheduled scans (daily + intraday event scan)
- Applies editable rules from YAML
- Ranks stocks with explainable scores
- Stores run history and recommendation details
- Provides web UI for:
  - dashboard
  - run history/details
  - rules editing
- Creates WhatsApp-style alert messages (stub log output)
- Supports live India mode:
  - Yahoo Finance snapshots (`yfinance`)
  - NSE corporate announcements classification for event scoring
- Supports real WhatsApp send via Twilio

## Tech stack
- FastAPI
- APScheduler
- SQLite
- Jinja templates
- YAML config

## Project layout
- `app/stock_mvp/main.py` - FastAPI app entrypoint
- `app/stock_mvp/services/` - pipeline, scoring, scheduler, notification
- `app/stock_mvp/providers/` - data provider interfaces and mock provider
- `app/stock_mvp/providers/india_live_provider.py` - live India provider
- `app/stock_mvp/templates/` - UI templates
- `config/rules.yaml` - editable rules and schedule
- `data/sample_*.csv` - mock stock/event data
- `data/stock_mvp.db` - SQLite DB (auto-created)
- `docs/TECHNICAL_SPEC.md` - architecture and design decisions

## Quick start
1. Create env and install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run app:
```bash
uvicorn app.stock_mvp.main:app --reload
```

3. Open:
- `http://127.0.0.1:8000/` dashboard
- `http://127.0.0.1:8000/rules` rule editor

## How to use
1. Go to `/rules` and tune filters/weights/schedules.
2. Click **Run Scan Now** on dashboard.
3. Open latest run and inspect per-stock score details.

## Frequency
Configured in `config/rules.yaml`:
- `schedules.full_scan_cron`
- `schedules.event_scan_cron`
- `schedules.timezone`

## Data
MVP uses CSV mock data:
- `data/sample_stocks.csv`
- `data/sample_events.csv`

Replace provider layer later with live APIs.

### Switch to live India mode
Update `/Users/abhishekasawa/Downloads/Claude/Stocks/config/rules.yaml`:
- `data_provider.type: india_live`
- `data_provider.symbols_file: data/universe_symbols.csv`

Edit `/Users/abhishekasawa/Downloads/Claude/Stocks/data/universe_symbols.csv` with NSE symbols.

## WhatsApp
Stub mode logs messages to:
- `data/outbox/whatsapp.log`

### Enable real WhatsApp via Twilio
1. Set rules:
- `notifications.mode: twilio`
- `notifications.whatsapp_enabled: true`
- `notifications.whatsapp_to: [+91...]`
2. Export environment variables:
```bash
export TWILIO_ACCOUNT_SID=...
export TWILIO_AUTH_TOKEN=...
export TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```
You can copy `/Users/abhishekasawa/Downloads/Claude/Stocks/.env.example` into your shell/env manager.

3. Send test message:
```bash
curl -X POST http://127.0.0.1:8000/api/notifications/test
```

### Fast setup helper
```bash
./scripts/setup_whatsapp_twilio.sh <SID> <TOKEN> <FROM_WHATSAPP> <TO_NUMBER>
```

### Important behavior
- If WhatsApp is enabled in `twilio` mode and credentials are missing, runs now fail fast with a clear error (no silent fallback).
- Check status via:
```bash
curl http://127.0.0.1:8000/api/notifications/status
```

## Notes
- This is recommendation support, not auto-trading.
- Always manually review recommendations.
