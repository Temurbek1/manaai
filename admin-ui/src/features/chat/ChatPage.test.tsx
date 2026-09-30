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
            turns: [{ ...turn, answer: "<img src=x onerror=alert(1)>" }],
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
    expect(screen.getByRole("button", { name: "Новый анализ" })).toBeDisabled();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });

  it("shows planned status without an executable action for Technical Reliability", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response({ enabled: false }));
    renderWithSession(<ChatPage agentId="technical-agent" />);
    expect(
      screen.getByText(/Выполнение задач этим агентом ещё не подключено/),
    ).toBeInTheDocument();
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
      return response({ topic, turns: [turn] });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    await screen.findByText("Нет подтверждённых данных.");
    fireEvent.click(screen.getByRole("button", { name: "Новый анализ" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "НЕ фильтрует источники",
    );
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
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
});
