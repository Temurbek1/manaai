import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { requestUrl } from "../test/http";
import { RunsPage } from "./RunsPage";

const run = {
  run_id: "run-0000000000000001",
  agent_id: "marketing-agent",
  correlation_id: "correlation-1",
  trigger: "user",
  initiated_by: "operator",
  status: "failed",
  current_stage: "verify",
  configuration_version: 1,
  idempotency_key: "run-once",
  started_at: "2026-07-22T08:00:00Z",
  updated_at: "2026-07-22T08:01:00Z",
  completed_at: "2026-07-22T08:01:00Z",
  error_code: "verification_mismatch",
  error_message: "Provider applied a different value",
  retry_count: 1,
};

function response(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("RunsPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("filters, paginates, renders failures, and redacts untrusted timeline details", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.endsWith("/runs/run-0000000000000001")) {
        return response({
          run,
          timeline: [
            {
              event_id: "event-1",
              event_type: "action_verified",
              agent_id: "marketing-agent",
              run_id: run.run_id,
              actor_id: "worker",
              actor_role: "admin",
              summary: "Verification failed <script>alert(1)</script>",
              details: {
                access_token: "EAA_REAL_LOOKING_SECRET_123456789",
                message: "Bearer test-secret-token-value",
                provider_html: "<script>alert(1)</script>",
              },
              correlation_id: "correlation-1",
              occurred_at: "2026-07-22T08:01:00Z",
            },
          ],
          snapshots: [],
          findings: [],
          recommendations: [],
          proposals: [],
        });
      }
      return response({
        items: [run],
        total: 21,
        limit: 20,
        offset: url.includes("offset=20") ? 20 : 0,
      });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    const rendered = renderWithSession(<RunsPage />, "viewer");

    expect(
      screen.queryByText("Provider applied a different value"),
    ).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /run-0000/ }));
    await waitFor(() =>
      expect(rendered.container).toHaveTextContent(
        "Provider applied a different value",
      ),
    );
    expect(await screen.findByText(/Verification failed/)).toBeInTheDocument();
    expect(rendered.container.querySelector("script")).toBeNull();
    expect(rendered.container).not.toHaveTextContent("EAA_REAL_LOOKING_SECRET");
    expect(rendered.container).not.toHaveTextContent("test-secret-token-value");
    expect(rendered.container).toHaveTextContent("[REDACTED]");

    fireEvent.change(screen.getByLabelText("Filter runs by status"), {
      target: { value: "failed" },
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("status=failed"),
        expect.anything(),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("offset=20"),
        expect.anything(),
      ),
    );
  });
});
