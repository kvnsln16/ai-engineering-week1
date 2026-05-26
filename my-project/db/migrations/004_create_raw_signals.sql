CREATE TABLE IF NOT EXISTS raw_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id VARCHAR(255),
    title TEXT,
    content TEXT,
    url TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_signals_source_id ON raw_signals(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_signals_received_at ON raw_signals(received_at);