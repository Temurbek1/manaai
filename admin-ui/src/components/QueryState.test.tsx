import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryState } from "./QueryState";

describe("QueryState", () => {
  it("keeps pending, failed, stale and successful states distinct", async () => {
    const onRetry = jest
      .fn<() => Promise<unknown>>()
      .mockRejectedValue(new Error("Offline"));
    const rendered = render(
      <QueryState loading hasData={false} onRetry={onRetry} subject="отчёт" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Загружаем отчёт");
    rendered.rerender(
      <QueryState
        loading={false}
        error={new Error("Offline")}
        hasData={false}
        onRetry={onRetry}
        subject="отчёт"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "это не означает, что записей нет",
    );
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
    await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(1));
    rendered.rerender(
      <QueryState
        loading={false}
        error={new Error("Offline")}
        hasData
        onRetry={onRetry}
        subject="отчёт"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("устаревшими");
    rendered.rerender(
      <QueryState loading={false} hasData onRetry={onRetry} subject="отчёт" />,
    );
    expect(rendered.container).toBeEmptyDOMElement();
  });
});
