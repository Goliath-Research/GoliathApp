/*
  Semantic action catalog columns (portal entity link arrives in A1).

  Prerequisites: wf.workflow_action, wf.workflow_action_schema, wf_data_type.sql
*/

ALTER TABLE wf.workflow_action
  ADD COLUMN IF NOT EXISTS namespace text NOT NULL DEFAULT 'domain',
  ADD COLUMN IF NOT EXISTS level varchar(16) NOT NULL DEFAULT 'domain',
  ADD COLUMN IF NOT EXISTS exposure varchar(16) NOT NULL DEFAULT 'rbac',
  ADD COLUMN IF NOT EXISTS display_name text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS schema_version text NOT NULL DEFAULT '1',
  ADD COLUMN IF NOT EXISTS base_namespace text NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_wf_action_level'
  ) THEN
    ALTER TABLE wf.workflow_action
      ADD CONSTRAINT ck_wf_action_level
      CHECK (level IN ('engine', 'core', 'domain'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_wf_action_exposure'
  ) THEN
    ALTER TABLE wf.workflow_action
      ADD CONSTRAINT ck_wf_action_exposure
      CHECK (exposure IN ('hidden', 'rbac'));
  END IF;
END $$;

ALTER TABLE wf.workflow_action_schema
  ADD COLUMN IF NOT EXISTS schema_version text NOT NULL DEFAULT '1',
  ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';

CREATE OR REPLACE PROCEDURE wf.wf_repo_upsert_semantic_action(
  IN p_action_name text,
  IN p_capability text,
  IN p_namespace text,
  IN p_level text,
  IN p_exposure text,
  IN p_display_name text,
  IN p_schema_version text,
  IN p_base_namespace text DEFAULT NULL,
  IN p_payload_schema_ref text DEFAULT NULL,
  IN p_execution_mode text DEFAULT 'in_process',
  IN p_in_process_handler text DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_action_name IS NULL OR btrim(p_action_name) = '' THEN
    RETURN;
  END IF;

  INSERT INTO wf.workflow_action (
    action_name,
    capability,
    payload_schema_ref,
    execution_mode,
    in_process_handler,
    namespace,
    level,
    exposure,
    display_name,
    schema_version,
    base_namespace
  )
  VALUES (
    p_action_name,
    p_capability,
    p_payload_schema_ref,
    p_execution_mode,
    p_in_process_handler,
    coalesce(p_namespace, 'domain'),
    coalesce(p_level, 'domain'),
    coalesce(p_exposure, 'rbac'),
    coalesce(p_display_name, p_action_name),
    coalesce(p_schema_version, '1'),
    p_base_namespace
  )
  ON CONFLICT (action_name) DO UPDATE SET
    capability = EXCLUDED.capability,
    payload_schema_ref = COALESCE(EXCLUDED.payload_schema_ref, wf.workflow_action.payload_schema_ref),
    execution_mode = COALESCE(EXCLUDED.execution_mode, wf.workflow_action.execution_mode),
    in_process_handler = COALESCE(EXCLUDED.in_process_handler, wf.workflow_action.in_process_handler),
    namespace = EXCLUDED.namespace,
    level = EXCLUDED.level,
    exposure = EXCLUDED.exposure,
    display_name = EXCLUDED.display_name,
    schema_version = EXCLUDED.schema_version,
    base_namespace = EXCLUDED.base_namespace;
END;
$$;

DROP PROCEDURE IF EXISTS wf.wf_repo_upsert_action_schema(text, text, jsonb, text);

CREATE OR REPLACE PROCEDURE wf.wf_repo_upsert_action_schema(
  IN p_action_name text,
  IN p_direction text,
  IN p_schema_json jsonb,
  IN p_schema_id text DEFAULT NULL,
  IN p_schema_version text DEFAULT '1',
  IN p_content_hash text DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_action_id bigint;
  v_hash text;
BEGIN
  IF p_action_name IS NULL OR btrim(p_action_name) = ''
     OR p_direction IS NULL OR p_direction NOT IN ('input', 'output')
     OR p_schema_json IS NULL THEN
    RETURN;
  END IF;

  v_hash := coalesce(
    p_content_hash,
    encode(sha256(convert_to(p_schema_json::text, 'UTF8')), 'hex')
  );

  SELECT id INTO v_action_id
  FROM wf.workflow_action
  WHERE action_name = p_action_name;

  IF v_action_id IS NULL THEN
    RETURN;
  END IF;

  INSERT INTO wf.workflow_action_schema (
    workflow_action_id,
    direction,
    schema_json,
    schema_id,
    schema_version,
    content_hash
  )
  VALUES (
    v_action_id,
    p_direction,
    p_schema_json,
    p_schema_id,
    coalesce(p_schema_version, '1'),
    v_hash
  )
  ON CONFLICT (workflow_action_id, direction) DO UPDATE SET
    schema_json = EXCLUDED.schema_json,
    schema_id = EXCLUDED.schema_id,
    schema_version = EXCLUDED.schema_version,
    content_hash = EXCLUDED.content_hash,
    updated_at_utc = (now() AT TIME ZONE 'utc');

  IF p_direction = 'input' AND p_schema_id IS NOT NULL THEN
    UPDATE wf.workflow_action
    SET payload_schema_ref = p_schema_id,
        schema_version = coalesce(p_schema_version, wf.workflow_action.schema_version)
    WHERE id = v_action_id;
  END IF;
END;
$$;
