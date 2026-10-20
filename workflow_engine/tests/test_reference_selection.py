"""Linear reference pins: bwa-meth index, Mojo pack only when that engine is selected."""

from __future__ import annotations

from pathlib import Path

from cfg.reference_selection import (
    LINEAR_FASTA_NAME,
    LINEAR_MOJO_K,
    mojo_linear_pack_required,
    selected_linear_engine,
    verify_selected_paths,
)

_PLAIN_BWA_SUFFIXES = ("amb", "ann", "bwt", "pac", "sa")
_BWAMETH_SUFFIXES = _PLAIN_BWA_SUFFIXES


def _fasta(work_root: Path) -> Path:
    return (
        work_root
        / "genomes"
        / "linear"
        / "GRCh38"
        / "ensembl-116"
        / LINEAR_FASTA_NAME
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def _linear_site(engine: str | None = None, *, section: str = "parabricks") -> dict:
    site: dict = {
        "reference_selection": {"linear": "linear/GRCh38/ensembl-116"},
    }
    if engine is not None:
        site["actionConfig"] = {section: {"engine": engine, "alignment_mode": "linear"}}
    return site


def _write_linear_index(fasta: Path, *, mojo: bool = False) -> None:
    _touch(fasta)
    _touch(Path(str(fasta) + ".fai"))
    converted = Path(str(fasta) + ".bwameth.c2t")
    _touch(converted)
    for suffix in _BWAMETH_SUFFIXES:
        _touch(Path(str(converted) + f".{suffix}"))
    if mojo:
        _touch(Path(str(fasta) + ".C2T.fa"))
        pack = Path(str(fasta) + f".mojo_linear_k{LINEAR_MOJO_K}")
        for name in ("meta.json", "kmers.bin", "offsets.bin", "postings.bin"):
            _touch(pack / name)


def test_linear_engine_comes_from_config() -> None:
    assert selected_linear_engine(_linear_site()) == ""
    assert selected_linear_engine(_linear_site("parabricks")) == "parabricks"
    assert selected_linear_engine(_linear_site("Mojo")) == "mojo"
    assert selected_linear_engine(_linear_site("mojo", section="sample_prep")) == "mojo"
    site = _linear_site("parabricks")
    site["parabricks"] = {"engine": "mojo"}
    assert selected_linear_engine(site) == "parabricks"
    assert selected_linear_engine({"parabricks": {"engine": "mojo"}}) == "mojo"


def test_mojo_pack_gate_follows_engine_and_env(monkeypatch) -> None:
    monkeypatch.delenv("METHYL_REQUIRE_MOJO_LINEAR", raising=False)
    assert mojo_linear_pack_required(_linear_site()) is False
    assert mojo_linear_pack_required(_linear_site("parabricks")) is False
    assert mojo_linear_pack_required(_linear_site("mojo")) is True
    monkeypatch.setenv("METHYL_REQUIRE_MOJO_LINEAR", "0")
    assert mojo_linear_pack_required(_linear_site("mojo")) is False
    monkeypatch.setenv("METHYL_REQUIRE_MOJO_LINEAR", "false")
    assert mojo_linear_pack_required(_linear_site("mojo")) is False
    monkeypatch.setenv("METHYL_REQUIRE_MOJO_LINEAR", "1")
    assert mojo_linear_pack_required(_linear_site("mojo")) is True
    assert mojo_linear_pack_required(_linear_site("parabricks")) is False


def test_parabricks_linear_requires_bwameth_index_not_plain_bwa_or_mojo(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("METHYL_REQUIRE_MOJO_LINEAR", raising=False)
    fasta = _fasta(tmp_path)
    _touch(fasta)
    for suffix in _PLAIN_BWA_SUFFIXES:
        _touch(Path(str(fasta) + f".{suffix}"))
    report = verify_selected_paths(_linear_site("parabricks"), work_root=tmp_path)
    assert report["ok"] is False
    missing = set(report["missing"])
    assert str(Path(str(fasta) + ".fai")) in missing
    assert str(Path(str(fasta) + ".bwameth.c2t")) in missing
    for suffix in _BWAMETH_SUFFIXES:
        assert str(Path(str(fasta) + f".bwameth.c2t.{suffix}")) in missing
    assert str(Path(str(fasta) + ".C2T.fa")) not in missing
    assert not any("mojo_linear" in path for path in missing)
    assert str(Path(str(fasta) + ".amb")) not in missing

    _write_linear_index(fasta, mojo=False)
    report = verify_selected_paths(_linear_site("parabricks"), work_root=tmp_path)
    assert report["ok"] is True
    assert str(fasta) in report["present"]
    assert str(Path(str(fasta) + ".bwameth.c2t")) in report["present"]


def test_unset_engine_does_not_require_mojo_pack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METHYL_REQUIRE_MOJO_LINEAR", "1")
    fasta = _fasta(tmp_path)
    _write_linear_index(fasta, mojo=False)
    report = verify_selected_paths(_linear_site(), work_root=tmp_path)
    assert report["ok"] is True
    assert not any("mojo_linear" in path or path.endswith(".C2T.fa") for path in report["present"])


def test_mojo_linear_requires_c2t_and_dense_pack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("METHYL_REQUIRE_MOJO_LINEAR", raising=False)
    fasta = _fasta(tmp_path)
    _write_linear_index(fasta, mojo=False)
    report = verify_selected_paths(_linear_site("mojo"), work_root=tmp_path)
    assert report["ok"] is False
    missing = set(report["missing"])
    pack = Path(str(fasta) + f".mojo_linear_k{LINEAR_MOJO_K}")
    assert str(Path(str(fasta) + ".C2T.fa")) in missing
    for name in ("meta.json", "kmers.bin", "offsets.bin", "postings.bin"):
        assert str(pack / name) in missing
    assert str(Path(str(fasta) + ".bwameth.c2t")) not in missing

    _write_linear_index(fasta, mojo=True)
    report = verify_selected_paths(_linear_site("mojo"), work_root=tmp_path)
    assert report["ok"] is True
    assert str(Path(str(fasta) + ".C2T.fa")) in report["present"]
    assert str(pack / "meta.json") in report["present"]


def test_mojo_pack_can_be_skipped_on_partial_trees(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("METHYL_REQUIRE_MOJO_LINEAR", "off")
    fasta = _fasta(tmp_path)
    _write_linear_index(fasta, mojo=False)
    report = verify_selected_paths(_linear_site("mojo"), work_root=tmp_path)
    assert report["ok"] is True
    assert str(Path(str(fasta) + ".bwameth.c2t.bwt")) in report["present"]
    assert not any(path.endswith(".C2T.fa") for path in report["missing"])


def test_without_linear_pin_bwameth_siblings_are_not_required(tmp_path: Path) -> None:
    gtf = tmp_path / "genomes" / "annotation" / "gencode" / "v49" / "gencode.v49.annotation.gtf"
    _touch(gtf)
    site = {"reference_selection": {"gene_annotation": "annotation/gencode/v49"}}
    report = verify_selected_paths(site, work_root=tmp_path)
    assert report["ok"] is True
    assert not any("bwameth" in path for path in report["present"] + report["missing"])
