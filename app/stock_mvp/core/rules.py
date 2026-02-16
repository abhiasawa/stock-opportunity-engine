from __future__ import annotations

from typing import Any

import yaml

from .settings import RULES_PATH


class RuleValidationError(ValueError):
    pass


def _required_keys() -> dict[str, list[str]]:
    return {
        "root": [
            "data_provider",
            "universe",
            "filters",
            "weights",
            "event_weights",
            "schedules",
            "ui",
        ],
        "weights": ["profit_trend", "valuation", "future_events", "quality", "risk"],
        "schedules": ["full_scan_cron", "event_scan_cron", "timezone"],
    }


def validate_rules(rules: dict[str, Any]) -> None:
    required = _required_keys()

    for key in required["root"]:
        if key not in rules:
            raise RuleValidationError(f"Missing root key: {key}")

    for key in required["weights"]:
        if key not in rules["weights"]:
            raise RuleValidationError(f"Missing weights.{key}")

    for key in required["schedules"]:
        if key not in rules["schedules"]:
            raise RuleValidationError(f"Missing schedules.{key}")

    weight_sum = (
        float(rules["weights"]["profit_trend"])
        + float(rules["weights"]["valuation"])
        + float(rules["weights"]["future_events"])
        + float(rules["weights"]["quality"])
    )
    if weight_sum <= 0:
        raise RuleValidationError("Sum of positive weights must be > 0")

    if float(rules["weights"]["risk"]) < 0:
        raise RuleValidationError("weights.risk must be >= 0")


def load_rules() -> dict[str, Any]:
    if not RULES_PATH.exists():
        raise RuleValidationError(f"Rules file not found: {RULES_PATH}")

    with RULES_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise RuleValidationError("Rules YAML must parse into a dictionary")

    validate_rules(data)
    return data


def load_rules_raw() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


def save_rules_raw(yaml_text: str) -> dict[str, Any]:
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise RuleValidationError("Rules YAML must parse into a dictionary")

    validate_rules(parsed)
    RULES_PATH.write_text(yaml_text, encoding="utf-8")
    return parsed
