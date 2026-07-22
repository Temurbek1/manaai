import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { MarketingPage } from "./MarketingPage";

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("MarketingPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders the provider snapshot and persisted nightly report", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url.includes("marketing/overview")) {
        return jsonResponse({
          integration_health: {
            integration_id: "fake_meta",
            status: "healthy",
            checked_at: "2026-07-22T12:00:00Z",
            message: "Sandbox ready",
            diagnostics: {},
          },
          last_synchronized_at: "2026-07-22T12:00:00Z",
          snapshot: {
            provider: "fake_meta",
            provider_mode: "fake_executable",
            schema_version: "1",
            collected_at: "2026-07-22T12:00:00Z",
            period_start: "2026-07-15T00:00:00Z",
            period_end: "2026-07-22T23:59:59Z",
            attribution_window: "7d_click",
            accounts: [
              {
                provider_id: "account-1",
                name: "Demo account",
                currency: "USD",
                timezone: "UTC",
                status: "ACTIVE",
              },
            ],
            campaigns: [
              {
                provider_id: "campaign-1",
                name: "Growth campaign",
                status: "ACTIVE",
                effective_status: "ACTIVE",
                daily_budget: "100",
                currency: "USD",
              },
            ],
            ad_sets: [],
            ads: [],
            creatives: [],
            audiences: [],
            available_targeting_attributes: {},
            insights: [],
            diagnostics: [],
            compatibility_matrix: [],
            data_quality_notes: [],
          },
          breakdown_performance: [],
          configuration: null,
          schedules: [],
        });
      }
      if (url.includes("/runs?")) {
        return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 });
      }
      if (url.includes("/reports?")) {
        return jsonResponse({
          items: [
            {
              report_id: "report-1",
              report_type: "nightly",
              human_readable: "Best creative today: Family Video. CPL: 0.80.",
              structured: {
                kpis: { spend: "120", leads: "30", ctr: "4.2", cpl: "0.80" },
              },
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        });
      }
      if (url.includes("/executions?")) {
        return jsonResponse({
          items: [
            {
              execution_id: "execution-stale",
              status: "failed",
              attempted_at: "2026-07-22T12:00:00Z",
              provider_request_id: null,
            },
            {
              execution_id: "execution-partial",
              status: "partially_applied",
              attempted_at: "2026-07-22T12:01:00Z",
              provider_request_id: "meta-1",
            },
            {
              execution_id: "execution-running",
              status: "executing",
              attempted_at: "2026-07-22T12:02:00Z",
              provider_request_id: "meta-2",
            },
          ],
          total: 3,
          limit: 100,
          offset: 0,
        });
      }
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<MarketingPage />);

    expect(await screen.findByText("Growth campaign")).toBeInTheDocument();
    expect(
      await screen.findByText(/Best creative today: Family Video/),
    ).toBeInTheDocument();
    expect(screen.getByText("nightly")).toBeInTheDocument();
    expect(await screen.findByText("partially applied")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("executing")).toBeInTheDocument();
  });
});
