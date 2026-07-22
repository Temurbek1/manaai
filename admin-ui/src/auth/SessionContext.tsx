"use client";

import { createContext, useContext } from "react";

import type { ActorSession } from "../api/client";

interface SessionContextValue {
  session: ActorSession;
  signOut: () => void;
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

const ROLE_RANK: Record<ActorSession["role"], number> = {
  viewer: 0,
  operator: 1,
  approver: 2,
  admin: 3,
};

export function hasRole(
  session: ActorSession,
  minimum: ActorSession["role"],
): boolean {
  return ROLE_RANK[session.role] >= ROLE_RANK[minimum];
}
