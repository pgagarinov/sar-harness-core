"""Metric tracking for autonomous research loops."""
import json
from pathlib import Path
from typing import Any


def extract_metric(report_path: Path, field: str) -> Any:
    """Read a JSON report and extract a scalar metric field."""
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data.get(field)


def report_summary(report_path: Path) -> dict | None:
    """Extract all scalar values and list counts from a JSON report."""
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"parse_error": True}
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    summary = {}
    for key, value in payload.items():
        if isinstance(value, (int, float, str, bool, type(None))):
            summary[key] = value
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary


def metric_trend(history_path: Path, field: str = "primary_metric", limit: int = 10) -> list[int | float]:
    """Extract recent metric values from a JSONL history file."""
    if not history_path.exists():
        return []
    counts = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            value = entry.get(field)
            if value is not None:
                counts.append(value)
        except json.JSONDecodeError:
            continue
    return counts[-limit:]


def trend_direction(trend: list[int | float]) -> str:
    """Classify metric trend as improving, stalled, regressing, or flat."""
    if len(trend) < 2:
        return "insufficient_data"
    if len(trend) >= 3 and trend[-1] < trend[-2] < trend[-3]:
        return "improving"
    if len(trend) >= 3 and all(abs(trend[-1] - trend[-(i + 1)]) <= 0.02 for i in range(1, min(3, len(trend)))):
        return "stalled"
    if trend[-1] > trend[-2]:
        return "regressing"
    if trend[-1] < trend[-2]:
        return "improving"
    return "flat"


def log_result(history_path: Path, entry: dict) -> None:
    """Append a result entry to a JSONL history file."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
