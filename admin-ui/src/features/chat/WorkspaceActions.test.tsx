import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { WorkspaceActions } from "./WorkspaceActions";

const action = {
  proposal_id: "p1",
  product: "mana",
  synthetic: true,
  provider: "fake_experiments",
  status: "awaiting_approval",
  self_approval_forbidden: false,
  fingerprint: "a".repeat(64),
  expires_at: "2099-01-01T00:00:00Z",
  reasoning: "Проверить первый экран",
  expected_effect: "Улучшить активацию",
  risks: ["Недостаточная выборка"],
  parameters: {
    kind: "create_experiment",
    experiment_key: "welcome_test",
    hypothesis: "Упростить первый шаг",
    primary_metric: "activation_rate",
    audience_segment: "parents",
    allocation_percent: 10,
    duration_days: 14,
    proposed_status: "DRAFT",
  },
};

function setup({ lost = false, self = false, receipt = false } = {}): jest.Mock<
  typeof fetch
> {
  let decided = receipt;
  const fetchMock = jest.fn<typeof fetch>((_input, init) => {
    if (init?.method === "POST") {
      decided = true;
      if (lost) return Promise.reject(new Error("Response lost"));
    }
    const item = {
      ...action,
      self_approval_forbidden: self,
      ...(decided
        ? {
            status: "succeeded",
            execution_status: "succeeded",
            verification_status: "verified",
            receipt: { state: "resolved", message: "Решение обработано." },
          }
        : {}),
    };
    return Promise.resolve(
      new Response(
        JSON.stringify(init?.method === "POST" ? item : { items: [item] }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
  });
  jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
  return fetchMock;
}

describe("Scoped workspace actions", () => {
  it("confirms immutable sandbox parameters and persists the outcome with only one POST", async () => {
    const requests = setup();
    renderWithSession(
      <WorkspaceActions topicId="topic" turnId="turn" />,
      "approver",
    );
    const create = await screen.findByRole("button", {
      name: "Создать в sandbox",
    });
    expect(create).toBeDisabled();
    expect(
      screen.getByText(/Реальные пользователи и платежи не меняются/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Причина решения"), {
      target: { value: "Проверено" },
    });
    fireEvent.click(create);
    expect(
      requests.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(false);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить создание" }),
    );
    expect(await screen.findByText("Решение обработано.")).toBeInTheDocument();
    const posts = requests.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(String(posts[0]?.[0])).toContain(
      "/workspace/topics/topic/messages/turn/actions/p1/decision",
    );
    expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual(
      expect.objectContaining({
        fingerprint: "a".repeat(64),
        confirmed: true,
        approve: true,
        reason: "Проверено",
      }),
    );
    expect(
      screen.getByText("Влияние на конверсию не измерено."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Создать в sandbox" }),
    ).not.toBeInTheDocument();
  });

  it("observes a lost response through GET without resending the decision", async () => {
    const requests = setup({ lost: true });
    renderWithSession(
      <WorkspaceActions topicId="topic" turnId="turn" />,
      "admin",
    );
    await screen.findByLabelText("Причина решения");
    fireEvent.change(screen.getByLabelText("Причина решения"), {
      target: { value: "Проверено" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать в sandbox" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить создание" }),
    );
    expect(await screen.findByText("Решение обработано.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить статус" }));
    await waitFor(() =>
      expect(
        requests.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toHaveLength(1),
    );
  });

  it("blocks self-approval and viewer mutations", async () => {
    setup({ self: true });
    renderWithSession(
      <WorkspaceActions topicId="topic" turnId="turn" />,
      "viewer",
    );
    expect(
      await screen.findByText("Решение должен принять другой сотрудник."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Создать в sandbox" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Отклонить" })).toBeDisabled();
  });

  it("restores closed receipts without offering another write", async () => {
    const requests = setup({ receipt: true });
    renderWithSession(
      <WorkspaceActions topicId="topic" turnId="turn" />,
      "admin",
    );
    expect(await screen.findByText("Решение обработано.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Создать в sandbox" }),
    ).not.toBeInTheDocument();
    expect(
      requests.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });
});
