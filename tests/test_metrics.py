"""Tests for metric tracking."""
import json
import tempfile
from pathlib import Path

from harness_core.metrics import extract_metric, report_summary, metric_trend, trend_direction, log_result


def test_extract_metric():
    d = Path(tempfile.mkdtemp())
    report = d / "report.json"
    report.write_text(json.dumps({"precision_at_5": 0.34, "recall_at_5": 0.92}))
    assert extract_metric(report, "precision_at_5") == 0.34
    assert extract_metric(report, "missing") is None


def test_extract_metric_missing_file():
    assert extract_metric(Path("/nonexistent"), "field") is None


def test_report_summary():
    d = Path(tempfile.mkdtemp())
    report = d / "report.json"
    report.write_text(json.dumps({"total": 20, "passed": 15, "items": [1, 2, 3]}))
    s = report_summary(report)
    assert s["total"] == 20
    assert s["passed"] == 15
    assert s["items_count"] == 3


def test_report_summary_missing_file():
    assert report_summary(Path("/nonexistent")) is None


def test_report_summary_invalid_json():
    d = Path(tempfile.mkdtemp())
    report = d / "report.json"
    report.write_text("not json at all {{{")
    s = report_summary(report)
    assert s == {"parse_error": True}


def test_report_summary_non_dict():
    d = Path(tempfile.mkdtemp())
    report = d / "report.json"
    report.write_text(json.dumps([1, 2, 3]))
    s = report_summary(report)
    assert s == {"type": "list"}


def test_metric_trend():
    d = Path(tempfile.mkdtemp())
    history = d / "history.jsonl"
    for val in [0.30, 0.35, 0.40, 0.38]:
        log_result(history, {"primary_metric": val})
    trend = metric_trend(history, field="primary_metric")
    assert trend == [0.30, 0.35, 0.40, 0.38]


def test_metric_trend_limit():
    d = Path(tempfile.mkdtemp())
    history = d / "history.jsonl"
    for val in range(20):
        log_result(history, {"primary_metric": val})
    trend = metric_trend(history, field="primary_metric", limit=5)
    assert trend == [15, 16, 17, 18, 19]


def test_trend_direction_improving():
    assert trend_direction([0.5, 0.4, 0.3]) == "improving"


def test_trend_direction_stalled():
    assert trend_direction([0.5, 0.5, 0.5]) == "stalled"


def test_trend_direction_regressing():
    assert trend_direction([0.3, 0.4]) == "regressing"


def test_trend_direction_insufficient():
    assert trend_direction([0.5]) == "insufficient_data"


def test_trend_direction_two_improving():
    assert trend_direction([0.5, 0.3]) == "improving"


def test_trend_direction_flat():
    assert trend_direction([0.5, 0.5]) == "flat"


def test_log_result():
    d = Path(tempfile.mkdtemp())
    history = d / "sub" / "history.jsonl"
    log_result(history, {"commit": "abc", "metric": 0.5, "status": "keep"})
    log_result(history, {"commit": "def", "metric": 0.6, "status": "discard"})
    lines = history.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["commit"] == "abc"
