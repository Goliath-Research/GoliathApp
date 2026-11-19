import Link from "next/link";
import { ObjectBadge } from "@goliath/ui";
import { platformHostRevision, platformHostVersion } from "@/lib/build-info";
import { SessionOperatorPanel } from "@/components/SessionOperatorPanel";

export default function HomePage() {
  return (
    <div className="g-host-home">
      <p className="kicker">GoliathApp platform host</p>
      <h2>Operator portal</h2>
      <p className="g-host-home__lead">
        This process is owned by <strong>GoliathApp</strong>. It serves shared packages (
        <code>@goliath/ui</code>, <code>@goliath/platform-ui</code>) and a labeled fixture route. It does not connect
        to PostgreSQL directly from the browser; signed-in screens under <Link href="/app">/app</Link> are how every
        child app visualizes, creates, edits, and manages what the platform uses.
      </p>
      <section className="g-host-home__grid" aria-label="Host capabilities">
        <article className="g-host-card">
          <ObjectBadge kind="meta_class" label="Shared presentation" fixture />
          <p>Deterministic default icons, class override resolution, and ObjectBadge primitives.</p>
        </article>
        <article className="g-host-card">
          <ObjectBadge kind="workflow_definition" label="Workflow designer" />
          <p>
            Signed-in operators create, edit, version, and activate workflows, actions (class methods), domain
            programs, and runs under <Link href="/app/workflows/definitions">/app/workflows</Link>. Child apps inherit
            these screens and only add data.
          </p>
        </article>
        <article className="g-host-card">
          <ObjectBadge kind="semantic_entity" label="Semantic layer" />
          <p>
            Namespaces, entities, attributes, and requests are managed under{" "}
            <Link href="/app/semantic">/app/semantic</Link>; a child app&apos;s seeded namespaces appear there.
          </p>
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
