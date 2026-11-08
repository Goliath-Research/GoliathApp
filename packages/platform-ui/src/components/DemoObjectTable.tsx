/**
 * Table pattern inspired by the read-only grid in Goliath-portal
 * (https://github.com/Goliath-Research/Goliath-portal — DataTable list rendering),
 * reimplemented for platform presentation badges.
 */
import { ObjectBadge } from "@goliath/ui";
import type { FixtureRow } from "../fixture/sample-rows.js";

export function DemoObjectTable({ rows, classIconOverrides }: { rows: FixtureRow[]; classIconOverrides?: Record<string, string> }) {
  return (
    <table className="g-demo-table">
      <thead>
        <tr>
          <th scope="col">Presentation</th>
          <th scope="col">Fixture id</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>
              <ObjectBadge
                kind={row.kind}
                label={row.label}
                subtitle={row.subtitle}
                classFqn={row.classFqn}
                classAncestry={row.classAncestry}
                classIconOverrides={classIconOverrides}
                fixture
              />
            </td>
            <td>{row.id}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
