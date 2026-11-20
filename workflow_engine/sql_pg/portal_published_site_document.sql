-- Resolve a published cfg.site document for instance bake / workers.
-- Generic: returns document_json only. Child apps own the document type and keys.
-- When p_site_id is null, uses the same default as study start: published site,
-- preferring name 'default', then latest id.
-- Returns NULL when no published row matches so callers can fall back to a
-- work-root site manifest.

CREATE OR REPLACE FUNCTION portal.fn_published_site_document(p_site_id bigint DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  IF p_site_id IS NOT NULL THEN
    SELECT s.document_json
      INTO v_doc
    FROM cfg.site s
    WHERE s.id = p_site_id
      AND s.status = 'published';
    RETURN v_doc;
  END IF;

  SELECT s.document_json
    INTO v_doc
  FROM cfg.site s
  WHERE s.status = 'published'
  ORDER BY CASE WHEN s.name = 'default' THEN 0 ELSE 1 END, s.id DESC
  LIMIT 1;
  RETURN v_doc;
END;
$$;
