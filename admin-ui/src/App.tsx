import { lazy, Suspense, useEffect, useState } from "react";

import {
  apiGet,
  configureCredentials,
  type ActorSession,
  type ClientCredentials,
} from "./api/client";
import { SessionProvider } from "./auth/SessionContext";
import { LoginPanel } from "./components/LoginPanel";

const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })),
);
const MarketingPage = lazy(() =>
  import("./pages/MarketingPage").then((module) => ({ default: module.MarketingPage })),
);
const ApprovalsPage = lazy(() =>
  import("./pages/ApprovalsPage").then((module) => ({ default: module.ApprovalsPage })),
);
const RunsPage = lazy(() =>
  import("./pages/RunsPage").then((module) => ({ default: module.RunsPage })),
);
const AgentsPage = lazy(() =>
  import("./pages/AgentsPage").then((module) => ({ default: module.AgentsPage })),
);

type View = "dashboard" | "marketing" | "approvals" | "runs" | "agents";

const NAVIGATION = [
  { id: "dashboard", label: "Overview", icon: "⌂" },
  { id: "marketing", label: "Marketing Agent", icon: "↗" },
  { id: "approvals", label: "Approvals", icon: "✓" },
  { id: "runs", label: "Runs & audit", icon: "≋" },
  { id: "agents", label: "Agent registry", icon: "◇" },
] as const satisfies readonly { id: View; label: string; icon: string }[];

export function App(): React.JSX.Element {
  const [view, setView] = useState<View>("dashboard");
  const [menuOpen, setMenuOpen] = useState(false);
  const [session, setSession] = useState<ActorSession | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  function selectView(next: View): void {
    setView(next);
    setMenuOpen(false);
  }

  async function login(credentials: ClientCredentials): Promise<void> {
    setLoginBusy(true);
    setLoginError(null);
    configureCredentials(credentials);
    try {
      setSession(await apiGet<ActorSession>("/api/v1/admin/operation/session"));
    } catch (error) {
      configureCredentials(null);
      setLoginError(error instanceof Error ? error.message : "Sign in failed");
    } finally {
      setLoginBusy(false);
    }
  }

  function signOut(): void {
    configureCredentials(null);
    setSession(null);
    setView("dashboard");
    setMenuOpen(false);
  }

  if (session === null) {
    return <LoginPanel busy={loginBusy} error={loginError} onLogin={login} />;
  }

  return (
    <SessionProvider value={{ session, signOut }}>
      <div className="app-shell">
      <aside className={menuOpen ? "sidebar open" : "sidebar"} id="primary-menu">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">M</span>
          <div><strong>MANA</strong><small>Operation AI</small></div>
        </div>
        <nav aria-label="Primary navigation">
          {NAVIGATION.map((item) => (
            <button
              aria-current={view === item.id ? "page" : undefined}
              className={view === item.id ? "nav-item active" : "nav-item"}
              key={item.id}
              onClick={() => selectView(item.id)}
              type="button"
            >
              <span aria-hidden="true">{item.icon}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-safety">
          <div className="pulse-dot" aria-hidden="true" />
          <div>
            <strong>{session.live_meta_read_only ? "Live read-only" : "Controlled execution"}</strong>
            <small>
              {session.live_meta_read_only
                ? "Meta writes unavailable"
                : "Server policy · approvals · audit"}
            </small>
          </div>
        </div>
        <div className="session-box">
          <span><strong>{session.actor_id}</strong><small>{session.role}</small></span>
          <button onClick={signOut} type="button">Sign out</button>
        </div>
      </aside>
      {menuOpen ? <button aria-label="Close menu" className="scrim" onClick={() => setMenuOpen(false)} type="button" /> : null}
      <div className="workspace">
        {session.live_meta_read_only ? (
          <div className="live-readonly-banner" role="status">
            <strong>LIVE META — READ ONLY</strong>
            <span>Recommendations are advisory. Budget, status, targeting, and creative writes are unavailable.</span>
          </div>
        ) : null}
        <header className="mobile-bar">
          <button
            aria-controls="primary-menu"
            aria-expanded={menuOpen}
            aria-label="Open menu"
            onClick={() => setMenuOpen(true)}
            type="button"
          >☰</button>
          <strong>MANA Operation AI</strong>
          <span className="pulse-dot" />
        </header>
        <main>
          <Suspense fallback={<div className="loading-state">Loading operational context…</div>}>
            {view === "dashboard" ? <DashboardPage /> : null}
            {view === "marketing" ? <MarketingPage /> : null}
            {view === "approvals" ? <ApprovalsPage /> : null}
            {view === "runs" ? <RunsPage /> : null}
            {view === "agents" ? <AgentsPage /> : null}
          </Suspense>
        </main>
      </div>
    </div>
    </SessionProvider>
  );
}
