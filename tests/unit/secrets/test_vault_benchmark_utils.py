from __future__ import annotations

from connector.infra.secrets.benchmark_gate import (
    BenchmarkGateThresholds,
    build_markdown_summary,
    compare_baseline,
    flatten_numeric_metrics,
)


def test_flatten_numeric_metrics_ignores_bool_values() -> None:
    flat = flatten_numeric_metrics(
        {
            "crypto": {"encrypt_p95_ms": 1.2, "enabled": True},
            "contention": {"busy_timeout_rate_pct": 0},
        }
    )
    assert "crypto.encrypt_p95_ms" in flat
    assert "crypto.enabled" not in flat
    assert flat["contention.busy_timeout_rate_pct"] == 0.0


def test_compare_baseline_detects_regression_for_lower_better_metric() -> None:
    compared = compare_baseline(
        current_metrics={"crypto.encrypt_p95_ms": 2.0},
        baseline_metrics={"crypto.encrypt_p95_ms": 1.0},
        thresholds=BenchmarkGateThresholds(regression_threshold_pct=15.0),
    )
    assert compared["gate_passed"] is False
    first = compared["comparisons"][0]
    assert first["metric"] == "crypto.encrypt_p95_ms"
    assert first["passed"] is False


def test_compare_baseline_detects_regression_for_higher_better_metric() -> None:
    compared = compare_baseline(
        current_metrics={"e2e.apply_throughput_rows_sec": 80.0},
        baseline_metrics={"e2e.apply_throughput_rows_sec": 100.0},
        thresholds=BenchmarkGateThresholds(regression_threshold_pct=15.0),
    )
    assert compared["gate_passed"] is False
    first = compared["comparisons"][0]
    assert first["metric"] == "e2e.apply_throughput_rows_sec"
    assert first["passed"] is False


def test_build_markdown_summary_contains_gate_and_table() -> None:
    markdown = build_markdown_summary(
        {
            "meta": {"run_id": "run-1", "git_commit": "abc", "profile": "fast"},
            "metrics": {"crypto": {"encrypt_p95_ms": 1.0}},
            "baseline_compare": {
                "gate_passed": True,
                "comparisons": [
                    {
                        "metric": "crypto.encrypt_p95_ms",
                        "baseline": 1.0,
                        "current": 1.0,
                        "regression_pct": 0.0,
                        "threshold_pct": 15.0,
                        "passed": True,
                    }
                ],
            },
        }
    )
    assert "gate_passed" in markdown
    assert "crypto.encrypt_p95_ms" in markdown
    assert "| metric | baseline | current | regression_pct | threshold_pct | pass |" in markdown
