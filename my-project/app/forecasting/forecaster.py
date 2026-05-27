from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


HORIZONS = [30, 90, 180, 365]
MIN_HISTORY_DAYS = 30
ARIMA_ORDER = (1, 1, 1)


@dataclass
class ForecastResult:
    horizon_days: int
    predicted_size: float
    confidence_lower: float | None
    confidence_upper: float | None
    confidence_score: float
    model: str
    history_days: int


@dataclass
class ForecastUnavailable:
    reason: str
    history_days: int
    required_days: int = MIN_HISTORY_DAYS


def forecast_cluster(
    sizes: list[float],
    *,
    distinct_sources: int = 1,
) -> list[ForecastResult] | ForecastUnavailable:
    history_days = len(sizes)

    if history_days < MIN_HISTORY_DAYS:
        return ForecastUnavailable(
            reason=f"need at least {MIN_HISTORY_DAYS} days of history, have {history_days}",
            history_days=history_days,
        )

    series = np.asarray(sizes, dtype=float)

    try:
        results = _forecast_arima(series)
        model_name = f"arima{ARIMA_ORDER}"
    except Exception as exc:
        logger.info("forecaster: ARIMA failed (%s), falling back to linear", exc)
        try:
            results = _forecast_linear(series)
            model_name = "linear"
        except Exception as exc2:
            logger.warning("forecaster: linear fallback also failed: %s", exc2)
            current = float(series[-1])
            results = {
                h: (current, current * 0.5, current * 1.5)
                for h in HORIZONS
            }
            model_name = "flat"

    confidence = _confidence_score(
        series=series,
        distinct_sources=distinct_sources,
    )

    return [
        ForecastResult(
            horizon_days=h,
            predicted_size=max(0.0, results[h][0]),
            confidence_lower=max(0.0, results[h][1]) if results[h][1] is not None else None,
            confidence_upper=results[h][2],
            confidence_score=confidence,
            model=model_name,
            history_days=history_days,
        )
        for h in HORIZONS
    ]


def _forecast_arima(series: np.ndarray) -> dict[int, tuple[float, float, float]]:
    from statsmodels.tsa.arima.model import ARIMA

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ARIMA(series, order=ARIMA_ORDER)
        fit = model.fit()

    max_horizon = max(HORIZONS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        forecast_obj = fit.get_forecast(steps=max_horizon)
        predicted_mean = forecast_obj.predicted_mean
        conf_int = forecast_obj.conf_int(alpha=0.05)

    results: dict[int, tuple[float, float, float]] = {}
    for h in HORIZONS:
        idx = h - 1
        mean = float(predicted_mean[idx])
        lower = float(conf_int[idx, 0])
        upper = float(conf_int[idx, 1])
        results[h] = (mean, lower, upper)

    return results


def _forecast_linear(series: np.ndarray) -> dict[int, tuple[float, float, float]]:
    n = len(series)
    t = np.arange(n, dtype=float)

    slope, intercept = np.polyfit(t, series, 1)

    fitted = slope * t + intercept
    residuals = series - fitted
    residual_std = float(np.std(residuals))

    results: dict[int, tuple[float, float, float]] = {}
    for h in HORIZONS:
        future_t = n + h - 1
        mean = float(slope * future_t + intercept)
        widening = math.sqrt(h)
        margin = 1.96 * residual_std * widening
        results[h] = (mean, mean - margin, mean + margin)

    return results


def _confidence_score(
    series: np.ndarray,
    *,
    distinct_sources: int,
) -> float:
    history_days = len(series)
    data_factor = min(1.0, history_days / 90.0)

    mean = float(np.mean(series))
    std = float(np.std(series))
    if mean > 0:
        cv = std / mean
    else:
        cv = 0.0 if std == 0 else 10.0
    variance_factor = math.exp(-min(cv, 10.0))

    source_factor = min(1.0, distinct_sources / 5.0)

    score = (
        0.4 * data_factor +
        0.4 * variance_factor +
        0.2 * source_factor
    )
    return max(0.0, min(1.0, score))
