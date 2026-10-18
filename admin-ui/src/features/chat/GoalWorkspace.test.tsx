import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { requestUrl } from "@/test/http";
import parentJourney from "@/test/fixtures/native-parent-journey.json";
import { formatDate } from "@/ui/format";
import {
  LANGUAGE_STORAGE_KEY,
  LanguageProvider,
} from "@/i18n/LanguageProvider";
import {
  GoalWorkspace,
  type Goal,
  type GoalsAvailability,
} from "./GoalWorkspace";

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

const limitAvailability: GoalsAvailability = {
  enabled: true,
  model: "fake",
  max_steps: 6,
  budget_microusd: 500000,
  agent_workspace_enabled: true,
  event_stream_enabled: true,
  model_selection_enabled: false,
  read_capabilities: [],
  limit_extensions_enabled: true,
  extension_max_steps: 24,
  extension_budget_microusd: 500000,
};
const limited: Goal = {
  ...fixture,
  request: {
    ...fixture.request,
    execution_mode: "agent",
    budget_microusd: 50000,
  },
  steps_used: 6,
  limit_tracking: true,
  limit_stop: "steps",
  limit_grants: [],
  unsettled_microusd: 0,
  waiting_reason: "Лимит шагов исчерпан.",
};

const savedEvidence: NonNullable<Goal["evidence"]>[number] = {
  report_id: "saved-evidence-1",
  capability_key: "retention.engagement.analyze",
  product: "mana",
  summary: "Saved synthetic aggregate; no observed event dates.",
  collected_at: "2026-10-08T00:00:00Z",
  fresh_until: "2026-10-08T06:00:00Z",
  refresh_status: "cached",
  shortened: false,
};

describe("GoalWorkspace", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it("renders the complete real-model synthetic journey and opens both original saved sources", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      response([
        {
          ...fixture,
          status: "completed",
          result: parentJourney.text,
          request: {
            ...fixture.request,
            execution_mode: "agent",
            analysis_scope: "saved_snapshot",
          },
          evidence: parentJourney.sources.map((source) => ({
            ...savedEvidence,
            ...source,
            refresh_status: "cached",
          })),
        },
      ]),
    );
    const { container } = renderWithSession(
      <GoalWorkspace topicId="topic-1" />,
    );
    const funnel = await screen.findByRole("button", {
      name: "Воронка — synthetic-journey-parent-funnel",
    });
    const retention = screen.getByRole("button", {
      name: "Удержание — synthetic-journey-parent-retention",
    });
    expect(screen.getAllByRole("table")).toHaveLength(3);
    expect(screen.getByRole("cell", { name: "37,5%" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "59,26%" })).toBeVisible();
    expect(container.textContent).toContain("не причинный эффект оплаты");
    expect(container.textContent).toContain(
      "не доказательство улучшения бизнеса или описание текущего MANA.",
    );
    expect(container.textContent).not.toContain("(report:");
    fireEvent.click(funnel);
    const panels = container.querySelectorAll(".goal-evidence-text");
    expect(panels).toHaveLength(2);
    expect(panels[0]).toBeVisible();
    expect(panels[0]!.textContent).toBe(parentJourney.sources[0]!.summary);
    fireEvent.click(retention);
    expect(panels[1]).toBeVisible();
    expect(panels[1]!.textContent).toBe(parentJourney.sources[1]!.summary);
    expect(panels[1]!.textContent).toMatch(
      /EXACT JOURNEY FOOTER[\s\S]*no contact, send or measured lift\.\n$/,
    );
    expect(container.querySelector("a, script, img")).toBeNull();
    expect(
      fetchMock.mock.calls.every(
        ([input, init]) =>
          requestUrl(input).includes("/goals/topics/topic-1") &&
          (!init?.method || init.method === "GET"),
      ),
    ).toBe(true);
  });

  it("opens the exact saved evidence from a bound citation without source or control requests", async () => {
    const summary =
      "  ORIGINAL saved text\n\n<script>not executable</script>\nEXACT TAIL  ";
    const fetchMock = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      response([
        {
          ...fixture,
          status: "completed",
          result:
            "Синтетический вывод. [Родительская сводка](report:saved-evidence-1). " +
            "[Неизвестный источник](report:not-loaded). [Внешний](https://example.com).",
          evidence: [{ ...savedEvidence, summary }],
        },
      ]),
    );
    const { container } = renderWithSession(
      <GoalWorkspace topicId="topic-1" />,
    );
    const citation = await screen.findByRole("button", {
      name: "Родительская сводка",
    });
    expect(container.querySelector(".goal-evidence-text")).not.toBeVisible();
    const requestCount = fetchMock.mock.calls.length;
    fireEvent.click(citation);
    const saved = container.querySelector(".goal-evidence-text")!;
    expect(saved).toBeVisible();
    expect(saved.textContent).toBe(summary);
    const details = saved.closest("details")!;
    expect(details).toHaveAttribute("open");
    expect(details.parentElement!.closest("details")).toHaveAttribute("open");
    expect(details.querySelector("summary")).toHaveFocus();
    expect(container.querySelector("script, img, a")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Неизвестный источник" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Внешний" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(requestCount);
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !init?.method || init.method === "GET",
      ),
    ).toBe(true);
    fireEvent.click(details.querySelector("summary")!);
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(citation);
    expect(saved).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(requestCount);
  });

  it.each(["ru", "uz"])(
    "keeps partial saved text and qualifications exact in %s",
    async (locale) => {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, locale);
      const text = "  EXACT partial source\n<b>not HTML</b>\nTAIL  ";
      const limitation = "Only ten fictional parents; not population coverage.";
      const fetchMock = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
        response([
          {
            ...fixture,
            status: "completed",
            evidence: [
              {
                ...savedEvidence,
                summary: text,
                shortened: true,
                limitations: [limitation],
              },
            ],
          },
        ]),
      );
      try {
        const { container } = renderWithSession(
          <LanguageProvider>
            <GoalWorkspace topicId="topic-1" />
          </LanguageProvider>,
        );
        const source = await screen.findByText(/saved-evidence-1/);
        fireEvent.click(
          source
            .closest("details")!
            .parentElement!.closest("details")!
            .querySelector("summary")!,
        );
        fireEvent.click(source);
        const region = screen.getByRole("region", {
          name:
            locale === "uz"
              ? "Saqlangan manba matni"
              : "Текст сохранённого источника",
        });
        expect(region).toBeVisible();
        expect(region.textContent).toBe(text);
        expect(region).toHaveAttribute("tabindex", "0");
        expect(screen.getByRole("note", { name: "" })).toHaveTextContent(
          locale === "uz"
            ? "Manba matni qisqartirilgan."
            : "Текст источника сокращён.",
        );
        expect(screen.getByText(limitation)).toBeVisible();
        expect(container.querySelector("b")).toBeNull();
        expect(
          fetchMock.mock.calls.every(
            ([input, init]) =>
              requestUrl(input).includes("/goals/topics/topic-1") &&
              (!init?.method || init.method === "GET"),
          ),
        ).toBe(true);
      } finally {
        localStorage.clear();
        document.documentElement.lang = "ru";
      }
    },
  );

  it("labels source collection separately from Goal creation without granting reads", async () => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
    const fetchMock = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      response([
        {
          ...fixture,
          status: "completed",
          created_at: "2026-10-08T01:00:00Z",
          evidence: [savedEvidence],
        },
      ]),
    );
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    const item = await screen.findByText(/saved-evidence-1/);
    expect(item).toHaveTextContent(
      `Сбор данных: ${formatDate(savedEvidence.collected_at)}`,
    );
    expect(item).toHaveTextContent("Срок кэша не истёк");
    expect(item).not.toHaveTextContent("Подтверждён");
    expect(item).not.toHaveTextContent(formatDate("2026-10-08T01:00:00Z"));
    expect(item.closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText(/Есть устаревшие данные/)).toBeNull();
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !init?.method || init.method === "GET",
      ),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.every(([input]) =>
        requestUrl(input).includes("/goals/topics/topic-1"),
      ),
    ).toBe(true);
  });

  it.each([null, "", "invalid-date"])(
    "does not replace missing/malformed collection date %j with Goal dates",
    async (collected_at) => {
      jest.spyOn(globalThis, "fetch").mockImplementation(() =>
        response([
          {
            ...fixture,
            status: "completed",
            evidence: [{ ...savedEvidence, collected_at }],
          },
        ]),
      );
      renderWithSession(<GoalWorkspace topicId="topic-1" />);
      const item = await screen.findByText(/saved-evidence-1/);
      expect(item).toHaveTextContent("Дата сбора неизвестна");
      expect(item).not.toHaveTextContent("Invalid Date");
      expect(item).not.toHaveTextContent(formatDate(fixture.created_at));
      expect(item).toHaveTextContent("Свежесть не подтверждена");
      expect(screen.getByText(/Есть устаревшие данные/)).toBeVisible();
    },
  );

  it.each([
    { collected_at: "2026-10-08T04:00:00Z" },
    { fresh_until: "invalid-date" },
    { fresh_until: "2026-10-08T00:00:00Z" },
    { refresh_status: "unknown" },
  ])("warns outside details about unverified timing %j", async (fields) => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
    jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      response([
        {
          ...fixture,
          status: "completed",
          evidence: [{ ...savedEvidence, ...fields }],
        },
      ]),
    );
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    const warning = await screen.findByText(/Есть устаревшие данные/);
    expect(warning).toBeVisible();
    expect(warning.closest("details")).toBeNull();
    expect(screen.getByText(/saved-evidence-1/)).toHaveTextContent(
      "Свежесть не подтверждена",
    );
  });

  it("does not leave expired cached evidence labelled as verified", async () => {
    jest
      .spyOn(Date, "now")
      .mockReturnValue(Date.parse(savedEvidence.fresh_until!));
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        response([
          { ...fixture, status: "completed", evidence: [savedEvidence] },
        ]),
      );
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    const item = await screen.findByText(/saved-evidence-1/);
    expect(item).toHaveTextContent("Устаревшие");
    expect(item).not.toHaveTextContent("Подтверждён");
    expect(screen.getByText(/Есть устаревшие данные/)).toBeVisible();
  });

  it("labels a completed historical slice separately from current measurements", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      response([
        {
          ...fixture,
          status: "completed",
          waiting_reason: "",
          request: {
            ...fixture.request,
            execution_mode: "agent",
            analysis_scope: "saved_snapshot",
          },
        },
      ]),
    );
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    expect(
      await screen.findByText("Исторический срез · не текущее состояние"),
    ).toBeVisible();
    expect(screen.getByText("Анализ готов")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Разрешить чтение данных" }),
    ).not.toBeInTheDocument();
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

  it("allows steering without resuming a paused in-flight provider call", async () => {
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
    expect(screen.getByRole("textbox")).toBeEnabled();
  });

  it("does not fabricate a workspace for an older backend", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(() => response([]));
    const { container } = renderWithSession(
      <GoalWorkspace topicId="topic-1" />,
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container.querySelector(".goal-workspace")).toBeNull();
  });

  it("extends the same goal only after exact human limit confirmation", async () => {
    const posts: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return response({
          ...limited,
          status: "queued",
          limit_stop: null,
          revision: 4,
        });
      }
      return response([limited]);
    });
    renderWithSession(
      <GoalWorkspace topicId="topic-1" availability={limitAvailability} />,
    );
    const button = await screen.findByRole("button", {
      name: "Продолжить эту цель",
    });
    expect(
      screen.queryByRole("button", { name: "Продолжить" }),
    ).not.toBeInTheDocument();
    expect(posts).toHaveLength(0);
    fireEvent.click(button);
    expect(posts).toHaveLength(0);
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Общий бюджет, $" }),
      { target: { value: "0.10" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить и продолжить" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      command: "extend_limits",
      expected_revision: 3,
      message: "",
      max_steps: 12,
      budget_microusd: 100000,
    });
    expect(
      screen.queryByRole("button", { name: "Разрешить чтение данных" }),
    ).not.toBeInTheDocument();
  });

  it("never submits decreased, fractional or over-ceiling limits", async () => {
    const posts: unknown[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") posts.push(init.body);
      return response([limited]);
    });
    renderWithSession(
      <GoalWorkspace topicId="topic-1" availability={limitAvailability} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Продолжить эту цель" }),
    );
    const steps = screen.getByRole("spinbutton", { name: "Всего шагов" });
    const budget = screen.getByRole("spinbutton", { name: "Общий бюджет, $" });
    const confirm = screen.getByRole("button", {
      name: "Подтвердить и продолжить",
    });
    for (const value of ["5", "6", "6.5", "25", ""]) {
      fireEvent.change(steps, { target: { value } });
      expect(confirm).toBeDisabled();
    }
    fireEvent.change(steps, { target: { value: "12" } });
    for (const value of ["0.01", "0.501", "0.51", ""]) {
      fireEvent.change(budget, { target: { value } });
      expect(confirm).toBeDisabled();
    }
    expect(posts).toHaveLength(0);
  });

  it.each(["viewer", "admin"] as const)(
    "unknown cost holds never offer extension to %s",
    async (role) => {
      jest
        .spyOn(globalThis, "fetch")
        .mockImplementation(() =>
          response([
            { ...limited, limit_stop: null, unsettled_microusd: 12000 },
          ]),
        );
      renderWithSession(
        <GoalWorkspace topicId="topic-1" availability={limitAvailability} />,
        role,
      );
      expect(
        await screen.findByText(/Исход AI-запроса неизвестен/),
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Продолжить эту цель" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Продолжить" }),
      ).not.toBeInTheDocument();
    },
  );

  it("fails closed when limit availability is missing or disabled", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response([limited]));
    renderWithSession(<GoalWorkspace topicId="topic-1" />);
    expect(
      await screen.findByText(
        /Продолжение с новыми лимитами сейчас недоступно/,
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Продолжить эту цель" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Продолжить" }),
    ).not.toBeInTheDocument();
  });

  it("reuses a lost extension receipt rather than doubling its grant", async () => {
    const posts: Record<string, unknown>[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return posts.length === 1
          ? Promise.reject(new Error("Lost reply"))
          : response(limited);
      }
      return response([limited]);
    });
    renderWithSession(
      <GoalWorkspace topicId="topic-1" availability={limitAvailability} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Продолжить эту цель" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить и продолжить" }),
    );
    await screen.findByRole("alert");
    const retry = screen.getByRole("button", {
      name: "Подтвердить и продолжить",
    });
    await waitFor(() => expect(retry).toBeEnabled());
    fireEvent.click(retry);
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
  });
});
