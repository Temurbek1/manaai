"use client";

import { createContext, useContext } from "react";

import type { AuthenticatedSession } from "../api/client";

interface SessionContextValue {
  session: AuthenticatedSession;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export const SessionProvider = SessionContext.Provider;

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("SessionProvider is required");
  }
  return value;
}

const ROLE_RANK: Record<AuthenticatedSession["user"]["role"], number> = {
  viewer: 0,
  operator: 1,
  approver: 2,
  admin: 3,
};

export function hasRole(
  session: AuthenticatedSession,
  minimum: AuthenticatedSession["user"]["role"],
): boolean {
  return ROLE_RANK[session.user.role] >= ROLE_RANK[minimum];
}
