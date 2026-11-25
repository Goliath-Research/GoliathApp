"""Render DomainProgram JSON documents as Mermaid flowcharts and Markdown catalogs.

Platform-generic module packaged with ``goliath-gateway`` (``domain.mermaid``).
Any descendant application or course repository can render a single
``*.program.json`` file or a directory of DomainProgram fixtures into
Mermaid 9.4.3 / 10+ flowcharts, MkDocs-ready Markdown pages, or standalone
``.mmd`` files.

CLI entry points:

    python3 -m domain.mermaid --program path/to/program.json
    python3 -m domain.mermaid --fixtures-dir path/to/fixtures --docs-dir docs/workflows
    goliath-cfg render-mermaid --fixtures-dir path/to/fixtures --docs-dir docs/workflows --check
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CategorySpec:
    """Grouping definition for organizing a catalog of DomainProgram fixtures."""

    slug: str
    title: str
    intro: str
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class ProgramEntry:
    """Parsed summary and rendered Mermaid diagram for one DomainProgram fixture."""

    filename: str
    stem: str
    name: str
    version: int
    description: str
    actions: tuple[str, ...]
    step_count: int
    variables: tuple[str, ...]
    triggers: tuple[str, ...]
    mermaid: str


_HINT_KEYS: tuple[str, ...] = ("mode", "source", "qcAttempt", "reason")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9_]+")
_VAR_WRAP_RE = re.compile(r"^\$\{(?:var\.)?([^}]+)\}$")


def slugify_anchor(text: str) -> str:
    """Return a GitHub/MkDocs-compatible lowercase anchor slug."""
    return _NON_ALNUM_RE.sub("-", text.lower()).strip("-")


def _clean_expr(raw: Any) -> str:
    """Format a DomainProgram condition, ref, or placeholder cleanly."""
    if isinstance(raw, dict):
        ref = raw.get("ref")
        if isinstance(ref, str):
            return ref
        return json.dumps(raw, sort_keys=True)
    text = str(raw).strip()
    m = _VAR_WRAP_RE.match(text)
    if m:
        return m.group(1)
    return text


def _escape_mermaid_text(text: str) -> str:
    """Sanitize text for double-quoted Mermaid 9.4.3 / 10+ node and subgraph labels."""
    cleaned = text.replace("\r", " ").replace("\n", " ")
    cleaned = cleaned.replace('"', "'")
    cleaned = cleaned.replace(";", ",")
    cleaned = cleaned.replace("`", "'")
    cleaned = cleaned.replace("<", "(").replace(">", ")")
    return cleaned.strip()


def _escape_edge_label(label: str) -> str:
    """Sanitize text for Mermaid edge labels inside ``|...|``."""
    cleaned = _escape_mermaid_text(label)
    cleaned = cleaned.replace("|", "/")
    return cleaned


def _format_foreach_dim(spec: Mapping[str, Any]) -> tuple[str, bool]:
    """Return ``('<item> in <collection>', is_parallel)`` for a foreach/for spec."""
    collection_raw = spec.get("collection")
    if collection_raw is None:
        collection_raw = spec.get("in")
    collection = _clean_expr(collection_raw) if collection_raw is not None else "items"

    item_raw = spec.get("item")
    if item_raw is None:
        item_raw = spec.get("as")
    item = str(item_raw).strip() if item_raw else "item"

    is_parallel = bool(spec.get("parallel", False))
    return f"{item} in {collection}", is_parallel


def _format_foreach_title(dims: list[tuple[str, bool]]) -> str:
    """Build a readable subgraph header for one or more collapsed foreach dimensions."""
    modes = {is_par for _, is_par in dims}
    if len(modes) == 1:
        mode = "parallel" if next(iter(modes)) else "sequential"
        joined = " x ".join(desc for desc, _ in dims)
        return f"FOREACH ({mode}): {joined}"
    parts = [f"{desc} ({'parallel' if is_par else 'seq'})" for desc, is_par in dims]
    return "FOREACH: " + " x ".join(parts)


def _action_hints(step: Mapping[str, Any]) -> list[str]:
    """Extract short, high-signal parameter hints for distinguishing repeated actions."""
    hints: list[str] = []
    with_map = step.get("with")
    if isinstance(with_map, dict):
        for key in _HINT_KEYS:
            val = with_map.get(key)
            if val is not None and not isinstance(val, (dict, list)):
                hints.append(f"{key}={val}")
    out_map = step.get("out")
    if isinstance(out_map, dict) and out_map:
        out_vars = ", ".join(str(k) for k in out_map.keys())
        hints.append(f"out: {out_vars}")
    return hints


def _as_step_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


@dataclass
class _FlowResult:
    entries: list[str]
    exits: list[tuple[str, str | None]]


@dataclass
class _MermaidBuilder:
    lines: list[str] = field(default_factory=lambda: ["flowchart TD"])
    edges: list[tuple[str, str, str | None]] = field(default_factory=list)
    _seen_edges: set[tuple[str, str, str | None]] = field(default_factory=set)
    _node_counter: int = 0
    _subgraph_counter: int = 0
    terminal_nodes: list[str] = field(default_factory=list)
    decision_nodes: list[str] = field(default_factory=list)
    wait_nodes: list[str] = field(default_factory=list)
    fail_nodes: list[str] = field(default_factory=list)

    def next_node(self) -> str:
        self._node_counter += 1
        return f"n{self._node_counter}"

    def next_subgraph(self) -> str:
        self._subgraph_counter += 1
        return f"sg_{self._subgraph_counter}"

    def emit(self, line: str, indent: int = 1) -> None:
        self.lines.append(("  " * indent) + line)

    def add_edge(self, src: str, dst: str, label: str | None = None) -> None:
        key = (src, dst, label)
        if key in self._seen_edges:
            return
        self._seen_edges.add(key)
        self.edges.append(key)

    def add_node(
        self,
        label_lines: list[str],
        *,
        shape: str = "rect",
        indent: int = 1,
        css_class: str | None = None,
    ) -> str:
        nid = self.next_node()
        safe_label = "<br/>".join(_escape_mermaid_text(part) for part in label_lines if part)
        if shape == "stadium":
            decl = f'{nid}(["{safe_label}"])'
        elif shape == "diamond":
            decl = f'{nid}{{"{safe_label}"}}'
        elif shape == "subroutine":
            decl = f'{nid}[["{safe_label}"]]'
        elif shape == "circle":
            decl = f'{nid}(("{safe_label}"))'
        else:
            decl = f'{nid}["{safe_label}"]'
        self.emit(decl, indent=indent)
        if css_class == "terminal":
            self.terminal_nodes.append(nid)
        elif css_class == "decision":
            self.decision_nodes.append(nid)
        elif css_class == "waitNode":
            self.wait_nodes.append(nid)
        elif css_class == "failNode":
            self.fail_nodes.append(nid)
        return nid

    def connect(
        self,
        exits: list[tuple[str, str | None]],
        entries: list[str],
        *,
        indent: int = 1,
    ) -> None:
        if not exits or not entries:
            return
        if len(exits) > 1 and len(entries) > 1:
            join_id = self.add_node([" "], shape="circle", indent=indent)
            for src, label in exits:
                self.add_edge(src, join_id, label)
            for dst in entries:
                self.add_edge(join_id, dst, None)
            return
        for src, label in exits:
            for dst in entries:
                self.add_edge(src, dst, label)

    def render_sequence(self, steps: list[dict[str, Any]], indent: int) -> _FlowResult:
        if not steps:
            return _FlowResult(entries=[], exits=[])
        first_entries: list[str] = []
        current_exits: list[tuple[str, str | None]] = []
        for step in steps:
            res = self.render_step(step, indent)
            if not res.entries:
                continue
            if not first_entries:
                first_entries = res.entries
            else:
                self.connect(current_exits, res.entries, indent=indent)
            current_exits = res.exits
        return _FlowResult(entries=first_entries, exits=current_exits)

    def _collapse_foreach(
        self,
        first_spec: Mapping[str, Any],
        body_steps: list[dict[str, Any]],
    ) -> tuple[list[tuple[str, bool]], list[dict[str, Any]]]:
        dims: list[tuple[str, bool]] = [_format_foreach_dim(first_spec)]
        cur_steps = body_steps
        while len(cur_steps) == 1:
            only = cur_steps[0]
            nested_spec = only.get("for")
            if nested_spec is None:
                nested_spec = only.get("foreach")
            if not isinstance(nested_spec, dict):
                break
            dims.append(_format_foreach_dim(nested_spec))
            cur_steps = _as_step_list(only.get("do") if "do" in only else only.get("steps"))
        return dims, cur_steps

    def render_foreach(
        self,
        spec: Mapping[str, Any],
        body_steps: list[dict[str, Any]],
        indent: int,
        phase_name: str | None = None,
    ) -> _FlowResult:
        dims, inner_steps = self._collapse_foreach(spec, body_steps)
        title = _format_foreach_title(dims)
        if phase_name:
            title = f"{phase_name} - {title}"
        sg_id = self.next_subgraph()
        self.emit(f'subgraph {sg_id} ["{_escape_mermaid_text(title)}"]', indent=indent)
        res = self.render_sequence(inner_steps, indent + 1)
        if not res.entries:
            noop = self.add_node(["(empty body)"], indent=indent + 1)
            res = _FlowResult(entries=[noop], exits=[(noop, None)])
        self.emit("end", indent=indent)
        return res

    def render_step(self, step: Mapping[str, Any], indent: int) -> _FlowResult:
        # 1. for / foreach
        for_spec = step.get("for")
        if for_spec is None:
            for_spec = step.get("foreach")
        if isinstance(for_spec, dict):
            body_steps = _as_step_list(step.get("do") if "do" in step else step.get("steps"))
            return self.render_foreach(for_spec, body_steps, indent)

        # 2. parallel
        if "parallel" in step:
            branches = _as_step_list(step.get("parallel"))
            sg_id = self.next_subgraph()
            self.emit(f'subgraph {sg_id} ["PARALLEL"]', indent=indent)
            entries: list[str] = []
            exits: list[tuple[str, str | None]] = []
            for branch in branches:
                res = self.render_step(branch, indent + 1)
                entries.extend(res.entries)
                exits.extend(res.exits)
            if not entries:
                noop = self.add_node(["(empty parallel)"], indent=indent + 1)
                entries = [noop]
                exits = [(noop, None)]
            self.emit("end", indent=indent)
            return _FlowResult(entries=entries, exits=exits)

        # 3. if / then / else
        if "if" in step:
            cond_expr = _clean_expr(step["if"])
            cond_id = self.add_node(
                [f"{cond_expr}?"],
                shape="diamond",
                indent=indent,
                css_class="decision",
            )
            then_steps = _as_step_list(step.get("then"))
            else_steps = _as_step_list(step.get("else"))
            exits = []
            if then_steps:
                then_res = self.render_sequence(then_steps, indent)
                if then_res.entries:
                    self.connect([(cond_id, "yes")], then_res.entries, indent=indent)
                    exits.extend(then_res.exits)
                else:
                    exits.append((cond_id, "yes"))
            else:
                exits.append((cond_id, "yes"))

            if else_steps:
                else_res = self.render_sequence(else_steps, indent)
                if else_res.entries:
                    self.connect([(cond_id, "no")], else_res.entries, indent=indent)
                    exits.extend(else_res.exits)
                else:
                    exits.append((cond_id, "no"))
            else:
                exits.append((cond_id, "no"))

            return _FlowResult(entries=[cond_id], exits=exits)

        # 4. switch / cases / default
        if "switch" in step:
            expr = _clean_expr(step["switch"])
            sw_id = self.add_node(
                [f"switch: {expr}"],
                shape="diamond",
                indent=indent,
                css_class="decision",
            )
            exits = []
            cases = step.get("cases")
            if isinstance(cases, dict):
                for case_key, case_val in cases.items():
                    case_steps = _as_step_list(case_val)
                    case_res = self.render_sequence(case_steps, indent)
                    if case_res.entries:
                        self.connect([(sw_id, str(case_key))], case_res.entries, indent=indent)
                        exits.extend(case_res.exits)
                    else:
                        exits.append((sw_id, str(case_key)))
            default_steps = _as_step_list(step.get("default"))
            if default_steps:
                def_res = self.render_sequence(default_steps, indent)
                if def_res.entries:
                    self.connect([(sw_id, "default")], def_res.entries, indent=indent)
                    exits.extend(def_res.exits)
                else:
                    exits.append((sw_id, "default"))
            else:
                exits.append((sw_id, "default"))
            return _FlowResult(entries=[sw_id], exits=exits)

        # 5. while
        if "while" in step:
            cond_expr = _clean_expr(step["while"])
            cond_id = self.add_node(
                [f"while: {cond_expr}?"],
                shape="diamond",
                indent=indent,
                css_class="decision",
            )
            body_steps = _as_step_list(step.get("do") if "do" in step else step.get("body"))
            body_res = self.render_sequence(body_steps, indent)
            if body_res.entries:
                self.connect([(cond_id, "true")], body_res.entries, indent=indent)
                self.connect(body_res.exits, [cond_id], indent=indent)
            return _FlowResult(entries=[cond_id], exits=[(cond_id, "false")])

        # 6. repeat
        if "repeat" in step:
            cond_expr = _clean_expr(step["repeat"])
            body_steps = _as_step_list(step.get("do") if "do" in step else step.get("body"))
            body_res = self.render_sequence(body_steps, indent)
            cond_id = self.add_node(
                [f"repeat: {cond_expr}?"],
                shape="diamond",
                indent=indent,
                css_class="decision",
            )
            if body_res.entries:
                self.connect(body_res.exits, [cond_id], indent=indent)
                self.connect([(cond_id, "again")], body_res.entries, indent=indent)
                return _FlowResult(entries=body_res.entries, exits=[(cond_id, "done")])
            return _FlowResult(entries=[cond_id], exits=[(cond_id, "done")])

        # 7. wait (WAIT_EVENT)
        if "wait" in step:
            wait_spec = step["wait"]
            node_key = str(step.get("node_key") or "").strip()
            if isinstance(wait_spec, dict):
                event_name = str(wait_spec.get("event") or "event")
                corr = wait_spec.get("correlation")
                lines = [f"WAIT: {event_name}"]
                if node_key:
                    lines.insert(0, node_key)
                if corr is not None:
                    lines.append(f"corr: {_clean_expr(corr)}")
            else:
                lines = [f"WAIT: {wait_spec}"]
                if node_key:
                    lines.insert(0, node_key)
            wid = self.add_node(lines, shape="subroutine", indent=indent, css_class="waitNode")
            return _FlowResult(entries=[wid], exits=[(wid, None)])

        # 8. assign
        if "assign" in step:
            target = str(step["assign"])
            using = str(step.get("using") or step.get("do") or "assign")
            node_key = str(step.get("node_key") or "").strip()
            lines = [f"{target} = {using}"]
            if node_key:
                lines.insert(0, node_key)
            aid = self.add_node(lines, shape="rect", indent=indent)
            return _FlowResult(entries=[aid], exits=[(aid, None)])

        # 9. action / do
        action_name_raw = step.get("action")
        if action_name_raw is None and isinstance(step.get("do"), str):
            action_name_raw = step["do"]
        if isinstance(action_name_raw, str):
            action_name = action_name_raw
            node_key = str(step.get("node_key") or "").strip()
            action_suffix = action_name.split(".")[-1]
            lines = []
            if node_key and node_key != action_suffix:
                lines.append(node_key)
            lines.append(action_name)
            hints = _action_hints(step)
            if hints:
                lines.append(", ".join(hints))
            is_fail = action_name.endswith("_failed") or action_name.endswith(".fail")
            css_class = "failNode" if is_fail else None
            aid = self.add_node(lines, shape="rect", indent=indent, css_class=css_class)
            return _FlowResult(entries=[aid], exits=[(aid, None)])

        # Fallback for nested step list under "steps" or "do"
        nested = _as_step_list(step.get("steps") if "steps" in step else step.get("do"))
        if nested:
            return self.render_sequence(nested, indent)
        return _FlowResult(entries=[], exits=[])

    def finalize(self) -> str:
        for src, dst, label in self.edges:
            if label:
                self.emit(f"{src} -->|{_escape_edge_label(label)}| {dst}", indent=1)
            else:
                self.emit(f"{src} --> {dst}", indent=1)

        class_defs: list[tuple[str, str, list[str]]] = [
            ("terminal", "fill:#eef2ff,stroke:#4f46e5,color:#1e1b4b", self.terminal_nodes),
            ("decision", "fill:#fef3c7,stroke:#d97706,color:#78350f", self.decision_nodes),
            ("waitNode", "fill:#f3e8ff,stroke:#7c3aed,color:#3b0764", self.wait_nodes),
            ("failNode", "fill:#fee2e2,stroke:#dc2626,color:#7f1d1d", self.fail_nodes),
        ]
        for cls_name, cls_style, nodes in class_defs:
            if nodes:
                self.emit(f"classDef {cls_name} {cls_style}", indent=1)
                self.emit(f"class {','.join(nodes)} {cls_name}", indent=1)

        return "\n".join(self.lines) + "\n"


def render_program_mermaid(program: Mapping[str, Any]) -> str:
    """Render a DomainProgram JSON document to a Mermaid ``flowchart TD`` string."""
    builder = _MermaidBuilder()

    triggers = program.get("on")
    start_exits: list[tuple[str, str | None]] = []
    if isinstance(triggers, list) and triggers:
        for trig in triggers:
            if not isinstance(trig, dict):
                continue
            ev = str(trig.get("event") or "event")
            mode = str(trig.get("mode") or "start_instance")
            tid = builder.add_node(
                [f"on: {ev}", f"({mode})"],
                shape="stadium",
                indent=1,
                css_class="terminal",
            )
            start_exits.append((tid, None))
    if not start_exits:
        start_id = builder.add_node(["Start"], shape="stadium", indent=1, css_class="terminal")
        start_exits = [(start_id, None)]

    body = _as_step_list(program.get("body"))
    phases = program.get("phases")

    flow: _FlowResult
    if body:
        flow = builder.render_sequence(body, indent=1)
    elif isinstance(phases, list) and phases:
        first_entries: list[str] = []
        cur_exits: list[tuple[str, str | None]] = []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            phase_name = str(phase.get("name") or "").strip() or None
            phase_steps = _as_step_list(phase.get("steps"))
            foreach_spec = phase.get("foreach")
            if isinstance(foreach_spec, dict):
                res = builder.render_foreach(
                    foreach_spec,
                    phase_steps,
                    indent=1,
                    phase_name=phase_name,
                )
            elif phase_name and len(phases) > 1:
                sg_id = builder.next_subgraph()
                builder.emit(f'subgraph {sg_id} ["{_escape_mermaid_text(phase_name)}"]', indent=1)
                res = builder.render_sequence(phase_steps, indent=2)
                if not res.entries:
                    noop = builder.add_node(["(empty phase)"], indent=2)
                    res = _FlowResult(entries=[noop], exits=[(noop, None)])
                builder.emit("end", indent=1)
            else:
                res = builder.render_sequence(phase_steps, indent=1)
            if not res.entries:
                continue
            if not first_entries:
                first_entries = res.entries
            else:
                builder.connect(cur_exits, res.entries, indent=1)
            cur_exits = res.exits
        flow = _FlowResult(entries=first_entries, exits=cur_exits)
    else:
        noop = builder.add_node(["(empty program)"], indent=1)
        flow = _FlowResult(entries=[noop], exits=[(noop, None)])

    end_id = builder.add_node(["End"], shape="stadium", indent=1, css_class="terminal")
    if flow.entries:
        start_edges = [(src, dst, label) for src, label in start_exits for dst in flow.entries]
        for edge in reversed(start_edges):
            if edge not in builder._seen_edges:
                builder._seen_edges.add(edge)
                builder.edges.insert(0, edge)
        builder.connect(flow.exits, [end_id], indent=1)
    else:
        builder.connect(start_exits, [end_id], indent=1)

    return builder.finalize()


def _collect_actions(program: Mapping[str, Any]) -> list[str]:
    """Return ordered list of unique action names referenced by a DomainProgram."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _record(name: Any) -> None:
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            ordered.append(name)

    def _walk(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if "assign" in step:
                _record(step.get("using") or step.get("do"))
            elif "action" in step:
                _record(step.get("action"))
            elif isinstance(step.get("do"), str):
                _record(step.get("do"))

            for key in ("steps", "then", "else", "body", "parallel"):
                if key in step:
                    _walk(_as_step_list(step[key]))
            if "do" in step and isinstance(step["do"], list):
                _walk(_as_step_list(step["do"]))
            cases = step.get("cases")
            if isinstance(cases, dict):
                for val in cases.values():
                    _walk(_as_step_list(val))
            if "default" in step:
                _walk(_as_step_list(step["default"]))

    body = _as_step_list(program.get("body"))
    if body:
        _walk(body)
    else:
        phases = program.get("phases")
        if isinstance(phases, list):
            for phase in phases:
                if isinstance(phase, dict):
                    _walk(_as_step_list(phase.get("steps")))
    return ordered


def _count_steps(program: Mapping[str, Any]) -> int:
    """Count executable action/assign/wait steps in a DomainProgram."""
    total = 0

    def _walk(steps: list[dict[str, Any]]) -> None:
        nonlocal total
        for step in steps:
            if (
                "assign" in step
                or "wait" in step
                or "action" in step
                or isinstance(step.get("do"), str)
            ):
                total += 1
            for key in ("steps", "then", "else", "body", "parallel"):
                if key in step:
                    _walk(_as_step_list(step[key]))
            if "do" in step and isinstance(step["do"], list):
                _walk(_as_step_list(step["do"]))
            cases = step.get("cases")
            if isinstance(cases, dict):
                for val in cases.values():
                    _walk(_as_step_list(val))
            if "default" in step:
                _walk(_as_step_list(step["default"]))

    body = _as_step_list(program.get("body"))
    if body:
        _walk(body)
    else:
        phases = program.get("phases")
        if isinstance(phases, list):
            for phase in phases:
                if isinstance(phase, dict):
                    _walk(_as_step_list(phase.get("steps")))
    return total


def load_program_entry(path: Path) -> ProgramEntry:
    """Parse one ``*.program.json`` file and render its Mermaid diagram."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected JSON object at top level")
    name = str(raw.get("name") or path.name.replace(".program.json", ""))
    version_raw = raw.get("programVersion", 2)
    version = int(version_raw) if isinstance(version_raw, int) else 2
    description = str(raw.get("description") or "").strip()
    actions = tuple(_collect_actions(raw))
    step_count = _count_steps(raw)
    vars_raw = raw.get("variables")
    variables = tuple(str(k) for k in vars_raw.keys()) if isinstance(vars_raw, dict) else ()
    on_raw = raw.get("on")
    triggers: list[str] = []
    if isinstance(on_raw, list):
        for trig in on_raw:
            if isinstance(trig, dict):
                ev = str(trig.get("event") or "event")
                mode = str(trig.get("mode") or "start_instance")
                triggers.append(f"{ev} ({mode})")
    stem = path.name[: -len(".program.json")] if path.name.endswith(".program.json") else path.stem
    return ProgramEntry(
        filename=path.name,
        stem=stem,
        name=name,
        version=version,
        description=description,
        actions=actions,
        step_count=step_count,
        variables=variables,
        triggers=tuple(triggers),
        mermaid=render_program_mermaid(raw),
    )


def load_categories_file(path: Path) -> tuple[CategorySpec, ...]:
    """Load category definitions from a JSON file (list of ``{slug, title, intro, filenames}``)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("categories")
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list or {{\"categories\": [...]}}")
    specs: list[CategorySpec] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        filenames_raw = item.get("filenames")
        filenames = (
            tuple(str(f) for f in filenames_raw)
            if isinstance(filenames_raw, list)
            else ()
        )
        specs.append(
            CategorySpec(
                slug=str(item["slug"]),
                title=str(item["title"]),
                intro=str(item.get("intro") or ""),
                filenames=filenames,
            )
        )
    return tuple(specs)


def _group_programs(
    entries_by_file: Mapping[str, ProgramEntry],
    categories: Sequence[CategorySpec],
) -> list[tuple[CategorySpec, list[ProgramEntry]]]:
    assigned: set[str] = set()
    grouped: list[tuple[CategorySpec, list[ProgramEntry]]] = []
    for cat in categories:
        cat_entries: list[ProgramEntry] = []
        for fname in cat.filenames:
            if fname in entries_by_file:
                cat_entries.append(entries_by_file[fname])
                assigned.add(fname)
        if cat_entries:
            grouped.append((cat, cat_entries))

    remaining = sorted(fname for fname in entries_by_file if fname not in assigned)
    if remaining:
        if categories:
            other_cat = CategorySpec(
                slug="other-programs",
                title="Additional DomainPrograms",
                intro="DomainProgram fixtures not yet assigned to a curated category.",
                filenames=tuple(remaining),
            )
        else:
            other_cat = CategorySpec(
                slug="programs",
                title="DomainPrograms",
                intro="Rendered Mermaid flowcharts for all DomainProgram fixtures.",
                filenames=tuple(remaining),
            )
        grouped.append((other_cat, [entries_by_file[fname] for fname in remaining]))
    return grouped


def _render_category_page(
    cat: CategorySpec,
    entries: Sequence[ProgramEntry],
    *,
    fixtures_display_prefix: str,
    banner_comment: str,
) -> str:
    out: list[str] = [
        f"<!-- {banner_comment} -->",
        "",
        f"# {cat.title}",
        "",
        cat.intro,
        "",
        "Back to [DomainProgram catalog](index.md).",
        "",
        "## Contents",
        "",
    ]
    for entry in entries:
        anchor = slugify_anchor(entry.name)
        out.append(f"- [{entry.name}](#{anchor}) (`{entry.filename}`)")
    out.append("")

    for entry in entries:
        out.extend(["---", "", f"## {entry.name}", ""])
        if entry.description:
            out.extend([entry.description, ""])

        meta_rows = [
            f"- **Fixture:** `{fixtures_display_prefix}/{entry.filename}` (v{entry.version})",
            f"- **Steps:** {entry.step_count} executable step(s), {len(entry.actions)} unique action(s)",
        ]
        if entry.triggers:
            meta_rows.append(
                "- **Event triggers:** " + ", ".join(f"`{t}`" for t in entry.triggers)
            )
        if entry.variables:
            meta_rows.append(
                "- **Declared variables:** " + ", ".join(f"`{v}`" for v in entry.variables)
            )
        if entry.actions:
            meta_rows.append("- **Actions:** " + ", ".join(f"`{a}`" for a in entry.actions))
        out.extend(meta_rows)
        out.extend(["", "```mermaid", entry.mermaid.rstrip("\n"), "```", ""])

    return "\n".join(out)


def _render_index_page(
    grouped: Sequence[tuple[CategorySpec, list[ProgramEntry]]],
    *,
    product_name: str,
    fixtures_display_prefix: str,
    regen_command: str,
    banner_comment: str,
) -> str:
    total = sum(len(entries) for _, entries in grouped)
    out: list[str] = [
        f"<!-- {banner_comment} -->",
        "",
        "# DomainProgram catalog",
        "",
        (
            f"{product_name} defines **{total}** workflow DomainProgram fixture(s) under "
            f"`{fixtures_display_prefix}/*.program.json`. Each program compiles into "
            "a GoliathApp workflow graph (`wf.workflow_node` / `wf.workflow_edge`) and is "
            "rendered below as a Mermaid flowchart directly from its JSON definition."
        ),
        "",
        "## Categories",
        "",
        "| Category | Programs | Focus |",
        "|----------|---------:|-------|",
    ]
    for cat, entries in grouped:
        out.append(f"| [{cat.title}]({cat.slug}.md) | {len(entries)} | {cat.intro} |")

    out.extend(["", "## All fixtures", ""])
    for cat, entries in grouped:
        out.extend(
            [
                f"### [{cat.title}]({cat.slug}.md)",
                "",
                "| Program | Fixture | Steps | Summary |",
                "|---------|---------|------:|---------|",
            ]
        )
        for entry in entries:
            anchor = slugify_anchor(entry.name)
            summary = entry.description.replace("|", "\\|").replace("\n", " ")
            if len(summary) > 140:
                summary = summary[:137].rstrip() + "..."
            out.append(
                f"| [{entry.name}]({cat.slug}.md#{anchor}) | `{entry.filename}` "
                f"| {entry.step_count} | {summary} |"
            )
        out.append("")

    out.extend(
        [
            "## Regenerating and reusing diagrams",
            "",
            "These pages are generated from the fixture JSON files so diagrams stay in sync "
            "with every workflow edit:",
            "",
            "```bash",
            "# Regenerate Markdown catalog pages",
            regen_command,
            "",
            "# Verify no drift (CI)",
            f"{regen_command} --check",
            "",
            "# Export standalone .mmd files (for courses or external docs)",
            f"{regen_command} --emit-mmd-dir /tmp/domain-program-mmd",
            "```",
            "",
        ]
    )
    return "\n".join(out)


def build_catalog_docs(
    fixtures_dir: Path,
    *,
    categories: Sequence[CategorySpec] = (),
    product_name: str = "This application",
    fixtures_display_prefix: str = "workflow_engine/domain/fixtures",
    regen_command: str = "goliath-cfg render-mermaid --fixtures-dir workflow_engine/domain/fixtures --docs-dir docs/workflows",
    banner_comment: str = "Generated by domain.mermaid. Do not edit by hand.",
) -> tuple[dict[str, str], dict[str, str]]:
    """Build ``(markdown_files_by_name, mmd_files_by_name)`` for all fixtures in ``fixtures_dir``."""
    program_paths = sorted(fixtures_dir.glob("*.program.json"))
    if not program_paths:
        raise FileNotFoundError(f"No *.program.json fixtures found in {fixtures_dir}")

    entries_by_file: dict[str, ProgramEntry] = {}
    mmd_files: dict[str, str] = {}
    for path in program_paths:
        entry = load_program_entry(path)
        entries_by_file[entry.filename] = entry
        mmd_files[f"{entry.stem}.mmd"] = entry.mermaid

    grouped = _group_programs(entries_by_file, categories)
    md_files: dict[str, str] = {
        "index.md": _render_index_page(
            grouped,
            product_name=product_name,
            fixtures_display_prefix=fixtures_display_prefix,
            regen_command=regen_command,
            banner_comment=banner_comment,
        )
    }
    for cat, entries in grouped:
        md_files[f"{cat.slug}.md"] = _render_category_page(
            cat,
            entries,
            fixtures_display_prefix=fixtures_display_prefix,
            banner_comment=banner_comment,
        )
    return md_files, mmd_files


def check_docs(docs_dir: Path, expected: Mapping[str, str]) -> list[str]:
    """Compare ``docs_dir`` Markdown files against ``expected`` and return drift messages."""
    problems: list[str] = []
    existing = {p.name for p in docs_dir.glob("*.md")} if docs_dir.is_dir() else set()
    for stale in sorted(existing - set(expected)):
        problems.append(f"stale file not generated from fixtures: {docs_dir / stale}")
    for name, content in sorted(expected.items()):
        target = docs_dir / name
        if not target.is_file():
            problems.append(f"missing generated file: {target}")
            continue
        actual = target.read_text(encoding="utf-8")
        if actual != content:
            diff = list(
                difflib.unified_diff(
                    actual.splitlines(),
                    content.splitlines(),
                    fromfile=f"{name} (committed)",
                    tofile=f"{name} (generated)",
                    n=2,
                    lineterm="",
                )
            )
            snippet = "\n".join(diff[:20])
            problems.append(f"out-of-date file: {target}\n{snippet}")
    return problems


def write_files(target_dir: Path, files: Mapping[str, str], *, clean_ext: str) -> None:
    """Write ``files`` into ``target_dir`` with LF newlines and remove stale files of ``clean_ext``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    expected_names = set(files)
    for existing in target_dir.glob(f"*{clean_ext}"):
        if existing.name not in expected_names:
            existing.unlink()
    for name, content in sorted(files.items()):
        (target_dir / name).write_text(content, encoding="utf-8", newline="\n")


def run_cli(args: argparse.Namespace) -> int:
    """Execute render-mermaid from parsed CLI arguments."""
    if args.program is not None:
        entry = load_program_entry(Path(args.program))
        if args.output is not None:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(entry.mermaid, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(entry.mermaid)
        return 0

    if args.fixtures_dir is None:
        print("Pass either --program <file> or --fixtures-dir <dir>.", file=sys.stderr)
        return 2

    categories: tuple[CategorySpec, ...] = ()
    if args.categories_json is not None:
        categories = load_categories_file(Path(args.categories_json))

    fixtures_dir = Path(args.fixtures_dir)
    md_files, mmd_files = build_catalog_docs(
        fixtures_dir,
        categories=categories,
        product_name=str(args.product_name),
        fixtures_display_prefix=str(args.fixtures_prefix),
        regen_command=str(args.regen_command),
    )

    if args.emit_mmd_dir is not None:
        mmd_dir = Path(args.emit_mmd_dir)
        write_files(mmd_dir, mmd_files, clean_ext=".mmd")
        print(f"Wrote {len(mmd_files)} standalone .mmd diagram(s) to {mmd_dir}")

    if args.docs_dir is None:
        if args.emit_mmd_dir is None:
            print("Pass --docs-dir and/or --emit-mmd-dir with --fixtures-dir.", file=sys.stderr)
            return 2
        return 0

    docs_dir = Path(args.docs_dir)
    if args.check:
        problems = check_docs(docs_dir, md_files)
        if problems:
            print(
                f"DomainProgram Mermaid docs are out of date. Run:\n  {args.regen_command}\n",
                file=sys.stderr,
            )
            for item in problems:
                print(item, file=sys.stderr)
            return 1
        print(
            f"OK: {len(mmd_files)} DomainProgram diagram(s) across "
            f"{len(md_files)} doc page(s) are up to date."
        )
        return 0

    write_files(docs_dir, md_files, clean_ext=".md")
    print(
        f"Generated {len(md_files)} Markdown page(s) covering "
        f"{len(mmd_files)} DomainProgram fixture(s) in {docs_dir}"
    )
    return 0


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Register generic DomainProgram Mermaid rendering options on ``parser``."""
    parser.add_argument(
        "--program",
        default=None,
        help="Render one *.program.json file as a Mermaid flowchart (stdout or --output).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output .mmd path when using --program.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="Directory containing *.program.json fixtures to render as a catalog.",
    )
    parser.add_argument(
        "--docs-dir",
        default=None,
        help="Output directory for generated Markdown catalog pages.",
    )
    parser.add_argument(
        "--emit-mmd-dir",
        default=None,
        help="Optional directory to write one standalone .mmd file per fixture.",
    )
    parser.add_argument(
        "--categories-json",
        default=None,
        help="Optional JSON file grouping fixture filenames into category pages.",
    )
    parser.add_argument(
        "--product-name",
        default="This application",
        help="Application name used in generated index prose.",
    )
    parser.add_argument(
        "--fixtures-prefix",
        default="workflow_engine/domain/fixtures",
        help="Display path prefix for fixtures in generated Markdown.",
    )
    parser.add_argument(
        "--regen-command",
        default="goliath-cfg render-mermaid --fixtures-dir workflow_engine/domain/fixtures --docs-dir docs/workflows",
        help="Regeneration command documented on index.md and check failures.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail with exit code 1 if --docs-dir does not match freshly rendered output.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m domain.mermaid",
        description="Render DomainProgram JSON fixtures as Mermaid flowcharts.",
    )
    add_cli_arguments(parser)
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
