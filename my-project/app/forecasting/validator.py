from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.forecasting.forecaster import forecast_cluster, ForecastResult
from app.forecasting.google_trends import fetch_multiple

logger = logging.getLogger(__name__)


TRENDS_KEYWORDS = [
    "ChatGPT",
    "Stable Diffusion",
    "Bitcoin",
]

SYNTHETIC_TOLERANCE = 0.30

REAL_WORLD_MAPE_THRESHOLD = 40.0


@dataclass
class ValidationCase:
    name: str
    passed: bool
    detail: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ValidationReport:
    synthetic_cases: list[ValidationCase] = field(default_factory=list)
    real_world_cases: list[ValidationCase] = field(default_factory=list)

    @property
    def total_passed(self) -> int:
        return (
            sum(1 for c in self.synthetic_cases if c.passed) +
            sum(1 for c in self.real_world_cases if c.passed)
        )

    @property
    def total_cases(self) -> int:
        return len(self.synthetic_cases) + len(self.real_world_cases)


def validate_forecaster(*, include_real_world: bool = True) -> ValidationReport:
    report = ValidationReport()

    report.synthetic_cases.extend(_run_synthetic_validation())

    if include_real_world:
        report.real_world_cases.extend(_run_real_world_validation())

    logger.info(
        "validator: %d/%d cases passed",
        report.total_passed, report.total_cases,
    )
    return report


def _run_synthetic_validation() -> list[ValidationCase]:
    cases: list[ValidationCase] = []

    sizes = _generate_linear(start=10, slope=0.5, days=90)
    expected_at_30 = sizes[-1] + 0.5 * 30
    cases.append(_check_synthetic(
        name="linear_growth",
        sizes=sizes,
        horizon=30,
        expected=expected_at_30,
    ))

    sizes = _generate_seasonal(mean=50, amplitude=15, period=30, days=120)
    cases.append(_check_synthetic(
        name="seasonal",
        sizes=sizes,
        horizon=90,
        expected=50.0,
        tolerance=0.5,
    ))

    sizes = _generate_decay(start=100, half_life_days=30, days=90)
    expected_at_30 = sizes[-1] * 0.5
    cases.append(_check_synthetic(
        name="exponential_decay",
        sizes=sizes,
        horizon=30,
        expected=expected_at_30,
        tolerance=1.0,
    ))

    return cases


def _check_synthetic(
    *,
    name: str,
    sizes: list[float],
    horizon: int,
    expected: float,
    tolerance: float = SYNTHETIC_TOLERANCE,
) -> ValidationCase:
    result = forecast_cluster(sizes, distinct_sources=3)
    if not isinstance(result, list):
        return ValidationCase(
            name=name,
            passed=False,
            detail=f"forecaster declined: {result.reason}",
        )

    forecast: ForecastResult | None = next(
        (f for f in result if f.horizon_days == horizon), None,
    )
    if forecast is None:
        return ValidationCase(
            name=name,
            passed=False,
            detail=f"no forecast returned for horizon {horizon}",
        )

    if expected == 0:
        relative_error = abs(forecast.predicted_size)
    else:
        relative_error = abs(forecast.predicted_size - expected) / abs(expected)

    passed = relative_error <= tolerance

    return ValidationCase(
        name=name,
        passed=passed,
        detail=(
            f"expected~{expected:.1f}, got={forecast.predicted_size:.1f}, "
            f"err={relative_error:.1%}, tol={tolerance:.0%}, model={forecast.model}"
        ),
        metrics={
            "expected": expected,
            "predicted": forecast.predicted_size,
            "relative_error": relative_error,
            "tolerance": tolerance,
            "model_confidence": forecast.confidence_score,
        },
    )


def _generate_linear(*, start: float, slope: float, days: int) -> list[float]:
    rng = np.random.default_rng(42)
    base = np.array([start + slope * t for t in range(days)])
    noise = rng.normal(0, 1.0, size=days)
    return list((base + noise).tolist())


def _generate_seasonal(
    *, mean: float, amplitude: float, period: int, days: int,
) -> list[float]:
    rng = np.random.default_rng(43)
    base = np.array([
        mean + amplitude * math.sin(2 * math.pi * t / period)
        for t in range(days)
    ])
    noise = rng.normal(0, 1.5, size=days)
    return list((base + noise).tolist())


def _generate_decay(
    *, start: float, half_life_days: float, days: int,
) -> list[float]:
    rng = np.random.default_rng(44)
    decay_const = math.log(2) / half_life_days
    base = np.array([start * math.exp(-decay_const * t) for t in range(days)])
    noise = rng.normal(0, 0.5, size=days)
    return list((np.maximum(0, base + noise)).tolist())


def _run_real_world_validation() -> list[ValidationCase]:
    cases: list[ValidationCase] = []

    logger.info("validator: fetching Google Trends data (may be slow)")
    series_by_keyword = fetch_multiple(TRENDS_KEYWORDS, timeframe="today 12-m")

    if not series_by_keyword:
        cases.append(ValidationCase(
            name="real_world_trends_unavailable",
            passed=False,
            detail="Google Trends fetch returned no data — skipped",
        ))
        return cases

    for keyword, series in series_by_keyword.items():
        cases.append(_check_real_world(keyword, series))

    return cases


def _check_real_world(keyword: str, series: list[int]) -> ValidationCase:
    n = len(series)
    if n < 50:
        return ValidationCase(
            name=f"real_world:{keyword}",
            passed=False,
            detail=f"only {n} points — need at least 50",
        )

    split = int(n * 0.8)
    train = series[:split]
    test = series[split:]
    test_horizon_days = len(test)

    nearest_horizon = min([30, 90, 180, 365], key=lambda h: abs(h - test_horizon_days * 7))

    result = forecast_cluster(
        sizes=[float(v) for v in train],
        distinct_sources=3,
    )
    if not isinstance(result, list):
        return ValidationCase(
            name=f"real_world:{keyword}",
            passed=False,
            detail=f"forecaster declined: {result.reason}",
        )

    forecast = next((f for f in result if f.horizon_days == nearest_horizon), None)
    if forecast is None:
        return ValidationCase(
            name=f"real_world:{keyword}",
            passed=False,
            detail=f"no forecast at horizon {nearest_horizon}",
        )

    actual_mean = float(np.mean(test))
    if actual_mean == 0:
        return ValidationCase(
            name=f"real_world:{keyword}",
            passed=False,
            detail="actual mean is zero, cannot compute MAPE",
        )

    mape = 100.0 * abs(forecast.predicted_size - actual_mean) / abs(actual_mean)
    passed = mape <= REAL_WORLD_MAPE_THRESHOLD

    return ValidationCase(
        name=f"real_world:{keyword}",
        passed=passed,
        detail=(
            f"actual_mean={actual_mean:.1f}, predicted={forecast.predicted_size:.1f}, "
            f"MAPE={mape:.1f}%, threshold={REAL_WORLD_MAPE_THRESHOLD}%"
        ),
        metrics={
            "actual_mean": actual_mean,
            "predicted": forecast.predicted_size,
            "mape": mape,
            "threshold": REAL_WORLD_MAPE_THRESHOLD,
        },
    )
