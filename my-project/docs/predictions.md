# Predictions — Documentation

Companion to `scoring.md` and `forecasting.md`. This document explains
the structured prediction object: how each field is computed, what
templates exist, and how `recommended_action` is derived.

Implementation: `app/predictions/`. Code-level comments mirror this doc
— editing one and not the other will drift.

## Why predictions are a separate object

A **forecast** is a raw number: "cluster size will be 47 ± 12 in 30 days."

A **prediction** is the human-readable wrapper around that number:

```
"LLM tooling continues gaining traction across the next 3 months."
  probability: 0.78
  confidence:  0.82
  direction:   growth
  recommended_action: "Invest in LLM developer tools or content..."
  supporting_signal_ids: [142, 187, 203, 211, 218]
  counter_signal_ids: []
```

Forecasts are for engineers and dashboards. Predictions are for
stakeholders and reviewers. Both live in the same database; one is
derived from the other.

## Object schema

| Field                   | Type            | Description                                       |
| ----------------------- | --------------- | ------------------------------------------------- |
| `id`                    | int             | Primary key                                       |
| `cluster_id`            | int             | Which topic cluster this is about                 |
| `horizon_days`          | int             | 30 / 90 / 180 / 365                               |
| `text`                  | string          | Human-readable prediction                         |
| `probability`           | float 0..1      | Likelihood the prediction direction comes true    |
| `confidence`            | float 0..1      | Trust in the underlying data                      |
| `direction`             | string          | `growth` / `decline` / `stable`                   |
| `recommended_action`    | string \| null  | Suggestion based on industry + direction          |
| `supporting_signal_ids` | int[]           | Top 5 signals matching the prediction             |
| `counter_signal_ids`    | int[]           | Signals opposing the prediction (may be empty)    |
| `forecast_predicted`    | float           | Underlying forecast value                         |
| `forecast_lower`        | float           | Forecast's 95% CI lower bound                     |
| `forecast_upper`        | float           | Forecast's 95% CI upper bound                     |
| `created_at`            | string          | ISO 8601 UTC timestamp                            |

## Generation pipeline

For each cluster that has forecasts:

1. **Read forecast(s)** — one per horizon (30, 90, 180, 365)
2. **Compute direction** — compare forecast vs current cluster size
3. **Compute magnitude** — relative change size determines text variant
4. **Compute probability** — derived from forecast strength
5. **Inherit confidence** — taken directly from the forecast's `confidence_score`
6. **Render text** — template lookup by (direction, magnitude)
7. **Pick signals** — supporting and counter from cluster members
8. **Look up action** — by (industry, direction)
9. **Persist** — one row per (cluster, horizon)

## Direction

Computed from the forecast vs current cluster size:

```
relative_change = (predicted - current) / max(current, 1)

if relative_change >  0.10  →  direction = "growth"
if relative_change < -0.10  →  direction = "decline"
otherwise                   →  direction = "stable"
```

The 10% threshold (`STABLE_THRESHOLD` in `generator.py`) is tunable in
one place. Lower = more sensitive; higher = more conservative.

## Magnitude

Within growth/decline, magnitude buckets the relative change:

| `|relative_change|` | Bucket     |
| ------------------- | ---------- |
| < 0.10              | (stable, no magnitude)  |
| 0.10 – 0.25         | small      |
| 0.25 – 0.75         | moderate   |
| ≥ 0.75              | large      |

Magnitude doesn't affect probability or confidence — it only controls
which **text template** gets selected.

## Probability

```
if direction == "stable":
    probability = 0.5

else:
    p = sigmoid(|relative_change| * 2)
    probability = clamp(p, 0.5, 1.0)
```

**Behavior:**
- Flat forecast (10% change exactly) → probability ≈ 0.55
- Moderate change (50% growth) → probability ≈ 0.73
- Large change (200% growth) → probability ≈ 0.98
- Stable predictions always report 0.5 (we genuinely don't have strong evidence either way)

## Confidence

**Inherited directly from the forecast's `confidence_score`.** See
`forecasting.md` for the full formula. Briefly:

```
confidence = 0.4 * data_factor      # how much history
           + 0.4 * variance_factor  # how stable the series
           + 0.2 * source_factor    # how many distinct sources
```

A prediction can be high-probability but low-confidence ("we'd bet on
growth but the data is thin") or vice versa ("we have a year of solid
data showing nothing is happening").

## Text templates

Templates live in `app/predictions/templates.py` in the
`TEXT_TEMPLATES` dict, keyed by `(direction, magnitude)`. Each entry
has 3 variants. The generator picks a variant deterministically based
on the cluster + horizon, so the same input produces the same output
every time.

Available placeholders:
- `{topic}` — comma-joined top 3 cluster keywords (title-cased)
- `{horizon_text}` — "next 30 days", "next 3 months", "next 6 months", "next 12 months"
- `{horizon}` — raw integer
- `{industry}` — industry name

**Example output:**
```
direction=growth, magnitude=moderate, horizon=90, keywords=["llm","tools","agents"]
→ "LLM, Tools, Agents continues gaining traction across the next 3 months."
```

## Supporting and counter signals

Each prediction includes up to **5 supporting signals** (sentiment
aligned with direction) and up to **5 counter signals** (sentiment
opposed). Both lists are ranked by `source_quality` descending so the
most trustworthy signals appear first.

**Alignment rules:**

| Direction | Supporting          | Counter             |
| --------- | ------------------- | ------------------- |
| growth    | positive sentiment  | negative sentiment  |
| decline   | negative sentiment  | positive sentiment  |
| stable    | neutral sentiment   | extreme sentiment   |

Counter signals **may be empty** when the cluster has unanimous
sentiment. This is honest — we don't fabricate opposition to fill the
slot. An empty counter list means "this prediction is unopposed within
its source data."

The full signal objects (title, URL, source) are hydrated by the
`/predictions/{id}` endpoint via JOIN, so reviewers see real evidence,
not just IDs.

## Recommended action

Looked up by `(industry, direction)` in `ACTION_RULES` in
`templates.py`. Industries currently covered:

- `llm`, `computer_vision`, `robotics`, `audio_speech`
- `research`, `funding`, `product_launch`, `policy_safety`
- `other` (fallback for unknown industries)

Each action is a one-sentence suggestion **plus a disclaimer**:

```
"Consider investing in LLM developer tools or content. (Heuristic suggestion only — not financial or legal advice.)"
```

**Important:** these are heuristic suggestions derived from simple
rules, not financial or legal advice. The disclaimer appears in every
action to make this clear to consumers of the prediction.

To add a new industry or change a recommendation, edit
`ACTION_RULES` directly. New industries also need to be added to
`app/enrichment/industry.py` so they can be detected during enrichment.

## Querying predictions

```
GET /predictions                            — all (top 50 by confidence)
GET /predictions?horizon=30                 — only 30-day predictions
GET /predictions?min_confidence=0.7         — high-confidence only
GET /predictions?cluster_id=5               — one topic's predictions
GET /predictions?direction=growth           — only growth predictions
GET /predictions?horizon=90&direction=growth&min_confidence=0.7   — combinations

GET /predictions/top?n=20                   — top 20 by confidence
GET /predictions/cluster/{id}               — all 4 horizons for one cluster
GET /predictions/{id}                       — full detail incl. hydrated signals
GET /predictions/stats                      — overall counts
```

Or directly via SQL:

```sql
SELECT p.text, p.probability, p.confidence, p.recommended_action,
       c.label AS topic
FROM predictions p
JOIN clusters c ON c.id = p.cluster_id
WHERE p.horizon_days = 30
  AND p.confidence >= 0.7
  AND p.direction = 'growth'
ORDER BY p.confidence DESC, p.probability DESC
LIMIT 20;
```

## Limitations

1. **Predictions require forecasts.** No forecasts → no predictions.
   On day 1, both tables are empty. This is correct behavior — see
   `forecasting.md` on the cold-start period.

2. **Templates are deterministic but limited.** Three variants per
   (direction, magnitude) combo. Reviewers will see repeated phrasing
   across runs. This is intentional for review consistency — if you
   want more linguistic variety, expand `TEXT_TEMPLATES`.

3. **Recommended actions are heuristics.** Industry rules don't know
   your business context. Treat them as conversation starters, not
   instructions.

4. **Stable predictions report probability = 0.5.** This is
   intellectually honest (no strong evidence either way) but feels
   counter-intuitive ("isn't 'stable' a high-probability statement?").
   If you prefer the alternative framing (high probability of no
   change), adjust `_probability_from_change` in `generator.py`.
