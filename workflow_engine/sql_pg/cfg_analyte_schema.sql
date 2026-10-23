-- Versioned analyte config catalog (platform cfg; Omics apps seed rows).

CREATE TABLE IF NOT EXISTS cfg.analyte (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  version text NOT NULL DEFAULT '1',
  status varchar(32) NOT NULL DEFAULT 'draft',
  content_hash text NOT NULL,
  document_json jsonb NOT NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  updated_at_utc timestamptz NULL,
  CONSTRAINT uq_cfg_analyte_name_version UNIQUE (name, version),
  CONSTRAINT ck_cfg_analyte_status CHECK (status IN ('draft', 'published', 'retired'))
);
