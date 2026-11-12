"use client";

import { PlatformRecordTable } from "@goliath/platform-ui";
import type { ViewDefinition, ViewVisualization } from "@/lib/operator-view-definition";
import { previewColumns } from "@/lib/operator-view-definition";

type Props = {
  definition: ViewDefinition;
  rows: Record<string, unknown>[];
  caption?: string;
};

export function ViewVisualizationPreview({ definition, rows, caption = "Preview" }: Props) {
  const viz: ViewVisualization = definition.visualization;
  const columns = previewColumns(definition, rows[0]);

  if (viz.type === "table" || rows.length === 0) {
    return <PlatformRecordTable caption={caption} columns={columns} rows={rows} />;
  }

  const catField = viz.categoryField ?? columns[0]?.key;
  const valField = viz.valueField ?? columns.find((c) => c.key !== catField)?.key ?? columns[0]?.key;

  if (!catField || !valField) {
    return <PlatformRecordTable caption={caption} columns={columns} rows={rows} />;
  }

  if (viz.type === "kpi") {
    const first = rows[0]?.[valField];
    const display =
      typeof first === "number" ? first.toLocaleString() : first == null ? "—" : String(first);
    return (
      <div className="g-view-kpi" role="figure" aria-label={caption}>
        <p className="g-view-kpi__value">{display}</p>
        <p className="g-view-kpi__label">{valField}</p>
      </div>
    );
  }

  const pairs = rows.slice(0, 24).map((row) => ({
    label: String(row[catField] ?? ""),
    value: Number(row[valField]) || 0,
  }));
  const max = Math.max(1, ...pairs.map((p) => p.value));

  if (viz.type === "pie") {
    const total = pairs.reduce((s, p) => s + p.value, 0) || 1;
    let acc = 0;
    const slices = pairs.map((p, i) => {
      const start = (acc / total) * 100;
      acc += p.value;
      const end = (acc / total) * 100;
      const hue = (i * 47) % 360;
      return `${`hsl(${hue} 55% 45%)`} ${start}% ${end}%`;
    });
    return (
      <div className="g-view-chart" role="figure" aria-label={caption}>
        <div
          className="g-view-chart__pie"
          style={{ background: `conic-gradient(${slices.join(", ")})` }}
        />
        <ul className="g-view-chart__legend">
          {pairs.map((p) => (
            <li key={p.label}>
              {p.label}: {p.value}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const isLine = viz.type === "line";

  return (
    <div className="g-view-chart" role="figure" aria-label={caption}>
      {isLine ? (
        <svg className="g-view-chart__line" viewBox="0 0 100 40" preserveAspectRatio="none">
          <polyline
            fill="none"
            stroke="var(--g-accent, #3a7)"
            strokeWidth="1.5"
            points={pairs
              .map((p, i) => {
                const x = pairs.length <= 1 ? 50 : (i / (pairs.length - 1)) * 100;
                const y = 38 - (p.value / max) * 36;
                return `${x},${y}`;
              })
              .join(" ")}
          />
        </svg>
      ) : (
        <div className="g-view-chart__bars">
          {pairs.map((p) => (
            <div key={p.label} className="g-view-chart__bar-wrap">
              <div
                className="g-view-chart__bar"
                style={{ height: `${(p.value / max) * 100}%` }}
                title={`${p.label}: ${p.value}`}
              />
              <span className="g-view-chart__bar-label">{p.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
