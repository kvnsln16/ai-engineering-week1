# Forecasting — Documentation

Companion to `scoring.md`. This document explains how the forecaster
generates predictions, what the confidence score means, and how to
read API responses honestly.

Implementation: `app/forecasting/`. Code-level comments mirror this doc
— editing one and not the other will drift.

## Overview

For each cluster in the top-20 by composite score, the system forecasts
how large that cluster will be at four future horizons:

- 30 days
- 90 days
- 180 days
- 365 days

Each forecast comes with two separate measures of confidence:

| Measure              | What it is                                          | Range          |
| -------------------- | --------------------------------------------------- | -------------- |
| `confidence_lower/upper` | Statistical 95% confidence interval from the model | size units     |
| `confidence_score`   | Our own quality assessment of the forecast          | 0.0 to 1.0     |

A forecast can have a high `confidence_score` (we trust the inputs) but
wide statistical confidence intervals (the model itself isn't sure).
Both numbers matter and they answer different questions.

## Model: ARIMA(1,1,1) with linear fallback

Primary: **ARIMA(1,1,1)** via statsmodels.
- `p=1` — one autoregressive term (yesterday matters)
- `d=1` — one differencing (removes linear trend)
- `q=1` — one moving average term (smooths noise)

This is a defensible default for time-series with trend and short-term
autocorrelation. Not the best for every cluster — clusters with strong
weekly seasonality would benefit from SARIMA, for example — but a solid
baseline that fits the wide variety of patterns we see.

Fallback: **simple linear regression** over the historical points,
with confidence intervals from residual standard deviation, widened by
√horizon to reflect growing uncertainty over time.

The fallback fires when ARIMA fails to converge or the series is too
weird (singular matrix, constant values, etc.). Both outcomes are valid
— we always return *something* rather than crashing.

## When does forecasting run?

After clustering and scoring each daily run, the scheduler:

1. Pulls the top 20 clusters by `composite_score`
2. For each, loads the full `cluster_history` series
3. Runs the forecaster at all four horizons
4. Writes results to the `forecasts` table

Only the top-20 are forecasted. Predicting every cluster would waste
compute on noise.

## Minimum history requirement

**A cluster needs at least 30 days of history before we forecast it.**

Why: forecasting 365 days into the future from 5 data points is
statistically meaningless. We'd be producing numbers, not predictions.
The minimum threshold keeps the system honest.

What this means in practice:
- Day 1 of the pipeline: every cluster returns `insufficient_history`
- Day 30+: clusters with continuous history start getting real forecasts
- Day 90+: forecasts become substantially more reliable

The API endpoint `/forecasts/cluster/{id}` returns a clear status when
there isn't enough history, rather than fake numbers:

```json
{
  "cluster_id": 7,
  "label": "Boston, Robotics, Humanoid",
  "status": "insufficient_history",
  "history_days": 1,
  "required_days": 30,
  "message": "Need at least 30 days of cluster history to forecast. Currently have 1.",
  "forecasts": []
}
```

## Confidence Score

This is our own 0..1 quality measure, separate from the statistical
confidence intervals.

**Formula:**
```
data_factor     = min(1.0, history_days / 90)
variance_factor = exp(-coefficient_of_variation)
source_factor   = min(1.0, distinct_sources / 5)

confidence_score = 0.4 * data_factor
                 + 0.4 * variance_factor
                 + 0.2 * source_factor
```

**Behavior:**
- `data_factor` — saturates at 90 days of history. More history = more confidence, but with diminishing returns.
- `variance_factor` — penalizes clusters with high relative variability (CV = std/mean). A stable cluster scores high; a chaotic cluster scores low.
- `source_factor` — saturates at 5 distinct sources. A topic confirmed by many sources is more credible.

**Interpretation:**
- `confidence_score >= 0.7` — reliable forecast, use as a primary signal
- `confidence_score 0.4 - 0.7` — useful but treat as directional, not precise
- `confidence_score < 0.4` — weak forecast, treat with skepticism

## Statistical Confidence Intervals

These come directly from the model:
- For ARIMA: 95% CIs from statsmodels' `get_forecast(...).conf_int()`
- For the linear fallback: ±1.96 × residual_std × √horizon

**Reading them:**
- A narrow interval means the model is confident about the point estimate
- A wide interval means the model thinks the value could realistically be anywhere in that range
- Intervals always widen at longer horizons (predicting farther = more uncertainty)

**Important:** these intervals reflect *statistical uncertainty assuming
the model is correct*. They don't account for "this newsletter ecosystem
might collapse" or "a new product launch could change everything." Real
confidence is `min(confidence_score, narrow_CI)`.

## Validation

The `validate_forecasts.py` script runs two suites:

### 1. Synthetic patterns (always runs)

Three generated time series with known shapes:
- **Linear growth** — `y = a + b*t` plus small noise
- **Seasonal** — sinusoidal around a constant mean
- **Exponential decay** — `y = a * exp(-b*t)` plus noise

For each, we check that the forecaster correctly extrapolates the
pattern within a reasonable tolerance.

### 2. Real-world (Google Trends)

Pulls 12 months of Google Trends data for three keywords:
- `ChatGPT` — recent explosive growth
- `Stable Diffusion` — spike then plateau
- `Bitcoin` — cyclic, well-known pattern

For each, we split 80/20 train/test, forecast the held-out period, and
compute MAPE (mean absolute percentage error). Passing threshold: MAPE
under 40%.

Google Trends uses an unofficial scraping endpoint via `pytrends`.
It's free but fragile. When the endpoint is unreachable (network issues,
rate limiting), the real-world tests are silently skipped and only
synthetic results are reported.

### Running validation

```bash
python validate_forecasts.py              # full suite
python validate_forecasts.py --no-trends  # synthetic only (offline-safe)
python validate_forecasts.py -v           # with detailed logging
```

Exit code is non-zero if any case fails, so this can be wired into CI.

## Querying forecasts

```
GET /forecasts/horizon/30          — top 20 30-day forecasts
GET /forecasts/horizon/90          — top 20 90-day forecasts
GET /forecasts/horizon/180         — top 20 180-day forecasts
GET /forecasts/horizon/365         — top 20 365-day forecasts
GET /forecasts/cluster/{id}        — all 4 horizons for one cluster
GET /forecasts/stats               — counts + coverage
```

Or query the database directly:

```sql
SELECT c.label, f.horizon_days, f.predicted_size,
       f.confidence_lower, f.confidence_upper, f.confidence_score
FROM forecasts f
JOIN clusters c ON c.id = f.cluster_id
WHERE f.horizon_days = 30
ORDER BY f.predicted_size DESC
LIMIT 20;
```

## Limitations

1. **Cold start.** First 30 days of pipeline operation produce zero
   forecasts. This is by design.

2. **Cluster identity instability.** Cluster IDs change between runs
   (HDBSCAN doesn't produce stable IDs). A cluster's history accrues
   per-day under whichever ID it had on that day. For long-term trend
   tracking of *specific topics*, you'd need centroid-based matching
   across runs — a follow-up task.

3. **No seasonality detection.** ARIMA(1,1,1) doesn't model weekly or
   monthly cycles. If you find your data has strong weekly patterns,
   switch to SARIMA in `forecaster.py`.

4. **365-day forecasts are speculative.** Confidence intervals for
   far-future predictions are wide for a reason. Use them as directional
   indicators, not precise targets.
