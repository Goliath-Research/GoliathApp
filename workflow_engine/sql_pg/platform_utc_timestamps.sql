-- GoliathApp: every timestamp is stored as UTC, whatever the session time zone.
--
-- All GoliathApp *_at_utc / *AtUtc columns are timestamptz. Older scripts defaulted and wrote them
-- with (now() AT TIME ZONE 'utc'), which yields a timestamp *without* time zone holding the UTC
-- wall clock; PostgreSQL then converts it back to timestamptz using the session TimeZone. On a UTC
-- server (Neon) that is harmless, but a session in any other zone stored instants shifted by its
-- offset. The scripts now write now() (an absolute instant). This migration rewrites the column
-- defaults that existing databases still carry, so CREATE TABLE IF NOT EXISTS tables are fixed too.
--
-- Scope: GoliathApp-owned schemas only. Idempotent. Stored values are not touched: rows written by
-- a UTC session (every production write path) are already correct.

DO $$
DECLARE
  r record;
  v_fixed int := 0;
BEGIN
  FOR r IN
    SELECT n.nspname, c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid) AS expr
    FROM pg_attrdef d
    JOIN pg_class c ON c.oid = d.adrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
    WHERE n.nspname IN ('wf', 'portal', 'cfg', 'inv', 'Meta', 'RBAC', 'Contract', 'Onboarding')
      AND c.relkind IN ('r', 'p')
      AND a.atttypid = 'timestamptz'::regtype
      AND NOT a.attisdropped
      AND pg_get_expr(d.adbin, d.adrelid) ~* '^\(?\s*(now|clock_timestamp|statement_timestamp|transaction_timestamp)\(\)\s+AT\s+TIME\s+ZONE\s+''utc''(::text)?\s*\)?$'
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I ALTER COLUMN %I SET DEFAULT %s',
      r.nspname, r.relname, r.attname,
      CASE WHEN r.expr ~* 'clock_timestamp' THEN 'clock_timestamp()' ELSE 'now()' END
    );
    v_fixed := v_fixed + 1;
  END LOOP;
  RAISE NOTICE 'platform_utc_timestamps: % column default(s) now store an absolute UTC instant', v_fixed;
END;
$$;

/*
  portal.fn_utc_timestamp_violations: GoliathApp timestamptz defaults or functions that still derive
  a value from now() AT TIME ZONE 'utc' outside to_char (formatting a UTC string is fine).
  Empty means every GoliathApp timestamp is stored as UTC in any session time zone.
*/
CREATE OR REPLACE FUNCTION portal.fn_utc_timestamp_violations()
RETURNS TABLE (object_kind text, object_name text, detail text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT 'column default', format('%I.%I.%I', n.nspname, c.relname, a.attname), pg_get_expr(d.adbin, d.adrelid)
  FROM pg_attrdef d
  JOIN pg_class c ON c.oid = d.adrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
  WHERE n.nspname IN ('wf', 'portal', 'cfg', 'inv', 'Meta', 'RBAC', 'Contract', 'Onboarding')
    AND pg_get_expr(d.adbin, d.adrelid) ~* 'AT\s+TIME\s+ZONE|timezone\('
  UNION ALL
  SELECT 'function', format('%I.%I(%s)', n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)),
         'derives a timestamp from now() AT TIME ZONE ''utc'''
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname IN ('wf', 'portal', 'cfg', 'inv', 'Meta', 'RBAC', 'Contract', 'Onboarding')
    AND regexp_replace(p.prosrc, 'to_char\(\s*now\(\)\s+AT\s+TIME\s+ZONE\s+''utc''', '', 'gi')
        ~* '(now|clock_timestamp|statement_timestamp|transaction_timestamp)\(\)\s+AT\s+TIME\s+ZONE\s+''utc'''
$$;

REVOKE ALL ON FUNCTION portal.fn_utc_timestamp_violations() FROM PUBLIC;
