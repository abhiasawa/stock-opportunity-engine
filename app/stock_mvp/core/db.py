from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .settings import DB_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            rules_snapshot TEXT NOT NULL,
            summary_json TEXT,
            error_text TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL,
            sector TEXT NOT NULL,
            market_cap_cr REAL NOT NULL,
            pe REAL NOT NULL,
            final_score REAL NOT NULL,
            score_breakdown_json TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_recommendations_run_id ON recommendations(run_id)")

    # Add metrics_json column if missing (for existing DBs)
    try:
        cur.execute("ALTER TABLE recommendations ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Fundamentals cache — stores everything except live price
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_cache (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL,
            sector TEXT NOT NULL,
            market_cap_cr REAL NOT NULL,
            pe REAL NOT NULL,
            profit_ttm_cr REAL NOT NULL,
            profit_prev_ttm_cr REAL NOT NULL,
            profit_q1_cr REAL NOT NULL,
            profit_q2_cr REAL NOT NULL,
            profit_q3_cr REAL NOT NULL,
            profit_q4_cr REAL NOT NULL,
            promoter_holding_pct REAL NOT NULL,
            pledge_pct REAL NOT NULL,
            hni_net_buying_cr REAL NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            fetched_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def create_run(run_type: str, rules_snapshot: dict[str, Any]) -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO runs (run_type, started_at, status, rules_snapshot)
        VALUES (?, ?, ?, ?)
        """,
        (
            run_type,
            utc_now_iso(),
            "running",
            json.dumps(rules_snapshot, ensure_ascii=True),
        ),
    )
    run_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return run_id


def complete_run(run_id: int, summary: dict[str, Any]) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE runs
        SET completed_at = ?, status = ?, summary_json = ?
        WHERE id = ?
        """,
        (utc_now_iso(), "completed", json.dumps(summary, ensure_ascii=True), run_id),
    )
    conn.commit()
    conn.close()


def fail_run(run_id: int, error_text: str) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE runs
        SET completed_at = ?, status = ?, error_text = ?
        WHERE id = ?
        """,
        (utc_now_iso(), "failed", error_text, run_id),
    )
    conn.commit()
    conn.close()


def insert_recommendations(run_id: int, rows: list[dict[str, Any]]) -> None:
    conn = _connect()
    cur = conn.cursor()

    payload = []
    for row in rows:
        payload.append(
            (
                run_id,
                row["rank"],
                row["symbol"],
                row["name"],
                row["exchange"],
                row["sector"],
                float(row["market_cap_cr"]),
                float(row["pe"]),
                float(row["final_score"]),
                json.dumps(row["score_breakdown"], ensure_ascii=True),
                json.dumps(row["reasons"], ensure_ascii=True),
                int(row["event_count"]),
                json.dumps(row.get("metrics", {}), ensure_ascii=True),
                utc_now_iso(),
            )
        )

    cur.executemany(
        """
        INSERT INTO recommendations (
            run_id, rank, symbol, name, exchange, sector, market_cap_cr, pe,
            final_score, score_breakdown_json, reasons_json, event_count,
            metrics_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )

    conn.commit()
    conn.close()


def _parse_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_type": row["run_type"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "status": row["status"],
        "rules_snapshot": json.loads(row["rules_snapshot"]),
        "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
        "error_text": row["error_text"],
    }


def _parse_recommendation(row: sqlite3.Row) -> dict[str, Any]:
    metrics_raw = row["metrics_json"] if "metrics_json" in row.keys() else "{}"
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "rank": row["rank"],
        "symbol": row["symbol"],
        "name": row["name"],
        "exchange": row["exchange"],
        "sector": row["sector"],
        "market_cap_cr": row["market_cap_cr"],
        "pe": row["pe"],
        "final_score": row["final_score"],
        "score_breakdown": json.loads(row["score_breakdown_json"]),
        "reasons": json.loads(row["reasons_json"]),
        "event_count": row["event_count"],
        "metrics": json.loads(metrics_raw) if metrics_raw else {},
        "created_at": row["created_at"],
    }


def get_latest_run() -> dict[str, Any] | None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return _parse_run(row)


def list_runs(limit: int = 30) -> list[dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [_parse_run(r) for r in rows]


def get_run(run_id: int) -> dict[str, Any] | None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return _parse_run(row)


def get_recommendations(run_id: int) -> list[dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM recommendations WHERE run_id = ? ORDER BY rank ASC, final_score DESC",
        (run_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [_parse_recommendation(r) for r in rows]


# ── Stock fundamentals cache ──────────────────────────────────────


def get_cached_fundamentals(symbols: list[str], max_age_days: int = 90) -> dict[str, dict[str, Any]]:
    """Return cached fundamentals for symbols that are fresh enough."""
    if not symbols:
        return {}
    conn = _connect()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in symbols)
    cur.execute(f"SELECT * FROM stock_cache WHERE symbol IN ({placeholders})", symbols)
    rows = cur.fetchall()
    conn.close()

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    result: dict[str, dict[str, Any]] = {}

    for row in rows:
        fetched_at_str = row["fetched_at"]
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if fetched_at < cutoff:
            continue
        result[row["symbol"]] = {
            "symbol": row["symbol"],
            "name": row["name"],
            "exchange": row["exchange"],
            "sector": row["sector"],
            "market_cap_cr": row["market_cap_cr"],
            "pe": row["pe"],
            "profit_ttm_cr": row["profit_ttm_cr"],
            "profit_prev_ttm_cr": row["profit_prev_ttm_cr"],
            "profit_q1_cr": row["profit_q1_cr"],
            "profit_q2_cr": row["profit_q2_cr"],
            "profit_q3_cr": row["profit_q3_cr"],
            "profit_q4_cr": row["profit_q4_cr"],
            "promoter_holding_pct": row["promoter_holding_pct"],
            "pledge_pct": row["pledge_pct"],
            "hni_net_buying_cr": row["hni_net_buying_cr"],
            "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else {},
        }
    return result


def upsert_fundamentals_cache(entries: list[dict[str, Any]]) -> None:
    """Insert or update fundamentals cache entries."""
    if not entries:
        return
    conn = _connect()
    cur = conn.cursor()
    for e in entries:
        cur.execute(
            """
            INSERT INTO stock_cache (
                symbol, name, exchange, sector, market_cap_cr, pe,
                profit_ttm_cr, profit_prev_ttm_cr,
                profit_q1_cr, profit_q2_cr, profit_q3_cr, profit_q4_cr,
                promoter_holding_pct, pledge_pct, hni_net_buying_cr,
                metrics_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name,
                exchange=excluded.exchange,
                sector=excluded.sector,
                market_cap_cr=excluded.market_cap_cr,
                pe=excluded.pe,
                profit_ttm_cr=excluded.profit_ttm_cr,
                profit_prev_ttm_cr=excluded.profit_prev_ttm_cr,
                profit_q1_cr=excluded.profit_q1_cr,
                profit_q2_cr=excluded.profit_q2_cr,
                profit_q3_cr=excluded.profit_q3_cr,
                profit_q4_cr=excluded.profit_q4_cr,
                promoter_holding_pct=excluded.promoter_holding_pct,
                pledge_pct=excluded.pledge_pct,
                hni_net_buying_cr=excluded.hni_net_buying_cr,
                metrics_json=excluded.metrics_json,
                fetched_at=excluded.fetched_at
            """,
            (
                e["symbol"],
                e["name"],
                e["exchange"],
                e["sector"],
                float(e["market_cap_cr"]),
                float(e["pe"]),
                float(e["profit_ttm_cr"]),
                float(e["profit_prev_ttm_cr"]),
                float(e["profit_q1_cr"]),
                float(e["profit_q2_cr"]),
                float(e["profit_q3_cr"]),
                float(e["profit_q4_cr"]),
                float(e["promoter_holding_pct"]),
                float(e["pledge_pct"]),
                float(e["hni_net_buying_cr"]),
                json.dumps(e.get("metrics", {}), ensure_ascii=True),
                utc_now_iso(),
            ),
        )
    conn.commit()
    conn.close()
