import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { apiGet, configureCredentials } from "./api/client";
import { requestUrl } from "./test/http";

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function renderApp(): void {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, fetcher: apiGet }}>
      <App />
    </SWRConfig>,
  );
}

describe("App authentication and navigation", () => {
  afterEach(() => {
    configureCredentials(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("verifies the session, keeps credentials out of browser storage, and applies viewer RBAC", async () => {
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.includes("/session")) {
        expect(new Headers(init?.headers).get("X-API-Key")).toBe("viewer-secret");
        expect(new Headers(init?.headers).get("X-MANA-Role")).toBe("viewer");
        return jsonResponse({
          actor_id: "internal-viewer",
          role: "viewer",
          ads_provider: "fake_meta",
          provider_mode: "fake_executable",
          live_meta_read_only: false,
        });
      }
      if (url.includes("/dashboard")) {
        return jsonResponse({
          agents: [{
            agent_id: "marketing-agent",
            display_name: "Marketing Agent",
            status: "enabled",
            health: "healthy",
            last_run: null,
            next_run: null,
            last_duration_ms: null,
            success_rate: "unavailable",
            pending_approvals: 0,
            recent_incidents: 0,
          }],
          global_kill_switch: false,
          generated_at: "2026-07-22T08:00:00Z",
        });
      }
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApp();

    fireEvent.change(screen.getByLabelText("Internal API key"), {
      target: { value: "viewer-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("internal-viewer")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Emergency stop" })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Run now" })).toBeDisabled();
    expect(storageSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Close menu" })).not.toBeInTheDocument();
  });

  it("shows a controlled authentication error", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => jsonResponse({ detail: "Invalid key" }, 401)));
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid key");
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
  });
});
