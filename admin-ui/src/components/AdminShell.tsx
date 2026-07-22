"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import {
  apiGet,
  apiPost,
  type AuthSession,
  type AuthenticatedSession,
  isAuthenticatedSession,
} from "@/api/client";
import { SessionProvider } from "@/auth/SessionContext";

import { AuthenticatedShell } from "./AuthenticatedShell";
import { LoginPanel } from "./LoginPanel";

interface AdminShellProps {
  children: ReactNode;
}

export function AdminShell({ children }: AdminShellProps): React.JSX.Element {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiGet<AuthSession>("/api/v1/auth/session")
      .then((current) => {
        if (active && isAuthenticatedSession(current)) setSession(current);
      })
      .catch(() => {
        if (active)
          setLoginNotice("Не удалось проверить сессию. Попробуйте ещё раз.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    function expireSession(): void {
      setSession(null);
      setLoginNotice("Сессия завершена. Войдите снова.");
    }
    window.addEventListener("mana:unauthorized", expireSession);
    return () => window.removeEventListener("mana:unauthorized", expireSession);
  }, []);

  async function signOut(): Promise<void> {
    try {
      await apiPost<void>("/api/v1/auth/logout", {});
    } finally {
      setSession(null);
      setLoginNotice(null);
    }
  }

  if (loading) {
    return (
      <main className="login-page" aria-busy="true">
        <div className="auth-loading" role="status">
          Проверяем защищённую сессию…
        </div>
      </main>
    );
  }

  if (session === null) {
    return (
      <LoginPanel
        notice={loginNotice}
        onAuthenticated={(authenticated) => {
          setLoginNotice(null);
          setSession(authenticated);
        }}
      />
    );
  }

  return (
    <SessionProvider value={{ session, signOut }}>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </SessionProvider>
  );
}
