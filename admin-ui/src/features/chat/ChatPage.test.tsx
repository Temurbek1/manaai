import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { ChatPage } from "./ChatPage";
import { renderWithSession as renderSession } from "@/test/render";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { useState, type ReactNode } from "react";
import { requestUrl } from "@/test/http";
import {
  LANGUAGE_STORAGE_KEY,
  LanguageProvider,
} from "@/i18n/LanguageProvider";

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

  it.each([
    [false, false],
    [true, false],
    [true, true],
  ])(
    "observes and stops a pending contact continuation without waiting for POST (paged=%s, goal=%s)",
    async (paged, withGoal) => {
      const contactTopic = { ...topic, agent_id: "retention-agent" };
      const origin = {
        ...turn,
        execution_mode: "agent",
        next_action: "retention_contacts",
      };
      let claimed = false;
      let stopped = false;
      let finish: (() => void) | undefined;
      let continuationFinished = false;
      const posts: string[] = [];
      function NavigateWhilePending(): React.JSX.Element {
        const [opened, setOpened] = useState("topic-1");
        return (
          <>
            <button onClick={() => setOpened("topic-2")}>Другой чат</button>
            <ChatPage agentId="retention-agent" topicId={opened} />
          </>
        );
      }
      const child = () => ({
        ...turn,
        turn_id: "child-1",
        request_id: "00000000-0000-4000-8000-000000000002",
        message: "Продолжи после сохранённого результата",
        status: stopped ? "cancelled" : "thinking",
        answer: stopped ? "Ответ остановлен." : "",
        execution_mode: "agent",
        next_action: "none",
      });
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") {
          posts.push(url);
          if (url.endsWith("/continue")) {
            claimed = true;
            return new Promise<Response>((resolve) => {
              finish = () => {
                continuationFinished = true;
                resolve(
                  new Response(JSON.stringify(child()), {
                    headers: { "Content-Type": "application/json" },
                  }),
                );
              };
            });
          }
          if (url.endsWith("/messages/child-1/stop")) {
            stopped = true;
            return response(child());
          }
          return response({}, 500);
        }
        if (url.endsWith("/chat/availability"))
          return response({
            enabled: true,
            agent_workspace_enabled: true,
            transcript_pagination_enabled: paged,
            retention_contact_reviews_enabled: true,
          });
        if (url.endsWith("/goals/availability"))
          return response({
            enabled: true,
            agent_workspace_enabled: true,
            budget_microusd: 500000,
            max_steps: 6,
          });
        if (url.endsWith("/goals/topics/topic-1"))
          return response(
            withGoal
              ? [
                  {
                    goal_id: "goal-1",
                    status: "running",
                    revision: 9,
                    lease_until: "2099-01-01T00:00:00Z",
                    request: {
                      objective: "Проанализировать удержание",
                      max_steps: 6,
                      budget_microusd: 500000,
                    },
                    plan: [],
                    events: [],
                    evidence: [],
                    result: "",
                    waiting_reason: "",
                    steps_used: 1,
                    accounted_microusd: 10000,
                  },
                ]
              : [],
          );
        if (
          url.endsWith("/chat/topics/topic-2") ||
          url.endsWith("/topics/topic-2/messages?limit=20")
        )
          return response({
            topic: { ...contactTopic, topic_id: "topic-2" },
            turns: [],
            has_more: false,
            next_cursor: null,
          });
        if (url.endsWith("/retention-contacts"))
          return response({
            items: [
              {
                action_id: "action-1",
                topic_id: "topic-1",
                turn_id: "turn-1",
                recipient: "sample_ru",
                product: "mana",
                synthetic: true,
                provider: "fake_retention_contact",
                message: {
                  template: "onboarding_help",
                  version: "retention-contact-ru-v1",
                  language: "ru",
                  text: "Exact fictional approved text",
                  sha256: "a".repeat(64),
                },
                fingerprint: "b".repeat(64),
                status: "verified",
                revision: 1,
                result_code: "fake_accepted",
                policy_reasons: [],
                decision_recorded: true,
                business_outcome: "not_measured",
              },
            ],
            recipients: [],
            more_omitted: false,
            continuation_available: !claimed,
            continuation: claimed ? child() : null,
          });
        if (
          url.endsWith("/chat/topics/topic-1") ||
          url.endsWith("/messages?limit=20")
        )
          return response({
            topic: contactTopic,
            turns: claimed ? [origin, child()] : [origin],
            has_more: false,
            next_cursor: null,
          });
        return response([]);
      });
      renderWithSession(<NavigateWhilePending />);
      fireEvent.click(
        await screen.findByRole("button", { name: "Продолжить с агентом" }),
      );
      try {
        const stop = await screen.findByRole(
          "button",
          { name: "Остановить ответ" },
          { timeout: 4500 },
        );
        expect(continuationFinished).toBe(false);
        expect(
          screen.getByRole("textbox", {
            name: withGoal ? "Уточнение цели" : "Сообщение агенту",
          }),
        ).toBeDisabled();
        expect(posts.filter((url) => url.endsWith("/continue"))).toHaveLength(
          1,
        );
        fireEvent.click(stop);
        expect(await screen.findByText("Ответ остановлен.")).toBeVisible();
        expect(posts.filter((url) => url.endsWith("/stop"))).toEqual([
          "/api/v1/admin/operation/chat/topics/topic-1/messages/child-1/stop",
        ]);
        expect(continuationFinished).toBe(false);
        fireEvent.click(screen.getByRole("button", { name: "Другой чат" }));
        await waitFor(() =>
          expect(
            screen.getByRole("textbox", { name: "Сообщение агенту" }),
          ).not.toBeDisabled(),
        );
      } finally {
        await act(async () => finish?.());
      }
      expect(screen.queryByText("Ответ остановлен.")).not.toBeInTheDocument();
      expect(
        posts.filter(
          (url) => !url.endsWith("/continue") && !url.endsWith("/stop"),
        ),
      ).toEqual([]);
    },
  );

  it("can stop an ordinary admitted answer while its send POST is still pending", async () => {
    let admitted = false;
    let stopped = false;
    let finish: (() => void) | undefined;
    const posts: string[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push(url);
        if (url.endsWith("/messages/turn-1/stop")) {
          stopped = true;
          return response({
            ...turn,
            status: "cancelled",
            answer: "Ответ остановлен.",
          });
        }
        if (url.endsWith("/messages")) {
          admitted = true;
          return new Promise<Response>((resolve) => {
            finish = () =>
              resolve(
                new Response(JSON.stringify(turn), {
                  headers: { "Content-Type": "application/json" },
                }),
              );
          });
        }
      }
      if (url.endsWith("/chat/availability"))
        return response({ enabled: true });
      if (url.endsWith("/chat/topics/topic-1"))
        return response({
          topic,
          turns: admitted
            ? [
                {
                  ...turn,
                  status: stopped ? "cancelled" : "thinking",
                  answer: stopped ? "Ответ остановлен." : "",
                },
              ]
            : [],
        });
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    const input = await screen.findByRole("textbox", {
      name: "Сообщение агенту",
    });
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.change(input, { target: { value: "Помоги" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    try {
      const stop = await screen.findByRole(
        "button",
        { name: "Остановить ответ" },
        { timeout: 4500 },
      );
      expect(stop).not.toBeDisabled();
      fireEvent.click(stop);
      expect(await screen.findByText("Ответ остановлен.")).toBeVisible();
    } finally {
      await act(async () => finish?.());
    }
    expect(posts.filter((url) => url.endsWith("/messages"))).toHaveLength(1);
    expect(posts.filter((url) => url.endsWith("/stop"))).toHaveLength(1);
    expect(screen.queryByText(turn.answer)).not.toBeInTheDocument();
  });

  it("refreshes a newly created topic after one fast native reply, not another generation", async () => {
    let done = false;
    let finish: (() => void) | undefined;
    let pageReads = 0;
    let generations = 0;
    const posted: string[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posted.push(url);
        if (url.endsWith("/chat/topics")) return response(topic);
        if (url.endsWith("/messages")) {
          generations += 1;
          return new Promise<Response>((resolve) => {
            finish = () => {
              done = true;
              resolve(
                new Response(
                  JSON.stringify({
                    turn: { ...turn, answer: "Fast verified reply" },
                    goal: null,
                  }),
                  { headers: { "Content-Type": "application/json" } },
                ),
              );
            };
          });
        }
      }
      if (url.endsWith("/chat/availability"))
        return response({
          enabled: true,
          agent_workspace_enabled: true,
          transcript_pagination_enabled: true,
        });
      if (url.endsWith("/goals/availability"))
        return response({
          enabled: true,
          agent_workspace_enabled: true,
          max_steps: 6,
          budget_microusd: 500000,
        });
      if (url.endsWith("/messages?limit=20")) {
        pageReads += 1;
        return response({
          topic,
          turns: done ? [{ ...turn, answer: "Fast verified reply" }] : [],
          has_more: false,
          next_cursor: null,
        });
      }
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" />);
    const input = await screen.findByRole("textbox", {
      name: "Сообщение агенту",
    });
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.change(input, { target: { value: "Hello native agent" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() => {
      expect(generations).toBe(1);
      expect(pageReads).toBeGreaterThan(0);
      expect(finish).toBeDefined();
    });
    await act(async () => {
      finish!();
    });
    expect(await screen.findByText("Fast verified reply")).toBeVisible();
    expect(generations).toBe(1);
    expect(pageReads).toBeGreaterThan(1);
    expect(posted.filter((url) => url.includes("/goals/"))).toEqual([]);
  });

  it("never silently submits Russian when an older server cannot honor Uzbek", async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "uz");
    sessionStorage.setItem(
      "mana:chat-draft:00000000-0000-4000-8000-000000000001:topic-1",
      "Asl vazifa saqlansin",
    );
    const posts: string[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") posts.push(url);
      if (url.endsWith("/chat/availability"))
        return response({ enabled: true });
      if (url.endsWith("/chat/topics/topic-1"))
        return response({ topic, turns: [] });
      return response([]);
    });
    try {
      renderWithSession(
        <LanguageProvider>
          <ChatPage agentId="growth-agent" topicId="topic-1" />
        </LanguageProvider>,
      );
      expect(
        await screen.findByText(
          "Tanlangan javob tili serverda hali mavjud emas. Qoralama saqlandi.",
        ),
      ).toBeVisible();
      expect(
        screen.getByRole("textbox", { name: "Agentga xabar" }),
      ).toHaveValue("Asl vazifa saqlansin");
      const send = screen.getByRole("button", { name: "Xabar yuborish" });
      expect(send).toBeDisabled();
      fireEvent.click(send);
      expect(posts).toEqual([]);
    } finally {
      localStorage.clear();
    }
  });

  it.each(["chat", "goal"] as const)(
    "submits the selected Uzbek %s language without replacing the objective",
    async (mode) => {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, "uz");
      const submitted: Array<{ url: string; body: Record<string, unknown> }> =
        [];
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") {
          submitted.push({
            url,
            body: JSON.parse(String(init.body)) as Record<string, unknown>,
          });
          return response({});
        }
        if (url.endsWith("/chat/availability"))
          return response({ enabled: true, response_languages: ["ru", "uz"] });
        if (url.endsWith("/goals/availability"))
          return response({
            enabled: true,
            max_steps: 6,
            budget_microusd: 500000,
            response_languages: ["ru", "uz"],
          });
        if (url.endsWith("/chat/topics/topic-1"))
          return response({ topic, turns: [] });
        return response([]);
      });
      try {
        renderWithSession(
          <LanguageProvider>
            <ChatPage agentId="growth-agent" topicId="topic-1" />
          </LanguageProvider>,
        );
        await waitFor(() =>
          expect(
            screen.getByRole("button", { name: "Chat" }),
          ).not.toBeDisabled(),
        );
        fireEvent.click(
          screen.getByRole("button", {
            name: mode === "goal" ? "Maqsad" : "Chat",
          }),
        );
        const objective = "MANA mijozlarini saqlashni tahlil qil.";
        fireEvent.change(
          screen.getByRole("textbox", { name: "Agentga xabar" }),
          { target: { value: objective } },
        );
        fireEvent.click(
          screen.getByRole("button", {
            name: mode === "goal" ? "Maqsad qo‘yish" : "Xabar yuborish",
          }),
        );
        await waitFor(() => expect(submitted).toHaveLength(1));
        const body = submitted[0]!.body;
        if (mode === "chat") {
          expect(body.message).toBe(objective);
          expect(body.response_language).toBe("uz");
        } else {
          expect(body.objective).toBe(objective);
          expect(body.constraints).toBe(
            "Ma’lumotlarni o‘zgartirmang va mijozlarga murojaat qilmang. O‘zbek tilida (lotin yozuvida) javob bering.",
          );
          expect(body.max_steps).toBe(6);
          expect(body.budget_microusd).toBe(500000);
        }
        expect(submitted[0]!.url).not.toMatch(/analysis|commands/);
      } finally {
        localStorage.clear();
      }
    },
  );

  it.each(["thinking", "cancelled"] as const)(
    "keeps a %s preview separate from the result and actions",
    async (status) => {
      jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = requestUrl(input);
        if (url.endsWith("/chat/availability"))
          return response({ enabled: true });
        if (url.endsWith("/chat/topics/topic-1"))
          return response({
            topic,
            turns: [
              {
                ...turn,
                status,
                preview: "Незавершённый черновик 🧒",
                preview_revision: 1,
                answer: status === "thinking" ? "" : "Ответ остановлен.",
                next_action: "analyze",
              },
            ],
          });
        return response([]);
      });
      renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
      const preview = await screen.findByText("Незавершённый черновик 🧒");
      if (status === "thinking") {
        expect(preview).toBeVisible();
        expect(screen.getByText("Пишу ответ…")).toBeVisible();
      } else {
        expect(screen.getByText("Ответ остановлен.")).toBeVisible();
        expect(preview).not.toBeVisible();
        fireEvent.click(screen.getByText("Прерванный черновик"));
        expect(preview).toBeVisible();
      }
      expect(
        screen.queryByRole("button", { name: /Запустить анализ|Подтвердить/ }),
      ).not.toBeInTheDocument();
    },
  );

  it("pages earlier history without model calls, duplicate turns or jumping to the end", async () => {
    const gets: string[] = [];
    const posts: string[] = [];
    const scroll = jest.fn<() => void>();
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    const savedTurn = (index: number) => ({
      ...turn,
      turn_id: `turn-${String(index).padStart(3, "0")}`,
      message: `Saved question ${index}`,
      answer: `Saved answer ${index}`,
    });
    try {
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") posts.push(url);
        else gets.push(url);
        if (url.endsWith("/availability"))
          return response({
            enabled: true,
            transcript_pagination_enabled: true,
          });
        if (url.includes("/goals/topics/")) return response([]);
        if (url.endsWith("/messages?limit=20"))
          return response({
            topic,
            turns: Array.from({ length: 20 }, (_, index) =>
              savedTurn(index + 91),
            ),
            has_more: true,
            next_cursor: "turn-091",
          });
        if (url.endsWith("&before=turn-091"))
          return response({
            topic,
            turns: Array.from({ length: 20 }, (_, index) =>
              savedTurn(index + 71),
            ),
            has_more: false,
            next_cursor: null,
          });
        return response([]);
      });
      renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
      expect(await screen.findByText("Saved answer 110")).toBeVisible();
      await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole("button", { name: "Ранние сообщения" }));
      expect(await screen.findByText("Saved answer 71")).toBeVisible();
      expect(screen.getAllByLabelText("Ваше сообщение")).toHaveLength(40);
      expect(screen.getAllByText("Saved answer 110")).toHaveLength(1);
      expect(scroll).toHaveBeenCalledTimes(1);
      expect(
        screen.queryByRole("button", { name: "Ранние сообщения" }),
      ).not.toBeInTheDocument();
      expect(gets.some((url) => url.endsWith("/chat/topics/topic-1"))).toBe(
        false,
      );
      expect(posts).toHaveLength(0);
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  it.each([403, 503])(
    "does not silently fall back when the advertised history API returns %s",
    async (status) => {
      const urls: string[] = [];
      jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = requestUrl(input);
        urls.push(url);
        if (url.endsWith("/availability"))
          return response({
            enabled: true,
            transcript_pagination_enabled: true,
          });
        if (url.includes("/goals/topics/")) return response([]);
        if (url.includes("/workspace/topics/"))
          return response({ detail: "История пока недоступна" }, status);
        return response({ topic, turns: [turn] });
      });
      renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
      expect(
        await screen.findByText("Не удалось загрузить переписку."),
      ).toBeVisible();
      expect(screen.queryByText(turn.answer)).not.toBeInTheDocument();
      expect(urls.some((url) => url.endsWith("/chat/topics/topic-1"))).toBe(
        false,
      );
    },
  );

  it("rejects a history page from a different topic", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input);
      if (url.endsWith("/availability"))
        return response({ enabled: true, transcript_pagination_enabled: true });
      if (url.includes("/goals/topics/")) return response([]);
      return response({
        topic: { ...topic, topic_id: "foreign" },
        turns: [turn],
        has_more: false,
        next_cursor: null,
      });
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    expect(
      await screen.findByText("Не удалось загрузить переписку."),
    ).toBeVisible();
    expect(screen.queryByText(turn.answer)).not.toBeInTheDocument();
  });

  it("opens saved history at the latest result without scrolling on every edit", async () => {
    const scroll = jest.fn<() => void>();
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    const posts: string[] = [];
    try {
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") posts.push(url);
        if (url.endsWith("/availability")) return response({ enabled: true });
        if (url.includes("/goals/topics/")) return response([]);
        if (url.endsWith("/topic-1")) return response({ topic, turns: [turn] });
        return response([]);
      });
      renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
      expect(await screen.findByText(turn.answer)).toBeVisible();
      await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
      fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
        target: { value: "Я пока читаю историю" },
      });
      expect(scroll).toHaveBeenCalledTimes(1);
      expect(posts).toHaveLength(0);
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  it("creates a historical Goal only after an explicit saved-snapshot choice", async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return response({});
      }
      if (url.endsWith("/availability"))
        return response({
          enabled: true,
          agent_workspace_enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        });
      if (url.includes("/goals/topics/")) return response([]);
      if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    expect(screen.queryByLabelText("Область анализа")).not.toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Режим работы"), {
      target: { value: "goal" },
    });
    expect(await screen.findByLabelText("Область анализа")).toHaveValue(
      "current",
    );
    fireEvent.change(screen.getByLabelText("Область анализа"), {
      target: { value: "saved_snapshot" },
    });
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Проанализируй сохранённую историческую сводку" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поставить цель" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      url: "/api/v1/admin/operation/goals/topics/topic-1",
      body: {
        analysis_scope: "saved_snapshot",
        execution_mode: "agent",
        objective: "Проанализируй сохранённую историческую сводку",
      },
    });
  });

  it("uses the agent workspace by default without forcing an Orchestrator room switch", async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    const workspaceTopic = { ...topic, agent_id: "operations-orchestrator" };
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return response({ turn: { ...turn, next_action: "start_goal" } });
      }
      if (url.endsWith("/availability"))
        return response({
          enabled: true,
          agent_workspace_enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        });
      if (url.includes("/goals/topics/")) return response([]);
      if (url.endsWith("/topic-1"))
        return response({ topic: workspaceTopic, turns: [] });
      return response([]);
    });
    renderWithSession(
      <ChatPage agentId="operations-orchestrator" topicId="topic-1" />,
    );
    expect(
      await screen.findByRole("combobox", { name: "Режим работы" }),
    ).toHaveValue("auto");
    expect(screen.queryByText(/Только планирование/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Как поднять конверсию? Изучи текущие данные." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toBe(
      "/api/v1/admin/operation/workspace/topics/topic-1/messages",
    );
    expect(posts[0]!.body).toMatchObject({ execution_mode: "agent" });
    expect(posts.every((post) => !post.url.includes("/agents/"))).toBe(true);
  });

  it("waits for Goals availability instead of falling back to discussion during native admission", async () => {
    const posts: string[] = [];
    let resolveGoals!: (value: Response) => void;
    const pendingGoals = new Promise<Response>((resolve) => {
      resolveGoals = resolve;
    });
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push(url);
        return response({ turn });
      }
      if (url === "/api/v1/admin/operation/goals/availability")
        return pendingGoals;
      if (url.endsWith("/availability"))
        return response({ enabled: true, agent_workspace_enabled: true });
      if (url.includes("/goals/topics/")) return response([]);
      return response({
        topic: { ...topic, agent_id: "operations-orchestrator" },
        turns: [],
      });
    });
    renderWithSession(
      <ChatPage agentId="operations-orchestrator" topicId="topic-1" />,
    );
    await screen.findByText("Проверяем рабочий режим…");
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Как можно поднять конверсию. Изучи текущие данные" },
    });
    expect(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    ).toBeDisabled();
    // Even an explicit DOM submit must not bypass the preflight guard.
    fireEvent.submit(
      screen.getByLabelText("Сообщение агенту").closest("form")!,
    );
    expect(posts).toEqual([]);
    await act(async () => {
      resolveGoals(
        await response({
          enabled: true,
          agent_workspace_enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        }),
      );
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Отправить сообщение" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toBe(
      "/api/v1/admin/operation/workspace/topics/topic-1/messages",
    );
  });

  it.each(["error", "disabled", "mismatched"])(
    "never silently downgrades native execution when Goals is %s; discussion is explicit",
    async (state) => {
      const posts: { url: string; body: Record<string, unknown> }[] = [];
      jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = requestUrl(input);
        if (init?.method === "POST") {
          posts.push({ url, body: JSON.parse(String(init.body)) });
          return response(turn);
        }
        if (url === "/api/v1/admin/operation/goals/availability")
          return state === "error"
            ? response({ detail: "Unavailable" }, 503)
            : response({
                enabled: state !== "disabled",
                agent_workspace_enabled: state !== "mismatched",
                budget_microusd: 500000,
                max_steps: 6,
              });
        if (url.endsWith("/availability"))
          return response({ enabled: true, agent_workspace_enabled: true });
        if (url.includes("/goals/topics/")) return response([]);
        return response({
          topic: { ...topic, agent_id: "operations-orchestrator" },
          turns: [],
        });
      });
      renderWithSession(
        <ChatPage agentId="operations-orchestrator" topicId="topic-1" />,
      );
      await screen.findByText("Рабочий режим недоступен. Запрос не отправлен.");
      const composer = screen.getByLabelText("Сообщение агенту");
      fireEvent.change(composer, { target: { value: "Изучи текущие данные" } });
      fireEvent.submit(composer.closest("form")!);
      expect(posts).toEqual([]);
      expect(composer).toHaveValue("Изучи текущие данные");
      fireEvent.change(screen.getByRole("combobox", { name: "Режим работы" }), {
        target: { value: "chat" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Отправить сообщение" }),
      );
      await waitFor(() => expect(posts).toHaveLength(1));
      expect(posts[0]!.url).toBe(
        "/api/v1/admin/operation/chat/topics/topic-1/messages",
      );
      expect(posts[0]!.body.execution_mode).toBeUndefined();
    },
  );

  it("rechecks a failed native preflight without sending the draft until explicit submission", async () => {
    const posts: string[] = [];
    let goalsChecks = 0;
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push(url);
        return response({ turn });
      }
      if (url === "/api/v1/admin/operation/goals/availability") {
        goalsChecks += 1;
        return goalsChecks === 1
          ? response({ detail: "Unavailable" }, 503)
          : response({
              enabled: true,
              agent_workspace_enabled: true,
              budget_microusd: 500000,
              max_steps: 6,
            });
      }
      if (url.endsWith("/availability"))
        return response({ enabled: true, agent_workspace_enabled: true });
      if (url.includes("/goals/topics/")) return response([]);
      return response({ topic, turns: [] });
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    await screen.findByText("Рабочий режим недоступен. Запрос не отправлен.");
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: "Изучи текущие данные" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Повторить проверку" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Отправить сообщение" }),
      ).toBeEnabled(),
    );
    expect(screen.getByLabelText("Сообщение агенту")).toHaveValue(
      "Изучи текущие данные",
    );
    expect(posts).toEqual([]);
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toContain("/operation/workspace/");
  });

  it("recovers a Goal after a lost handoff response through reads, without resending the message", async () => {
    const posts: string[] = [];
    let handedOff = false;
    const goal = {
      goal_id: "goal-lost-response",
      status: "waiting",
      phase: "investigate",
      revision: 2,
      request: {
        objective: "Как можно поднять конверсию. Изучи текущие данные",
        max_steps: 6,
        budget_microusd: 500000,
        execution_mode: "agent",
      },
      plan: [],
      events: [],
      evidence: [],
      result: "",
      waiting_reason: "Нужны подтверждённые оплаты.",
      steps_used: 0,
      accounted_microusd: 0,
    };
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push(url);
        handedOff = true;
        return Promise.reject(new Error("Ответ на отправку потерян"));
      }
      if (url.endsWith("/availability"))
        return response({
          enabled: true,
          agent_workspace_enabled: true,
          budget_microusd: 500000,
          max_steps: 6,
        });
      if (url.includes("/goals/topics/"))
        return response(handedOff ? [goal] : []);
      return response({
        topic: { ...topic, agent_id: "operations-orchestrator" },
        turns: [],
      });
    });
    renderWithSession(
      <ChatPage agentId="operations-orchestrator" topicId="topic-1" />,
    );
    await screen.findByRole("combobox", { name: "Режим работы" });
    fireEvent.change(screen.getByLabelText("Сообщение агенту"), {
      target: { value: goal.request.objective },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await screen.findByText("Нужны подтверждённые оплаты.");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ответ на отправку потерян",
    );
    expect(screen.getByLabelText("Уточнение цели")).toHaveValue(
      goal.request.objective,
    );
    expect(posts).toEqual([
      "/api/v1/admin/operation/workspace/topics/topic-1/messages",
    ]);
    expect(screen.getByRole("button", { name: "Уточнить цель" })).toBeEnabled();
  });

  it("accepts an in-flight goal clarification from the main composer and keeps stop available", async () => {
    const posts: { url: string; body: Record<string, unknown> }[] = [];
    const goal = {
      goal_id: "goal-1",
      status: "running",
      revision: 9,
      lease_until: "2099-01-01T00:00:00Z",
      request: {
        objective: "Проанализировать удержание",
        max_steps: 6,
        budget_microusd: 500000,
      },
      plan: [],
      events: [],
      evidence: [],
      result: "",
      waiting_reason: "",
      steps_used: 1,
      accounted_microusd: 10000,
    };
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return response({ ...goal, revision: 10 });
      }
      if (url.endsWith("/availability"))
        return response({
          enabled: true,
          max_steps: 6,
          budget_microusd: 500000,
        });
      if (url.includes("/goals/topics/")) return response([goal]);
      if (url.endsWith("/topic-1")) return response({ topic, turns: [] });
      return response([]);
    });
    renderWithSession(<ChatPage agentId="growth-agent" topicId="topic-1" />);
    const composer = await screen.findByLabelText("Уточнение цели");
    expect(composer).toBeEnabled();
    fireEvent.change(composer, {
      target: { value: "Только родительская активность MANA" },
    });
    expect(
      screen.getByRole("button", { name: "Поставить цель на паузу" }),
    ).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Уточнить цель" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.url).toContain("/goals/goal-1/commands");
    expect(posts[0]!.body).toMatchObject({
      command: "steer",
      expected_revision: 9,
      message: "Только родительская активность MANA",
    });
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
