# Pipeline profiles

`workflow_engine/domain/pipeline_profiles.py` turns a pipeline profile into scope flags that workflow `IF` nodes read. The database stores profile documents in `cfg.pipeline_profile` (`cfg_registry_tables.sql`). The Python module merges a profile dict into an instance context. It does not write SQL by itself.

## Precedence

`enrich_instance_context` in `workflow_engine/domain/workflow_context.py` documents the merge order, highest first: instance, then procedure, then profile or mode, then analyte, then site. The function rebuilds `actionConfig` in that order so a procedure value of JSON null can clear a profile key.

That enrichment imports `methyl_utils` (project load, site manifest, modality gate, sample-arm layout). Those modules are not in this repository. The local engine calls `finalize_instance_context` and, on `ImportError`, `FileNotFoundError`, or `ValueError`, logs the failure and runs with the context it already has. `goliath-workflow-run --compile-only` does not enrich.

`seed_pipeline_scope_flags` itself has no `methyl_utils` import. Tests in `workflow_engine/tests/test_pipeline_scope_flags.py` call it directly.

## Flags

`seed_pipeline_scope_flags` writes booleans and a few strings onto the context, including `runDmpSelection`, `runGeneFeaturecuts`, `runBiomarkerFilter`, `runGeneFeatureSelect`, `runProgressionAnalysis`, the `stability*Enabled` flags, `usePangenome`, `useWgbsPangenome`, `useEpiGbs`, `useEmseqTargeted`, `skipDemultiplex`, `deleteFastqs` (default true when the sample-prep config is silent), `libraryProtocol`, and `alignmentMode`.

`libraryProtocol` defaults to `wgbs_linear` when unset, and normalizes aliases (`wgbs`, `pangenome`, `epi_gbs`, `emseq`, and others). `alignmentMode` defaults from that protocol: `wgbs_pangenome` becomes `pangenome_wgbs`; other protocols become `linear`.

`PROFILE_PRESETS` in the same module supplies boolean overlays for named profiles (`legacy_dual`, `discovery_interpretation`, `full_biomarker_gene_fc`, `structural_features`, `staged_ovr_mc`, and others). Explicit keys already on the context win over the preset.

## Modality

`regulatory.primary_modality` chooses which pack flags are written. Tokens normalize through `_MODALITY_ALIASES`:

| Canonical | Accepted tokens |
|-----------|-----------------|
| `methylation` | `methylation`, `wgbs`, `methyl`, `dna_methylation`, `bisulfite` |
| `rnaseq` | `rnaseq`, `rna_seq`, `rna`, `transcriptomics`, `transcriptome` |
| `proteomics` | `proteomics`, `proteome`, `protein`, `ms_proteomics`, `mass_spec` |

An unknown token is kept as cleaned text and does not receive RNA or proteomics defaults.

| Modality | Scope keys |
|----------|------------|
| `rnaseq` | Sets `quantMode` (default `star`) and `useKallisto`. Drops proteomics keys `ingestMode`, `usePanel`, `useDda`, `useRescore`. |
| `proteomics` | Sets `ingestMode` (default `dia`), `usePanel`, `useDda`, and `useRescore`. Drops `quantMode` and `useKallisto`. |
| `methylation` | Drops the RNA keys and the proteomics keys. |
| Absent | Does not invent those keys. Values already present stay. |

The modality is read from the context. The function does not infer it from the profile name or from `primary_analyte`.

## Loading a named profile

`load_profile` imports `methyl_utils.profile_paths`. A filesystem path that exists is read as JSON. A name is resolved by that package to a profile file. Mode overlays are `profiles/modes/<id>.mode.json`, searched under `workflow_engine/domain/profiles/` and the directories `methyl_utils` returns. `METHYL_PROFILE_DIR` is honored inside `methyl_utils`. This repository has no `workflow_engine/domain/profiles/` directory.

If resolution raises `FileNotFoundError` and the name is a key of `PROFILE_PRESETS`, `load_profile` returns `{pipelineProfile, ...preset}`. Otherwise it raises `FileNotFoundError`.

`_PROFILE_ALIASES` and `_SAMD_RESEARCH_MODES` map older names (`mc_dmp`, `buffy_mc_gene_fc`, and others) onto `samd_research` plus a mode id (`dmp_raw`, `dmp_fc`, `gene_enricher`, `gene_fc`, `dual_fc`). `load_samd_research_with_mode` merges `samd_research` with that overlay. Those JSON files are product content. `_DEPRECATED_PROFILE_NAMES` is the set `cfg_status_for_catalog` can treat as retired when a catalog document is present.

`apply_pipeline_profile` deep-merges `actionConfig`. The instance overlay wins, and a JSON null deletes the key. `apply_pipeline_procedure` fills procedure fields only when the instance does not already have them, then merges procedure `actionConfig` underneath the instance.

`cfg` kind `pipeline_profile` is one of the file-store kinds. `goliath-cfg` can upsert and materialize a profile document. Procedure packs use kind `assay_procedure`.
