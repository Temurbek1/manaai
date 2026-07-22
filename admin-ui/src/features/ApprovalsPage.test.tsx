import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { requestUrl } from "../test/http";
import { ApprovalsPage } from "./ApprovalsPage";

const proposal = {
  proposal_id: "proposal-1",
  run_id: "run-1",
  recommendation_id: "recommendation-1",
  provider: "fake-meta",
  provider_object_id: "campaign-1",
  object_type: "campaign",
  action_type: "decrease_budget",
  parameters: { action_type: "decrease_budget", new_daily_budget: "45.00" },
  expected_state_hash: "state-hash",
  evidence: [],
  reasoning: "Efficiency deteriorated.",
  risks: ["Delivery can decrease."],
  confidence: "0.91",
  policy_decision: "requires_approval",
  policy_reasons: ["Budget writes require approval."],
  status: "awaiting_approval",
  created_at: "2026-07-22T08:00:00Z",
  expires_at: "2026-07-23T08:00:00Z",
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApprovalsPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("requires a reason and sends an approval decision", async () => {
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({ items: [proposal], total: 1, limit: 100, offset: 0 }),
        );
      }
      if (url.includes("approvals?")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                approval_id: "approval-1",
                proposal_id: "proposal-1",
                requested_at: "2026-07-22T08:00:00Z",
                expires_at: "2026-07-23T08:00:00Z",
                requested_by: "marketing-agent",
                required_role: "approver",
                status: "pending",
              },
            ],
            total: 1,
            limit: 100,
            offset: 0,
          }),
        );
      }
      if (url.includes("/decision")) {
        expect(init?.method).toBe("POST");
        const requestBody = typeof init?.body === "string" ? init.body : "{}";
        expect(JSON.parse(requestBody) as unknown).toMatchObject({
          approve: true,
          reason: "Evidence reviewed by operator",
        });
        return Promise.resolve(
          jsonResponse({
            proposal,
            approval: null,
            execution: { status: "succeeded" },
          }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<ApprovalsPage />, "approver");

    const approve = await screen.findByRole("button", { name: "Approve" });
    fireEvent.click(approve);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Add a decision reason",
    );

    fireEvent.change(screen.getByLabelText("Decision reason"), {
      target: { value: "Evidence reviewed by operator" },
    });
    fireEvent.click(approve);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/decision"),
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("renders expired proposals and disables every decision control for viewers", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({
            items: [{ ...proposal, status: "expired" }],
            total: 1,
            limit: 100,
            offset: 0,
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
      );
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<ApprovalsPage />, "viewer");

    expect(await screen.findByText("expired")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByLabelText("Decision reason")).toBeDisabled();
  });

  it("keeps approval controls unavailable to operators", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({ items: [proposal], total: 1, limit: 100, offset: 0 }),
        );
      }
      return Promise.resolve(
        jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
      );
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<ApprovalsPage />, "operator");

    expect(
      await screen.findByRole("button", { name: "Approve" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("prevents self-approval before a mutation reaches the API", async () => {
    const ownApproval = {
      approval_id: "approval-self",
      proposal_id: proposal.proposal_id,
      requested_at: "2026-07-22T08:00:00Z",
      expires_at: proposal.expires_at,
      requested_by: "test-approver",
      required_role: "approver",
      status: "pending",
    };
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({ items: [proposal], total: 1, limit: 100, offset: 0 }),
        );
      }
      return Promise.resolve(
        jsonResponse({ items: [ownApproval], total: 1, limit: 100, offset: 0 }),
      );
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<ApprovalsPage />, "approver");

    expect(
      await screen.findByText(/Self-approval is not permitted/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByLabelText("Decision reason")).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/decision"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("submits a rejection and surfaces failed API mutations", async () => {
    let failDecision = false;
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({ items: [proposal], total: 1, limit: 100, offset: 0 }),
        );
      }
      if (url.includes("approvals?")) {
        return Promise.resolve(
          jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
        );
      }
      if (url.includes("/decision")) {
        const body = JSON.parse(
          typeof init?.body === "string" ? init.body : "{}",
        ) as Record<string, unknown>;
        expect(body.approve).toBe(false);
        if (failDecision) {
          return Promise.resolve(
            new Response(JSON.stringify({ detail: "Proposal became stale" }), {
              status: 409,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({
            proposal: { ...proposal, status: "rejected" },
            approval: null,
            execution: null,
          }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ApprovalsPage />, "approver");

    fireEvent.change(await screen.findByLabelText("Decision reason"), {
      target: { value: "Risk outweighs expected improvement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Proposal rejected",
    );

    failDecision = true;
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Proposal became stale",
    );
  });

  it("renders live proposals as advisory acknowledgements without execution controls", async () => {
    const liveProposal = {
      ...proposal,
      provider: "meta",
      provider_mode: "live_read_only",
      execution_forbidden: true,
      manual_action_instructions: [
        "Review the recommendation manually in Ads Manager.",
      ],
    };
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("action-proposals")) {
        return Promise.resolve(
          jsonResponse({
            items: [liveProposal],
            total: 1,
            limit: 100,
            offset: 0,
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
      );
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);

    renderWithSession(<ApprovalsPage />, "approver");

    expect(
      await screen.findByText("LIVE META — READ-ONLY ADVISORY"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Acknowledge advisory" }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("Select decrease_budget proposal"),
    ).toBeDisabled();
  });
});
