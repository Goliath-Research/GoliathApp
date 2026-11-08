/** Host applications must import `@goliath/ui/styles.css` in their root layout (Next/other bundler). */
import { DemoNavTree } from "../components/DemoNavTree.js";
import { DemoObjectTable } from "../components/DemoObjectTable.js";
import { FIXTURE_NAV_TREE, FIXTURE_PLATFORM_ROWS } from "./sample-rows.js";

const CHILD_DEMO_OVERRIDES = {
  "portal/Study": "platform:collection",
  "meta/BaseNode": "meta:tree",
};

export function PlatformFixtureDemo() {
  return (
    <div className="g-fixture-demo">
      <h1>Platform presentation fixture (P0)</h1>
      <p>Sample rows for Meta, workflow, semantic, admin, and config kinds — not live database data.</p>
      <section aria-labelledby="fixture-table-heading">
        <h2 id="fixture-table-heading">Object table</h2>
        <DemoObjectTable rows={FIXTURE_PLATFORM_ROWS} classIconOverrides={CHILD_DEMO_OVERRIDES} />
      </section>
      <section aria-labelledby="fixture-tree-heading">
        <h2 id="fixture-tree-heading">Navigation tree</h2>
        <DemoNavTree root={FIXTURE_NAV_TREE} />
      </section>
    </div>
  );
}
