"use client";

import { useCallback, useEffect, useState } from "react";
import { createPlatformBffClient, type PlatformSessionSnapshot } from "@goliath/client";
import { OperatorNavList } from "@goliath/platform-ui";
import type { OperatorNavNode } from "@goliath/client";

export function SessionOperatorPanel() {
  const client = createPlatformBffClient();
  const [session, setSession] = useState<PlatformSessionSnapshot | null | undefined>(undefined);
  const [nodes, setNodes] = useState<OperatorNavNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const snap = await client.getSession();
      setSession(snap);
      if (snap) {
        const nav = await client.getOperatorNavigation();
        setNodes(nav);
      } else {
        setNodes(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "transport error");
      setSession(null);
      setNodes(null);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (session === undefined) {
    return <p role="status">Checking session…</p>;
  }

  if (!session) {
    return (
      <section className="g-host-card" aria-labelledby="session-panel-guest">
        <h3 id="session-panel-guest">Authentication (P1)</h3>
        <p>No platform session cookie. Use your identity provider integration or operator bootstrap.</p>
        <p>
          <a href="/app">Try protected /app route</a> (server redirect when unauthenticated).
        </p>
      </section>
    );
  }

  return (
    <section className="g-host-card" aria-labelledby="session-panel-auth">
      <h3 id="session-panel-auth">Authenticated transport</h3>
      <p>
        {session.fullName} · <code>{session.email}</code>
      </p>
      {error ? <p role="alert">{error}</p> : null}
      {nodes ? <OperatorNavList nodes={nodes} aria-label="Live operator navigation preview" /> : null}
      <button type="button" className="g-host-button" onClick={() => void client.logout().then(refresh)}>
        Sign out
      </button>
    </section>
  );
}
