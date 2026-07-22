import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";

import type { AuthenticatedSession } from "../api/client";
import { apiGet } from "../api/client";
import { SessionProvider } from "../auth/SessionContext";

export function renderWithSession(
  ui: ReactNode,
  role: AuthenticatedSession["user"]["role"] = "admin",
  sessionOverrides: Partial<AuthenticatedSession> = {},
): RenderResult {
  return render(
    <SessionProvider
      value={{
        session: {
          authenticated: true,
          user: {
            user_id: "00000000-0000-4000-8000-000000000001",
            telegram_id: 976835256,
            display_name: "Test User",
            username: "test_user",
            role,
            permissions: ["view", "operate", "approve", "administer"],
          },
          expires_at: "2026-07-22T20:00:00Z",
          ads_provider: "fake_meta",
          provider_mode: "fake_executable",
          live_meta_read_only: false,
          ...sessionOverrides,
        },
        signOut: () => Promise.resolve(),
      }}
    >
      <SWRConfig
        value={{
          provider: () => new Map(),
          dedupingInterval: 0,
          fetcher: apiGet,
        }}
      >
        {ui}
      </SWRConfig>
    </SessionProvider>,
  );
}
