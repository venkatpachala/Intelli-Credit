-- ============================================================
-- storage/init_db.sql
-- PostgreSQL schema for Research Agent
-- ============================================================

-- Enable pg_trgm for fuzzy name matching (RBI source)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── RBI Wilful Defaulter List ─────────────────────────────────
CREATE TABLE IF NOT EXISTS ra_rbi_defaulters (
    id               SERIAL PRIMARY KEY,
    entity_name      TEXT        NOT NULL,
    name_normalized  TEXT        NOT NULL,     -- lowercased for pg_trgm
    pan              VARCHAR(10),
    bank_name        TEXT,
    list_type        VARCHAR(50) DEFAULT 'wilful_defaulter',
    outstanding_amt  NUMERIC(18,2),
    date_reported    DATE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- GIN index on name_normalized for fast trigram matching
CREATE INDEX IF NOT EXISTS idx_rbi_defaulters_name_trgm
    ON ra_rbi_defaulters
    USING GIN (name_normalized gin_trgm_ops);

-- B-tree index on PAN for exact lookup
CREATE INDEX IF NOT EXISTS idx_rbi_defaulters_pan
    ON ra_rbi_defaulters (pan)
    WHERE pan IS NOT NULL;


-- ── Research Results Store ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS ra_research_results (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id          TEXT        NOT NULL UNIQUE,
    company_name     TEXT        NOT NULL,
    cin              VARCHAR(21) NOT NULL,
    gstin            VARCHAR(16) NOT NULL,
    risk_score       SMALLINT    NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_band        VARCHAR(10) NOT NULL,
    auto_reject      BOOLEAN     NOT NULL DEFAULT FALSE,
    flags_json       JSONB       NOT NULL DEFAULT '[]',
    findings_json    JSONB       NOT NULL DEFAULT '[]',
    tags             TEXT[]      NOT NULL DEFAULT '{}',
    source_results   JSONB       NOT NULL DEFAULT '{}',
    ingestion_version TEXT,
    started_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_case_id
    ON ra_research_results (case_id);

CREATE INDEX IF NOT EXISTS idx_results_risk_band
    ON ra_research_results (risk_band);

CREATE INDEX IF NOT EXISTS idx_results_cin
    ON ra_research_results (cin);

CREATE INDEX IF NOT EXISTS idx_results_auto_reject
    ON ra_research_results (auto_reject)
    WHERE auto_reject = TRUE;


-- ── Audit Log ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ra_audit_log (
    id          BIGSERIAL   PRIMARY KEY,
    case_id     TEXT        NOT NULL,
    event       TEXT        NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_case_id
    ON ra_audit_log (case_id, created_at DESC);
