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
            turns: [{ ...turn, next_action: "mana_parents" }],
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
