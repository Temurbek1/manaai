import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";

import type { ActorSession } from "../api/client";
import { apiGet } from "../api/client";
import { SessionProvider } from "../auth/SessionContext";

export function renderWithSession(
  ui: ReactNode,
  role: ActorSession["role"] = "admin",
): RenderResult {
  return render(
    <SessionProvider
      value={{
        session: {
          actor_id: `test-${role}`,
          role,
          ads_provider: "fake_meta",
          provider_mode: "fake_executable",
          live_meta_read_only: false,
        },
        signOut: () => undefined,
      }}
    >
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, fetcher: apiGet }}>
        {ui}
      </SWRConfig>
    </SessionProvider>,
  );
}
