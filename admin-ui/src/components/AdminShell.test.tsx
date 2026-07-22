import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { configureCredentials } from "@/api/client";
import { DashboardPage } from "@/features/DashboardPage";
import { requestUrl } from "@/test/http";

import { AdminShell } from "./AdminShell";
import { Providers } from "./Providers";

jest.mock("next/navigation", () => ({ usePathname: () => "/" }));

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderShell(): void {
  render(
    <Providers>
      <AdminShell>
        <DashboardPage />
      </AdminShell>
    </Providers>,
  );
}

describe("AdminShell authentication and navigation", () => {
  afterEach(() => {
    configureCredentials(null);
  });

  it("keeps credentials in memory, exposes real routes, and applies viewer RBAC", async () => {
    const storageSpy = jest.spyOn(Storage.prototype, "setItem");
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.includes("/session")) {
        expect(new Headers(init?.headers).get("X-API-Key")).toBe(
          "viewer-secret",
        );
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
          agents: [
            {
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
            },
          ],
          global_kill_switch: false,
          generated_at: "2026-07-22T08:00:00Z",
        });
      }
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderShell();

    fireEvent.change(screen.getByLabelText("Internal API key"), {
      target: { value: "viewer-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("internal-viewer")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Emergency stop" }),
    ).toBeDisabled();
    expect(
      await screen.findByRole("button", { name: "Run now" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("link", { name: "Marketing Agent" }),
    ).toHaveAttribute("href", "/marketing");
    expect(storageSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(
      screen.getByRole("button", { name: "Close menu" }),
    ).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("button", { name: "Close menu" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(
      screen.getByRole("heading", { name: "Sign in to the control room" }),
    ).toBeInTheDocument();
  });

  it("shows a controlled authentication error", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(
        jest.fn<typeof fetch>(() =>
          jsonResponse({ detail: "Invalid key" }, 401),
        ),
      );
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid key");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(),
    );
  });
});
