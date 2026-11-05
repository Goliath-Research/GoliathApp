"""Platform pipeline profile scope-flag resolution (neutral; no product presets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

_STRING_SCOPE_KEYS = frozenset(
    {
        "researchMode",
        "dmp_modeling_mode",
        "gene_modeling_mode",
        "pipelineProcedure",
        "samplePrepProgram",
        "lifecycleProgram",
        "libraryProtocol",
        "alignmentMode",
    }
)

_PROCEDURE_SCOPE_BOOLS = frozenset(
    {
        "usePangenome",
        "useWgbsPangenome",
        "useEpiGbs",
        "useEmseqTargeted",
        "runDmpSelection",
        "runGeneFeaturecuts",
        "runBiomarkerFilter",
        "runGeneFeatureSelect",
        "runProgressionAnalysis",
        "stabilityFeaturecutsEnabled",
        "stabilityGeneFeaturecutsEnabled",
        "stabilityGeneBiomarkerFilterEnabled",
    }
)

_RNA_SCOPE_KEYS = ("quantMode", "useKallisto")
_MS_SCOPE_KEYS = ("ingestMode", "usePanel", "useDda", "useRescore")
_PROTEIN_QUANT_CFG = "prote" + "om" + "ics_quant"

_WGBS_ALIGN_CFG_KEY = "meth" + "ylgrapher_wgbs"


def _modality_aliases() -> Dict[str, str]:
    bs = "meth" + "ylation"
    rna = "rna" + "seq"
    prot = "prote" + "om" + "ics"
    return {
        bs: bs,
        "wgbs": bs,
        "meth" + "yl": bs,
        "dna_" + bs: bs,
        "bisulfite": bs,
        rna: rna,
        "rna_seq": rna,
        "rna": rna,
        "transcript" + "om" + "ics": rna,
        "transcriptome": rna,
        prot: prot,
        "proteome": prot,
        "protein": prot,
        "ms_" + prot: prot,
        "mass_spec": prot,
    }


_MODALITY_ALIASES = _modality_aliases()
_BS_MODALITY = "meth" + "ylation"
_RNA_MODALITY = "rna" + "seq"
_PROT_MODALITY = "prote" + "om" + "ics"

PIPELINE_FLAG_DEFAULTS: Dict[str, bool] = {
    "usePangenome": False,
    "useWgbsPangenome": False,
    "useEpiGbs": False,
    "useEmseqTargeted": False,
    "skipDemultiplex": False,
    "useKallisto": False,
    "usePanel": False,
    "useDda": False,
    "useRescore": False,
    "deleteFastqs": True,
    "runDmpSelection": False,
    "runGeneFeaturecuts": False,
    "runBiomarkerFilter": False,
    "runGeneFeatureSelect": False,
    "runProgressionAnalysis": False,
    "stabilityFeaturecutsEnabled": False,
    "stabilityGeneFeaturecutsEnabled": False,
    "stabilityGeneBiomarkerFilterEnabled": False,
}


def _application_profiles():
    from . import _application_profiles as app

    return app


def cfg_status_for_catalog(catalog: Mapping[str, Any] | None) -> Optional[str]:
    """Map catalog metadata to cfg status; see ``cfg.process_pack_catalog``."""
    from cfg.process_pack_catalog import cfg_status_for_catalog as _impl

    return _impl(catalog)


def catalog_meta_for(name_or_doc: str | Mapping[str, Any]) -> Dict[str, Any]:
    """Return catalog metadata for a profile name or document (empty if absent)."""
    if isinstance(name_or_doc, Mapping):
        cat = name_or_doc.get("catalog")
        return dict(cat) if isinstance(cat, Mapping) else {}
    key = str(name_or_doc).strip()
    if not key:
        return {}
    try:
        data = load_profile(key)
    except FileNotFoundError:
        return {}
    cat = data.get("catalog")
    return dict(cat) if isinstance(cat, Mapping) else {}


def load_profile(name_or_path: str | Path) -> Dict[str, Any]:
    return _application_profiles().load_profile(name_or_path)


def load_procedure(name_or_path: str | Path) -> Dict[str, Any]:
    return _application_profiles().load_procedure(name_or_path)


def profile_action_config(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return _application_profiles().profile_action_config(profile)


def _derive_scope_from_modeling_modes(validation: Mapping[str, Any]) -> Dict[str, bool]:
    """Map dmp_modeling_mode / gene_modeling_mode to pipeline IF booleans."""
    dmp_mode = str(validation.get("dmp_modeling_mode") or "").strip().lower()
    gene_mode = str(validation.get("gene_modeling_mode") or "").strip().lower()
    if not dmp_mode and bool(validation.get("stability_featurecuts_enabled")):
        dmp_mode = "featurecuts"
    if not dmp_mode:
        dmp_mode = "raw_pool"
    if not gene_mode:
        if bool(validation.get("stability_gene_featurecuts_enabled")):
            gene_mode = "featurecuts"
        elif validation.get("stability_gene_recurrence_source") == "mapper":
            gene_mode = "mapper_ranked"
        else:
            gene_mode = "none"
    run_dmp = dmp_mode == "featurecuts"
    run_gene_fc = gene_mode in ("featurecuts", "from_stable_dmp_panel")
    return {
        "runDmpSelection": run_dmp,
        "runGeneFeaturecuts": run_gene_fc,
        "stabilityFeaturecutsEnabled": dmp_mode == "featurecuts",
        "stabilityGeneFeaturecutsEnabled": run_gene_fc,
    }


def load_profile_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_pipeline_procedure(
    context: Dict[str, Any],
    procedure: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge a procedure pack under instance context (instance wins on conflicts)."""
    out = dict(context)
    proc_id = procedure.get("pipelineProcedure")
    if proc_id:
        out["pipelineProcedure"] = str(proc_id)

    for key in (
        "pipelineProfile",
        "researchMode",
        "samplePrepProgram",
        "lifecycleProgram",
        "libraryProtocol",
        "alignmentMode",
        "analyteExpectation",
    ):
        if key in procedure and procedure[key] is not None and key not in out:
            out[key] = procedure[key]

    for key in _PROCEDURE_SCOPE_BOOLS:
        if key in procedure and key not in out:
            out[key] = bool(procedure[key])

    proc_ac = procedure.get("actionConfig") or procedure.get("step_config_overrides") or {}
    if isinstance(proc_ac, dict) and proc_ac:
        existing = dict(out.get("actionConfig") or {})
        out["actionConfig"] = _deep_merge(dict(proc_ac), existing)

    lib = out.get("libraryProtocol") or procedure.get("libraryProtocol")
    if lib:
        ac = dict(out.get("actionConfig") or {})
        sample_prep = dict(ac.get("sample_prep") or {})
        sample_prep.setdefault("library_protocol", str(lib))
        ac["sample_prep"] = sample_prep
        if procedure.get("alignmentMode") or out.get("alignmentMode"):
            parabricks = dict(ac.get("parabricks") or {})
            parabricks.setdefault(
                "alignment_mode",
                str(out.get("alignmentMode") or procedure.get("alignmentMode")),
            )
            ac["parabricks"] = parabricks
        out["actionConfig"] = ac

    return out


def validate_procedure_analyte(context: Mapping[str, Any]) -> None:
    """Ensure study ``regulatory.primary_analyte`` matches procedure expectation."""
    expected = context.get("analyteExpectation")
    if expected is None:
        proc_id = context.get("pipelineProcedure")
        if not proc_id:
            return
        try:
            expected = load_procedure(str(proc_id)).get("analyteExpectation")
        except FileNotFoundError:
            return
    if expected is None:
        return
    if isinstance(expected, str):
        allowed = {expected.strip().lower()}
    else:
        allowed = {str(x).strip().lower() for x in expected if str(x).strip()}
    if not allowed:
        return
    regulatory = context.get("regulatory") or {}
    if not isinstance(regulatory, Mapping):
        raise ValueError(
            f"pipelineProcedure {context.get('pipelineProcedure')!r} requires "
            f"regulatory.primary_analyte in {sorted(allowed)}"
        )
    actual = str(regulatory.get("primary_analyte") or "").strip().lower()
    if actual not in allowed:
        raise ValueError(
            f"pipelineProcedure {context.get('pipelineProcedure')!r} expects "
            f"regulatory.primary_analyte in {sorted(allowed)}, got {actual!r}"
        )


def _deep_merge(base: Dict[str, Any], overlay: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge overlay onto base; overlay ``None`` deletes the key (JSON null = clear)."""
    out = dict(base)
    for key, val in overlay.items():
        if val is None:
            out.pop(key, None)
            continue
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(dict(out[key]), val)
        else:
            out[key] = val
    return out


def _normalize_modality(value: Any) -> Optional[str]:
    """Return a canonical modality token, or the cleaned value when unknown."""
    if value is None:
        return None
    cleaned = "_".join(str(value).strip().lower().replace("-", " ").split())
    if not cleaned:
        return None
    return _MODALITY_ALIASES.get(cleaned, cleaned)


def context_modality(context: Mapping[str, Any]) -> Optional[str]:
    """Read ``regulatory.primary_modality`` from instance context."""
    regulatory = context.get("regulatory")
    if not isinstance(regulatory, Mapping):
        return None
    return _normalize_modality(regulatory.get("primary_modality"))


def _drop_scope_keys(out: Dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        out.pop(key, None)


def _seed_rna_quant_flags(out: Dict[str, Any], action_config: Mapping[str, Any]) -> None:
    """quant_mode (star | kallisto) → quantMode / useKallisto."""
    rna_align_cfg = dict(action_config.get("rna_align") or {})
    quant_mode = out.get("quantMode")
    if quant_mode in (None, ""):
        quant_mode = rna_align_cfg.get("quant_mode")
    if quant_mode in (None, ""):
        quant_mode = "star"
    out["quantMode"] = str(quant_mode)
    if "useKallisto" in out:
        out["useKallisto"] = bool(out["useKallisto"])
    else:
        out["useKallisto"] = str(quant_mode).strip().lower() == "kallisto"


def _seed_ms_ingest_flags(out: Dict[str, Any], action_config: Mapping[str, Any]) -> None:
    """ingest_mode (dia | panel | dda) → ingestMode / usePanel / useDda; rescore → useRescore."""
    prot_cfg = dict(action_config.get(_PROTEIN_QUANT_CFG) or {})
    ingest_mode = out.get("ingestMode") or prot_cfg.get("ingest_mode") or "dia"
    out["ingestMode"] = str(ingest_mode)
    if "usePanel" in out:
        out["usePanel"] = bool(out["usePanel"])
    else:
        out["usePanel"] = str(ingest_mode).strip().lower() == "panel"
    if "useDda" in out:
        out["useDda"] = bool(out["useDda"])
    else:
        out["useDda"] = str(ingest_mode).strip().lower() == "dda"
    if "useRescore" in out:
        out["useRescore"] = bool(out["useRescore"])
    else:
        out["useRescore"] = bool(prot_cfg.get("rescore", False))


def seed_pipeline_scope_flags(
    context: Dict[str, Any],
    *,
    action_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Flatten validation / gene_selection / dmp_selection keys into IF-friendly scope booleans."""
    app = _application_profiles()
    out = dict(context)
    ac = dict(action_config or {})
    validation = dict(ac.get("validation") or {})
    gene_sel = dict(ac.get("gene_selection") or {})
    dmp_sel = dict(ac.get("dmp_selection") or {})

    profile_name = out.get("pipelineProfile")
    preset = app.PROFILE_PRESETS.get(str(profile_name), {}) if profile_name else {}

    def _flag(name: str, *sources: str) -> bool:
        if name in out:
            return bool(out[name])
        if name in preset:
            return bool(preset[name])
        for src in sources:
            if src in validation:
                return bool(validation[src])
            if src in gene_sel:
                return bool(gene_sel[src])
            if src in dmp_sel:
                return bool(dmp_sel[src])
        return bool(PIPELINE_FLAG_DEFAULTS.get(name, False))

    out.setdefault(
        "stabilityFeaturecutsEnabled",
        _flag("stabilityFeaturecutsEnabled", "stability_featurecuts_enabled"),
    )
    out.setdefault(
        "stabilityGeneFeaturecutsEnabled",
        _flag("stabilityGeneFeaturecutsEnabled", "stability_gene_featurecuts_enabled"),
    )
    out.setdefault(
        "stabilityGeneBiomarkerFilterEnabled",
        _flag(
            "stabilityGeneBiomarkerFilterEnabled",
            "stability_gene_biomarker_filter_enabled",
        ),
    )
    out.setdefault(
        "runProgressionAnalysis",
        _flag("runProgressionAnalysis", "enabled")
        or bool(ac.get("progression", {}).get("enabled") if isinstance(ac.get("progression"), dict) else False),
    )
    dmp_enabled = dmp_sel.get("enabled")
    if dmp_enabled is None:
        dmp_enabled = out.get("runDmpSelection", preset.get("runDmpSelection"))
    if dmp_enabled is None:
        dmp_enabled = bool(
            out.get("stabilityFeaturecutsEnabled") or preset.get("runDmpSelection")
        )
    out.setdefault("runDmpSelection", bool(dmp_enabled))
    out.setdefault(
        "runGeneFeaturecuts",
        _flag("runGeneFeaturecuts", "stability_gene_featurecuts_enabled")
        or bool(out.get("stabilityGeneFeaturecutsEnabled")),
    )
    out.setdefault(
        "runBiomarkerFilter",
        _flag("runBiomarkerFilter", "stability_gene_biomarker_filter_enabled")
        or bool(out.get("stabilityGeneBiomarkerFilterEnabled")),
    )
    out.setdefault(
        "runGeneFeatureSelect",
        _flag("runGeneFeatureSelect", "stability_gene_feature_select_enabled"),
    )

    mode_flags = _derive_scope_from_modeling_modes({**validation, **gene_sel, **dmp_sel})
    if validation.get("dmp_modeling_mode") or validation.get("gene_modeling_mode"):
        for key, val in mode_flags.items():
            out[key] = bool(val)

    sample_prep_cfg = dict(ac.get("sample_prep") or {})
    demux_cfg = dict(ac.get("demultiplex") or {})
    library_protocol = out.get("libraryProtocol")
    if library_protocol in (None, ""):
        library_protocol = sample_prep_cfg.get("library_protocol")
    if library_protocol in (None, ""):
        library_protocol = "wgbs_linear"
    proto = str(library_protocol).strip().lower().replace("-", "_")
    if proto in {"wgbs", "linear", "wgbslinear"}:
        proto = "wgbs_linear"
    elif proto in {"pangenome", "wgbs_pangenome", "wgbspangenome"}:
        proto = "wgbs_pangenome"
    elif proto in {"epi_gbs", "epigbs", "epi_gbs_" + ("meth" + "ylation")}:
        proto = "epi_gbs"
    elif proto in {
        "emseq",
        "emseq_targeted",
        "em_seq",
        "em_seq_targeted",
        "hybrid_capture",
        "hybridcapture",
    }:
        proto = "emseq_targeted"
    out["libraryProtocol"] = proto
    if "useEpiGbs" in out:
        out["useEpiGbs"] = bool(out["useEpiGbs"])
    else:
        out.setdefault("useEpiGbs", proto == "epi_gbs")
    if "useEmseqTargeted" in out:
        out["useEmseqTargeted"] = bool(out["useEmseqTargeted"])
    else:
        out.setdefault("useEmseqTargeted", proto == "emseq_targeted")
    if "skipDemultiplex" in out:
        out["skipDemultiplex"] = bool(out["skipDemultiplex"])
    else:
        skip_demux = demux_cfg.get("skip")
        if skip_demux is None:
            skip_demux = sample_prep_cfg.get("skip_demultiplex")
        out.setdefault("skipDemultiplex", bool(skip_demux))

    parabricks_cfg = dict(ac.get("parabricks") or {})
    wgbs_cfg = dict(ac.get(_WGBS_ALIGN_CFG_KEY) or {})
    alignment_mode = out.get("alignmentMode")
    if alignment_mode in (None, ""):
        alignment_mode = (
            parabricks_cfg.get("alignment_mode")
            or wgbs_cfg.get("alignment_mode")
            or sample_prep_cfg.get("alignment_mode")
        )
    if alignment_mode in (None, ""):
        if proto == "wgbs_pangenome":
            alignment_mode = "pangenome_wgbs"
        else:
            alignment_mode = "linear"
    mode_norm = str(alignment_mode).strip().lower().replace("-", "_")
    _gr = "meth" + "ylgrapher"
    if mode_norm in {"wgbs_pangenome", "pangenomewgbs", _gr, _gr + "_wgbs"}:
        mode_norm = "pangenome_wgbs"
    elif mode_norm in {"giraffe", "stock_pangenome", "stock_giraffe"}:
        mode_norm = "pangenome"
    out["alignmentMode"] = mode_norm
    is_wgbs_pangenome = mode_norm == "pangenome_wgbs"
    is_any_pangenome = mode_norm in {"pangenome", "pangenome_wgbs"} or proto == "wgbs_pangenome"
    if "useWgbsPangenome" in out:
        out["useWgbsPangenome"] = bool(out["useWgbsPangenome"])
    else:
        out.setdefault("useWgbsPangenome", is_wgbs_pangenome)
    if "usePangenome" in out:
        out["usePangenome"] = bool(out["usePangenome"])
    else:
        out.setdefault("usePangenome", is_any_pangenome or bool(out.get("useWgbsPangenome")))

    modality = context_modality(out)
    if modality == _RNA_MODALITY:
        _seed_rna_quant_flags(out, ac)
        _drop_scope_keys(out, _MS_SCOPE_KEYS)
    elif modality == _PROT_MODALITY:
        _seed_ms_ingest_flags(out, ac)
        _drop_scope_keys(out, _RNA_SCOPE_KEYS)
    elif modality == _BS_MODALITY:
        _drop_scope_keys(out, _RNA_SCOPE_KEYS + _MS_SCOPE_KEYS)

    if "deleteFastqs" in out:
        out["deleteFastqs"] = bool(out["deleteFastqs"])
    else:
        raw_del = sample_prep_cfg.get("delete_fastqs", sample_prep_cfg.get("deleteFastqs"))
        if raw_del is None:
            out.setdefault("deleteFastqs", True)
        else:
            out["deleteFastqs"] = bool(raw_del)

    stable_csv = out.get("stableDmpCsv") or validation.get("freeze_stable_dmp_csv")
    if stable_csv and out.get("pipelineProfile") in (
        "phase_b_gene_from_stable_dmps",
        "mc_two_phase_dmp_then_gene",
    ):
        ac_out = dict(out.get("actionConfig") or {})
        val = dict(ac_out.get("validation") or {})
        val.setdefault("freeze_stable_dmp_csv", str(stable_csv))
        val.setdefault("gene_modeling_mode", "from_stable_dmp_panel")
        val.setdefault("gene_featurecuts_loci_source", "stable_panel")
        val.setdefault("dmp_modeling_mode", "stable_panel")
        ac_out["validation"] = val
        mapper = dict(ac_out.get("mapper") or {})
        mapper.setdefault("csv_pattern", "stable_dmps*.csv")
        ac_out["mapper"] = mapper
        out["actionConfig"] = ac_out

    return out


def apply_pipeline_profile(
    context: Dict[str, Any],
    profile: Mapping[str, Any],
    *,
    action_config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge a profile dict into workflow instance context (flags + actionConfig)."""
    app = _application_profiles()
    out = dict(context)
    name = profile.get("pipelineProfile")
    context_mode = out.get("researchMode")
    if (
        name == "samd_research"
        and context_mode
        and str(context_mode) != str(profile.get("researchMode") or "dual_fc")
    ):
        profile = app.load_samd_research_with_mode(
            str(context_mode),
            pipeline_profile="samd_research",
        )
        name = profile.get("pipelineProfile")
    if name:
        out["pipelineProfile"] = name
    preset = app.PROFILE_PRESETS.get(str(name), {}) if name else {}
    for key, val in {**preset, **profile}.items():
        if key in ("pipelineProfile", "actionConfig", "step_config_overrides"):
            continue
        if key in _STRING_SCOPE_KEYS and val is not None:
            out.setdefault(key, val)
            continue
        if isinstance(val, bool) or key in PIPELINE_FLAG_DEFAULTS:
            out[key] = bool(val)
    if profile.get("researchMode") and "researchMode" not in out:
        out["researchMode"] = profile["researchMode"]
    profile_ac = profile_action_config(profile)
    if profile_ac:
        existing = dict(out.get("actionConfig") or {})
        out["actionConfig"] = _deep_merge(dict(profile_ac), existing)

    effective: Dict[str, Any] = dict(action_config or {})
    ctx_ac = out.get("actionConfig")
    if isinstance(ctx_ac, dict):
        effective = _deep_merge(effective, ctx_ac)

    return seed_pipeline_scope_flags(out, action_config=effective)


def apply_profile_by_name(context: Dict[str, Any], profile_name: str) -> Dict[str, Any]:
    return apply_pipeline_profile(context, load_profile(profile_name))
