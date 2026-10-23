"""GoliathApp sql_pg must not reference GoliathOmics-owned portal domain tables."""

from __future__ import annotations

import re
from pathlib import Path

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"

# Portal clinical / project tables owned by GoliathOmics (P1b).
_OMICS_PORTAL_TABLES = (
    "Batches",
    "CustomerInstitutions",
    "Customers",
    "DiseaseDataSource",
    "DiseaseFieldContract",
    "Diseases",
    "Groups",
    "GroupSamples",
    "InstitutionLabs",
    "Institutions",
    "Labs",
    "LabSamples",
    "Patients",
    "SampleImportBatch",
    "SampleImportRow",
    "Samples",
    "SamplesBreastCancer",
    "SamplesProstateCancer",
    "project",
)

_TABLE_REF = re.compile(
    r'portal\."(' + "|".join(_OMICS_PORTAL_TABLES) + r')"',
)

# Legacy scope / contract columns removed from GoliathApp RBAC and Contract DDL.
_FORBIDDEN_COLUMNS = re.compile(
    r'"((?:Institution|Lab|Customer)ID)"'
)


def test_sql_pg_has_no_omics_portal_table_references() -> None:
    offenders: list[str] = []
    for path in sorted(SQL_PG.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for match in _TABLE_REF.finditer(text):
            offenders.append(f"{path.name}: portal.\"{match.group(1)}\"")
        for match in _FORBIDDEN_COLUMNS.finditer(text):
            offenders.append(f'{path.name}: column "{match.group(1)}"')
    assert not offenders, "Omics domain references in GoliathApp SQL:\n" + "\n".join(offenders)
