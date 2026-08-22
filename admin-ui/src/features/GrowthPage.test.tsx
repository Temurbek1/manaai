import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { requestUrl } from "../test/http";
import { GrowthPage } from "./GrowthPage";

function response(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("GrowthPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("presents Growth as one agent and exposes the funnel evidence lifecycle", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input);
      if (url.endsWith("/agents/growth-agent")) {
        return response({
          agent: {
            agent_id: "growth-agent",
            display_name: "Growth & Conversion Agent",
            description: "Growth control plane",
            version: "1.0.0",
            status: "enabled",
            default_capability_key: "growth.advertising",
            capabilities: [
              {
                key: "growth.advertising",
                agent_id: "growth-agent",
                description: "Advertising intelligence",
                risk: "financial",
                minimum_role: "operator",
              },
              {
                key: "growth.funnel.analyze",
                agent_id: "growth-agent",
                description: "Deterministic funnel analysis",
                risk: "financial",
                minimum_role: "operator",
              },
            ],
            configuration_schema: {},
            registered_at: "2026-08-22T08:00:00Z",
          },
          configuration: null,
          configurations: [
            {
              configuration_id: "funnel-config",
              agent_id: "growth-agent",
              capability_key: "growth.funnel.analyze",
              version: 2,
              values: { experiment_mode: "sandbox" },
              created_at: "2026-08-22T08:00:00Z",
              created_by: "admin",
              active: true,
            },
          ],
          schedules: [
            {
              schedule_id: "growth-funnel-analysis",
              agent_id: "growth-agent",
              capability_key: "growth.funnel.analyze",
              job_type: "analysis",
              cron_expression: "0 4 * * *",
              timezone: "UTC",
              enabled: true,
            },
          ],
          integration_health: [],
          kill_switch_enabled: false,
          capability_kill_switches: {
            "growth.advertising": false,
            "growth.funnel.analyze": false,
          },
        });
      }
      if (
        url.includes("/runs?agent_id=growth-agent") &&
        url.includes("growth.funnel.analyze")
      ) {
        return response({
          items: [
            {
              run_id: "funnel-run-12345678",
              started_at: "2026-08-22T08:00:00Z",
              status: "waiting_approval",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }
      if (url.includes("/marketing/overview")) {
        return response({
          integration_health: {
            integration_id: "fake_meta",
            status: "healthy",
            checked_at: "2026-08-22T08:00:00Z",
            diagnostics: {},
          },
          last_synchronized_at: null,
          snapshot: null,
          breakdown_performance: [],
          configuration: null,
          schedules: [],
        });
      }
      if (url.includes("/findings") && url.includes("run_id=funnel-run")) {
        return response({
          items: [
            {
              finding_id: "finding-1",
              title: "Activation conversion is below threshold",
              deterministic_calculation: "activated / signed_up = 0.42",
              severity: "warning",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (
        url.includes("/recommendations") &&
        url.includes("run_id=funnel-run")
      ) {
        return response({
          items: [
            {
              recommendation_id: "recommendation-1",
              action_type: "create_experiment",
              reasoning: "Test one bounded onboarding variant.",
              confidence: "0.8",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (
        url.includes("/action-proposals") &&
        url.includes("run_id=funnel-run")
      ) {
        return response({
          items: [
            {
              proposal_id: "proposal-12345678",
              action_type: "create_experiment",
              status: "awaiting_approval",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (url.includes("/outcome-evaluations")) {
        return response({
          items: [
            {
              evaluation_id: "outcome-1",
              metric_name: "activation_rate",
              baseline_value: "0.42",
              status: "pending",
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }
      return response({ items: [], total: 0, limit: 100, offset: 0 });
    });

    renderWithSession(<GrowthPage />, "viewer");
    expect(
      await screen.findByRole("heading", { name: "Growth & Conversion" }),
    ).toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: /growth\.funnel\.analyze/ }),
    );

    expect(
      await screen.findByText("Activation conversion is below threshold"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("create_experiment")).toHaveLength(2);
    expect(screen.getByText("activation_rate")).toBeInTheDocument();
    expect(
      screen.getByText(/deterministic fake adapters/i),
    ).toBeInTheDocument();
  });
});
