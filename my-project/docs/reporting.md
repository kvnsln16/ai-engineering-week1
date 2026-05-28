# Reporting — Documentation

Companion to `scoring.md`, `forecasting.md`, and `predictions.md`. This
document describes the daily report: what each section contains, how
it's generated, and how to access it.

Implementation: `app/reporting/`.

## What gets generated

Every report is two files written to `reports/`:

```
reports/
├── report-YYYY-MM-DDTHH-MM-SSZ.md     ← markdown, full content
├── report-YYYY-MM-DDTHH-MM-SSZ.html   ← styled HTML, same content
├── latest.md                          ← copy of newest .md
└── latest.html                        ← copy of newest .html
```

The HTML embeds CSS inline so it's a fully self-contained file —
double-click to view, email as attachment, host on any static server.

## When reports are generated

Three ways:

| Method | When | How |
|--------|------|-----|
| **Daily auto** | Every 6 AM Manila | Phase 7 of the scheduled run |
| **CLI** | Whenever you want | `python generate_report.py` |
| **API** | From another tool | `POST /reports/generate` |

All three call the same underlying function, so output is identical
across methods.

## The 10 sections

### 1. Executive Summary

Headline counts: total signals, clusters, predictions. Top 3 movers by
composite score. Flags if any threats or weak signals are detected.

This is the only section a busy reader might read. Everything else is
detail.

### 2. Market Forecast

Top 10 30-day forecasts sorted by predicted cluster size. Shows current
size, predicted size, and confidence for each. Pulls from the
`forecasts` table.

Falls back to "no forecasts available yet" when clusters lack the
required 30-day history.

### 3. Opportunity Report

Top 10 clusters ranked by `opportunity_score` from `cluster_scores`.
Includes industry, trend score for comparison.

`opportunity_score` formula explained in `scoring.md`.

### 4. Topic Heatmap

Cluster + signal counts grouped by industry. Higher numbers indicate
hotter sectors. Includes avg composite score per industry as a
quality indicator.

### 5. Trend Velocity

Top 10 clusters by `trend_score` (growth velocity vs recent average).
Day-1 trend scores are all 0.500 because the formula requires multiple
days of history; meaningful values appear after ~1 week.

### 6. Market Analysis

Cross-source consensus stats: signals per source, average distinct
sources per cluster. Helps assess whether trending topics are picked
up by multiple newsletters or only one.

### 7. Weak Signal Report

> Clusters with 3-6 signals but at least 3 distinct sources.

Early indicators: topics multiple newsletters have noticed independently
but that haven't broken out yet. Often the highest-value section for
strategic planning.

Definition shown inline in the report so readers know the criteria.

### 8. Contrarian Report

> Clusters where forecast direction contradicts member sentiment.

Examples:
- Forecast says growth but signals are mostly negative → "growth amid
  controversy" — likely a topic gaining attention despite (or because
  of) skepticism
- Forecast says decline but signals are positive → "fading enthusiasm" —
  people don't yet realize a trend is cooling

Definition shown inline in the report.

### 9. Threat Report

> Two patterns:
> - Policy/safety industry + forecast growth (regulatory risk)
> - Rapid decline (forecast < 60% of current) + negative sentiment
>   (market deterioration)

Definition shown inline. Action items section listed at the top of the
table for quick triage.

### 10. Recommendations

Top 10 predictions by confidence × probability. Each shows prediction
text, direction, scores, and the recommended_action with disclaimer.

Pulls from the `predictions` table; falls back to "no predictions yet"
when the forecasting pipeline hasn't produced output.

## Querying past reports

```
GET  /reports                     — list every report
GET  /reports/latest              — metadata for the newest
GET  /reports/latest/html         — newest as HTML (browser-friendly)
GET  /reports/latest/markdown     — newest as markdown text
GET  /reports/{timestamp}         — fetch one by timestamp
POST /reports/generate            — generate a fresh one now
```

Or just browse the `reports/` folder directly — every file is plain
text/HTML.

## Editing the templates

The report layout is one Jinja2 template:

```
app/reporting/templates/report.md.j2
```

Edit it to:
- Change section ordering or wording
- Add new sections (template + data in `generator._build_context()`)
- Tweak table columns

CSS for HTML output:

```
app/reporting/templates/styles.css
```

Edit for fonts, colors, table styles. Changes apply on next generation.

## When sections will be empty

| Section | Empty when | Becomes useful |
|---------|------------|----------------|
| Market Forecast | No cluster has 30+ days of history | After 30 days of pipeline runs |
| Opportunity | No scored clusters | First scheduled run |
| Topic Heatmap | No clusters | First scheduled run |
| Trend Velocity | No history | First scheduled run (scores ≈ 0.5) |
| Market Analysis | No signals | First scheduled run |
| Weak Signal | All small clusters single-source | Real-world data eventually triggers |
| Contrarian | All forecasts align with sentiment | When real trends emerge |
| Threat | No policy/decline patterns | When relevant data appears |
| Recommendations | No predictions | After forecasts exist |

The report is never broken; it just shows "no data yet" for empty
sections with a one-line explanation of what's needed.

## Retention

Reports accumulate in `reports/` forever. They're small (~50 KB each).
A year of daily reports is ~18 MB. If you want to prune older reports
later, delete the older files manually or add a cleanup function.
