"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import {
  apiGet,
  configureCredentials,
  type ActorSession,
  type ClientCredentials,
} from "@/api/client";
import { SessionProvider } from "@/auth/SessionContext";

import { AuthenticatedShell } from "./AuthenticatedShell";
import { LoginPanel } from "./LoginPanel";

interface AdminShellProps {
  children: ReactNode;
}

export function AdminShell({ children }: AdminShellProps): React.JSX.Element {
  const [session, setSession] = useState<ActorSession | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    function expireSession(): void {
      configureCredentials(null);
      setSession(null);
      setLoginError("Your session is no longer authorized. Sign in again.");
    }
    window.addEventListener("mana:unauthorized", expireSession);
    return () => window.removeEventListener("mana:unauthorized", expireSession);
  }, []);

  async function login(credentials: ClientCredentials): Promise<void> {
    setLoginBusy(true);
    setLoginError(null);
    configureCredentials(credentials);
    try {
      const actor = await apiGet<ActorSession>(
        "/api/v1/admin/operation/session",
      );
      setSession(actor);
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
    setLoginError(null);
  }

  if (session === null) {
    return <LoginPanel busy={loginBusy} error={loginError} onLogin={login} />;
  }

  return (
    <SessionProvider value={{ session, signOut }}>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </SessionProvider>
  );
}
