-- SOURCES

INSERT INTO sources (
    name,
    type,
    base_url
)
VALUES
(
    'reddit',
    'api',
    'https://reddit.com'
),
(
    'github',
    'api',
    'https://api.github.com'
),
(
    'hackernews',
    'api',
    'https://news.ycombinator.com'
),
(
    'producthunt',
    'rss',
    'https://www.producthunt.com'
),
(
    'ai_news',
    'rss',
    'https://example.com'
)
ON CONFLICT (name) DO NOTHING;



-- TOPICS

INSERT INTO topics (
    name,
    description
)
VALUES
(
    'Artificial Intelligence',
    'AI related signals'
),
(
    'Developer Tools',
    'Developer and coding tools'
),
(
    'Startups',
    'Startup ecosystem signals'
)
ON CONFLICT (name) DO NOTHING;



-- CLUSTERS

INSERT INTO clusters (
    topic_id,
    name,
    description
)
SELECT
    t.id,
    'AI Agents',
    'Signals related to AI agents'
FROM topics t
WHERE t.name = 'Artificial Intelligence';



-- RAW SIGNALS

INSERT INTO raw_signals (
    source_id,
    external_id,
    title,
    content,
    url,
    payload,
    received_at
)
SELECT
    s.id,
    'reddit-test-001',
    'Sample Reddit Post',
    'This is sample content from Reddit.',
    'https://reddit.com/sample',
    '{"upvotes": 100, "comments": 10}'::jsonb,
    now()
FROM sources s
WHERE s.name = 'reddit';



-- SCORES

INSERT INTO scores (
    raw_signal_id,
    topic_id,
    cluster_id,
    score,
    model_version
)
SELECT
    rs.id,
    t.id,
    c.id,
    0.95,
    'v1'
FROM raw_signals rs
JOIN topics t
    ON t.name = 'Artificial Intelligence'
JOIN clusters c
    ON c.name = 'AI Agents'
LIMIT 1;



-- PREDICTIONS

INSERT INTO predictions (
    raw_signal_id,
    topic_id,
    cluster_id,
    prediction_label,
    confidence,
    status
)
SELECT
    rs.id,
    t.id,
    c.id,
    'Trending',
    0.92,
    'completed'
FROM raw_signals rs
JOIN topics t
    ON t.name = 'Artificial Intelligence'
JOIN clusters c
    ON c.name = 'AI Agents'
LIMIT 1;



-- REPORTS

INSERT INTO reports (
    topic_id,
    cluster_id,
    report_date,
    summary,
    metrics
)
SELECT
    t.id,
    c.id,
    CURRENT_DATE,
    'Daily AI report summary',
    '{"mentions": 25, "growth": 12.5}'::jsonb
FROM topics t
JOIN clusters c
    ON c.name = 'AI Agents'
WHERE t.name = 'Artificial Intelligence'
LIMIT 1;