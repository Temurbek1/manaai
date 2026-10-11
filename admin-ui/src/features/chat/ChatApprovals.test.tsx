import { screen } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { ChatApprovals } from "./ChatApprovals";

describe("Historical chat approvals", () => {
  it("cannot approve unverified product proposals even as an administrator", async () => {
    const fetchMock = jest.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            items: [
              {
                proposal_id: "p1",
                agent_id: "growth-agent",
                action_type: "decrease_budget",
                status: "awaiting_approval",
                reasoning: "Расходы выросли",
                execution_forbidden: true,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatApprovals />, "admin");
    expect(await screen.findByText("Расходы выросли")).toBeInTheDocument();
    expect(
      screen.getByText(/Согласование в этом чате недоступно/),
    ).toBeInTheDocument();
    expect(screen.getByText(/изменения в Meta запрещены/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Одобрить|Отклонить/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Профессиональная очередь/ }),
    ).toHaveAttribute("href", "/approvals");
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });
});
