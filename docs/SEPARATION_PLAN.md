# Plan: Separate GoliathApp from GoliathOmics

**Status:** Draft plan (2026-09-22)  
**Author context:** David Izada Rodriguez / Goliath Research  
**Source of truth for current code:** `Goliath-Research/GoliathWorkflow` (product identity in-repo: **MethylPipeline**)  
**Reserved empty platform repo:** `Goliath-Research/GoliathApp` (private, empty)  
**Independent tool repos (keep separate):** `mojo-align`, `MethylExtractor`

---

## 1. Purpose

Split the long-lived **generic application platform** (Goliath / GoliathApp) from its **genomics specialization** (GoliathOmics), so that:

1. **GoliathApp** remains a reusable builder: database-governed Meta model, RBAC, object store, portal UI, workflow engine, middle-tier REST, and remote workers — without methylation semantics.
2. **GoliathOmics** (today mostly branded MethylPipeline inside `GoliathWorkflow`) becomes the genomics product: science packages, DomainPrograms/profiles/analytes, genomics worker handlers, and docs — depending on GoliathApp as a library/service.
3. **mojo-align** and **MethylExtractor** stay independent tool projects consumed by GoliathOmics (image/binary contracts only).

This document is an executable separation plan: target boundaries, move map, coupling cuts, phased sequence, naming, and success criteria.

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
| **obj** — instances of Meta classes | **`Meta.Objs`** (+ related Meta tables) | Rename/document as “obj layer” in GoliathApp docs; avoid inventing a parallel schema unless migrating. |
| **portal** — UI objects | SQL schema `portal` (+ `portal_*_api.sql`, EpiPortal) | Platform shell; some clinical/disease columns are domain content. |
| **wf** — event-driven workflows → actions for portal users or remote workers | SQL schema `wf` + gateway + worker protocol | Platform; action *names/handlers* for genomics are app data + GoliathOmics worker. |
| **cfg** (evolution) | SQL schema `cfg` — sites, profiles, programs, storage, assets | Platform registry; science rows are GoliathOmics content. |

**Additional platform schemas today:** `Contract`, `Onboarding` (keep with GoliathApp).

**Invariant to preserve:** *The database does not encode methylation semantics* — action definitions and DomainPrograms are data; the engine remains agnostic.

---

## 3. Current state (as of inventory)

### 3.1 Repositories

| Repo | State | Role today |
|------|-------|------------|
| `Goliath-Research/GoliathWorkflow` | Public monorepo | Engine + MethylPipeline science + workers + docs |
| `Goliath-Research/GoliathApp` | Private, **empty** | Intended platform destination |
| `Goliath-Research/mojo-align` | Separate | GPU alignment / methylgrapher family |
| `Goliath-Research/MethylExtractor` | Separate | BAM→HDF5 MethylDackel fork |

### 3.2 Naming mismatch (must be planned)

| Name | Where | Meaning |
|------|-------|---------|
| GoliathWorkflow | GitHub repo + description | Monorepo host |
| MethylPipeline | `pyproject` name `methylpipeline`, docs, CLIs `methyl-*`, Docker | Current product identity |
| GoliathOmics | Outreach / business language; **not** in-repo branding | Proposed genomics product name |
| GoliathApp | Empty repo | Proposed platform name |
| EpiPortal | Portal UI docs | Company portal over `portal.sp_*` |
| `goliath` (infra) | DB name, `/work/goliath/`, image org | Namespace |

**Decision required:** Rename genomics product to **GoliathOmics** with long-lived `methyl-*` aliases, or keep MethylPipeline as the package brand under a GoliathOmics umbrella. This plan assumes **GoliathOmics** as the product/repo name and **MethylPipeline** as a transitional package/CLI alias set.

### 3.3 What already matches the platform vision

Inside `GoliathWorkflow` today:

- **Platform-shaped:** `workflow_engine/rest/` (gateway), `sql_pg` / `sql_mssql` (wf/cfg/portal/Meta/RBAC/…), `cfg/` CLI, `local/` runner, `delphi/` middle-tier, worker protocol, OpenAPI, DomainProgram **compiler/IR**, `/work` materialization contract.
- **Genomics-shaped:** `packages/methyl*` (+ rna/proteomics/omicsfeatures), `workers/methyl_worker/`, domain analytes/profiles/fixtures, science schemas, methylgrapher Docker bake of mojo-align, science docs.

---

## 4. Target repository map

```
┌─────────────────────────────────────────────────────────────┐
│  GoliathApp (platform)                                      │
│  Meta · RBAC · Meta.Objs · portal · wf · cfg · Contract     │
│  REST gateway · optional Delphi MT · local engine           │
│  Worker protocol + thin reference worker                    │
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
        │               │         │  /work/goliath/) │
        └───────────────┘         └──────────────────┘
```

### 4.1 GoliathApp — take / keep

| Path / artifact | Role |
|-----------------|------|
| `workflow_engine/rest/` | Agnostic gateway (`goliath-gateway`; alias `methyl-gateway`) |
| `workflow_engine/sql_pg/`, `sql_mssql/` | Platform DDL/APIs for Meta, RBAC, portal, wf, cfg, Contract, Onboarding |
| `workflow_engine/cfg/` | Config registry CLI (`goliath-cfg` / alias `methyl-cfg`) |
| `workflow_engine/local/` | In-process DomainProgram runner |
| `workflow_engine/contract/`, `delphi/`, thin `portal/` helpers | Platform |
| Domain **compiler** + JSON Schema for DomainProgram IR | Platform |
| `contracts/openapi.yaml` | Published HTTP contract |
| Platform slices of `schemas/` (workflow, domain_program, storage, …) | Platform |
| `deploy/` control-plane pieces, worker join docs (generic) | Platform |
| `workers/WORKER_PROTOCOL.md` + reference REST worker stub | Platform |
| Platform architecture docs (component-boundaries, distributed-runtime, config-registry — demethylated examples) | Platform |

### 4.2 GoliathOmics — take / keep

| Path / artifact | Role |
|-----------------|------|
| `packages/*` (methyl*, rna*, proteomics*, omicsfeatures) | Science libraries |
| `workers/methyl_worker/` | Genomics action handlers + catalog |
| `workers/docker/methylgrapher/` | Image bake wiring to mojo-align |
| `workflow_engine/domain/{analytes,profiles,fixtures}/` | App content (programs/profiles) |
| Science `schemas/actions`, `schemas/tasks`, methyl_* domain schemas | App contracts |
| Science docs (theory, usage SamplePrep, regulatory) | Product docs |
| Science scripts (genome provision content, analyte compares, …) | Ops content |
| Root packaging renamed toward GoliathOmics / keep `methylpipeline` alias | Product surface |

### 4.3 Leave independent

| Repo | Contract with GoliathOmics |
|------|----------------------------|
| **mojo-align** | `MOJO_ALIGN_ROOT` → build `goliath/methylgrapher:*-mojo-*`; in-image `/opt/mojo-align`; SamplePrep owns `/work/samples/...` arm dirs |
| **MethylExtractor** | Binary under `/work/goliath/methyl-extractor-*/`; extraction_manifest / QC JSON consumed by `methylextractionqc` |

### 4.4 Ambiguous items — explicit decisions

| Item | Recommendation |
|------|----------------|
| `workflow_engine/domain/` tree | **Split:** compiler/IR → GoliathApp; analytes/profiles/fixtures → GoliathOmics |
| `workflow_engine/ops/sample_prep_*`, `study_lifecycle*` | **GoliathOmics** (or thin generic hooks in App + science plugins) |
| `workflow_engine/admin/study_*` | Generic instance APIs → App; methylation finalize/bake helpers → Omics |
| RNA / proteomics packages | **Stay in GoliathOmics** as modality packs (same product family), not separate repos yet |
| Portal clinical / disease-specific columns | Keep portal **engine** in App; migrate disease-specific DDL/seeds to Omics migrations or cfg content |
| `tools/methyl-config-editor` | Omics-named tooling → rename under App as generic config editor later, or keep in Omics until Delphi MT is extracted |
| Empty `GoliathApp` repo | **Primary destination** for platform move (prefer over renaming GoliathWorkflow in place) |
| Current `GoliathWorkflow` name | After split: either **rename to GoliathOmics** or archive as redirect; do not keep three names long-term |

---

## 5. Coupling cuts (must be designed before moving code)

1. **Python packaging**  
   - Today: one venv via `scripts/packages.list` (science + engine).  
   - Target: GoliathOmics depends on published `goliath-app` (or path/git dep); workers depend on science packages + App client libs only.

2. **Database**  
   - Single DB `goliath` with cross-schema FKs (`cfg` ↔ `wf` ↔ `portal`).  
   - Target: **same logical DB allowed**, owned/versioned by GoliathApp migrations; Omics contributes **content migrations/seeds** (actions, analytes, process packs) without forking engine DDL.  
   - Action catalog: git → `wf.workflow_action` via sync (`methyl-cfg sync-actions` → `goliath-cfg sync-actions`).

3. **Deploy / images**  
   - Cut hard-coded sibling `../mojo-align` into documented build args / CI checkout.  
   - Document `METHYL_EXTRACTOR_BIN`, Parabricks image, methylgrapher image as **Omics worker env**, not App.

4. **`/work` shared storage** (Backblaze B2 shared `/work` in current ops plan)  
   - Keep layout contract stable (see `init_work_layout.sh`):  
     `samples/`, `projects/`, `cache/` writable; `genomes/`, `site/`, `goliath/` ops-controlled.  
   - App owns the layout script + mount contract; Omics owns site/analyte content and sample arm conventions.

5. **CLI surface**  
   - Introduce `goliath-*` entrypoints in App; keep `methyl-*` as aliases in Omics (or shim package) for ≥1 major cycle.

6. **Credentials**  
   - Remain in `cfg.credential` / Neon secrets — never under `/work` (unchanged).

---

## 6. Phased execution plan

### Phase 0 — Freeze contracts (1–2 weeks, low risk)

**Deliverables**

- Published contract pack (tag or `contracts/` release):
  - OpenAPI (`contracts/openapi.yaml`)
  - DomainProgram IR schema
  - Worker protocol MD
  - `/work` layout + env vars (`METHYL_WORK_ROOT` / future `GOLIATH_WORK_ROOT`)
  - Action I/O schema versioning rules
- ADR: repo names (GoliathApp / GoliathOmics) + alias policy for `methyl-*`
- Inventory spreadsheet: every path → App / Omics / Tool / Delete

**Exit:** Both future repos can depend on a versioned contract without reading each other’s source trees ad hoc.

### Phase 1 — Populate GoliathApp from empty repo (mechanical extract)

**Deliverables**

- Copy/move platform trees into `GoliathApp` on a branch (history: `git filter-repo` preferred if history matters; otherwise clean import + ATTRIBUTION).
- Standalone App CI: SQL deploy smoke (Postgres), gateway boot, reference worker claim/submit against fixture DB.
- Package rename: `goliath-app` (or `goliathapp`); document dual SQL backends.

**Exit:** Empty App is no longer empty; gateway boots without importing `packages/methyl*`.

### Phase 2 — Thin GoliathWorkflow → GoliathOmics (depend on App)

**Deliverables**

- Replace in-tree engine with dependency on GoliathApp.
- Keep science packages + `methyl_worker` + domain content in this repo.
- Rename GitHub repo / docs brand to **GoliathOmics** (or dual-title “GoliathOmics (MethylPipeline)” during transition).
- Update bootstrap scripts to install App then Omics.

**Exit:** Omics CI green using App as external package; no duplicated gateway source.

### Phase 3 — Content & CLI cleanup

**Deliverables**

- Move analytes/profiles/fixtures fully under Omics; App ships only empty/example domain fixtures.
- Demethylate App docs; Omics docs own SamplePrep / Clara / mojo / extractor narrative.
- Alias matrix: `methyl-gateway` → `goliath-gateway`, etc.
- Portal disease-specific seeds classified as Omics content migrations.

**Exit:** Contributor can build a non-genomics demo app on GoliathApp alone (even a trivial “hello workflow”).

### Phase 4 — Tooling contracts only

**Deliverables**

- Documented pins: mojo-align tag → methylgrapher image tag; MethylExtractor release → `/work/goliath/...` layout.
- No source vendoring; CI builds images from declared tags.
- Optional: small `goliath-omics-tools` meta-repo or just Omics docs “Tools” chapter.

**Exit:** Omics can bump tools without App release (unless OpenAPI/worker protocol changes).

### Phase 5 — Optional future (out of scope for first cut)

- Extract Delphi / config editor into App-facing tooling package.
- Multi-tenant SaaS packaging of GoliathApp.
- Separate RNA/proteomics repos if product lines diverge.

---

## 7. Suggested first milestone checklist

- [ ] Approve naming: **GoliathApp** + **GoliathOmics** (+ `methyl-*` aliases Y/N)
- [ ] Approve RNA/proteomics stay inside GoliathOmics
- [ ] Tag contract freeze from current `GoliathWorkflow` main
- [ ] Seed `GoliathApp` with Phase 1 tree (no science packages)
- [ ] Add Omics → App dependency and prove gateway-less science unit tests still pass
- [ ] One smoke: Neon + middle-tier + B2 `/work` + one GPU worker (48GB) claiming a SamplePrep task via App gateway + Omics worker
- [ ] Update partner-facing one-pager: platform vs omics vs tools

---

## 8. Risk register

| Risk | Mitigation |
|------|------------|
| Cross-schema FKs break if schemas split across DBs | Keep **one DB**, two migration owners (App owns DDL; Omics owns seeds) |
| History loss / blame | Prefer `git filter-repo` into App; keep GoliathWorkflow history for science |
| Rename thrash (`methyl-*`) | Alias shims for one release cycle; document deprecation |
| Portal clinical tables look “domain” | Engine in App; content classification review in Phase 3 |
| Accidental methylation imports in App | CI import-linter / banned-module check for `methyl*` |
| Empty App stays empty | Phase 1 timeboxed; do not wait for perfect purity |
| Partner docs still say MethylPipeline / GoliathWorkflow | Explicit rename ADR + outreach glossary |

---

## 9. Success criteria

1. **GoliathApp** builds and runs gateway + DB + reference worker with **zero** imports from genomics packages.
2. **GoliathOmics** runs MethylPipeline-equivalent SamplePrep / validation paths using App as dependency.
3. **mojo-align** and **MethylExtractor** remain separate; consumed only via documented image/binary contracts.
4. A new non-genomics vertical could start from GoliathApp + new DomainPrograms without forking Omics.
5. Naming in GitHub, docs, and partner materials consistently map to: Platform = GoliathApp, Product = GoliathOmics, Tools = mojo-align + MethylExtractor.

---

## 10. Immediate next actions (proposed)

1. **Decide naming** (confirm GoliathApp / GoliathOmics / alias policy).  
2. **Park this plan** in one of:  
   - `Goliath-Research/GoliathApp` as `docs/SEPARATION_PLAN.md` (preferred — bootstraps the empty repo), or  
   - `GoliathWorkflow/docs/architecture/goliathapp-separation-plan.md`, or  
   - internal Notion/Drive only.  
3. **Phase 0:** extract and tag the contract pack from current main.  
4. **Phase 1:** populate `GoliathApp` with platform trees (cloud agent / PR).

---

## Appendix A — Current path cheat sheet (GoliathWorkflow)

**Platform-leaning:** `workflow_engine/rest|sql_*|cfg|local|contract|delphi|portal/`, `contracts/`, `deploy/`, `workers/WORKER_PROTOCOL.md`

**Omics-leaning:** `packages/`, `workers/methyl_worker/`, `workers/docker/methylgrapher/`, `workflow_engine/domain/{analytes,profiles,fixtures}`, science schemas & docs

**Init `/work`:** `scripts/init_work_layout.sh` — writable: `samples`, `projects`, `cache`; readable: `genomes`, `site`, `goliath`

## Appendix B — Glossary

| Term | Meaning |
|------|---------|
| GoliathApp | Generic platform (this split’s platform repo) |
| GoliathOmics | Genomics application product (specialization) |
| MethylPipeline | Current in-repo product name / package |
| GoliathWorkflow | Current GitHub monorepo name hosting both |
| EpiPortal | Portal UI product surface |
| DomainProgram | Portable workflow IR executed by local or DB engine |
| Worker | Claim/submit agent (human via portal or headless cluster node) |

---

*End of draft plan.*
