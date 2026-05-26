CREATE TABLE IF NOT EXISTS scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_signal_id UUID NOT NULL REFERENCES raw_signals(id) ON DELETE CASCADE,
    topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
    cluster_id UUID REFERENCES clusters(id) ON DELETE SET NULL,
    score NUMERIC(10,4) NOT NULL,
    model_version VARCHAR(100),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scores_raw_signal_id ON scores(raw_signal_id);
CREATE INDEX IF NOT EXISTS idx_scores_topic_id ON scores(topic_id);
CREATE INDEX IF NOT EXISTS idx_scores_cluster_id ON scores(cluster_id);