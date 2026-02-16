"""Global scan status tracker — lets the UI poll progress."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScanProgress:
    running: bool = False
    phase: str = ""           # "fetching_fundamentals", "fetching_prices", "scoring", etc.
    current: int = 0          # current symbol index
    total: int = 0            # total symbols
    symbol: str = ""          # symbol being processed right now
    started_at: str = ""
    message: str = ""         # human-readable status

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "phase": self.phase,
            "current": self.current,
            "total": self.total,
            "symbol": self.symbol,
            "started_at": self.started_at,
            "message": self.message,
            "pct": round(self.current / max(self.total, 1) * 100),
        }


_lock = threading.Lock()
_status = ScanProgress()


def get_scan_status() -> dict:
    with _lock:
        return _status.to_dict()


def start_scan(total: int) -> None:
    with _lock:
        _status.running = True
        _status.phase = "starting"
        _status.current = 0
        _status.total = total
        _status.symbol = ""
        _status.started_at = datetime.now(timezone.utc).isoformat()
        _status.message = f"Starting scan of {total} symbols..."


def update_scan(phase: str, current: int, symbol: str = "", message: str = "") -> None:
    with _lock:
        _status.phase = phase
        _status.current = current
        _status.symbol = symbol
        _status.message = message


def finish_scan(message: str = "Scan complete") -> None:
    with _lock:
        _status.running = False
        _status.phase = "done"
        _status.current = _status.total
        _status.message = message
