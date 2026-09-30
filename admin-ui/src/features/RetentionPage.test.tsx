import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { RetentionPage } from "./RetentionPage";

describe("RetentionPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows Russian evidence and does not turn absent mobile analytics into zero", async () => {
    const fetch = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            mode: "live",
            mobile_analytics_available: false,
            snapshot_age_seconds: 10,
            findings: [],
            recent_runs: [],
            reports: [],
            snapshot: {
              period_start: "2026-09-22T12:20:00Z",
              period_end: "2026-09-29T12:20:00Z",
              collected_at: "2026-09-29T12:20:00Z",
              completeness: "0",
              total_children: 150,
              backend_active_children: 20,
              parent_accounts_joined: 5,
              mobile_sessions: 0,
              evidence_refs: [
                {
                  source: "manakids_admin_api",
                  completeness: "0.2",
                  collected_at: "2026-09-29T12:20:00Z",
                },
              ],
              limitations: ["Bounded sample"],
              operational_telemetry: null,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    renderWithSession(<RetentionPage />);
    expect(await screen.findByText("150")).toBeInTheDocument();
    expect(
      screen.getByText("Сеансы мобильного приложения").closest("article"),
    ).toHaveTextContent("Нет данных");
    expect(screen.getByText("Приложение Manakids")).toBeInTheDocument();
    expect(screen.getByText(/Разделение MANA и 360REC/)).toBeInTheDocument();
    expect(screen.getByText(/Даже 100% не означает/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Удержание и лояльность" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить экран" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    for (const [, options] of fetch.mock.calls)
      expect(options?.method).toBe("GET");
  });

  it("does not present a failed request as an empty analysis history", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "unavailable" }), {
        status: 503,
      }),
    );
    renderWithSession(<RetentionPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось загрузить отчёт",
    );
    expect(
      screen.queryByText("Пока нет завершённого анализа"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Запусков пока нет.")).not.toBeInTheDocument();
  });

  it("explains an empty history without suggesting fabricated results", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          mode: "unavailable",
          snapshot: null,
          recent_runs: [],
          findings: [],
          reports: [],
        }),
        { status: 200 },
      ),
    );
    renderWithSession(<RetentionPage />);
    expect(
      await screen.findByText("Пока нет завершённого анализа"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0 %")).not.toBeInTheDocument();
  });
});
