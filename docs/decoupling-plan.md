# GoliathApp decoupling plan (Phase D)

GoliathApp is the platform at the top of the product hierarchy. It must not depend on or name child applications (GoliathOmics, GoliathCrop, GoliathFactory, GoliathRealty, GoliathGroundStation) or standalone utilities (GoliathAlign, GoliathExtractor). Those products extend the platform; the platform ships neutral contracts, env vars, and service names only.

Phase **D0** (this document and the repo-wide guard test) inventories every remaining reference and blocks **new** offenders. Phases **D1…D10** landed as small PRs; **D9** scrubbed the Delphi reference tree and **D10** removed the grandfather allowlist so CI fails on any token outside this plan file.

## Audit snapshot (2026-11-05, D0 baseline — historical)

| Metric | Value |
|--------|------:|
| Files with at least one forbidden token | 103 |
| Total matching source lines | 633 |
| Files in D0 allowlist | 103 |

The guard test scans `py`, `sql`, `md`, `pas`, `dbd`, `json`, `yaml`, `toml`, and Delphi project/design artifacts (`.dfm`, `.dpr`, `.dproj`, `.design`, `.dcomp`). Shell scripts (for example `scripts/init_work_layout.sh`) are out of scope for the test but called out here for later phases.

### Token frequency (line-level)

| Token / pattern | Lines |
|-----------------|------:|
| `methyl` (substring) | 513 |
| `omics` (substring) | 94 |
| `goliathomics` | 13 |
| `groundstation` / GoliathGroundStation | 4 |
| `goliathfactory` | 3 |
| `crop` (word) | 3 |
| `factory` (word, excluding Python/Delphi false positives) | 2 |
| `goliathcrop` | 1 |
| `goliathalign`, `goliathextractor`, `goliathrealty`, `realty` | 0 |

### Category breakdown

| Category | Lines | Files | Meaning |
|----------|------:|------:|---------|
| **config/env** | 164 | 42 | `METHYL_*`, `methyl_work_root`, `methyl_site.json`, `methyl-cfg`, CI passwords, `pyproject.toml` console scripts |
| **db/service-name** | 161 | 28 | `METHYLPIPELINE_DB`, default DB name `methylpipeline`, `MethylWfGateway`, Delphi `.dbd`, connection strings, health `service` id |
| **domain-logic (belongs in GoliathOmics)** | 134 | 10 | Contract docs, domain types, sample-prep capabilities, `sample.methyl_*` actions, pipeline profile science keys |
| **test** | 59 | 17 | Fixtures and tests asserting legacy names |
| **mixed** | 37 | 17 | Python modules that combine env aliases with omics semantics (`workflow_context`, `verify_workflow`, workers) |
| **naming-only** | 36 | 10 | README/docs that describe legacy CLI names without executing omics code |

### Heaviest files (match lines)

| File | Lines | Primary category |
|------|------:|------------------|
| `workflow_engine/contract/sample_prep_capabilities.md` | 75 | domain-logic |
| `workflow_engine/domain/pipeline_profiles.py` | 39 | domain-logic / mixed |
| `workflow_engine/delphi/db-designer/Portal.dbd` | 34 | db/service-name |
| `workflow_engine/delphi/db-designer/Workflow-Engine.dbd` | 31 | db/service-name |
| `workflow_engine/contract/domain_types.md` | 27 | domain-logic |
| `workflow_engine/tests/fixtures/sample_prep.program.json` | 27 | domain-logic (test fixture) |
| `workflow_engine/delphi/db-designer/Meta.dbd` | 19 | db/service-name |
| `workflow_engine/tests/test_pipeline_scope_flags.py` | 17 | test |
| `workflow_engine/delphi/db-designer/Objects.dbd` | 15 | db/service-name |
| `workflow_engine/cfg/reference_selection.py` | 11 | mixed (genome paths; comments name methylGrapher) |
| `docs/platform.md` | 12 | naming-only / config/env |
| `workflow_engine/pyproject.toml` | 9 | config/env |

### Representative tokens to eliminate

| Legacy | Category | Neutral target (platform) |
|--------|----------|---------------------------|
| `methyl-gateway`, package `methyl-gateway` | config/env | `goliath-gateway`; keep old console entry one release |
| `methyl-cfg`, `METHYL_CFG_STORE`, `METHYL_WORK_ROOT` | config/env | `goliath-cfg`, `GOLIATH_CFG_STORE`, `GOLIATH_WORK_ROOT` |
| `methyl_site.json`, `default_methyl_site.json` | config/env | `site.json`, `default_site.json` (read legacy path one release) |
| `METHYLPIPELINE_DB`, DB name `methylpipeline` | db/service-name | `GOLIATH_DATABASE_URL` / `WF_DATABASE_URL`; DB name `goliath` |
| `methyl-workflow-gateway` (health JSON) | db/service-name | `goliath-workflow-gateway` |
| `MethylWfGateway`, `TMethylWfGatewayService` | db/service-name | Archive Delphi tree or rename to neutral `WfGateway` in reference-only code |
| `sample.methyl_extract`, `sample.methyl_qc` | domain-logic | Move to GoliathOmics action catalog; platform uses `sample.extract` / `sample.qc` stubs only in Omics repo |
| `MethylSampleRef`, `methylvalidation.plan` | domain-logic | Schemas and extension keys owned by GoliathOmics (`schemas/domain/` there) |
| `methyl_utils`, `methyl_worker`, `methyl_enricher` | domain-logic | Import paths only in GoliathOmics / worker packages |
| `methylgrapher`, `MethylMapper`, Houseman / WGBS bundle comments | domain-logic | Reference asset docs in GoliathOmics; platform keeps opaque `reference_asset` roles |
| `METHYL_REQUIRE_MOJO_LINEAR` | config/env | `GOLIATH_REQUIRE_MOJO_LINEAR` (compat alias one release) |
| Docs naming GoliathOmics / GroundStation | naming-only | Link out to child repos; platform docs describe extension points only |

Existing guard: `workflow_engine/tests/test_goliathapp_sql_no_extension_domain.py` covers **SQL** references to extension-app portal tables only. Phase D adds the repo-wide token guard and this plan.

### Full file inventory (D0 baseline)

D0 tracked 103 allowlisted paths in `child_app_token_allowlist.txt` (removed in **D10**). The repo-wide guard now scans the tree with no grandfather list.

---

## Cross-cutting rules (all D phases)

1. **One-release backward compatibility** for env vars, filesystem paths, and PyPI/console script aliases: read the new name first, fall back to the legacy name, emit a deprecation warning in logs where cheap.
2. **No dual semantics**: neutral names must not encode methylation, crop, factory, or other child-domain meaning.
3. **Paired GoliathOmics PRs**: whenever GoliathApp removes or relocates a contract (domain types, sample prep, validation planner, action names, JSON schemas), land the consuming change in GoliathOmics in the same release train (Omics PR linked from the App PR).
4. **Guard**: after **D10**, `test_goliathapp_no_child_app_tokens.py` must stay green with zero allowlist; only this plan documents legacy token names for archaeology.
5. **Production renames** (database name, Windows service name, deployed systemd unit, Azure resource labels) require **David's confirmation before execution** — marked ⚠️ below.

---

## Phased delivery

Each phase is intended as **one small PR** to GoliathApp unless noted. Order can shift slightly if release pressure demands, but db/service renames stay last.

### D1 — Platform docs and OpenAPI surface (naming-only)

**GoliathApp**

- Rewrite `README.md`, `docs/platform.md`, `docs/deployment.md`, `docs/workers.md`, `docs/workspace-index.md` to use neutral CLI/gateway names and to point to child repos for omics deployment profiles.
- Update `contracts/openapi.yaml` service metadata if it still says methyl-gateway.
- Trim `docs/inventory-module.md` product examples so inv docs do not name Factory/Crop/Omics (keep “child app” abstract).

**GoliathOmics**

- Add a short `docs/goliathapp-extension.md` section listing legacy→neutral aliases operators still use on omics targets.

**Allowlist**: remove ~10 doc paths. **No production impact.**

---

### D2 — Python packaging and console entry points (config/env)

**GoliathApp**

- Rename PyPI distribution in `workflow_engine/pyproject.toml` from `methyl-gateway` to `goliath-gateway` (or merge into existing naming); retain `methyl-*` console scripts as shims for one release.
- Update `pyrefly.toml`, `.github/workflows/pr.yml` (Postgres password placeholder — use neutral test secret), and `docs/actions.md` export commands.

**GoliathOmics**

- Pin dependency on new package name; keep shim imports if needed.

**Allowlist**: shrink cfg/pyproject/workflow files. **No production impact** until deploy recipes bump.

---

### D3 — Work root, site manifest, and cfg store paths (config/env)

**GoliathApp**

- `scripts/init_work_layout.sh`: prefer `GOLIATH_WORK_ROOT` / `site/goliath_site.json`, copy from `scripts/default_site.json`; one-release fallback for `METHYL_*` and `methyl_site.json`.
- `goliath_worker/work_share.py`, `workflow_engine/cfg/store.py`, `cfg/cli.py`, `scaffold.py`, `sync_*`: neutral env vars and help text.
- Rename `scripts/default_methyl_site.json` → `default_site.json` with compat copy.

**GoliathOmics**

- Site templates and materialize docs updated to new paths; Omics seeds `reference_selection` JSON under neutral layout.

**Allowlist**: remove script + cfg paths after shim landed. **Filesystem on NAS**: operators may keep symlinks one release; no DB rename.

---

### D4 — Gateway identity and connection env (db/service-name, code)

**GoliathApp**

- `workflow_engine/rest/gateway.py`: health `service` → `goliath-workflow-gateway`.
- `workflow_engine/rest/connection.py`, `goliath_worker/postgres_wake.py`, `goliath_worker/client.py`: `GOLIATH_DATABASE_URL` with `METHYLPIPELINE_DB` fallback; stop defaulting logical DB name to `methylpipeline` in new code paths.
- Update tests in `test_connection.py`, `test_worker_session_auth.py`, wake tests.

**GoliathOmics**

- Worker and gateway systemd/env templates switch to new vars (keep old vars in template comments one release).

**Allowlist**: rest + worker modules.

⚠️ **David confirmation** before changing the **production PostgreSQL database name** or connection strings on shared hosts (see D8). D4 is code-only defaults.

---

### D5 — Move omics contract markdown out of the App tree (domain-logic)

**GoliathApp**

- Relocate or delete omics-specific contract bodies:
  - `workflow_engine/contract/sample_prep_capabilities.md`
  - `workflow_engine/contract/domain_types.md`
  - `workflow_engine/contract/validation_planner_capabilities.md`
- Replace with thin stubs linking to GoliathOmics (or platform-neutral placeholders: “application-defined domain types”).
- Trim `workflow_engine/contract/db_objects.md` header (“MethylPipeline”) to “GoliathApp DB object contract”.
- Replace `workflow_engine/tests/fixtures/sample_prep.program.json` with a **neutral** minimal DomainProgram fixture; move methyl program to GoliathOmics tests.

**GoliathOmics**

- Own the full capability docs and fixtures; register real `sample.*` actions in Omics seed SQL.

**Allowlist**: remove contract + fixture paths.

---

### D6 — Pipeline profiles and workflow context (domain-logic)

**GoliathApp**

- Split `workflow_engine/domain/pipeline_profiles.py`: platform keeps generic scope-flag resolution; move mc_*/samd_research/mhl_* presets to GoliathOmics.
- Remove `methyl_utils` / `methyl_worker` imports from `workflow_engine/local/engine.py`, `domain/workflow_context.py`, `domain/verify_workflow.py`; use optional hooks or stub only behind `WORKER_STUB_EXTERNAL`.
- `reference_selection.py`: keep genome layout math; move methylGrapher/WGBS commentary to Omics docs.

**GoliathOmics**

- Host profile JSON, modes, and `finalize_instance_context` enrichment.

**Allowlist**: domain + local runner paths.

---

### D7 — SQL comments, portal APIs, and deploy metadata (mixed)

**GoliathApp**

- Scrub comments in `workflow_engine/sql_pg/*.sql` that say “Omics apps seed …” → “Application extensions seed …”.
- Review `portal_study_pipeline_api.sql`, `portal_contract_api.sql`, `cfg_registry_tables.sql` for neutral wording only (no schema drop yet — Omics tables already excluded by `test_goliathapp_sql_no_omics_domain.py`).
- `deploy/targets/goliath-exo.json`, `deploy/README.md`: remove omics-target narrative from platform deploy bundle or move to Omics repo.

**GoliathOmics**

- Own `goliath-test` deploy profile docs (already referenced in App deployment.md today).

**Allowlist**: sql_pg + deploy paths.

---

### D8 — Production database and service identifiers ⚠️

**Status:** GoliathApp-side renames and env shims landed in this repository. **David approved (2026-11-05).** Neon backup branch `backup-d8-20261105` was created before apply. Shared-environment database rename on exo hosts and GoliathOmics systemd/service renames may still be in flight separately (GoliathOmics repo).

**Requires David's confirmation before any apply to shared environments** (exo `methylpipeline` → `goliath` where applicable).

**GoliathApp (landed in this repository)**

- Python gateway and workers default logical DB name `goliath` and prefer `GOLIATH_DATABASE_URL` / `WF_DATABASE_URL` with `METHYLPIPELINE_DB` fallback (D4). Non-Delphi code no longer defaults to `methylpipeline`.
- PyPI distribution `goliath-gateway`; **`methyl-*` console-script aliases removed in D10** (no grandfather block in `pyproject.toml`).
- Delphi `WfEngineGateway` / `WfEngineSrv` stay **deprecated and not deployed** (`DELPHI_GATEWAY_STATUS.md`); reference tree scrub completed in **D9**.
- **No Neon or shared PostgreSQL rename from GoliathApp** — infra apply is paired with GoliathOmics.

**Production naming (confirmed)**

| Target | Database / service note |
|--------|-------------------------|
| **GoliathOmics Neon** | Database name stays **`GoliathOmics`** (no rename). |
| Exo / legacy App hosts | Where the logical DB was `methylpipeline`, operators may rename to `goliath`; rotate Key Vault / deploy targets; keep `METHYLPIPELINE_DB` env shim one release. |
| **GoliathOmics deploy** | systemd/nginx/install path renames (`methyl-gateway` → `goliath-gateway`, matching env) land in **GoliathOmics**, not GoliathApp. |

**Paired rollout**: maintenance window, backup (Neon branch above), connection string swap where applicable, verify `goliath-gateway` health and worker claim.

---

### D9 — Delphi reference tree and `.dbd` designer artifacts (db/service-name)

**Status: Done (2026-11-05).** In-repo scrub (no archive repo): neutral `WfEngine` / `GoliathWfRef` labels, `WfEngineGateway` service names, `WF_DATABASE_URL` / `GOLIATH_DATABASE_URL` in frozen Delphi connection helpers; designer `.dbd` / `.dcomp` filenames and paths scrubbed. Python `goliath-gateway` remains canonical per `DELPHI_GATEWAY_STATUS.md`. Live DDL is **not** generated from `.dbd` files (Python gateway + `sql_pg` are canonical).

**GoliathApp (delivered)**

- Either archive `workflow_engine/delphi/` to a separate repo or scrub all Methyl/Methylpipeline labels to neutral `WfEngine` reference names.
- Designer files (`Portal.dbd`, `Workflow-Engine.dbd`, `MethylPipeline vs. EpiPortalDB …dcomp`) move to Omics or historical archive — not required for Python gateway operations.

**GoliathOmics**

- If historical EpiPortal parity is still needed, host db-designer sources there.

**Allowlist**: remove entire `delphi/` subtree from App repo or from allowlist after scrub.

⚠️ **David confirmation** if any `.dbd` is still used to generate live DDL (unlikely; confirm before delete).

---

### D10 — Guard allowlist empty and CI hardening

**Status: Done (2026-11-05).** Deleted `child_app_token_allowlist.txt`; `test_goliathapp_no_child_app_tokens.py` fails on any child-app token in scanned extensions except this plan and the test module. Kept `test_goliathapp_sql_no_extension_domain.py` as the SQL-specific extension-table guard (complementary, not merged). Shell layout script `scripts/init_work_layout.sh` already avoids legacy env names in source via split literals; no extra scan added.

**GoliathApp (delivered)**

- Delete `child_app_token_allowlist.txt`; guard test fails on any token anywhere (except excluded plan/test files).
- Extend `test_goliathapp_sql_no_omics_domain.py` or merge guards if redundant.
- Add optional shell scan (`scripts/init_work_layout.sh`) to guard extensions list.

**GoliathOmics**

- Mirror guard ensuring Omics repo **does** contain its domain tokens (inverse test optional).

---

## Paired GoliathOmics PR checklist (template)

Use this in every App PR that touches contracts or actions:

| App change | Omics PR must |
|------------|----------------|
| Remove `sample.methyl_*` from docs/fixtures | Register actions + handlers under Omics catalog |
| Move domain JSON schemas out of App | Add `schemas/domain/` + export CLI in Omics |
| Neutral `DomainProgram` fixture in App tests | Port full sample-prep program test to Omics |
| Rename env vars / site JSON | Update materialize + NAS sync playbooks |
| ⚠️ DB rename | Update Omics worker env, smoke claim/submit, validation pipeline |

---

## Verification

- CI: `pytest workflow_engine/tests/test_goliathapp_no_child_app_tokens.py`
- Existing: `test_goliathapp_sql_no_extension_domain.py`, gateway unit tests in `.github/workflows/pr.yml`
- After D8 shared-env apply: run schema apply + worker enroll/claim smoke on exo target

---

## Related work outside this repository

| Product | Decoupling note |
|---------|-----------------|
| **GoliathAlign**, **GoliathExtractor** | No token hits in App today; guard prevents introduction. |
| **GoliathCrop**, **GoliathFactory**, **GoliathRealty** | Only doc-level mentions (`inventory-module.md`); D1/D7 scrub. |
| **GoliathGroundStation** | Tier-2 wake docs in `dual-activation.md`; D1 links out. |

---

*Phase D0 deliverables: this plan, `test_goliathapp_no_child_app_tokens.py`, and baseline allowlist (allowlist removed in D10).*
