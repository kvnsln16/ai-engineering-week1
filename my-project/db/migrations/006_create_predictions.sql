CREATE TABLE IF NOT EXISTS predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_signal_id UUID NOT NULL REFERENCES raw_signals(id) ON DELETE CASCADE,
    topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
    cluster_id UUID REFERENCES clusters(id) ON DELETE SET NULL,
    prediction_label VARCHAR(255),
    confidence NUMERIC(10,4),
    status VARCHAR(50),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_predictions_raw_signal_id ON predictions(raw_signal_id);
CREATE INDEX IF NOT EXISTS idx_predictions_topic_id ON predictions(topic_id);
CREATE INDEX IF NOT EXISTS idx_predictions_cluster_id ON predictions(cluster_id);