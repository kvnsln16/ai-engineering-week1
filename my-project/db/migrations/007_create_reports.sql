CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id UUID REFERENCES topics(id) ON DELETE SET NULL,
    cluster_id UUID REFERENCES clusters(id) ON DELETE SET NULL,
    report_date DATE NOT NULL,
    summary TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reports_topic_id ON reports(topic_id);
CREATE INDEX IF NOT EXISTS idx_reports_cluster_id ON reports(cluster_id);
CREATE INDEX IF NOT EXISTS idx_reports_report_date ON reports(report_date);