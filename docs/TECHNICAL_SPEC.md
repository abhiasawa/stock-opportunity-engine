# Stock Opportunity Engine - Technical Spec (MVP)

## 1) Objective
Build a rule-driven system that scans Indian stocks (micro/small/mid), ranks opportunities, and gives transparent recommendations with editable rules.

Core requirements:
- Run at set frequency (daily/intraday).
- Show why each stock is recommended.
- Let user edit/tune rules without code changes.
- Keep architecture ready for real APIs and WhatsApp alerts.

## 2) Product Decision: App vs Cron vs Website
### Recommended architecture (hybrid)
Use **all three in one system**:
1. **Web app (FastAPI + server-rendered UI)**
   - Rule editing (YAML + safe validation)
   - Dashboard and recommendation details
   - Manual trigger and run history
2. **Background scheduler (APScheduler in-process for MVP)**
   - Daily full scan
   - Intraday event scan
3. **Cron-compatible trigger endpoint/script**
   - If later deployed as separate worker, cron can call trigger endpoint.

Why hybrid:
- UI solves rule tinkering and explainability.
- Scheduler solves frequency automation.
- Cron compatibility keeps deployment portable.

## 3) Scope of This MVP
Included:
- Configurable rule engine
- Data providers:
  - Mock data provider (CSV-based)
  - Live India provider (Yahoo Finance + NSE announcements)
- Scoring + ranking pipeline
- SQLite persistence for run history
- Web UI for rules, runs, recommendations
- Notification abstraction:
  - WhatsApp stub logger
  - Twilio WhatsApp sender

Deferred (next phase):
- Dedicated paid financial/fundamental APIs for higher reliability
- Earnings call transcript ingestion
- News sentiment and event NLP
- Portfolio tracking, order execution, and broker integration

## 4) System Architecture
### Components
1. **Config Layer**
   - `config/rules.yaml`
   - Single source of truth for filters, weights, schedule, and notification toggles.

2. **Provider Layer**
  - `MockDataProvider` reads:
    - `data/sample_stocks.csv`
    - `data/sample_events.csv`
  - `IndiaLiveProvider` reads:
    - Symbol universe from `data/universe_symbols.csv`
    - Snapshot data from Yahoo Finance
    - Events from NSE corporate announcements endpoint

3. **Scoring Engine**
   - Computes:
     - Profit trend score
     - Valuation score
     - Future-event score
     - Quality score
     - Risk penalty
   - Produces final rank score and reason breakdown.

4. **Pipeline Runner**
   - Pulls data -> filters universe -> scores -> sorts -> stores results.

5. **Persistence Layer**
   - SQLite file at `data/stock_mvp.db`
   - Tables:
     - `runs`
     - `recommendations`

6. **API + UI Layer**
   - Pages: dashboard, runs, run detail, rule editor
   - JSON API: latest results, trigger run, get/update rules

7. **Scheduler + Notifications**
   - APScheduler cron jobs read schedule from rules
   - Notification message creation from top picks
   - WhatsApp stub writes to `data/outbox/whatsapp.log`
   - Twilio notifier sends to WhatsApp recipients

## 5) Scoring Model (MVP)
Final score formula:

`final = weighted_positive_scores - risk_penalty`

### Positive score blocks
- Profit Trend (`weight: 35`)
- Valuation (`weight: 20`)
- Future Events (`weight: 25`)
- Quality (`weight: 10`)

### Penalty block
- Risk (`weight: 10`)

### Event examples and scoring
- Large order
- Capacity expansion
- New plant/subsidiary
- Preferential allotment
- Partnership/acquisition

Event score decays by age so recent events score higher.

## 6) Rule Editability
Rules are editable from UI in two ways:
1. **Raw YAML editor** (full control)
2. **Structured form fields** (for common knobs)

Validation gates:
- YAML parse validation
- Required key checks
- Weight total sanity check

## 7) Frequency Model
Default schedule from rules:
- Full scan: weekdays at 4:30 PM IST
- Event scan: every 30 minutes during market hours

For MVP, timezone defaults to `Asia/Kolkata`.

## 8) API Contract (MVP)
- `GET /api/recommendations/latest`
- `POST /api/runs/trigger`
- `GET /api/runs/{run_id}`
- `GET /api/rules`
- `POST /api/rules` (raw YAML)

## 9) Deployment Options
### MVP single-service deployment
- One FastAPI service hosting API, UI, and scheduler.
- Best for speed and early iteration.

### Scalable split deployment (later)
- Service A: Web/API
- Service B: Worker/Scheduler
- Shared DB and queue

## 10) Security/Guardrails (MVP)
- No trade execution.
- Recommendation-only outputs.
- Explainability required per recommendation.
- Manual review expected before investing.

## 11) WhatsApp (Implemented in MVP)
- Modes:
  - `stub` (log only)
  - `twilio` (real send)
- Fail-fast policy:
  - if `whatsapp_enabled=true` and mode is `twilio` but env/recipients missing, run fails with explicit config error.
- Message template includes:
  - run id/type
  - universe/passed/picks
  - top 3 picks with reasons
- Next enhancement:
  - retry policy
  - delivery status tracking

## 12) Acceptance Criteria (MVP)
- Can edit rules from UI and save.
- Can trigger a run and see ranked recommendations.
- Can inspect scoring details per stock.
- Scheduler auto-runs based on configured cron.
- Notification pipeline logs WhatsApp-formatted output.
