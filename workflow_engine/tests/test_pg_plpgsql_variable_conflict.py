"""Static guard: PL/pgSQL OUT / RETURNS TABLE names must not clash with columns.

In PL/pgSQL every ``RETURNS TABLE (...)`` column and ``OUT`` parameter is a
variable in the function body. When one of those names is also a column of a
table (or set-returning function) referenced by an embedded SQL statement and
the name is used unqualified there (``ON CONFLICT (col)``, ``WHERE col = ...``,
``SELECT col ...``), PostgreSQL raises SQLSTATE 42702 "column reference ... is
ambiguous" at *call* time. The scripts deploy cleanly and only the first caller
fails (this broke ``portal.sp_upsert_worker_enrollment``).

The fix used in sql_pg/ is ``#variable_conflict use_column`` as the first line
of the body (right after ``AS $$``). This test fails when a PL/pgSQL function
with OUT names references one of them unqualified in a statement whose
relations have a column of that name and the body lacks a
``#variable_conflict`` directive.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_QNAME = r"(?:\"?[A-Za-z_][\w]*\"?\.)?\"?[A-Za-z_][\w]*\"?"
_CREATE_FN = re.compile(rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?P<name>{_QNAME})\s*\(", re.IGNORECASE)
_CREATE_TABLE = re.compile(
    rf"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_QNAME})\s*\(", re.IGNORECASE
)
_ALTER_ADD = re.compile(
    rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<name>{_QNAME})(?P<rest>[^;]*);", re.IGNORECASE
)
_DOLLAR = re.compile(r"\$[A-Za-z_]*\$")
# First embedded SQL keyword of a statement; text before it (BEGIN, IF ... THEN,
# LOOP, ...) is PL/pgSQL control flow where no table column is in scope.
_SQL_START = re.compile(r"\b(?:WITH|SELECT|INSERT|UPDATE|DELETE|PERFORM)\b", re.IGNORECASE)
_RELATION = re.compile(rf"\b(?:FROM|JOIN|UPDATE|INTO|USING)\s+(?:ONLY\s+)?(?P<name>{_QNAME})", re.IGNORECASE)
_TABLE_CONSTRAINT = re.compile(r"(?:CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|EXCLUDE|LIKE)\b", re.IGNORECASE)


def _norm(name: str) -> str:
    return name.replace('"', "").lower()


def _matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced parentheses")


def _split_top(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _strip_comments_and_strings(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    return re.sub(r"'(?:[^']|'')*'", "''", text)


def _out_names(args: str, after_args: str) -> list[str]:
    names: list[str] = []
    for arg in _split_top(args):
        m = re.match(rf"(?:OUT|INOUT)\s+({_IDENT})\s", arg + " ", re.IGNORECASE)
        if m:
            names.append(m.group(1).lower())
    m = re.match(r"\s*RETURNS\s+TABLE\s*\(", after_args, re.IGNORECASE)
    if m:
        close = _matching_paren(after_args, m.end() - 1)
        for col in _split_top(after_args[m.end() : close]):
            names.append(_norm(col.split()[0]))
    return names


def _functions(path: Path) -> Iterator[tuple[str, int, str, list[str], str]]:
    """Yield (name, line, language, out_names, body) for each CREATE FUNCTION."""
    text = path.read_text(encoding="utf-8")
    for m in _CREATE_FN.finditer(text):
        open_idx = m.end() - 1
        close = _matching_paren(text, open_idx)
        tag = _DOLLAR.search(text, close)
        if tag is None:
            continue
        header = text[close + 1 : tag.start()]
        end = text.find(tag.group(0), tag.end())
        body = text[tag.end() : end]
        lang = re.search(r"LANGUAGE\s+'?(\w+)", header + text[end : end + 200], re.IGNORECASE)
        line = text.count("\n", 0, m.start()) + 1
        yield (
            m.group("name"),
            line,
            (lang.group(1).lower() if lang else ""),
            _out_names(text[open_idx + 1 : close], header),
            body,
        )


@lru_cache(maxsize=1)
def _relation_columns() -> dict[str, frozenset[str]]:
    """Column names per relation (tables and set-returning functions) in sql_pg/."""
    cols: dict[str, set[str]] = defaultdict(set)
    for path in sorted(SQL_PG.rglob("*.sql")):
        text = _strip_comments_and_strings(path.read_text(encoding="utf-8"))
        for m in _CREATE_TABLE.finditer(text):
            close = _matching_paren(text, m.end() - 1)
            for item in _split_top(text[m.end() : close]):
                if not _TABLE_CONSTRAINT.match(item):
                    cols[_norm(m.group("name"))].add(_norm(item.split()[0]))
        for m in _ALTER_ADD.finditer(text):
            for add in re.finditer(
                rf"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\"?{_IDENT}\"?)", m.group("rest"), re.IGNORECASE
            ):
                if not _TABLE_CONSTRAINT.match(add.group(1)):
                    cols[_norm(m.group("name"))].add(_norm(add.group(1)))
        for name, _line, _lang, outs, _body in _functions(path):
            cols[_norm(name)].update(outs)
    return {k: frozenset(v) for k, v in cols.items()}


def _statement_columns(stmt: str) -> set[str]:
    rels = _relation_columns()
    seen: set[str] = set()
    for m in _RELATION.finditer(stmt):
        key = _norm(m.group("name"))
        if key in rels:
            seen |= rels[key]
        else:  # unqualified reference: match by bare relation name
            for full, columns in rels.items():
                if full.split(".")[-1] == key:
                    seen |= columns
    return seen


def _strip_values(stmt: str) -> str:
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"\bVALUES\s*\(", stmt, re.IGNORECASE):
        if m.start() < pos:
            continue
        out.append(stmt[pos : m.start()] + "VALUES ()")
        pos = _matching_paren(stmt, m.end() - 1) + 1
    out.append(stmt[pos:])
    return "".join(out)


def _clashes(names: list[str], body: str) -> set[str]:
    """OUT names used unqualified in a statement whose relations have that column."""
    hits: set[str] = set()
    for stmt in _strip_comments_and_strings(body).split(";"):
        start = _SQL_START.search(stmt)
        if start is None:
            continue
        stmt = stmt[start.start() :]
        columns = _statement_columns(stmt)
        candidates = [n for n in names if n in columns]
        if not candidates:
            continue
        # Positions that never resolve to a variable-vs-column ambiguity.
        scan = re.sub(
            rf"INSERT\s+INTO\s+{_QNAME}(?:\s+AS\s+{_IDENT})?\s*\([^)]*\)", "INSERT INTO t ()", stmt, flags=re.I
        )
        scan = _strip_values(scan)
        scan = re.sub(rf"(?:\bSET|,)\s*{_IDENT}\s*=(?!=)", " SET _ =", scan, flags=re.I)  # UPDATE SET targets
        scan = re.sub(rf"\bAS\s+\"?{_IDENT}\"?", " AS _", scan, flags=re.I)  # aliases
        scan = re.sub(
            rf"(?<!INSERT\s)\bINTO\s+(?:STRICT\s+)?{_IDENT}(?:\s*,\s*{_IDENT})*", " INTO _", scan, flags=re.I
        )  # SELECT/RETURNING ... INTO targets
        scan = re.sub(rf"{_QNAME}\s*\(", " f(", scan)  # function / relation names before '('
        scan = re.sub(r"\b(?:FROM|JOIN|UPDATE|USING)\s+(?:ONLY\s+)?" + _QNAME, " FROM t", scan, flags=re.I)
        for name in candidates:
            if re.search(rf"(?<![\w.\"$]){re.escape(name)}(?![\w\"])", scan, re.IGNORECASE):
                hits.add(name)
    return hits


def _cases() -> Iterator[object]:
    for path in sorted(SQL_PG.rglob("*.sql")):
        for name, line, lang, outs, body in _functions(path):
            if lang == "plpgsql" and outs:
                yield pytest.param(path, name, outs, body, id=f"{path.relative_to(SQL_PG)}:{line}:{name}")


@pytest.mark.parametrize(("path", "name", "outs", "body"), list(_cases()))
def test_out_names_do_not_clash_with_columns(path: Path, name: str, outs: list[str], body: str) -> None:
    if re.match(r"\s*#variable_conflict\s+\w+", body):
        return
    hits = _clashes(outs, body)
    assert not hits, (
        f"{path.name}: {name} has OUT/RETURNS TABLE names {sorted(hits)} referenced "
        "unqualified in SQL over relations with those columns; add "
        "'#variable_conflict use_column' as the first line of the body (after AS $$) "
        "or qualify the column references"
    )


def test_relation_columns_parsed() -> None:
    cols = _relation_columns()
    assert {"cluster_id", "external_worker_key", "public_ip", "status"} <= cols["wf.worker_enrollment"]


def test_detector_flags_known_clash() -> None:
    body = """
BEGIN
  INSERT INTO wf.worker_enrollment AS e (cluster_id, public_ip, external_worker_key, status)
  VALUES (1, '1.2.3.4', 'k', 'PENDING')
  ON CONFLICT (cluster_id, external_worker_key) DO UPDATE SET public_ip = EXCLUDED.public_ip;
  UPDATE wf.cluster SET status = 'ACTIVE' WHERE id = 1;
END;
"""
    assert _clashes(["id", "external_worker_key", "public_ip", "status"], body) == {"external_worker_key", "id"}


def test_detector_ignores_qualified_targets_and_variables() -> None:
    body = """
BEGIN
  INSERT INTO wf.worker_enrollment (cluster_id, external_worker_key) VALUES (1, external_worker_key)
  RETURNING worker_enrollment.id INTO id;
  RETURN QUERY SELECT e.id, e.external_worker_key AS external_worker_key FROM wf.worker_enrollment e
  WHERE e.external_worker_key = p_key;
  RAISE EXCEPTION 'external_worker_key missing';
END;
"""
    assert _clashes(["id", "external_worker_key"], body) == set()
