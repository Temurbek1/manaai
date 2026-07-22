import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithSession } from "../test/render";
import { requestUrl } from "../test/http";
import { DashboardPage } from "./DashboardPage";

const dashboard = {
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
};

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

describe("DashboardPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("runs an agent manually and changes the global kill switch for an admin", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("/dashboard")) return response(dashboard);
      if (url.includes("/agents/marketing-agent/run")) return response({ status: "accepted" });
      if (url.includes("/kill-switch/global")) return response({ enabled: true });
      return response({});
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithSession(<DashboardPage />, "admin");

    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/agents/marketing-agent/run"),
      expect.objectContaining({ method: "POST" }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Emergency stop" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/kill-switch/global"),
      expect.objectContaining({ method: "PUT" }),
    ));
  });

  it("renders loading, error, and empty states", async () => {
    let resolveRequest: ((value: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => { resolveRequest = resolve; });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(() => pending));
    const rendered = renderWithSession(<DashboardPage />, "viewer");
    expect(rendered.container).toHaveTextContent("…");
    expect(screen.getByText("No agents")).toBeInTheDocument();

    resolveRequest?.(new Response(JSON.stringify({ detail: "Database unavailable" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    }));
    expect(await screen.findByText(/Unable to load dashboard/)).toBeInTheDocument();
  });
});
