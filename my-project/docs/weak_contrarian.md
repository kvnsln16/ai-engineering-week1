# Weak Signal & Contrarian Detection — Documentation

Companion to `scoring.md`, `forecasting.md`, `predictions.md`, and
`reporting.md`. This document explains the specialized rules for two
report sections that surface non-obvious patterns in the signal data.

Implementation: `app/reporting/analyses.py`.

## Why these are special

Most reports focus on what's *biggest* (top clusters, highest scores).
Weak signal and contrarian detection surface what's *interesting*
despite being small or going against the grain — exactly the kind of
patterns that get overlooked by score-ranking alone.

| Section | What it surfaces | Why it matters |
|---------|------------------|----------------|
| Weak Signal | Small but cross-sourced rising clusters | Early indicators before topics break out |
| Contrarian | Clusters diverging from industry consensus | Hidden risks or contrarian opportunities |

## Weak Signal Detection

### Definition

> Clusters with small size but high source diversity, indicating early
> cross-confirmed interest. When historical data is available, we also
> require the cluster to be growing or stable (not fading).

### Two-tier detection

The system runs two passes and merges results to guarantee at least
3 entries in the report:

**Tier 1 (strict):** cluster size 3-6 AND at least 3 distinct sources
AND not fading. Labelled `kind = "strict"` in the output.

**Tier 2 (candidate fallback):** cluster size up to 10 AND at least 2
distinct sources. Used to pad the report when strict matches are scarce.
Labelled `kind = "candidate"`.

Both kinds appear in the same report section but are labelled so
reviewers know which detections are high-confidence vs lower-bar.

### Rising / stable / fading

When cluster_history has at least 3 days of data for a cluster:

```
recent_avg = average of the most recent 3 days
earlier_avg = average of older days

is_rising_or_stable = (recent_avg >= earlier_avg * 0.9)
```

We allow up to 10% decline before classifying as fading — small daily
fluctuations shouldn't disqualify a cluster.

When there's <3 days of history, direction is `unknown` and the cluster
remains eligible. This is the "lenient day-1" behavior — strict checks
kick in as data accrues.

### Output structure

Each weak signal includes:

| Field | Type | Description |
|-------|------|-------------|
| `cluster_id` | int | Reference to clusters table |
| `label` | str | Top-keywords label |
| `industry` | str | Detected industry |
| `size` | int | Current signal count |
| `distinct_sources` | int | Number of unique sources |
| `kind` | str | `"strict"` or `"candidate"` |
| `is_rising_or_stable` | bool/None | Direction check result |
| `history_days` | int | Days of cluster_history available |
| `evidence` | list | Top 5 supporting signals |

## Contrarian Detection

### Definition

> Clusters whose forecasted direction OR sentiment diverges from the
> average for their industry.

### How "mainstream" is computed

For each industry, we compute the baseline:

```
industry_avg_sentiment = AVG(sentiment_score) across all signals in industry
industry_avg_trend     = AVG(trend_score) across all clusters in industry
```

Then for each cluster, we measure divergence:

```
sentiment_diff = cluster_sentiment - industry_avg_sentiment
trend_diff     = cluster_trend     - industry_avg_trend
```

A cluster is flagged contrarian if either:

- `|sentiment_diff| >= 0.15` (sentiment significantly different)
- `|trend_diff| >= 0.20` (trend score significantly different)

### Five contrarian types

The detection classifies what kind of divergence it found:

| Type | Pattern | Meaning |
|------|---------|---------|
| `positive_outlier` | Sentiment much higher than industry | Bullish in a generally negative space |
| `negative_outlier` | Sentiment much lower than industry | Bearish in a generally positive space |
| `rising_against_industry` | Trend much higher than industry | Growing despite industry stagnation |
| `falling_against_industry` | Trend much lower than industry | Cooling despite industry growth |
| `double_divergence` | Both sentiment AND trend diverge | Strongly contrarian on both axes |

### Output structure

Each contrarian signal includes:

| Field | Description |
|-------|-------------|
| `cluster_id`, `label`, `industry`, `size` | Cluster identification |
| `cluster_sentiment` | This cluster's avg sentiment |
| `industry_sentiment` | The industry's avg sentiment |
| `cluster_trend` | This cluster's trend_score |
| `industry_trend` | The industry's avg trend_score |
| `sentiment_diff` | Cluster minus industry sentiment |
| `trend_diff` | Cluster minus industry trend |
| `contrarian_type` | One of the 5 labels above |
| `evidence` | Top 5 supporting signals |

## Supporting Evidence

Both functions attach `evidence` — a list of up to 5 actual signals
from the cluster, ranked by `source_quality` descending. Each evidence
item shows:

- Signal title (truncated to 120 chars)
- Source (newsletter name)
- Sentiment score
- Signal URL (for follow-up)

The report renders these inline under each detection so a reviewer can
see *why* a cluster was flagged without leaving the report.

## Tuning the thresholds

All constants live at the top of `analyses.py` and can be edited:

```python
WEAK_STRICT_MIN_SOURCES = 3
WEAK_STRICT_MAX_SIZE = 6
WEAK_FALLBACK_MIN_SOURCES = 2
WEAK_FALLBACK_MAX_SIZE = 10
EVIDENCE_LIMIT = 5
WEAK_TARGET_MIN = 3
CONTRARIAN_DELTA = 0.15
```

Want stricter weak signals? Raise `WEAK_STRICT_MIN_SOURCES` to 4 or 5.
Want noisier contrarian detection? Lower `CONTRARIAN_DELTA` to 0.10.

## Limitations

1. **Industry baselines need data.** With only 3 clusters in 3 different
   industries, each "industry baseline" is just one cluster — meaning
   no cluster can diverge from itself. Contrarian detection becomes
   meaningful when industries have 3+ clusters each.

2. **Direction check requires history.** Same cold-start problem as
   forecasting. The lenient day-1 behavior keeps the report populated;
   strict filtering kicks in after ~3 days of pipeline runs.

3. **The "candidate" fallback can produce false positives.** A size-8
   cluster with 2 sources isn't really a weak signal in the strict
   sense — it's getting flagged because the report needs content.
   The `kind` field on each row tells reviewers when they're looking
   at a fallback match vs a real one.

4. **No memory of past detections.** Each run is independent. A cluster
   flagged as weak signal today might not be tomorrow (if its size
   crosses 6). Tracking "has this cluster been weak for N consecutive
   days" would be more useful but requires a new table.
