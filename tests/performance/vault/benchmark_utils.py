"""Назначение:
    Утилиты benchmark-артефактов vault и baseline gate comparison.

Граница ответственности:
    Тестовый performance-модуль (не production runtime).
    Не запускает benchmark и не выполняет операции с filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkGateThresholds:
    """Пороговая политика для baseline comparison gate."""

    regression_threshold_pct: float = 15.0
    busy_timeout_rate_threshold_pct: float = 0.0
    schema_changed_rate_threshold_pct: float = 0.0


def flatten_numeric_metrics(payload: dict[str, Any], *, prefix: str = "") -> dict[str, float]:
    """Развернуть вложенный `dict` в dotted metric-path с числовыми скалярами."""
    flat: dict[str, float] = {}
    for key, value in payload.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_numeric_metrics(value, prefix=dotted))
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            flat[dotted] = float(value)
    return flat


def compare_baseline(
    *,
    current_metrics: dict[str, float],
    baseline_metrics: dict[str, float],
    thresholds: BenchmarkGateThresholds,
) -> dict[str, Any]:
    """Сравнить текущие метрики с baseline и вернуть детали решения по gate."""
    comparisons: list[dict[str, Any]] = []
    failed = False

    for metric, baseline in sorted(baseline_metrics.items()):
        if metric not in current_metrics:
            continue
        current = current_metrics[metric]
        direction = _metric_direction(metric)

        threshold = thresholds.regression_threshold_pct
        if metric.endswith("busy_timeout_rate_pct"):
            threshold = thresholds.busy_timeout_rate_threshold_pct
        elif metric.endswith("schema_changed_rate_pct"):
            threshold = thresholds.schema_changed_rate_threshold_pct

        # Micro-latency метрики чувствительны к jitter планировщика.
        # Для очень малых абсолютных дельт считаем сравнение стабильным.
        if metric.endswith("_ms") and abs(current - baseline) < 0.5:
            regression_pct = 0.0
        else:
            regression_pct = _regression_pct(
                baseline=baseline,
                current=current,
                direction=direction,
            )
        passed = regression_pct <= threshold
        failed = failed or not passed
        comparisons.append(
            {
                "metric": metric,
                "direction": direction,
                "baseline": baseline,
                "current": current,
                "regression_pct": round(regression_pct, 3),
                "threshold_pct": threshold,
                "passed": passed,
            }
        )

    return {
        "gate_passed": not failed,
        "comparisons": comparisons,
    }


def build_markdown_summary(payload: dict[str, Any]) -> str:
    """Построить компактный markdown summary для benchmark-артефакта."""
    meta = payload.get("meta", {})
    metrics = payload.get("metrics", {})
    gate = payload.get("baseline_compare", {})
    comparisons = gate.get("comparisons", []) if isinstance(gate, dict) else []

    lines: list[str] = [
        "# Vault Rollout Benchmark",
        "",
        f"- run_id: `{meta.get('run_id', 'unknown')}`",
        f"- commit: `{meta.get('git_commit', 'unknown')}`",
        f"- profile: `{meta.get('profile', 'unknown')}`",
        f"- gate_passed: `{gate.get('gate_passed', True)}`",
        "",
        "## Metrics",
        "",
    ]
    flat = flatten_numeric_metrics(metrics)
    if not flat:
        lines.append("- (no numeric metrics)")
    else:
        for key, value in sorted(flat.items()):
            lines.append(f"- `{key}`: `{round(value, 3)}`")

    lines.extend(
        [
            "",
            "## Baseline Compare",
            "",
            "| metric | baseline | current | regression_pct | threshold_pct | pass |",
            "|---|---:|---:|---:|---:|:---:|",
        ]
    )
    if not comparisons:
        lines.append("| (no baseline) | - | - | - | - | PASS |")
    else:
        for row in comparisons:
            status = "PASS" if row.get("passed") else "FAIL"
            lines.append(
                "| {metric} | {baseline:.3f} | {current:.3f} | {regression_pct:.3f} | {threshold_pct:.3f} | {status} |".format(
                    metric=row.get("metric", "-"),
                    baseline=float(row.get("baseline", 0.0)),
                    current=float(row.get("current", 0.0)),
                    regression_pct=float(row.get("regression_pct", 0.0)),
                    threshold_pct=float(row.get("threshold_pct", 0.0)),
                    status=status,
                )
            )
    return "\n".join(lines) + "\n"


def _metric_direction(metric_name: str) -> str:
    if metric_name.endswith("_ops_sec") or metric_name.endswith("_throughput_rows_sec"):
        return "higher_better"
    return "lower_better"


def _regression_pct(*, baseline: float, current: float, direction: str) -> float:
    if baseline == 0:
        if current == 0:
            return 0.0
        if direction == "higher_better":
            return 0.0
        return float("inf")

    if direction == "higher_better":
        if current >= baseline:
            return 0.0
        return ((baseline - current) / baseline) * 100.0

    if current <= baseline:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


__all__ = [
    "BenchmarkGateThresholds",
    "build_markdown_summary",
    "compare_baseline",
    "flatten_numeric_metrics",
]
