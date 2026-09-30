import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { requestUrl } from "@/test/http";
import { ChatApprovals } from "./ChatApprovals";

const proposal = {
  proposal_id: "p1",
  agent_id: "growth-agent",
  provider: "fake_meta",
  provider_mode: "fake_executable",
  provider_object_id: "campaign-1",
  object_type: "campaign",
  action_type: "decrease_budget",
  parameters: {
    kind: "decrease_budget",
    current_daily_budget: "50",
    proposed_daily_budget: "40",
    currency: "USD",
  },
  current_state_hash: "state-1",
  status: "awaiting_approval",
  expires_at: "2099-01-01T00:00:00Z",
  reasoning: "Расходы выросли.",
  expected_effect: "Снижение затрат.",
  risks: ["Снижение охвата"],
  missing_data: [],
};

function setup(
  author = "another-admin",
  live = false,
): jest.Mock<typeof fetch> {
  const fetchMock = jest.fn<typeof fetch>((input, init) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          requestUrl(input).includes("action-proposals")
            ? { items: [{ ...proposal, execution_forbidden: live }] }
            : init?.method === "POST"
              ? { execution: { status: "dry_run" } }
              : { items: [{ proposal_id: "p1", requested_by: author }] },
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
  return fetchMock;
}

describe("ChatApprovals", () => {
  it("requires a reason and a separate confirmation before using the existing action lifecycle", async () => {
    const requests = setup();
    renderWithSession(<ChatApprovals />, "approver");
    const approve = await screen.findByRole("button", { name: "Одобрить" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина решения"), {
      target: { value: "Проверены объект и риски" },
    });
    fireEvent.click(approve);
    expect(
      requests.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить решение" }),
    );
    await waitFor(() =>
      expect(
        requests.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toHaveLength(1),
    );
    expect(await screen.findByText(/Решение принято/)).toBeInTheDocument();
  });

  it("blocks self-approval and makes live read-only recommendations explicit", async () => {
    setup("00000000-0000-4000-8000-000000000001", true);
    renderWithSession(<ChatApprovals />, "admin");
    expect(
      await screen.findByText(/изменения в Meta запрещены/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ознакомиться" })).toBeDisabled();
    expect(
      screen.getByText(/Решение должен принять другой сотрудник/),
    ).toBeInTheDocument();
  });
});
