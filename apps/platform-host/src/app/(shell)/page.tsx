import Link from "next/link";
import { ObjectBadge } from "@goliath/ui";
import { platformHostRevision, platformHostVersion } from "@/lib/build-info";
import { SessionOperatorPanel } from "@/components/SessionOperatorPanel";

export default function HomePage() {
  return (
    <div className="g-host-home">
      <p className="kicker">[Fixture host]</p>
      <h2>Platform UI foundation (P0)</h2>
      <p className="g-host-home__lead">
        This process is owned by <strong>GoliathApp</strong>. It serves shared packages (
        <code>@goliath/ui</code>, <code>@goliath/platform-ui</code>) and a labeled fixture route. It does not connect
        to PostgreSQL when the portal bridge is configured. P2 adds a session-gated Meta browser at{" "}
        <Link href="/app/meta">/app/meta</Link>.
      </p>
      <section className="g-host-home__grid" aria-label="Host capabilities">
        <article className="g-host-card">
          <ObjectBadge kind="meta_class" label="Shared presentation" fixture />
          <p>Deterministic default icons, class override resolution, and ObjectBadge primitives.</p>
        </article>
        <article className="g-host-card">
          <ObjectBadge kind="workflow_definition" label="Workflows (roadmap)" fixture />
          <p>First-class in packages and docs; designer/monitor is P3 — not in this host yet.</p>
        </article>
        <article className="g-host-card">
          <ObjectBadge kind="semantic_entity" label="Semantic layer (roadmap)" fixture />
          <p>Registry-driven screens are P4; this host only demonstrates static fixture rows.</p>
        </article>
        <article className="g-host-card g-host-card--wide">
          <SessionOperatorPanel />
        </article>
        <article className="g-host-card">
          <h3>Build identity</h3>
          <p>
            Version <code>{platformHostVersion()}</code> · revision <code>{platformHostRevision()}</code>
          </p>
          <p>
            <a href="/api/health">/api/health</a>
          </p>
        </article>
        <article className="g-host-card">
          <h3>Fixture demo</h3>
          <p>
            <Link href="/fixture">Open P0 presentation fixture</Link> — table and tree with every platform object kind.
          </p>
        </article>
      </section>
    </div>
  );
}
