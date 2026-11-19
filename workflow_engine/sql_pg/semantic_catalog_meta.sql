/*
  Semantic catalog in Meta: namespaces, entities, attributes, requests, action and nav bindings are
  platform/semantic classes' objects (generic catalog projection, meta_catalog_projection.sql).
  Idempotent: registers the kinds, then migrates every row (parents first).
*/

BEGIN;

SELECT "Meta".sp_catalog_register_kind('semantic.namespace', 'platform/semantic/Namespace', 'platform/Entity',
  'portal.semantic_namespace', ARRAY['code'], ARRAY['code']);
SELECT "Meta".sp_catalog_register_kind('semantic.entity', 'platform/semantic/Entity', 'platform/Entity',
  'portal.semantic_entity', ARRAY['id'], ARRAY['namespace', 'code']);
SELECT "Meta".sp_catalog_register_kind('semantic.attribute', 'platform/semantic/Attribute', 'platform/Entity',
  'portal.semantic_attribute', ARRAY['id'], ARRAY['code']);
SELECT "Meta".sp_catalog_register_kind('semantic.request', 'platform/semantic/Request', 'platform/Entity',
  'portal.semantic_request', ARRAY['id'], ARRAY['request_code', 'version']);
SELECT "Meta".sp_catalog_register_kind('semantic.action_binding', 'platform/semantic/ActionBinding', 'platform/Entity',
  'portal.semantic_action_binding', ARRAY['workflow_action_id', 'entity_id'], ARRAY['workflow_action_id', 'entity_id']);
SELECT "Meta".sp_catalog_register_kind('semantic.nav_binding', 'platform/semantic/NavBinding', 'platform/Entity',
  'portal.semantic_nav_binding', ARRAY['id'], ARRAY['nav_tree_id']);

SELECT m.* FROM unnest(ARRAY[
  'semantic.namespace', 'semantic.entity', 'semantic.attribute',
  'semantic.request', 'semantic.action_binding', 'semantic.nav_binding'
]) WITH ORDINALITY k(kind, ord)
CROSS JOIN LATERAL "Meta".sp_catalog_migrate(k.kind) m
ORDER BY k.ord;

COMMIT;
