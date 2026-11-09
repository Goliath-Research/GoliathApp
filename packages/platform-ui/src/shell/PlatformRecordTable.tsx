/**
 * Read-only operator grid for platform list/query surfaces.
 */
export function PlatformRecordTable({
  columns,
  rows,
  caption,
}: {
  caption: string;
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
}) {
  if (rows.length === 0) {
    return (
      <p className="g-operator-nav__empty" role="status">
        No rows returned for {caption}.
      </p>
    );
  }
  return (
    <div className="g-portal-table-wrap">
      <table className="g-host-table" aria-label={caption}>
        <caption className="g-sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {columns.map((col) => (
                <td key={col.key}>{formatCell(row[col.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
