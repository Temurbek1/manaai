import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithSession } from "../test/render";
import { requestBodyText, requestUrl } from "../test/http";
import { AgentsPage } from "./AgentsPage";

const agent = {
  agent_id: "marketing-agent",
  display_name: "Marketing Agent",
  description: "Analyzes advertising performance.",
  version: "1.0.0",
  status: "enabled",
  capabilities: [{ key: "marketing.write", description: "Controlled changes", risk: "financial", minimum_role: "approver" }],
  configuration_schema: {},
  registered_at: "2026-07-22T08:00:00Z",
};

const schedule = {
  schedule_id: "schedule-analysis",
  agent_id: "marketing-agent",
  job_type: "analysis",
  cron_expression: "0 * * * *",
  timezone: "UTC",
  enabled: true,
  next_run_at: "2026-07-22T09:00:00Z",
  last_run_at: null,
};

const detail = {
  agent,
  configuration: {
    configuration_id: "config-1",
    agent_id: "marketing-agent",
    version: 1,
    values: { currency: "USD" },
    created_at: "2026-07-22T08:00:00Z",
    created_by: "bootstrap",
    active: true,
  },
  schedules: [schedule],
  integration_health: [{
    integration_id: "fake_meta",
    status: "healthy",
    checked_at: "2026-07-22T08:00:00Z",
    message: "Fake provider ready",
    diagnostics: {},
  }],
  kill_switch_enabled: false,
};

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function mockAgentApi(onRequest?: (url: string, init?: RequestInit) => Promise<Response> | null): ReturnType<typeof vi.fn<typeof fetch>> {
  return vi.fn<typeof fetch>((input, init) => {
    const url = requestUrl(input);
    const custom = onRequest?.(url, init);
    if (custom) return custom;
    if (url.includes("configuration-schema")) return response({ properties: { currency: { type: "string" } } });
    if (url.includes("/agents/marketing-agent") && !url.includes("/run")) return response(detail);
    if (url.endsWith("/agents")) return response({ items: [agent], total: 1, limit: 100, offset: 0 });
    if (url.includes("/runs") || url.includes("/reports")) return response({ items: [], total: 0, limit: 5, offset: 0 });
    return response({});
  });
}

describe("AgentsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("disables configuration, schedule, status, and kill-switch controls for viewers", async () => {
    vi.stubGlobal("fetch", mockAgentApi());
    renderWithSession(<AgentsPage />, "viewer");
    fireEvent.click(await screen.findByRole("button", { name: /Marketing Agent/ }));

    expect(await screen.findByRole("button", { name: "Validate & activate version" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Emergency stop agent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeDisabled();
    expect(screen.getByLabelText("analysis cron expression")).toBeDisabled();
  });

  it("validates configuration locally and edits a schedule through the typed API", async () => {
    const fetchMock = mockAgentApi((url, init) => {
      if (url.includes("/schedules/schedule-analysis")) {
        expect(init?.method).toBe("PUT");
        expect(JSON.parse(requestBodyText(init?.body))).toEqual({
          cron_expression: "15 * * * *",
          timezone: "Asia/Samarkand",
          enabled: false,
        });
        return response({ ...schedule, cron_expression: "15 * * * *", timezone: "Asia/Samarkand", enabled: false });
      }
      return null;
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithSession(<AgentsPage />, "admin");
    fireEvent.click(await screen.findByRole("button", { name: /Marketing Agent/ }));

    const editor = await screen.findByLabelText("Active JSON values");
    fireEvent.change(editor, { target: { value: "not-json" } });
    fireEvent.click(screen.getByRole("button", { name: "Validate & activate version" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Unexpected token");

    fireEvent.change(screen.getByLabelText("analysis cron expression"), { target: { value: "15 * * * *" } });
    fireEvent.change(screen.getByLabelText("analysis timezone"), { target: { value: "Asia/Samarkand" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/schedules/schedule-analysis"),
      expect.objectContaining({ method: "PUT" }),
    ));
    expect(await screen.findByRole("status")).toHaveTextContent("analysis schedule updated");
  });
});
