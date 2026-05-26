# Cluster Scoring — Documentation

This document explains how each cluster gets its four scores. The actual
implementation lives in `app/clustering/scorer.py` — code-level comments
mirror what's here, so editing one and not the other will drift.

## Overview

Every cluster (a topic group discovered by HDBSCAN) is scored on four
dimensions. All scores are normalized to a `0.0` to `1.0` range where
`1.0` is the best possible score. This makes scores comparable across
clusters and across runs.

| Score             | What it measures                          | Where it comes from           |
| ----------------- | ----------------------------------------- | ----------------------------- |
| `trend_score`     | Growth velocity — is this topic accelerating? | Cluster size today vs recent average |
| `opportunity_score` | Demand × monetization potential         | Cluster size + sentiment + industry |
| `market_score`    | Cross-source consensus                    | Distinct sources + source quality |
| `composite_score` | Weighted combination, used for ranking    | All three of the above        |

## 1. Trend Score

**Question it answers:** Is this topic gaining momentum, fading, or steady?

**Formula:**
```
velocity     = today_size / max(avg_of_previous_days, 1.0)
trend_score  = sigmoid(velocity - 1.0)
```

**Behavior:**
- A cluster the same size as yesterday averages → trend = 0.50 (steady)
- A cluster twice as big as yesterday's average → trend ≈ 0.73 (rising)
- A cluster half the size of yesterday's average → trend ≈ 0.38 (fading)
- An exploding 10x cluster → trend ≈ 0.99 (sigmoid caps spikes)
- Day-1 clusters (no history) → trend = 0.50 (neutral)

**Why sigmoid:** Without it, a single viral topic would dominate every
ranking. The sigmoid bounds extreme growth to ~1.0 so other meaningful
trends still show up in the top 20.

**Data requirement:** Needs `cluster_history` data. Trend scores become
meaningful after roughly 3-7 days of pipeline runs.

## 2. Opportunity Score

**Question it answers:** How commercially interesting is this topic?

**Formula:**
```
demand_share     = cluster_size / total_signals_in_clusters
demand           = min(1.0, demand_share * 10)        # cap at 10% share = 1.0
sentiment_lift   = (average_sentiment + 1) / 2         # map -1..+1 to 0..1
monetization     = MONETIZATION_WEIGHTS[industry]      # see table below

opportunity_score = demand * sentiment_lift * monetization
```

**Industry monetization weights** (editable in `scorer.py`):

| Industry          | Weight | Reasoning                                       |
| ----------------- | ------ | ----------------------------------------------- |
| `funding`         | 1.00   | Direct money flow                               |
| `product_launch`  | 0.90   | New product = new revenue                       |
| `llm`             | 0.75   | LLM products are heavily monetized              |
| `computer_vision` | 0.70   | Active commercial market                        |
| `audio_speech`    | 0.65   | Growing but smaller market                      |
| `robotics`        | 0.60   | Long capex cycles                               |
| `policy_safety`   | 0.30   | Rarely directly monetizable                     |
| `research`        | 0.25   | Years from production                           |
| `other`           | 0.40   | Default for unclassified                        |

**Behavior:**
- A small cluster gets low demand → low opportunity score
- A negative-sentiment cluster (controversies, lawsuits) gets dampened
- A research-tagged cluster scores lower than a funding-tagged one
- All three factors matter — a cluster needs to be popular **and**
  positively received **and** in a monetizable industry

## 3. Market Score

**Question it answers:** Do multiple trustworthy sources agree this matters?

**Formula:**
```
distinct_sources = count of distinct source names in the cluster
avg_quality      = average source_quality of all member signals

diversity   = min(1.0, distinct_sources / 5.0)
market_score = 0.6 * diversity + 0.4 * avg_quality
```

**Behavior:**
- A topic in only one newsletter → low diversity, low market score
- A topic across 5+ different newsletters → full diversity credit
- A trusted single source (e.g., GitHub, HackerNews) still scores
  moderately well via the quality term
- A spammy single source → lowest possible market score

**Cap at 5 sources:** beyond 5, the signal is strong enough — more
sources don't add much information.

## 4. Composite Score

**Question it answers:** Overall, how important is this topic?

**Formula:**
```
composite_score =
    0.40 * trend_score        +
    0.35 * opportunity_score  +
    0.25 * market_score
```

These weights live in `COMPOSITE_WEIGHTS` in `scorer.py` and are easy to
tune. The defaults reflect: **trends > opportunity > consensus**.

**Why this weighting:**

- **Trend is weighted most heavily (40%)** because the system is designed
  to surface what's *emerging*, not just what's already established.
- **Opportunity is close behind (35%)** because commercial relevance is
  the second-strongest filter.
- **Market consensus (25%)** is included to dampen false positives — a
  single hyped source isn't enough to top the rankings on its own.

## Editing the formulas

Each formula is a single function in `scorer.py`. If you want to:

- **Add a new score:** copy `_trend_score` as a template, add a column
  to the `cluster_scores` table in `db.py`, include it in `_composite`.
- **Reweight composite:** edit `COMPOSITE_WEIGHTS` at the top of `scorer.py`.
- **Tune monetization:** edit `MONETIZATION_WEIGHTS` at the top of `scorer.py`.
- **Use different industry data:** the `industry` field comes from
  `app/enrichment/industry.py` — adding new industries means updating
  both files.

## Querying the scores

Top 20 trending topics:
```
GET /clusters/top?n=20&sort=trend
```

Top 20 commercial opportunities:
```
GET /clusters/top?n=20&sort=opportunity
```

Most agreed-upon topics:
```
GET /clusters/top?n=20&sort=market
```

Default ranking (composite):
```
GET /clusters/top?n=20
```

Or query the database directly:
```sql
SELECT c.label, c.industry, c.size, cs.composite_score
FROM clusters c
JOIN cluster_scores cs ON cs.cluster_id = c.id
ORDER BY cs.composite_score DESC
LIMIT 20;
```
