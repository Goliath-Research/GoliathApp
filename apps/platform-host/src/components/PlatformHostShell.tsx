"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ObjectBadge } from "@goliath/ui";
import type { HostNavItem } from "@/lib/child-extension";

const CORE_NAV: HostNavItem[] = [
  { id: "home", label: "Platform host", href: "/", kind: "config" },
  { id: "fixture", label: "P0 presentation fixture", href: "/fixture", kind: "view" },
];

export function PlatformHostShell({
  revision,
  version,
  childNav = [],
  children,
}: {
  revision: string;
  version: string;
  childNav?: HostNavItem[];
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const nav = [...CORE_NAV, ...childNav];

  return (
    <div className="g-host">
      <header className="g-host__bar">
        <ObjectBadge kind="config" label="Goliath platform host" subtitle={`v${version}`} />
        <p className="g-host__meta">
          Build <code>{revision}</code> · fixture-only · no database
        </p>
      </header>
      <h1 className="g-visually-hidden">Goliath platform navigation</h1>
      <nav className="g-host__nav" aria-label="Platform sections">
        {nav.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.id}
              href={item.href}
              className={active ? "g-host__nav-link g-host__nav-link--active" : "g-host__nav-link"}
              aria-current={active ? "page" : undefined}
            >
              <ObjectBadge kind={item.kind} label={item.label} />
            </Link>
          );
        })}
      </nav>
      <main className="g-host__main">{children}</main>
      <footer className="g-host__footer">
        <p>Static demonstration — not an operator portal. Authentication and live data are P1.</p>
      </footer>
    </div>
  );
}
