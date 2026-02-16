from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote as url_quote

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from app.stock_mvp.core import db
from app.stock_mvp.core.rules import RuleValidationError, load_rules, load_rules_raw, save_rules_raw
from app.stock_mvp.core.settings import STATIC_DIR, TEMPLATE_DIR
from app.stock_mvp.services.pipeline import PipelineService
from app.stock_mvp.services.scheduler import reload_scheduler, start_scheduler, stop_scheduler

load_dotenv()

pipeline = PipelineService()
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["screener_encode"] = lambda s: url_quote(str(s), safe="")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    start_scheduler(pipeline)
    yield
    stop_scheduler()


app = FastAPI(title="Stock Opportunity Engine", version="0.3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _latest_payload() -> dict[str, Any]:
    latest = db.get_latest_run()
    if not latest:
        return {"run": None, "recommendations": []}
    recs = db.get_recommendations(latest["id"])
    return {"run": latest, "recommendations": recs}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    payload = _latest_payload()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "run": payload["run"],
            "recommendations": payload["recommendations"],
            "active_page": "dashboard",
        },
    )


@app.post("/runs/trigger")
def trigger_run_form() -> RedirectResponse:
    pipeline.run_scan(run_type="manual")
    return RedirectResponse(url="/", status_code=303)


@app.get("/runs", response_class=HTMLResponse)
def list_runs_page(request: Request):
    runs = db.list_runs(limit=100)
    return templates.TemplateResponse(
        "runs.html",
        {"request": request, "runs": runs, "active_page": "runs"},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail_page(request: Request, run_id: int):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    recs = db.get_recommendations(run_id)
    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "recommendations": recs, "active_page": "runs"},
    )


@app.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request):
    yaml_text = load_rules_raw()
    rules = load_rules()
    return templates.TemplateResponse(
        "rules.html",
        {
            "request": request,
            "yaml_text": yaml_text,
            "rules": rules,
            "error": None,
            "saved": False,
            "active_page": "rules",
        },
    )


@app.post("/rules")
def save_rules_page(request: Request, yaml_text: str = Form(...)):
    try:
        save_rules_raw(yaml_text)
        reload_scheduler(pipeline)
        rules = load_rules()
        return templates.TemplateResponse(
            "rules.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "rules": rules,
                "error": None,
                "saved": True,
                "active_page": "rules",
            },
        )
    except RuleValidationError as exc:
        rules = load_rules()
        return templates.TemplateResponse(
            "rules.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "rules": rules,
                "error": str(exc),
                "saved": False,
                "active_page": "rules",
            },
            status_code=400,
        )


@app.post("/rules/visual")
async def save_rules_visual(request: Request):
    form = await request.form()

    # Load current rules as base, then overlay form values
    rules = load_rules()

    # Data provider
    rules["data_provider"]["type"] = form.get("provider_type", "mock")
    rules["data_provider"]["max_symbols"] = int(form.get("max_symbols", 500))
    rules["data_provider"]["requests_timeout_sec"] = int(form.get("requests_timeout_sec", 15))
    rules["data_provider"]["events_lookback_days"] = int(form.get("events_lookback_days", 90))
    rules["data_provider"]["nse_events_enabled"] = "nse_events_enabled" in form

    # Universe
    rules["universe"]["min_market_cap_cr"] = int(form.get("min_market_cap_cr", 50))
    rules["universe"]["max_market_cap_cr"] = int(form.get("max_market_cap_cr", 50000))
    sectors_str = form.get("sectors_allowlist", "").strip()
    rules["universe"]["sectors_allowlist"] = (
        [s.strip() for s in sectors_str.split(",") if s.strip()] if sectors_str else []
    )

    # Filters
    rules["filters"]["exclude_esm"] = "exclude_esm" in form
    rules["filters"]["exclude_loss_making"] = "exclude_loss_making" in form
    rules["filters"]["min_profit_ttm_cr"] = float(form.get("min_profit_ttm_cr", 1))
    rules["filters"]["min_profit_yoy_growth_pct"] = float(form.get("min_profit_yoy_growth_pct", 5))
    rules["filters"]["max_pe"] = float(form.get("max_pe", 60))
    rules["filters"]["max_pledge_pct"] = float(form.get("max_pledge_pct", 40))

    # Weights
    rules["weights"]["profit_trend"] = int(form.get("w_profit_trend", 35))
    rules["weights"]["valuation"] = int(form.get("w_valuation", 20))
    rules["weights"]["future_events"] = int(form.get("w_future_events", 25))
    rules["weights"]["quality"] = int(form.get("w_quality", 10))
    rules["weights"]["risk"] = int(form.get("w_risk", 10))

    # Event weights
    for key in list(rules.get("event_weights", {}).keys()):
        field_name = f"ew_{key}"
        if field_name in form:
            rules["event_weights"][key] = int(form.get(field_name, 0))

    # Schedule
    rules["schedules"]["full_scan_cron"] = form.get("full_scan_cron", "30 16 * * 1-5")
    rules["schedules"]["event_scan_cron"] = form.get("event_scan_cron", "*/30 9-15 * * 1-5")
    rules["schedules"]["timezone"] = form.get("timezone", "Asia/Kolkata")

    # UI
    rules["ui"]["max_recommendations_per_run"] = int(form.get("max_recommendations_per_run", 25))

    # Save
    try:
        yaml_text = yaml.dump(rules, default_flow_style=False, sort_keys=False, allow_unicode=True)
        save_rules_raw(yaml_text)
        reload_scheduler(pipeline)
        return templates.TemplateResponse(
            "rules.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "rules": rules,
                "error": None,
                "saved": True,
                "active_page": "rules",
            },
        )
    except RuleValidationError as exc:
        yaml_text = load_rules_raw()
        return templates.TemplateResponse(
            "rules.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "rules": rules,
                "error": str(exc),
                "saved": False,
                "active_page": "rules",
            },
            status_code=400,
        )


@app.get("/api/recommendations/latest")
def api_recommendations_latest() -> JSONResponse:
    return JSONResponse(content=_latest_payload())


@app.post("/api/runs/trigger")
def api_trigger_run() -> JSONResponse:
    payload = pipeline.run_scan(run_type="manual_api")
    return JSONResponse(content=payload)


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: int) -> JSONResponse:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse(content={"run": run, "recommendations": db.get_recommendations(run_id)})


@app.get("/api/rules")
def api_rules_get() -> JSONResponse:
    return JSONResponse(content=load_rules())


@app.post("/api/rules")
def api_rules_save(yaml_text: str = Form(...)) -> JSONResponse:
    try:
        parsed = save_rules_raw(yaml_text)
        reload_scheduler(pipeline)
        return JSONResponse(content={"ok": True, "rules": parsed})
    except RuleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
