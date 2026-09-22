# Plan: Separate GoliathApp from GoliathOmics

**Status:** Decisions locked (2026-09-22). Platform source still lives in `GoliathWorkflow`.  
**Author context:** David Izada Rodriguez / Goliath Research  
**Source of truth for current code:** `Goliath-Research/GoliathWorkflow` (in-repo package: **methylpipeline**)  
**Platform repo:** `Goliath-Research/GoliathApp` (`main` at `9b30a57`, plan and README only)  
**Independent tool repos (keep separate):** `mojo-align`, `MethylExtractor`

---

## 1. Purpose

Split the long-lived **generic application platform** (GoliathApp) from its **genomics specialization** (GoliathOmics), so that:

1. **GoliathApp** remains a reusable builder: database-governed Meta model, RBAC, object store, portal UI, workflow engine, middle-tier REST, and remote workers — without methylation semantics.
2. **GoliathOmics** (today the MethylPipeline package inside `GoliathWorkflow`) becomes the genomics product: science packages, DomainPrograms/profiles/analytes, genomics worker handlers, and docs — depending on GoliathApp as a library/service.
3. **mojo-align** and **MethylExtractor** stay independent tool projects consumed by GoliathOmics (image/binary contracts only).

This document is an executable separation plan: target boundaries, move map, coupling cuts, phased sequence, naming, and success criteria.

**Do not call the platform an “application pack.”** Inside MethylPipeline that phrase already means a config overlay on a process pack (Alzheimer cfDNA, plant abiotic stress). See `GoliathWorkflow/docs/plans/generic-application-pack-pattern.plan.md`.

---

## 2. Historical product model (platform invariant)

Since ~1986, GoliathApp has abstracted what every application repeats:

| Layer | Role |
|-------|------|
| **Database** | System of record and governor of behavior (evolved from custom DB → MSSQL → PostgreSQL; Azure SQL twin still present). |
| **Middle-tier** | From embedded data modules → REST service with generic services; local/remote DB protocol. |
| **Frontend** | UI dynamically generated from DB-described portal objects. |

### Schema architecture (conceptual → current names)

| Concept (historical) | Current home in `GoliathWorkflow` | Notes |
|----------------------|-----------------------------------|-------|
| **Meta** — OOP model of application information | SQL schema `Meta` (`meta_schema.sql`, …); object identity in **`Meta.Objs`** | There is no separate top-level `obj` schema; instances live under Meta. |
| **RBAC** — roles over Meta classes and concrete objects | SQL schema `RBAC` | Platform. |
| **obj** — instances of Meta classes | **`Meta.Objs`** (+ related Meta tables) | Document as the “obj layer” in GoliathApp docs; do not invent a parallel schema. |
| **portal** — UI objects | SQL schema `portal` (+ `portal_*_api.sql`, EpiPortal) | Platform shell. Clinical/disease columns are Omics content (`portal_clinical_schema.sql`). |
| **wf** — event-driven workflows → actions for portal users or remote workers | SQL schema `wf` + gateway + worker protocol | Platform. Genomics action *names and handlers* are Omics seeds plus `methyl_worker`. |
| **cfg** (evolution) | SQL schema `cfg` — sites, profiles, programs, storage, assets | Platform registry tables. Science rows and reference-asset seeds are GoliathOmics content. |

**Additional platform schemas today:** `Contract`, `Onboarding` (keep with GoliathApp).

**Invariant to preserve:** *The database does not encode methylation semantics* — action definitions and DomainPrograms are data; the engine remains agnostic.

---

## 3. Current state (as of 2026-09-22)

### 3.1 Repositories

| Repo | State | Role today |
|------|-------|------------|
| `Goliath-Research/GoliathWorkflow` | Public monorepo | Engine + MethylPipeline science + workers + docs. **All platform code still lives here.** |
| `Goliath-Research/GoliathApp` | Private, **plan only** | `main` `9b30a57` (PR #1): `README.md` and this file. No gateway, SQL, or worker source yet. |
| `Goliath-Research/mojo-align` | Separate | GPU alignment / methylgrapher family. Toolchain is Mojo 1.1 (Modular 26.6), not the 1.0 beta. |
| `Goliath-Research/MethylExtractor` | Separate | BAM→HDF5 MethylDackel fork |

This plan is already parked in GoliathApp. The next step is Phase 0 (contract freeze), not another home for the document.

### 3.2 Naming (locked)

| Name | Where | Meaning |
|------|-------|---------|
| GoliathWorkflow | GitHub repo | Monorepo host until the split. Science history stays here, then the repo is renamed. |
| methylpipeline / `methyl-*` | `pyproject`, CLIs, Docker | Transitional package and CLI aliases for one release cycle |
| GoliathOmics | Product and future repo name | Genomics product |
| GoliathApp | This repo | Platform |
| `goliath-*` | Born in GoliathApp | Platform entry points (`goliath-gateway`, `goliath-cfg`, …) |
| EpiPortal | Portal UI docs | Company portal over `portal.sp_*` |
| `goliath` (infra) | DB name, `/work/goliath/`, image org | Namespace |
| Application pack | MethylPipeline docs only | Config overlay on an existing process pack. Not a name for this platform. |
| Process pack | MethylPipeline docs | New omics modality (actions, programs, QC) |

### 3.3 What already matches the platform vision

Inside `GoliathWorkflow` today:

- **Platform-shaped:** `workflow_engine/rest/` (gateway), `sql_pg` / `sql_mssql` engine DDL (wf/cfg/portal/Meta/RBAC/Contract/Onboarding), `cfg/` CLI, `local/` runner, `delphi/` middle-tier, worker protocol, OpenAPI, DomainProgram compiler/IR, `/work` materialization contract.
- **Genomics-shaped:** 26 packages under `packages/` (21 `methyl*`, `omicsfeatures`, `rnaexpress`, `rnaalignmentqc`, `proteomicsfeatures`, `proteomicsqc`), `workers/methyl_worker/`, domain analytes/profiles/fixtures/checks, science SQL seeds, methylgrapher Docker bake of mojo-align, science docs.

Copying all of `sql_pg/` into GoliathApp would fail the Phase 1 exit. Detector, study, and reference-asset seeds live in that tree.

---

## 4. Target repository map

```
┌─────────────────────────────────────────────────────────────┐
│  GoliathApp (platform)                                      │
│  Meta · RBAC · Meta.Objs · portal engine · wf · cfg DDL     │
│  REST gateway · optional Delphi MT · local engine           │
│  Shared worker (claim/submit) · /work optional              │
│  Deploy/bootstrap for control plane                         │
└───────────────────────────┬─────────────────────────────────┘
                            │ publishes contracts:
                            │ OpenAPI, SQL migrations, IR schemas,
                            │ /work layout, action I/O shapes
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  GoliathOmics (application)                                 │
│  Science packages · DomainPrograms/profiles/analytes        │
│  methyl_worker handlers · action catalog seeds              │
│  Site/process-pack content · science docs                   │
│  Depends on GoliathApp (pip/git + running gateway/DB)       │
└───────────────┬─────────────────────────┬───────────────────┘
                │                         │
                ▼                         ▼
        ┌───────────────┐         ┌──────────────────┐
        │  mojo-align   │         │ MethylExtractor  │
        │  (image bake) │         │ (binary under    │
        │  Mojo 1.1     │         │  /work/goliath/) │
        └───────────────┘         └──────────────────┘
```

### 4.1 GoliathApp — engine, no science rows

| Path / artifact | Role |
|-----------------|------|
| `workflow_engine/rest/` | Agnostic gateway (`goliath-gateway`; alias `methyl-gateway` for one cycle) |
| `workflow_engine/sql_pg/`, `sql_mssql/` **engine files only** | DDL/APIs for Meta, RBAC, portal engine, wf engine, cfg schema, Contract, Onboarding. See §4.2 for seeds that stay out. |
| `workflow_engine/cfg/` | Config registry CLI (`goliath-cfg` / alias `methyl-cfg`) |
| `workflow_engine/local/` | In-process DomainProgram runner |
| `workflow_engine/contract/`, `delphi/`, thin `portal/` helpers | Platform |
| `workflow_engine/domain/compiler.py`, `verify_workflow.py`, `pipeline_profiles.py`, `workflow_context.py` | DomainProgram compiler, IR check, profile resolution, instance-context contract |
| `contracts/openapi.yaml` | Published HTTP contract |
| Platform slices of `schemas/` (workflow, domain_program, storage, …) | Platform |
| `deploy/` control-plane pieces, worker join docs (generic) | Platform |
| `scripts/init_work_layout.sh` | `/work` layout contract. Storage is optional: a workflow that never calls the helpers runs with no mount. |
| `workers/WORKER_PROTOCOL.md` | Claim/submit protocol |
| `goliath_worker/client.py`, `goliath_worker/work_share.py` | Shared worker. Lifted from `workers/methyl_worker/` (stdlib only). Action handlers stay in Omics. |
| Platform architecture docs (component-boundaries, distributed-runtime, config-registry — examples stripped of methylation) | Platform |

### 4.2 GoliathOmics — content and handlers

| Path / artifact | Role |
|-----------------|------|
| `packages/*` (all 26) | Science libraries. RNA and proteomics stay here. |
| `workers/methyl_worker/` handlers and runners | Specific workers that execute Omics actions. Does not own the claim protocol or `init_work_layout.sh`. |
| Database content | Data-type rows, action catalog, analyte rows, reference-asset seeds. Engine DDL stays in App. |
| `workers/docker/methylgrapher/` | Image bake wiring to mojo-align |
| `workflow_engine/domain/{analytes,profiles,fixtures,checks}/` | Programs, profiles, CI cohorts |
| `workflow_engine/domain/modality_gate.py` | Omics. It imports `methyl_utils` and lists methylation-only actions. |
| `workflow_engine/ops/` (`sample_prep_*`, `study_lifecycle*`) | Omics, or thin generic hooks in App plus science plugins |
| `workflow_engine/admin/` methylation finalize/bake helpers | Omics. Generic instance APIs stay in App. File-level pass in Phase 1; do not move the whole `admin/` directory. |
| Science `schemas/actions`, `schemas/tasks`, methyl_* domain schemas | App contracts owned by the product |
| Science docs (theory, usage SamplePrep, regulatory) | Product docs |
| Science scripts (genome provision content, analyte compares, …) | Ops content |
| Root packaging | Product surface stays `methylpipeline`, with `methyl-*` aliases |

**Science SQL that must not ship as App engine** (same names in `sql_pg` and the `sql_mssql` twin where one exists):

| File | Why it stays in Omics |
|------|------------------------|
| `wf_split_detector_actions_seed.sql` | Methylation detector action catalog |
| `wf_two_group_test_seed.sql` | Study/test seed |
| `wf_mc_two_group_test_seed.sql` | Monte Carlo study seed |
| `migrate_work_paths_prostate_cancer.sql` | Disease-specific path migration |
| `cfg_reference_assets_seed.sql` | Genome / reference-asset rows |
| `cfg_site_reference_assets_seed.sql` | Site-to-asset links |
| `cfg_analyte_catalog.sql` | `cfg.analyte` table and catalog. Not created by App `cfg_registry_tables.sql`. |
| `portal_clinical_schema.sql` | Clinical/disease columns. Portal *engine* APIs stay in App. Column review in Phase 3. |
| `portal_clinical_api.sql`, `portal_clinical_api_parity.sql` | Procedures over those clinical tables |
| `seed_action_catalog.py`, `seed_action_schemas.py`, `seed_data_types.py` | Load Omics action and data-type documents. `wf_data_type.sql` (the table) stays in App. |
| `wf_data_driven_pipeline_seed.sql`, `wf_validation_pipeline_seed.sql` | Product workflow graphs |
| `sql_mssql/deprecated/*`, `PCaOvrFlow.md`, `PCaTwoGroupFlow.md`, `SamplePrepFlow.md`, `DataDrivenPipeline.md` | Historical PCa, SamplePrep, and methylvalidation seeds |
| `wf_worker_contracts_pca_*.md` | Study-specific worker contracts |
| `instance_context_examples/` | Buffy, PCa, SamplePrep, and Monte Carlo instance payloads |
| `migrations/20260721_site_reference_asset_deconv_roles.sql` | Deconvolution reference-asset roles |
| `MethylPipeline.sql`, `MethylPipelineDB_Script.sql` | Product database dumps, not the engine source |

`cfg.analyte` and `cfg_analyte_catalog.sql` belong to GoliathOmics (specimen and matrix documents such as cfdna and buffy coat). App registry scripts do not create that table. Some App queries still join it and run only after the Omics catalog migration.

`workflow_seed_examples.sql` stays in App. DemoFlow uses only `demo.echo`, `demo.branch`, `demo.parallel`, and `demo.repeat`. `workflow_tree_seed_example.sql` stays for the same reason: its actions are `delphi.*`, not GoliathOmics actions.

### 4.3 Leave independent

| Repo | Contract with GoliathOmics |
|------|----------------------------|
| **mojo-align** | Image tag built from a declared git tag. Toolchain pin: Mojo 1.1 / Modular 26.6 (`pixi` channel), not Mojo 1.0.0b2. `MOJO_ALIGN_ROOT` → `goliath/methylgrapher:*-mojo-*`; in-image `/opt/mojo-align`. SamplePrep owns `/work/samples/...` arm dirs. Required features: `GoliathWorkflow/docs/contracts/omics-tool-requirements.md`. |
| **MethylExtractor** | Binary under `/work/goliath/methyl-extractor-*/`. `extraction_manifest` / QC JSON consumed by `methylextractionqc`. Required features are in the same Omics document. A change to either tool that drops a listed feature breaks GoliathOmics. |

### 4.4 Decisions (locked)

| Item | Decision |
|------|----------|
| `workflow_engine/domain/` tree | **Split.** Compiler, verify, profile resolver, and `workflow_context.py` → GoliathApp. `analytes/`, `profiles/`, `fixtures/`, `checks/`, and `modality_gate.py` → GoliathOmics. |
| `workflow_engine/ops/sample_prep_*`, `study_lifecycle*` | **GoliathOmics** (or thin generic hooks in App + science plugins). |
| `workflow_engine/admin/study_*` | Generic instance APIs → App. Methylation finalize/bake helpers → Omics, after a file-level pass. |
| RNA / proteomics packages | **Stay in GoliathOmics** (`rnaexpress`, `rnaalignmentqc`, `proteomicsfeatures`, `proteomicsqc`). Not separate repos. |
| Portal clinical / disease-specific columns | Portal engine in App. `portal_clinical_schema.sql` is Omics content until Phase 3 reclassifies individual columns. |
| `tools/methyl-config-editor` | Stays with Omics until a generic config editor is extracted into App. |
| `GoliathApp` repo | **Primary destination** for the platform move. Do not rename GoliathWorkflow in place and call that the platform. |
| `GoliathWorkflow` name | After the split, rename the science repo to **GoliathOmics**. Do not keep three product names. |
| History | `git filter-repo` for platform paths into GoliathApp. Science history stays in GoliathWorkflow until that rename. |
| Database | **One database** named `goliath`. App owns engine DDL. Omics owns content seeds. No second database. |
| Shared worker | App owns claim/submit (`goliath_worker`) and the `/work` layout. Omics owns action handlers. `/work` is optional for workflows that do not call the storage helpers. |
| Inherited names | Omics-facing docs and the App package use the `goliath` prefix for platform pieces (`goliath-gateway`, `goliath-cfg`, `goliath-workflow-run`, `GOLIATH_WORK_ROOT`, database `goliath`). `methyl-*` remains on methylation-specific actions and as one-cycle aliases. The MethylPipeline tree is not renamed in the first extract. |

### 4.5 Couplings that still block a clean boot

Copying the engine does not finish Phase 1. These files still import science code, so the gateway is not yet free of `methyl*`:

| File | Import |
|------|--------|
| `workflow_engine/domain/compiler.py` | `methyl_domain`, `methyl_worker` |
| `workflow_engine/rest/execution_scope.py` | `methyl_worker` (lazy) |
| `workflow_engine/local/engine.py` | `methyl_worker` handlers |
| `workers/reference_rest_worker.py` | Shim that calls `methyl_worker` |

`workers/methyl_worker/client.py` and `work_share.py` do not import science packages. The extract branch moves them to `goliath_worker/`.

---

## 5. Coupling cuts (must be designed before moving code)

1. **Python packaging**  
   - Today: one venv via `scripts/packages.list` (science + engine).  
   - Target: GoliathOmics depends on published `goliath-app` (path or git dep until a release). Workers depend on science packages plus the App client only.  
   - Phase 0 designs the banned-import check: GoliathApp CI fails if it imports `methyl*`, `omicsfeatures`, `rnaexpress`, `rnaalignmentqc`, `proteomicsfeatures`, or `proteomicsqc`.

2. **Database**  
   - Single DB `goliath` with cross-schema FKs (`cfg` ↔ `wf` ↔ `portal`).  
   - GoliathApp migrations own engine DDL. Omics contributes content migrations and seeds (actions, analytes, process packs, reference assets) and does not fork engine DDL.  
   - Action catalog: git → `wf.workflow_action` via sync (`methyl-cfg sync-actions`, later `goliath-cfg sync-actions`).

3. **Deploy / images**  
   - Replace the hard-coded sibling `../mojo-align` with a documented build arg / CI checkout of a pinned tag.  
   - `METHYL_EXTRACTOR_BIN`, the Parabricks image, and the methylgrapher image are **Omics worker env**, not App.

4. **`/work` shared storage**  
   - Keep the layout from `scripts/init_work_layout.sh`:  
     `samples/`, `projects/`, `cache/` writable; `genomes/`, `site/`, `goliath/` ops-controlled.  
   - App owns the layout script and the mount contract. Omics owns site/analyte content and sample-arm conventions.  
   - Shared storage is optional. A workflow that never calls `goliath_worker.work_share` runs with no `/work` mount.  
   - Env: inherited platform name is `GOLIATH_WORK_ROOT`. `METHYL_WORK_ROOT` remains a one-cycle alias.

5. **CLI surface**  
   - `goliath-*` entry points are born in App. `methyl-*` remains an alias shim in Omics for one major cycle, then deprecates.

6. **Credentials**  
   - Remain in `cfg.credential`. They never materialize under `/work`.

---

## 6. Phased execution plan

### Phase 0 — Freeze contracts (1–2 weeks, low risk)

**Deliverables**

- Published contract pack (tag or `contracts/` release) from current `GoliathWorkflow` main:
  - OpenAPI (`contracts/openapi.yaml`)
  - DomainProgram IR schema
  - Worker protocol MD
  - `/work` layout + env vars (`METHYL_WORK_ROOT`, future `GOLIATH_WORK_ROOT`)
  - Action I/O schema versioning rules
- ADR recording the locked names in §3.2 and §4.4 (this document is that record until a shorter ADR is split out).
- Path inventory: every top-level path → App engine / Omics content / Tool / Delete. SQL files classified with the seed list in §4.2, not by directory.
- Banned-import check designed (and wired as soon as App has a package): App cannot import the science packages listed in §5.1.

**Exit:** Both future repos can depend on a versioned contract without reading each other’s source trees ad hoc. The import ban is specified before code moves, not deferred to Phase 3.

### Phase 1 — Populate GoliathApp (engine extract)

**Deliverables**

- Move platform trees into `GoliathApp` with `git filter-repo` on the engine paths in §4.1. Do not copy `sql_pg/` or `sql_mssql/` wholesale: detector, study, prostate-path, and reference-asset seeds stay behind for Omics.
- Standalone App CI: Postgres SQL deploy smoke, gateway boot, reference worker claim/submit against a fixture DB.
- Package name `goliath-app`. Document the PostgreSQL and Azure SQL twins.

**First slice (`engine-extract`):** the branch contains the engine tree and `goliath_worker`, and the science SQL seeds in §4.2 are absent from the tip. That slice does **not** meet the boot exit below, because §4.5 files still import science code.

**Exit:** GoliathApp contains the gateway and engine DDL. The gateway boots with zero imports from `packages/methyl*` or the other science packages, which requires cutting the imports in §4.5. A tree that still contains `wf_split_detector_actions_seed.sql` has not met this exit.

### Phase 2 — Thin GoliathWorkflow → GoliathOmics (depend on App)

**Deliverables**

- Replace the in-tree engine with a dependency on GoliathApp.
- Keep science packages, `methyl_worker`, domain content, and the seeds in §4.2 in this repo.
- Rename the GitHub repo and docs brand to **GoliathOmics**. During the alias cycle, docs may say “GoliathOmics (methylpipeline)”.
- Bootstrap installs App, then Omics.

**Exit:** Omics CI is green using App as an external package. Gateway source is not duplicated.

### Phase 3 — Content and CLI cleanup

**Deliverables**

- Analytes, profiles, fixtures, and checks live only under Omics. App ships an empty or hello-workflow fixture, not a methylation program.
- App docs have no SamplePrep / Clara / mojo / extractor narrative. Omics docs own that.
- Alias matrix: `methyl-gateway` → `goliath-gateway`, `methyl-cfg` → `goliath-cfg`, and the rest of the `methyl-*` set.
- `portal_clinical_schema.sql` columns classified: engine columns stay in App; disease-specific columns become Omics content migrations.

**Exit:** A contributor can build a non-genomics demo on GoliathApp alone (a trivial hello workflow is enough).

### Phase 4 — Tooling contracts only

**Deliverables**

- Pinned tags: mojo-align tag (Mojo 1.1 / Modular 26.6) → methylgrapher image tag; MethylExtractor release → `/work/goliath/...` layout.
- No source vendoring. CI builds images from those tags.
- Tool chapter in Omics docs. No meta-repo required for the first cut.

**Exit:** Omics can bump tools without an App release, unless OpenAPI or the worker protocol changes.

### Phase 5 — Optional future (out of scope for the first cut)

- Extract Delphi / config editor into App-facing tooling.
- Multi-tenant SaaS packaging of GoliathApp.
- Separate RNA or proteomics repos only if those product lines diverge.

---

## 7. Milestone checklist

- [x] Naming: **GoliathApp** + **GoliathOmics**, with `methyl-*` aliases for one release cycle and `goliath-*` born in App
- [x] RNA/proteomics stay inside GoliathOmics
- [x] One database `goliath`; App owns DDL; Omics owns seeds
- [x] History via `git filter-repo` for platform paths
- [ ] Tag the contract pack from current `GoliathWorkflow` main (Phase 0)
- [ ] Seed `GoliathApp` with the Phase 1 engine tree (no science packages, no science SQL seeds)
- [ ] Add the Omics → App dependency and prove gateway-less science unit tests still pass
- [ ] One smoke: gateway + DB + one worker claiming a SamplePrep task (App gateway, Omics worker, mojo-align image, MethylExtractor binary)
- [ ] Partner one-pager: platform vs omics vs tools, and “application pack” kept as the MethylPipeline overlay term

---

## 8. Risk register

| Risk | Mitigation |
|------|------------|
| Cross-schema FKs break if schemas split across DBs | One DB. App owns DDL. Omics owns seeds. |
| Copying `sql_pg/` wholesale drags methylation seeds into App | Seed denylist in §4.2 is part of the Phase 1 exit. |
| History loss / blame | `git filter-repo` into App. Science history stays in GoliathWorkflow. |
| Rename thrash (`methyl-*`) | Alias shims for one release cycle, then deprecate. |
| Portal clinical tables look like engine | Engine APIs in App. `portal_clinical_schema.sql` reviewed in Phase 3. |
| Accidental methylation imports in App | Banned-import check designed in Phase 0 and enforced in Phase 1 CI. |
| “Application pack” used for the platform | Glossary in §3.2 and §Appendix B. That phrase stays a MethylPipeline overlay. |
| Partner docs still say MethylPipeline / GoliathWorkflow | This naming lock, plus the partner one-pager in the checklist. |

---

## 9. Success criteria

1. **GoliathApp** builds and runs gateway + DB + reference worker with **zero** imports from genomics packages, and without the science SQL seeds in §4.2.
2. **GoliathOmics** runs the current SamplePrep / validation paths using App as a dependency.
3. **mojo-align** (Mojo 1.1) and **MethylExtractor** remain separate, consumed only via documented image and binary pins.
4. A new non-genomics vertical can start from GoliathApp plus new DomainPrograms without forking Omics.
5. GitHub, docs, and partner materials use: Platform = GoliathApp, Product = GoliathOmics, Tools = mojo-align + MethylExtractor. “Application pack” remains the MethylPipeline config-overlay term.

---

## 10. Immediate next actions

1. **Phase 0:** tag the contract pack from current `GoliathWorkflow` main (OpenAPI, DomainProgram IR, worker protocol, `/work` layout, action I/O versioning) and write the path inventory, including the SQL seed denylist.
2. **Phase 0:** specify the banned-import check before any tree is copied.
3. **Phase 1:** populate `GoliathApp` with the engine-only tree (`git filter-repo`), excluding science packages and the seeds in §4.2.

Parking this plan is done: it lives at `GoliathApp/docs/SEPARATION_PLAN.md`.

---

## Appendix A — Path cheat sheet (GoliathWorkflow)

**App engine**

- `workflow_engine/rest/`, `local/`, `cfg/`, `contract/`, `delphi/`
- `workflow_engine/domain/compiler.py`, `verify_workflow.py`, `pipeline_profiles.py`, `workflow_context.py`
- `sql_pg/` and `sql_mssql/` engine DDL and APIs for Meta, RBAC, portal engine, wf engine, cfg schema, Contract, Onboarding
- `contracts/`, generic `deploy/`, `workers/WORKER_PROTOCOL.md`, `scripts/init_work_layout.sh`
- `goliath_worker/client.py`, `goliath_worker/work_share.py` (from `workers/methyl_worker/`; handlers stay in Omics)

**Omics content**

- `packages/` (26 packages)
- `workers/methyl_worker/`, `workers/docker/methylgrapher/`
- `workflow_engine/domain/{analytes,profiles,fixtures,checks}/`, `domain/modality_gate.py`
- `workflow_engine/ops/`
- Methylation finalize/bake helpers under `workflow_engine/admin/` (not the whole directory)
- Science schemas and docs
- SQL seeds: `wf_split_detector_actions_seed.sql`, `wf_two_group_test_seed.sql`, `wf_mc_two_group_test_seed.sql`, `migrate_work_paths_prostate_cancer.sql`, `cfg_reference_assets_seed.sql`, `cfg_site_reference_assets_seed.sql`, `portal_clinical_schema.sql`

**`/work`:** `scripts/init_work_layout.sh` — writable: `samples`, `projects`, `cache`; readable: `genomes`, `site`, `goliath`

## Appendix B — Glossary

| Term | Meaning |
|------|---------|
| GoliathApp | Generic platform (this repo, once the engine is extracted) |
| GoliathOmics | Genomics product. Future name of the science repo. |
| methylpipeline / `methyl-*` | Current package and CLI aliases, kept for one release cycle |
| `goliath-*` | Platform CLIs introduced in GoliathApp |
| GoliathWorkflow | Current GitHub monorepo hosting both layers |
| Application pack | MethylPipeline term only: config overlay on an existing process pack. Not this platform. |
| Process pack | MethylPipeline term: a new omics modality (actions, programs, QC) |
| EpiPortal | Portal UI product surface |
| DomainProgram | Portable workflow IR executed by the local or DB engine |
| Worker | Claim/submit agent. The protocol and `/work` helpers are GoliathApp. Action handlers are GoliathOmics. |

---

*Decisions locked 2026-09-22. First engine extract is the `engine-extract` branch. GoliathWorkflow remains the live product.*
