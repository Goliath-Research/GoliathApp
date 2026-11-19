"""Workflow and cfg catalogs are registered as Meta catalog kinds with no drift."""

from __future__ import annotations

from workflow_engine.tests.test_portal_record_editors import _psql, editor_env  # noqa: F401

WF_CFG_KINDS = [
    "wf.action",
    "wf.action_schema",
    "wf.action_compile_profile",
    "wf.event_type",
    "wf.pipeline_stage",
    "wf.workflow_def",
    "wf.workflow_version",
    "wf.node",
    "wf.edge",
    "wf.input_template",
    "wf.input_binding",
    "wf.output_binding",
    "wf.scope_default",
    "wf.collection_binding",
    "cfg.kind_document_type",
    "cfg.analyte",
    "cfg.storage_endpoint",
    "cfg.storage_profile",
    "cfg.reference_asset",
    "cfg.site",
    "cfg.site_reference_asset",
    "cfg.pipeline_profile",
    "cfg.enrichment_library_preset",
    "cfg.action_definition",
    "cfg.domain_program",
    "cfg.program_publish",
    "cfg.assay_procedure",
    "cfg.node_config",
    "cfg.portal_auth_default",
    "cfg.study",
    "cfg.study_group",
    "cfg.study_group_member",
]


def test_wf_and_cfg_catalogs_are_in_meta(editor_env: dict[str, str]) -> None:
    env = editor_env
    kinds = _psql(
        """SELECT kind FROM "Meta".catalog_kind
           WHERE kind LIKE 'wf.%' OR kind LIKE 'cfg.%' ORDER BY kind""",
        env,
    ).splitlines()
    assert kinds == sorted(WF_CFG_KINDS)
    assert _psql("""SELECT count(*) FROM "Meta".fn_catalog_drift() WHERE kind LIKE 'wf.%' OR kind LIKE 'cfg.%'""", env) == "0"
    # Secrets and the type registry stay out of Meta.
    excluded = _psql(
        """SELECT kind FROM "Meta".catalog_kind
           WHERE kind IN ('cfg.credential', 'wf.data_type', 'wf.cluster')""",
        env,
    ).strip()
    assert excluded == ""
    # portal_auth_defaults is only integer timeout keys, not secrets.
    keys = _psql("SELECT key FROM cfg.portal_auth_defaults ORDER BY key", env).splitlines()
    assert keys == [
        "portal_session_absolute_seconds",
        "portal_session_idle_seconds",
        "worker_heartbeat_seconds",
        "worker_session_max_failed_attempts",
        "worker_session_miss_factor",
    ]
    for key in keys:
        typ = _psql(
            f"SELECT jsonb_typeof(value_json) FROM cfg.portal_auth_defaults WHERE key = '{key}'",
            env,
        )
        assert typ == "number", key
