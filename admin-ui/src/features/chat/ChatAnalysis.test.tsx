import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { AnalysisButton, AnalysisResult } from "./ChatAnalysis";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("Chat analysis consent", () => {
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
