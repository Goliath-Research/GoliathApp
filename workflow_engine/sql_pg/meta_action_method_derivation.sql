/*
  Actions are methods on exactly one owning entity class (generic derivation and checks).

  Every catalog action already publishes an input schema (wf.workflow_action_schema). From it,
  "Meta".sp_derive_action_methods() derives, for each action's owning method that has no
  parameters yet:
    - the method parameters (names, required flags, non-null defaults);
    - their data types: the semantic attribute of the owning class's entity when one matches the
      parameter name, else a platform action type for a plain scalar, else a named data type
      generated from the schema (nested objects named after their schema title, under the owning
      class's namespace);
    - the semantic action binding (action -> the entity mapped to the owning class).
  Nothing application-specific is hard-coded: child apps call it from their seed.

  "Meta".fn_check_action_owners() flags actions without exactly one owning class. An action
  with a method on a platform class and duplicates elsewhere is reported as a known duplicate
  (removing those methods is an owner decision) and does not block.
*/

CREATE OR REPLACE FUNCTION "Meta".fn_action_owner_methods(p_action_name text)
RETURNS TABLE (method_id integer, class_id integer, class_name text, is_platform boolean)
LANGUAGE sql
STABLE
SET search_path = "Meta", pg_temp
AS $$
  SELECT m."ID", c."ID", c."Name", c."Name" LIKE 'platform/%'
  FROM "Meta"."Methods" m
  JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
  WHERE m."ImplKind" = 'action' AND m."ImplRef" = p_action_name AND NOT COALESCE(m."IsOverride", false)
  ORDER BY c."Name";
$$;

/* ok | known_duplicate | no_owner | multiple_owners, with the owning (canonical) class. */
CREATE OR REPLACE FUNCTION "Meta".fn_check_action_owners()
RETURNS TABLE (action_name text, status text, owner_class text, owners text)
LANGUAGE sql
STABLE
SET search_path = "Meta", wf, pg_temp
AS $$
  SELECT a.action_name,
         CASE
           WHEN o.n = 0 THEN 'no_owner'
           WHEN o.n = 1 THEN 'ok'
           WHEN o.n_platform = 1 THEN 'known_duplicate'
           ELSE 'multiple_owners'
         END,
         CASE WHEN o.n = 1 THEN o.first_class WHEN o.n_platform = 1 THEN o.platform_class END,
         o.owners
  FROM wf.workflow_action a
  CROSS JOIN LATERAL (
    SELECT count(*)::int AS n,
           count(*) FILTER (WHERE x.is_platform)::int AS n_platform,
           min(x.class_name) AS first_class,
           min(x.class_name) FILTER (WHERE x.is_platform) AS platform_class,
           string_agg(x.class_name, ', ' ORDER BY x.class_name) AS owners
    FROM "Meta".fn_action_owner_methods(a.action_name) x
  ) o
  ORDER BY a.action_name;
$$;

/* JSON Schema of one property without nullability, titles, defaults or descriptions. */
CREATE OR REPLACE FUNCTION "Meta".fn_derive_property_schema(p_prop jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v jsonb := COALESCE(p_prop, '{}'::jsonb);
  v_alts jsonb;
BEGIN
  IF jsonb_typeof(v->'anyOf') = 'array' THEN
    SELECT jsonb_agg(e) INTO v_alts FROM jsonb_array_elements(v->'anyOf') e WHERE e <> '{"type":"null"}'::jsonb;
    IF jsonb_array_length(COALESCE(v_alts, '[]'::jsonb)) = 1 THEN
      v := (v - 'anyOf') || (v_alts->0);
    END IF;
  END IF;
  IF jsonb_typeof(v->'type') = 'array' THEN
    SELECT jsonb_agg(e) INTO v_alts FROM jsonb_array_elements(v->'type') e WHERE e <> '"null"'::jsonb;
    IF jsonb_array_length(COALESCE(v_alts, '[]'::jsonb)) = 1 THEN
      v := jsonb_set(v, '{type}', v_alts->0);
    END IF;
  END IF;
  RETURN v - 'title' - 'default' - 'description' - 'examples';
END;
$$;

/* Platform action type for a plain scalar or untyped document schema (NULL otherwise). */
CREATE OR REPLACE FUNCTION "Meta".fn_platform_action_type_for(p_schema jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN p_schema = '{"type":"string"}'::jsonb THEN 'platform/action/Text'
    WHEN p_schema = '{"type":"integer"}'::jsonb THEN 'platform/action/Integer'
    WHEN p_schema = '{"type":"number"}'::jsonb THEN 'platform/action/Decimal'
    WHEN p_schema = '{"type":"boolean"}'::jsonb THEN 'platform/action/Boolean'
    WHEN p_schema = '{"type":"object"}'::jsonb THEN 'platform/action/Document'
    WHEN p_schema = '{"type":"array","items":{"type":"object"}}'::jsonb THEN 'platform/action/DocumentList'
    WHEN p_schema = '{"type":"array","items":{"type":"string"}}'::jsonb THEN 'platform/action/TextList'
    WHEN p_schema = '{"type":"array","items":{"type":"integer"}}'::jsonb THEN 'platform/action/IntegerList'
    WHEN p_schema = '{"type":"array","items":{"type":"number"}}'::jsonb THEN 'platform/action/DecimalList'
    WHEN p_schema = '{"type":"array","items":{"type":"boolean"}}'::jsonb THEN 'platform/action/BooleanList'
  END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_semantic_json_type_schema(p_json_type text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE lower(COALESCE(p_json_type, ''))
    WHEN 'string' THEN '{"type":"string"}'::jsonb
    WHEN 'text' THEN '{"type":"string"}'::jsonb
    WHEN 'integer' THEN '{"type":"integer"}'::jsonb
    WHEN 'int' THEN '{"type":"integer"}'::jsonb
    WHEN 'number' THEN '{"type":"number"}'::jsonb
    WHEN 'boolean' THEN '{"type":"boolean"}'::jsonb
    WHEN 'bool' THEN '{"type":"boolean"}'::jsonb
  END;
$$;

/* Data type id for a name and schema: reuse an identical one, create it, or NULL on conflict. */
CREATE OR REPLACE FUNCTION "Meta".fn_ensure_derived_data_type(p_name text, p_schema jsonb)
RETURNS bigint
LANGUAGE plpgsql
SET search_path = wf, pg_temp
AS $$
DECLARE
  v_id bigint;
  v_existing jsonb;
  v_kind text := CASE
    WHEN p_schema ? 'enum' THEN 'enum'
    WHEN p_schema->>'type' = 'string' THEN 'string'
    WHEN p_schema->>'type' = 'integer' THEN 'int'
    WHEN p_schema->>'type' = 'number' THEN 'number'
    WHEN p_schema->>'type' = 'boolean' THEN 'bool'
    WHEN p_schema->>'type' = 'object' OR p_schema ? '$ref' OR p_schema ? 'properties' THEN 'object'
    WHEN p_schema->>'type' = 'array' THEN 'array'
    ELSE 'any' END;
BEGIN
  SELECT t.id, t.schema_json INTO v_id, v_existing
  FROM wf.data_type t WHERE t.name = p_name AND t.status <> 'retired'
  ORDER BY t.id DESC LIMIT 1;
  IF v_id IS NOT NULL THEN
    RETURN CASE WHEN (v_existing - '$id' - '$schema') = p_schema THEN v_id END;
  END IF;
  INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
  VALUES (p_name, '1.0', 'published', v_kind, p_schema, md5(p_schema::text))
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

/*
  Derive parameters and semantic bindings for action methods (all actions, or those whose
  owning class is in p_namespace). p_apply = false reports without writing.
  status: typed (already had parameters) | derived | no_owner | multiple_owners |
          no_input_schema | ambiguous (detail says what is missing).
*/
CREATE OR REPLACE FUNCTION "Meta".sp_derive_action_methods(
  p_namespace text DEFAULT NULL,
  p_apply boolean DEFAULT true
)
RETURNS TABLE (action_name text, owner_class text, status text, param_count integer, semantic_entity text, detail text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = "Meta", wf, portal, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  a record;
  v_owner record;
  v_method_id integer;
  v_class_id integer;
  v_class text;
  v_ns text;
  v_entity record;
  v_input jsonb;
  v_title text;
  p record;
  v_schema jsonb;
  v_ref text;
  v_type_name text;
  v_type_id bigint;
  v_attr record;
  v_params jsonb;
  v_problems text[];
  v_ord integer;
  v_status text;
  v_required jsonb;
BEGIN
  FOR a IN SELECT c.* FROM "Meta".fn_check_action_owners() c ORDER BY c.action_name
  LOOP
    v_class := a.owner_class;
    v_ns := split_part(COALESCE(v_class, ''), '/', 1);
    CONTINUE WHEN p_namespace IS NOT NULL AND v_ns IS DISTINCT FROM p_namespace
      AND a.action_name NOT LIKE p_namespace || '.%'
      AND COALESCE(a.owners, '') NOT LIKE '%' || p_namespace || '/%';
    IF a.status IN ('no_owner', 'multiple_owners') THEN
      RETURN QUERY SELECT a.action_name, NULL::text, a.status, 0, NULL::text, a.owners;
      CONTINUE;
    END IF;

    SELECT x.method_id, x.class_id INTO v_method_id, v_class_id
    FROM "Meta".fn_action_owner_methods(a.action_name) x WHERE x.class_name = v_class;

    -- Semantic entity mapped to the owning class, else to its nearest mapped ancestor.
    SELECT e.id, e.namespace || '.' || e.code AS label INTO v_entity
    FROM portal.semantic_entity e
    JOIN "Meta"."Classes" c ON c."ID" = v_class_id
    WHERE e.meta_class_id = c."ID" OR e.meta_class_id = ANY (COALESCE(c."AncestorPath", '{}'))
    ORDER BY (e.meta_class_id = c."ID") DESC, array_position(c."AncestorPath", e.meta_class_id) DESC NULLS LAST
    LIMIT 1;

    IF p_apply AND v_entity.id IS NOT NULL THEN
      INSERT INTO portal.semantic_action_binding (workflow_action_id, entity_id)
      SELECT wa.id, v_entity.id FROM wf.workflow_action wa WHERE wa.action_name = a.action_name
      ON CONFLICT DO NOTHING;
      UPDATE wf.workflow_action wa SET semantic_entity_id = v_entity.id
      WHERE wa.action_name = a.action_name AND wa.semantic_entity_id IS NULL;
    END IF;

    IF EXISTS (SELECT 1 FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id) THEN
      RETURN QUERY SELECT a.action_name, v_class, 'typed'::text,
        (SELECT count(*)::int FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id),
        v_entity.label, CASE WHEN a.status = 'known_duplicate' THEN 'duplicates: ' || a.owners END;
      CONTINUE;
    END IF;

    SELECT s.schema_json INTO v_input
    FROM wf.workflow_action wa
    JOIN wf.workflow_action_schema s ON s.workflow_action_id = wa.id AND s.direction = 'input'
    WHERE wa.action_name = a.action_name
    ORDER BY s.updated_at_utc DESC LIMIT 1;
    IF v_input IS NULL OR jsonb_typeof(v_input->'properties') <> 'object' THEN
      RETURN QUERY SELECT a.action_name, v_class, 'no_input_schema'::text, 0, v_entity.label, NULL::text;
      CONTINUE;
    END IF;

    v_title := COALESCE(NULLIF(v_input->>'title', ''), replace(a.action_name, '.', '_'));
    v_required := COALESCE(v_input->'required', '[]'::jsonb);
    v_params := '[]'::jsonb;
    v_problems := '{}';
    FOR p IN
      SELECT e.key, e.value FROM jsonb_each(v_input->'properties') e
      ORDER BY (v_required ? e.key) DESC, e.key
    LOOP
      v_schema := "Meta".fn_derive_property_schema(p.value);
      v_type_name := NULL;
      v_type_id := NULL;

      SELECT sa.code, sa.json_type INTO v_attr
      FROM portal.semantic_attribute sa
      WHERE v_entity.id IS NOT NULL AND sa.entity_id = v_entity.id
        AND (lower(sa.code) = lower(p.key) OR lower(sa.column_name) = lower(p.key)
             OR lower(sa.code) = lower(regexp_replace(p.key, '([a-z0-9])([A-Z])', '\1_\2', 'g')))
      LIMIT 1;
      IF v_attr.code IS NOT NULL AND "Meta".fn_semantic_json_type_schema(v_attr.json_type) IS NOT NULL
         AND (v_schema->>'type' IS NULL OR v_schema->>'type' = "Meta".fn_semantic_json_type_schema(v_attr.json_type)->>'type') THEN
        v_type_name := "Meta".fn_platform_action_type_for("Meta".fn_semantic_json_type_schema(v_attr.json_type));
      END IF;

      IF v_type_name IS NULL THEN
        v_type_name := "Meta".fn_platform_action_type_for(v_schema);
      END IF;
      IF v_type_name IS NOT NULL THEN
        SELECT t.id INTO v_type_id FROM wf.data_type t WHERE t.name = v_type_name AND t.status <> 'retired' ORDER BY t.id DESC LIMIT 1;
      ELSE
        v_ref := substring(v_schema->>'$ref' FROM '^#/\$defs/(.+)$');
        IF v_ref IS NOT NULL THEN
          IF jsonb_typeof(v_input->'$defs'->v_ref) <> 'object' THEN
            v_problems := v_problems || format('%s: unresolved $ref %s', p.key, v_ref);
            CONTINUE;
          END IF;
          v_type_name := v_ns || '/' || v_ref;
          v_schema := (v_input->'$defs'->v_ref);
        ELSE
          v_type_name := v_ns || '/' || v_title || '.' || p.key;
        END IF;
        IF v_schema::text LIKE '%"$ref"%' THEN
          v_schema := v_schema || jsonb_build_object('$defs', v_input->'$defs');
        END IF;
        IF p_apply THEN
          v_type_id := "Meta".fn_ensure_derived_data_type(v_type_name, v_schema);
        ELSE
          v_type_id := -1;
        END IF;
      END IF;
      IF v_type_id IS NULL THEN
        v_problems := v_problems || format('%s: data type %s exists with a different schema', p.key, v_type_name);
        CONTINUE;
      END IF;
      v_params := v_params || jsonb_build_object(
        'name', p.key, 'type_id', v_type_id, 'required', v_required ? p.key,
        'default', CASE WHEN p.value ? 'default' AND jsonb_typeof(p.value->'default') <> 'null' THEN p.value->'default' END
      );
    END LOOP;

    IF cardinality(v_problems) > 0 THEN
      RETURN QUERY SELECT a.action_name, v_class, 'ambiguous'::text, 0, v_entity.label, array_to_string(v_problems, '; ');
      CONTINUE;
    END IF;

    IF p_apply THEN
      v_ord := 0;
      FOR p IN SELECT e.value FROM jsonb_array_elements(v_params) e
      LOOP
        v_ord := v_ord + 1;
        INSERT INTO "Meta"."MethodParams" ("MethodID", "Ordinal", "Name", "TypeID", "Required", "DefaultValue")
        VALUES (v_method_id, v_ord, p.value->>'name', (p.value->>'type_id')::bigint, (p.value->>'required')::boolean,
                CASE WHEN jsonb_typeof(p.value->'default') = 'null' THEN NULL ELSE p.value->'default' END);
      END LOOP;
    END IF;
    v_status := 'derived';
    RETURN QUERY SELECT a.action_name, v_class, v_status, jsonb_array_length(v_params), v_entity.label,
      CASE WHEN a.status = 'known_duplicate' THEN 'duplicates: ' || a.owners END;
  END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION "Meta".sp_derive_action_methods(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION "Meta".fn_ensure_derived_data_type(text, jsonb) FROM PUBLIC;

/* Generic list types used by derived parameters. */
INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
SELECT v.name, '1.0', 'published', 'array', v.schema_json, md5(v.schema_json::text)
FROM (VALUES
  ('platform/action/TextList', '{"type":"array","items":{"type":"string"}}'::jsonb),
  ('platform/action/IntegerList', '{"type":"array","items":{"type":"integer"}}'::jsonb),
  ('platform/action/DecimalList', '{"type":"array","items":{"type":"number"}}'::jsonb),
  ('platform/action/BooleanList', '{"type":"array","items":{"type":"boolean"}}'::jsonb)
) AS v(name, schema_json)
WHERE NOT EXISTS (SELECT 1 FROM wf.data_type t WHERE t.name = v.name);
