import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { requestUrl } from "@/test/http";
import { GoalWorkspace, type Goal } from "./GoalWorkspace";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const fixture: Goal = {
  goal_id: "goal-1",
  topic_id: "topic-1",
  agent_id: "operations-orchestrator",
  product: "mana",
  request: {
    request_id: "00000000-0000-4000-8000-000000000001",
    objective: "Проанализируй удержание пользователей",
    success_criteria: "Проверенный отчёт",
    constraints: "Без изменений",
    max_steps: 6,
    budget_microusd: 500000,
    model_choice: "auto",
    reasoning: "auto",
  },
  status: "waiting",
  phase: "investigate",
  revision: 3,
  created_at: "2026-10-08T00:00:00Z",
  updated_at: "2026-10-08T00:00:00Z",
  steps_used: 2,
  accounted_microusd: 12000,
  plan: [{ title: "Проверить удержание", status: "blocked" }],
  events: [
    {
      at: "2026-10-08T00:00:00Z",
      kind: "progress",
      message: "Проверил доступные данные",
    },
  ],
  evidence: [],
  result: "Частичный отчёт. Платежи не подтверждены.",
  waiting_reason: "Нужны данные об оплатах",
  requested_capability: null,
  approved_capability: null,
  read_attempted: false,
  lease_until: null,
};

describe("GoalWorkspace", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it("shows durable plan and partial work, preserves constraints and resumes with version fencing", async () => {
    const posts: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return response({ ...fixture, status: "queued", revision: 4 });
      }
      return response([fixture]);
    });
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    expect(
      await screen.findByText("Нужны данные об оплатах"),
    ).toBeInTheDocument();
    expect(screen.getByText("Проверить удержание")).toBeInTheDocument();
    expect(screen.getByText(fixture.result!)).toBeInTheDocument();
    expect(
      screen.queryByText("Разрешить чтение данных"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Продолжить" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      command: "resume",
      expected_revision: 3,
      message: "",
    });
    expect(posts[0]!["request_id"]).toBeTruthy();
  });

  it("steering is an explicit command, never a provider write", async () => {
    const posts: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        expect(requestUrl(input)).toContain("/goals/goal-1/commands");
        return response(fixture);
      }
      return response([fixture]);
    });
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    const input = await screen.findByRole("textbox", {
      name: "Уточнение цели",
    });
    fireEvent.change(input, {
      target: { value: "Не объединяй родителей с детьми" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    await waitFor(() =>
      expect(posts[0]).toMatchObject({
        command: "steer",
        message: "Не объединяй родителей с детьми",
      }),
    );
  });

  it("requires separate read consent and exposes admission conditions without opening details", async () => {
    const posts: object[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return response(fixture);
      }
      return response([
        { ...fixture, requested_capability: "retention.engagement.analyze" },
      ]);
    });
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    const button = await screen.findByRole("button", {
      name: "Разрешить чтение данных",
    });
    expect(posts).toHaveLength(0);
    expect(
      screen.getByText(/привязка приложения, интервал 6 ч и общий бюджет/),
    ).toBeVisible();
    fireEvent.click(button);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      command: "approve_read",
      expected_revision: 3,
    });
  });

  it.each(["viewer", "admin"] as const)(
    "a completed goal is read-only for %s",
    async (role) => {
      jest
        .spyOn(globalThis, "fetch")
        .mockImplementation(() =>
          response([{ ...fixture, status: "completed" }]),
        );
      renderWithSession(<GoalWorkspace topicId="topic-1" />, role);
      expect(await screen.findByText("Анализ готов")).toBeInTheDocument();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Продолжить" }),
      ).not.toBeInTheDocument();
    },
  );

  it("blocks steering while a paused provider call is still ending", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        response([
          { ...fixture, status: "paused", lease_until: "2099-10-08T00:00:00Z" },
        ]),
      );
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    expect(
      await screen.findByText("Заканчивается текущий запрос…"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Продолжить" })).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("does not fabricate a workspace for an older backend", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(() => response([]));
    const { container } = renderWithSession(
      <GoalWorkspace topicId="topic-1" />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container.querySelector(".goal-workspace")).toBeNull();
  });
});
