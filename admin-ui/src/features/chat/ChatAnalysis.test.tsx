import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { AnalysisButton, AnalysisResult } from "./ChatAnalysis";
import type { components } from "@/api/schema";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("Chat analysis consent", () => {
  it.each([
    [{}, "24 часа"],
    [{ minimum_interval_seconds: 75600 }, "21 час"],
    [{ minimum_interval_seconds: 21601 }, "21601 с"],
    [{ minimum_interval_seconds: 21599 }, "6 часов"],
    [{ minimum_interval_seconds: 21600.5 }, "6 часов"],
    [{ minimum_interval_seconds: 86401 }, "6 часов"],
    [{ admission_checks: ["access", "product_scope", "cooldown"] }, "6 часов"],
    [{ product: "360rec" }, "6 часов"],
    [{ capability_key: "retention.engagement.analyze" }, "6 часов"],
    [{ kind: "default" }, "6 часов"],
    [{ confirmation_required: false }, "6 часов"],
  ])(
    "uses valid server conditions but never loosens a malformed policy (%j)",
    (patch, interval) => {
      const fetchMock = jest.fn<typeof fetch>(() => response({}));
      jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
      // Simulate unvalidated legacy/corrupt JSON at the HTTP boundary.
      const confirmation = {
        kind: "mana_parents",
        product: "mana",
        capability_key: "retention.parents.analyze",
        confirmation_required: true,
        admission_checks: ["access", "product_scope", "cooldown", "budget"],
        minimum_interval_seconds: 86400,
        ...patch,
      } as components["schemas"]["ChatReadConfirmation"];
      renderWithSession(
        <AnalysisButton
          kind="mana_parents"
          confirmation={confirmation}
          topicId="topic-1"
          disabled={false}
          onDone={async () => undefined}
        />,
      );
      const region = screen.getByRole("region", {
        name: "Предлагаемый следующий шаг",
      });
      expect(region).toHaveTextContent(`не чаще раза в ${interval}`);
      expect(region).toHaveTextContent("соответствие источника приложению");
      expect(region).toHaveTextContent("Подтверждение не гарантирует сбор");
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each(["default", "mana_parents"] as const)(
    "warns that %s confirmation can be refused, without reading on render",
    (kind) => {
      const fetchMock = jest.fn<typeof fetch>(() => response({}));
      jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
      renderWithSession(
        <AnalysisButton
          kind={kind}
          topicId="topic-1"
          disabled={false}
          onDone={async () => undefined}
        />,
      );
      expect(
        screen.getByRole("region", { name: "Предлагаемый следующий шаг" }),
      ).toHaveTextContent("Подтверждение не гарантирует сбор");
      expect(
        screen.getByRole("region", { name: "Предлагаемый следующий шаг" }),
      ).toHaveTextContent(
        "доступ, соответствие источника приложению, бюджет или интервал между чтениями",
      );
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("uses one explicit confirmation and the existing production request contract", async () => {
    const fetchMock = jest.fn<typeof fetch>(() => response({}));
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    const onDone = jest.fn(async () => undefined);
    renderWithSession(
      <AnalysisButton topicId="topic-1" disabled={false} onDone={onDone} />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/платные чтения/)).toBeInTheDocument();
    const button = screen.getByRole("button", {
      name: "Подтвердить сбор данных",
    });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      request_id: expect.any(String),
      confirmed: true,
    });
    expect(
      screen.getByRole("button", { name: "Запрос принят" }),
    ).toBeDisabled();
  });

  it("does not send server policy metadata as read authorization", async () => {
    const fetchMock = jest.fn<typeof fetch>(() => response({}));
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(
      <AnalysisButton
        kind="mana_parents"
        confirmation={{
          kind: "mana_parents",
          product: "mana",
          capability_key: "retention.parents.analyze",
          confirmation_required: true,
          admission_checks: ["access", "product_scope", "cooldown", "budget"],
          minimum_interval_seconds: 86400,
        }}
        topicId="topic-1"
        disabled={false}
        onDone={async () => undefined}
      />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    );
    await screen.findByRole("button", { name: "Запрос принят" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      request_id: expect.any(String),
      confirmed: true,
      kind: "mana_parents",
    });
  });

  it("reuses the same idempotency key after an uncertain response", async () => {
    const fetchMock = jest
      .fn<typeof fetch>()
      .mockImplementationOnce(() =>
        response({ detail: "Связь прервалась" }, 503),
      )
      .mockImplementationOnce(() => response({}));
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(
      <AnalysisButton
        topicId="topic-1"
        disabled={false}
        onDone={async () => undefined}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    );
    await screen.findByRole("alert");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    );
    await screen.findByRole("button", { name: "Запрос принят" });
    expect(fetchMock.mock.calls[0]?.[1]?.body).toEqual(
      fetchMock.mock.calls[1]?.[1]?.body,
    );
  });

  it("never re-enables a submitted request when refreshing the chat fails", async () => {
    const fetchMock = jest.fn<typeof fetch>(() => response({}));
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(
      <AnalysisButton
        topicId="topic-1"
        disabled={false}
        onDone={async () => {
          throw new Error("offline");
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Запрос принят");
    expect(
      screen.getByRole("button", { name: "Запрос принят" }),
    ).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps manual polling and the run link out of the completed result", async () => {
    const fetchMock = jest.fn<typeof fetch>(() =>
      response({
        state: "completed",
        summary: "Готовая сводка",
        run_id: "run-1",
      }),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<AnalysisResult topicId="topic-1" turnId="turn-1" />);
    await screen.findByText("Готовая сводка");
    expect(
      screen.queryByRole("button", { name: "Обновить состояние" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Открыть журнал/ }),
    ).not.toBeVisible();
    expect(
      fetchMock.mock.calls.every(([, init]) => init?.method === "GET"),
    ).toBe(true);
  });
});
