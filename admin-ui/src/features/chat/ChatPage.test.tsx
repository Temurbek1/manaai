import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { ChatPage } from "./ChatPage";
import { renderWithSession as renderSession } from "@/test/render";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import type { ReactNode } from "react";
import { requestUrl } from "@/test/http";

const push = jest.fn();
function renderWithSession(
  ui: ReactNode,
  role: "admin" | "viewer" = "admin",
): ReturnType<typeof renderSession> {
  return renderSession(
    <AppRouterContext.Provider
      value={{
        back: () => {},
        forward: () => {},
        refresh: () => {},
        push: (href) => {
          push(href);
        },
        replace: () => {},
        prefetch: () => {},
        bfcacheId: "test",
      }}
    >
      {ui}
    </AppRouterContext.Provider>,
    role,
  );
}

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
const topic = {
  topic_id: "topic-1",
  agent_id: "growth-agent",
  product: "mana",
  title: "Моя тема",
  created_at: "2026-09-30T00:00:00Z",
  updated_at: "2026-09-30T00:00:00Z",
};
const turn = {
  turn_id: "turn-1",
  topic_id: "topic-1",
  request_id: "00000000-0000-4000-8000-000000000001",
  message: "Помоги",
  status: "completed",
  answer: "Нет подтверждённых данных.",
  sources: [],
  created_at: "2026-09-30T00:00:00Z",
};

describe("ChatPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    push.mockClear();
  });

  it.each(["chat", "goal"])(
    "sends manual model and reasoning choices in %s mode",
    async (mode) => {
      const posts: { url: string; body: Record<string, unknown> }[] = [];
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") {
          posts.push({ url, body: JSON.parse(String(init.body)) });
          return response({ goal_id: "goal-1" });
        }
        if (url.endsWith("/availability"))
          return response({
            enabled: true,
            model_selection_enabled: true,
            max_steps: 6,
            budget_microusd: 1000000,
          });
        if (url.includes("/goals/topics/")) return response([]);
        if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
        return response([]);
      });
      renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
      fireEvent.change(
        await screen.findByRole("combobox", { name: "Модель AI" }),
        {
          target: { value: "gpt-6-astra" },
        },
      );
      fireEvent.change(
        screen.getByRole("combobox", { name: "Глубина анализа" }),
        {
          target: { value: "high" },
        },
      );
      if (mode === "goal")
        fireEvent.click(screen.getByRole("button", { name: "Цель" }));
      fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
        target: { value: "Сравни географию заказов по областям" },
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: mode === "goal" ? "Поставить цель" : "Отправить сообщение",
        }),
      );
      await waitFor(() => expect(posts).toHaveLength(1));
      expect(posts[0]!.body).toMatchObject({
        model_choice: "gpt-6-astra",
        reasoning: "high",
      });
    },
  );

  it("creates a durable goal instead of a chat turn from the same composer", async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return response({ goal_id: "goal-1" });
      }
      if (url.includes("/goals/availability"))
        return response({
          enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        });
      if (url.endsWith("/availability")) return response({ enabled: true });
      if (url.includes("/goals/topics/")) return response([]);
      if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Цель" }));
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Проанализируй удержание пользователей MANA" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поставить цель" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toContain("/goals/topics/topic-1");
    expect(posts[0]!.body).toMatchObject({
      objective: "Проанализируй удержание пользователей MANA",
      max_steps: 6,
      budget_microusd: 500000,
    });
    expect(posts[0]!.body["request_id"]).toBeTruthy();
  });

  it("steers a saved goal through the only composer, without creating another goal or model turn", async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    const savedGoal = {
      goal_id: "goal-1",
      topic_id: "topic-1",
      agent_id: "growth-agent",
      product: "mana",
      status: "waiting",
      revision: 9,
      plan: [],
      events: [],
      evidence: [],
      request: {
        objective: "Сохранённая цель",
        max_steps: 6,
        budget_microusd: 500000,
      },
      created_at: "2026-10-08T00:00:00Z",
      updated_at: "2026-10-08T00:00:00Z",
      waiting_reason: "Уточните период",
      steps_used: 1,
      accounted_microusd: 1000,
    };
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return response(savedGoal);
      }
      if (url.includes("/goals/availability"))
        return response({
          enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        });
      if (url.endsWith("/availability")) return response({ enabled: true });
      if (url.includes("/goals/topics/")) return response([savedGoal]);
      if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    const input = await screen.findByLabelText("Уточнение цели");
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(
      screen.queryByText("Тема создана. Напишите первое сообщение."),
    ).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "7 дней" } });
    fireEvent.click(screen.getByRole("button", { name: "Уточнить цель" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toContain("/goals/goal-1/commands");
    expect(posts[0]!.body).toMatchObject({
      command: "steer",
      message: "7 дней",
      expected_revision: 9,
    });
  });

  it.each(["mana", "360rec"])(
    "offers the parent source only in MANA Retention topics (%s)",
    async (product) => {
      const fetchMock = jest.fn<typeof fetch>((input) => {
        const url = requestUrl(input);
        if (url.endsWith("/availability"))
          return response({ enabled: true, parent_summary_enabled: true });
        if (url.endsWith("/topic-1"))
          return response({
            topic: { ...topic, agent_id: "retention-agent", product },
            turns: [
              {
                ...turn,
                next_action: "mana_parents",
                read_confirmation: {
                  kind: "mana_parents",
                  product: "mana",
                  capability_key: "retention.parents.analyze",
                  confirmation_required: true,
                  admission_checks: [
                    "access",
                    "product_scope",
                    "cooldown",
                    "budget",
                  ],
                  minimum_interval_seconds: 86400,
                },
              },
            ],
          });
        return response([]);
      });
      jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
      renderWithSession(
        <ChatPage agentId="retention-agent" topicId="topic-1" />,
      );
      await screen.findByLabelText("Сообщение агенту");
      if (product === "mana") {
        await screen.findByRole("button", { name: "Подтвердить сбор данных" });
        expect(
          screen.getByRole("region", { name: "Предлагаемый следующий шаг" }),
        ).toHaveTextContent("Firebase не вызывается");
        expect(
          screen.getByRole("region", { name: "Предлагаемый следующий шаг" }),
        ).toHaveTextContent("не чаще раза в 24 часа");
        expect(
          fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
        ).toHaveLength(0);
      } else {
        expect(
          screen.queryByRole("button", { name: "Подтвердить сбор данных" }),
        ).not.toBeInTheDocument();
      }
    },
  );

  it("creates a product-specific topic and sends exactly one explicit message", async () => {
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("/availability")) return response({ enabled: true });
      if (url.endsWith("/topics") && init?.method === "POST")
        return response(topic, 201);
      if (url.endsWith("/messages")) return response(turn);
      if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
      return response([]);
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" />);
    fireEvent.change(screen.getByLabelText("Приложение"), {
      target: { value: "360rec" },
    });
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Разбери конверсию" },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Отправить сообщение" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/chat/growth-agent/topic/topic-1"),
    );
    const posts = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[0]?.[1]?.body as string)).toMatchObject({
      product: "360rec",
      agent_id: "growth-agent",
      title: "Разбери конверсию",
    });
    expect(JSON.parse(posts[1]?.[1]?.body as string)).toMatchObject({
      message: "Разбери конверсию",
      request_id: expect.any(String),
    });
  });

  it("restores history, keeps untrusted text inert and never posts on opening a topic", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) =>
      requestUrl(input).endsWith("/availability")
        ? response({ enabled: true })
        : response({
            topic,
            turns: [
              {
                ...turn,
                answer: "<img src=x onerror=alert(1)>",
                next_action: "analyze",
              },
            ],
          }),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(
      <ChatPage agentId="growth-agent" topicId="topic-1" />,
      "viewer",
    );
    expect(
      await screen.findByText("<img src=x onerror=alert(1)>"),
    ).toBeInTheDocument();
    expect(document.querySelector(".agent-message img")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    ).toBeDisabled();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });

  it("shows budget-fallback source warnings even when the model turn failed", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) =>
      requestUrl(input).endsWith("/availability")
        ? response({ enabled: true })
        : response({
            topic,
            turns: [
              {
                ...turn,
                status: "failed",
                answer: "Лимит AI исчерпан. Последняя сохранённая сводка.",
                sources: [
                  {
                    report_id: "historical",
                    run_id: "saved-run",
                    title: "Engagement",
                    created_at: "2026-10-08T03:00:00Z",
                    collected_at: "2026-10-07T00:00:00Z",
                    fresh_until: "2026-10-07T06:00:00Z",
                    refresh_status: "stale",
                    scope_verified: true,
                    product: "mana",
                  },
                ],
              },
            ],
          }),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    expect(await screen.findByRole("note")).toHaveTextContent(
      "устаревшие данные",
    );
    expect(screen.getByRole("note")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Подтвердить сбор данных" }),
    ).toBeNull();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });

  it("shows planned status without an executable action for Technical Reliability", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response({ enabled: false }));
    renderWithSession(<ChatPage agentId="technical-agent" />);
    expect(screen.getByText("Только планирование")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Новый анализ" })).toBeNull();
    expect(
      await screen.findByText(/AI временно недоступен/),
    ).toBeInTheDocument();
  });

  it("does not erase a draft on a network failure and requires explicit analysis confirmation", async () => {
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      if (requestUrl(input).endsWith("/availability"))
        return response({ enabled: true });
      if (init?.method === "POST")
        return response({ detail: "Временная ошибка" }, 503);
      return response({ topic, turns: [{ ...turn, next_action: "analyze" }] });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    await screen.findByText("Нет подтверждённых данных.");
    expect(
      screen.getByRole("region", { name: "Предлагаемый следующий шаг" }),
    ).toHaveTextContent("НЕ фильтрует источники");
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Важный черновик" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Временная ошибка",
    );
    expect(screen.getByLabelText("Сообщение агенту")).toHaveValue(
      "Важный черновик",
    );
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1);
  });

  it("starts with one send button, no setup form or automatic source calls", async () => {
    const fetchMock = jest.fn<typeof fetch>(() => response({ enabled: true }));
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" />);
    await waitFor(() =>
      expect(
        screen.queryByText("Проверяем доступность AI…"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByLabelText(/Название темы/)).not.toBeInTheDocument();
    expect(
      document.querySelector(".chat-starters, .chat-tools-links"),
    ).toBeNull();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });

  it("remembers the product for a new topic but never overrides an existing topic", async () => {
    sessionStorage.setItem(
      "mana:chat-product:00000000-0000-4000-8000-000000000001",
      "360rec",
    );
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation((input) =>
        requestUrl(input).endsWith("/availability")
          ? response({ enabled: true })
          : response({ topic, turns: [] }),
      );
    const first = renderWithSession(<ChatPage agentId="growth-agent" />);
    expect(screen.getByLabelText("Приложение")).toHaveValue("360rec");
    first.unmount();
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    await screen.findByText("Моя тема");
    expect(screen.getByLabelText("Приложение: MANA")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("hides old proposals and folds technical details into one disclosure", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) =>
      requestUrl(input).endsWith("/availability")
        ? response({ enabled: true })
        : response({
            topic,
            turns: [
              { ...turn, next_action: "analyze", plan: ["Проверить отчёт"] },
              {
                ...turn,
                turn_id: "turn-2",
                request_id: "00000000-0000-4000-8000-000000000002",
                next_action: "none",
              },
            ],
          }),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    await screen.findByText("Моя тема");
    expect(
      screen.queryByRole("button", { name: "Подтвердить сбор данных" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Скопировать ответ" })[0],
    ).not.toBeVisible();
    const details = document.querySelector(
      ".chat-message-details",
    ) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    fireEvent.click(details.querySelector("summary")!);
    expect(
      screen.getAllByRole("button", { name: "Скопировать ответ" })[0],
    ).toBeVisible();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });
});
