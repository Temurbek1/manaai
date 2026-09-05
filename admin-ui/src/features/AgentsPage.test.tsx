import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { requestBodyText, requestUrl } from "../test/http";
import { AgentsPage } from "./AgentsPage";

const agent = {
  agent_id: "growth-agent",
  display_name: "Growth & Conversion Agent",
  description: "Analyzes growth, advertising, and conversion performance.",
  version: "1.0.0",
  status: "enabled",
  default_capability_key: "growth.advertising",
  capabilities: [
    {
      key: "growth.advertising",
      agent_id: "growth-agent",
      description: "Advertising analysis and controlled changes",
      risk: "financial",
      minimum_role: "approver",
      input_schema: {},
      output_schema: {},
      required_integrations: ["fake_meta"],
      supported_triggers: ["user", "schedule"],
    },
  ],
  configuration_schema: {},
  registered_at: "2026-07-22T08:00:00Z",
};

const retentionAgent = {
  ...agent,
  agent_id: "retention-agent",
  display_name: "Retention & Loyalty Agent",
  description: "Measures first-party product engagement.",
  default_capability_key: "retention.engagement.analyze",
  capabilities: [
    {
      ...agent.capabilities[0],
      key: "retention.engagement.analyze",
      agent_id: "retention-agent",
      description: "First-party engagement analysis",
      risk: "read",
      minimum_role: "operator",
      required_integrations: [
        "fake_manakids_admin_api",
        "fake_firestore_activity",
      ],
    },
  ],
};

const schedule = {
  schedule_id: "schedule-analysis",
  agent_id: "growth-agent",
  capability_key: "growth.advertising",
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
    agent_id: "growth-agent",
    capability_key: "growth.advertising",
    version: 1,
    values: { currency: "USD" },
    created_at: "2026-07-22T08:00:00Z",
    created_by: "bootstrap",
    active: true,
  },
  configurations: [
    {
      configuration_id: "config-1",
      agent_id: "growth-agent",
      capability_key: "growth.advertising",
      version: 1,
      values: { currency: "USD" },
      created_at: "2026-07-22T08:00:00Z",
      created_by: "bootstrap",
      active: true,
    },
  ],
  schedules: [schedule],
  integration_health: [
    {
      integration_id: "fake_meta",
      status: "healthy",
      checked_at: "2026-07-22T08:00:00Z",
      message: "Fake provider ready",
      diagnostics: {},
    },
  ],
  kill_switch_enabled: false,
  capability_kill_switches: { "growth.advertising": false },
};

const retentionDetail = {
  ...detail,
  agent: retentionAgent,
  configuration: {
    ...detail.configuration,
    configuration_id: "retention-config-1",
    agent_id: "retention-agent",
    capability_key: "retention.engagement.analyze",
    values: { lookback_days: 7 },
  },
  configurations: [
    {
      ...detail.configuration,
      configuration_id: "retention-config-1",
      agent_id: "retention-agent",
      capability_key: "retention.engagement.analyze",
      values: { lookback_days: 7 },
    },
  ],
  schedules: [
    {
      ...schedule,
      schedule_id: "retention-engagement-analysis",
      agent_id: "retention-agent",
      capability_key: "retention.engagement.analyze",
    },
  ],
  integration_health: [
    {
      integration_id: "fake_manakids_admin_api",
      status: "healthy",
      checked_at: "2026-07-22T08:00:00Z",
      message: "Backend fixture ready",
      diagnostics: {},
    },
    {
      integration_id: "fake_firestore_activity",
      status: "healthy",
      checked_at: "2026-07-22T08:00:00Z",
      message: "Mobile fixture ready",
      diagnostics: {},
    },
  ],
  capability_kill_switches: { "retention.engagement.analyze": false },
};

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockAgentApi(
  onRequest?: (url: string, init?: RequestInit) => Promise<Response> | null,
): jest.MockedFunction<typeof fetch> {
  return jest.fn<typeof fetch>((input, init) => {
    const url = requestUrl(input);
    const custom = onRequest?.(url, init);
    if (custom) return custom;
    if (url.includes("configuration-schema"))
      return response({ properties: { currency: { type: "string" } } });
    if (url.includes("/agents/growth-agent") && !url.includes("/run"))
      return response(detail);
    if (url.includes("/agents/retention-agent") && !url.includes("/run"))
      return response(retentionDetail);
    if (url.endsWith("/agents"))
      return response({
        items: [agent, retentionAgent],
        total: 2,
        limit: 100,
        offset: 0,
      });
    if (url.includes("/runs") || url.includes("/reports"))
      return response({ items: [], total: 0, limit: 5, offset: 0 });
    return response({});
  });
}

describe("AgentsPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("exposes Retention engagement through the generic agent controls", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(mockAgentApi());
    renderWithSession(<AgentsPage />, "operator");
    fireEvent.click(
      await screen.findByRole("button", { name: /Retention & Loyalty Agent/ }),
    );

    expect(
      await screen.findByText("retention.engagement.analyze"),
    ).toBeInTheDocument();
    expect(screen.getByText("fake_manakids_admin_api")).toBeInTheDocument();
    expect(screen.getByText("fake_firestore_activity")).toBeInTheDocument();
  });

  it("disables configuration, schedule, status, and kill-switch controls for viewers", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(mockAgentApi());
    renderWithSession(<AgentsPage />, "viewer");
    fireEvent.click(
      await screen.findByRole("button", { name: /Growth & Conversion Agent/ }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Validate & activate version",
      }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Emergency stop agent" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Emergency stop capability" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Save schedule" }),
    ).toBeDisabled();
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
        return response({
          ...schedule,
          cron_expression: "15 * * * *",
          timezone: "Asia/Samarkand",
          enabled: false,
        });
      }
      return null;
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<AgentsPage />, "admin");
    fireEvent.click(
      await screen.findByRole("button", { name: /Growth & Conversion Agent/ }),
    );

    const editor = await screen.findByLabelText("Active JSON values");
    fireEvent.change(editor, { target: { value: "not-json" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Validate & activate version" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Unexpected token",
    );

    fireEvent.change(screen.getByLabelText("analysis cron expression"), {
      target: { value: "15 * * * *" },
    });
    fireEvent.change(screen.getByLabelText("analysis timezone"), {
      target: { value: "Asia/Samarkand" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Enabled" }));
    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/schedules/schedule-analysis"),
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "analysis schedule updated",
    );
  });

  it("requires confirmation before an admin changes the per-agent kill switch", async () => {
    const fetchMock = mockAgentApi((url, init) => {
      if (url.includes("/kill-switch/agents/growth-agent")) {
        expect(init?.method).toBe("PUT");
        return response({ enabled: true });
      }
      return null;
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<AgentsPage />, "admin");
    fireEvent.click(
      await screen.findByRole("button", { name: /Growth & Conversion Agent/ }),
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Emergency stop agent" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/kill-switch/agents/growth-agent"),
      expect.objectContaining({ method: "PUT" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm emergency stop" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/kill-switch/agents/growth-agent"),
        expect.objectContaining({ method: "PUT" }),
      ),
    );
  });
});
