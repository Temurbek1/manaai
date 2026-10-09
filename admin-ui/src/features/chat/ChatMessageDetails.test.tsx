import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { ChatMessageDetails } from "./ChatMessageDetails";
import type { ChatViewTurn } from "./contracts";
import { formatDate } from "@/ui/format";

describe("ChatMessageDetails evidence dates", () => {
  it.each(["mana", "360rec"] as const)(
    "shows original collection time and verified %s scope",
    (product) => {
      const turn: ChatViewTurn = {
        turn_id: "turn-1",
        topic_id: "topic-1",
        request_id: "00000000-0000-4000-8000-000000000001",
        created_at: "2026-10-08T07:00:00Z",
        message: "Что известно?",
        answer: "Сохранённая сводка",
        status: "failed",
        analysis_requested: false,
        analysis_kind: "default",
        sources: [
          {
            report_id: "report-1",
            run_id: "run-1",
            title: "Engagement",
            created_at: "2026-10-08T07:00:00Z",
            collected_at: "2026-10-08T00:00:00Z",
            fresh_until: "2026-10-08T06:00:00Z",
            refresh_status: "stale",
            scope_verified: true,
            product,
          },
        ],
      };
      render(<ChatMessageDetails turn={turn} />);
      const link = screen.getByRole("link", { hidden: true });
      expect(link).toHaveTextContent("Данные:");
      expect(link).toHaveTextContent(formatDate("2026-10-08T00:00:00Z"));
      expect(link).not.toHaveTextContent(formatDate("2026-10-08T07:00:00Z"));
      expect(link).toHaveTextContent("Устаревшие");
      expect(link).toHaveTextContent(
        product === "mana" ? "Только MANA" : "Только 360REC",
      );
      expect(link).not.toHaveTextContent("Приложение не подтверждено");
    },
  );

  it("does not treat the report creation date as a legacy collection date", () => {
    render(
      <ChatMessageDetails
        turn={{
          turn_id: "turn-1",
          topic_id: "topic-1",
          request_id: "00000000-0000-4000-8000-000000000001",
          message: "Помоги",
          answer: "Нет даты сбора",
          status: "completed",
          analysis_requested: false,
          analysis_kind: "default",
          created_at: "2026-10-08T07:00:00Z",
          sources: [
            {
              report_id: "legacy",
              run_id: "run-1",
              title: "Historical report",
              created_at: "2026-10-08T07:00:00Z",
              scope_verified: false,
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole("link", { hidden: true })).toHaveTextContent(
      "Дата сбора неизвестна",
    );
  });

  const source = {
    report_id: "report-1",
    run_id: "run-1",
    title: "Engagement",
    created_at: "2026-10-08T03:00:00Z",
    collected_at: "2026-10-08T00:00:00Z",
    fresh_until: "2026-10-08T06:00:00Z",
    refresh_status: "cached" as const,
    scope_verified: true,
    product: "mana" as const,
  };
  const turn: ChatViewTurn = {
    turn_id: "turn-1",
    topic_id: "topic-1",
    request_id: "00000000-0000-4000-8000-000000000001",
    created_at: "2026-10-08T03:00:00Z",
    message: "Объясни сводку",
    answer: "Ответ модели без оговорки",
    status: "completed",
    analysis_requested: false,
    analysis_kind: "default",
    sources: [source],
  };

  it.each(["cached", "live"] as const)(
    "does not add clutter to verified %s evidence within its window",
    (refresh_status) => {
      jest
        .spyOn(Date, "now")
        .mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
      render(
        <ChatMessageDetails
          turn={{ ...turn, sources: [{ ...source, refresh_status }] }}
        />,
      );
      expect(screen.queryByRole("note")).toBeNull();
      expect(
        screen.getByText("Детали ответа · 1 ист.").closest("details"),
      ).not.toHaveAttribute("open");
    },
  );

  it.each([
    { now: "2026-10-08T03:00:00Z", refresh_status: "stale" as const },
    { now: "2026-10-08T06:00:00Z", refresh_status: "cached" as const },
  ])(
    "shows stale evidence outside closed details, including expiry at render",
    ({ now, refresh_status }) => {
      jest.spyOn(Date, "now").mockReturnValue(Date.parse(now));
      render(
        <ChatMessageDetails
          turn={{ ...turn, sources: [{ ...source, refresh_status }] }}
        />,
      );
      expect(screen.getByRole("note")).toBeVisible();
      expect(screen.getByRole("note")).toHaveTextContent("устаревшие данные");
      expect(screen.getByRole("note")).toHaveTextContent(
        "исторического разбора",
      );
      expect(screen.getByRole("note").closest("details")).toBeNull();
    },
  );

  it.each([
    { collected_at: null },
    { collected_at: "invalid-date" },
    { collected_at: "2026-10-08T04:00:00Z" },
    { fresh_until: null },
    { fresh_until: "invalid-date" },
    { fresh_until: "2026-10-08T00:00:00Z" },
    { refresh_status: "unknown" as const },
  ])("does not trust unknown/future/malformed freshness %j", (fields) => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
    render(
      <ChatMessageDetails
        turn={{ ...turn, sources: [{ ...source, ...fields }] }}
      />,
    );
    expect(screen.getByRole("note")).toBeVisible();
    expect(screen.getByRole("note")).toHaveTextContent(
      "Свежесть части данных не подтверждена",
    );
    expect(screen.getByRole("note")).not.toHaveTextContent("устаревшие данные");
  });

  it("does not infer freshness from a legacy payload without refresh status", () => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
    const legacy: NonNullable<ChatViewTurn["sources"]>[number] = { ...source };
    delete legacy.refresh_status;
    render(<ChatMessageDetails turn={{ ...turn, sources: [legacy] }} />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Свежесть части данных не подтверждена",
    );
  });

  it("keeps failed-turn evidence and unknown product scope visible without calling providers", () => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-08T03:00:00Z"));
    const fetchMock = jest.spyOn(globalThis, "fetch");
    render(
      <ChatMessageDetails
        turn={{
          ...turn,
          status: "failed",
          sources: [{ ...source, scope_verified: false, product: null }],
        }}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "Приложение источника не подтверждено",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("updates once at evidence expiry without polling data or the model", () => {
    jest.useFakeTimers({
      now: new Date("2026-10-08T03:00:00Z"),
      doNotFake: ["queueMicrotask"],
    });
    const schedule = jest.spyOn(window, "setTimeout");
    const cancel = jest.spyOn(window, "clearTimeout");
    const fetchMock = jest.spyOn(globalThis, "fetch");
    const view = render(<ChatMessageDetails turn={turn} />);
    try {
      expect(screen.queryByRole("note")).toBeNull();
      const expiryDelay = 3 * 60 * 60 * 1000;
      const timerIndex = schedule.mock.calls.findIndex(
        ([, delay]) => delay === expiryDelay,
      );
      expect(
        schedule.mock.calls.filter(([, delay]) => delay === expiryDelay),
      ).toHaveLength(1);
      const expiryTimer = schedule.mock.results[timerIndex]?.value;
      if (typeof expiryTimer !== "number")
        throw new Error("Missing window expiry timer");
      act(() => jest.advanceTimersByTime(3 * 60 * 60 * 1000));
      expect(screen.getByRole("note")).toHaveTextContent("устаревшие данные");
      expect(cancel).toHaveBeenCalledWith(expiryTimer);
      expect(fetchMock).not.toHaveBeenCalled();
    } finally {
      view.unmount();
      jest.useRealTimers();
    }
  });

  it("replaces the expiry timer on evidence changes and cleans it on unmount", () => {
    jest.useFakeTimers({
      now: new Date("2026-10-08T03:00:00Z"),
      doNotFake: ["queueMicrotask"],
    });
    const schedule = jest.spyOn(window, "setTimeout");
    const cancel = jest.spyOn(window, "clearTimeout");
    const view = render(
      <ChatMessageDetails
        turn={{
          ...turn,
          sources: [{ ...source, fresh_until: "2026-10-08T03:00:01Z" }],
        }}
      />,
    );
    try {
      const firstIndex = schedule.mock.calls.findIndex(
        ([, delay]) => delay === 1000,
      );
      const firstTimer = schedule.mock.results[firstIndex]?.value;
      if (typeof firstTimer !== "number")
        throw new Error("Missing first expiry timer");
      view.rerender(
        <ChatMessageDetails
          turn={{
            ...turn,
            sources: [{ ...source, fresh_until: "2026-10-08T03:00:02Z" }],
          }}
        />,
      );
      expect(cancel).toHaveBeenCalledWith(firstTimer);
      const secondIndex = schedule.mock.calls.findIndex(
        ([, delay]) => delay === 2000,
      );
      expect(
        schedule.mock.calls.filter(([, delay]) => delay === 2000),
      ).toHaveLength(1);
      const secondTimer = schedule.mock.results[secondIndex]?.value;
      if (typeof secondTimer !== "number")
        throw new Error("Missing replacement expiry timer");
      act(() => jest.advanceTimersByTime(1000));
      expect(screen.queryByRole("note")).toBeNull();
      view.unmount();
      expect(cancel).toHaveBeenCalledWith(secondTimer);
    } finally {
      view.unmount();
      jest.useRealTimers();
    }
  });
});
