import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, jest } from "@jest/globals";

import { renderWithSession } from "../test/render";
import { requestUrl } from "../test/http";
import { DashboardPage } from "./DashboardPage";

const dashboard = {
  agents: [
    {
      agent_id: "marketing-agent",
      display_name: "Marketing Agent",
      status: "enabled",
      health: "healthy",
      last_run: null,
      next_run: null,
      last_duration_ms: null,
      success_rate: "unavailable",
      pending_approvals: 0,
      recent_incidents: 0,
    },
  ],
  global_kill_switch: false,
  generated_at: "2026-07-22T08:00:00Z",
};

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("DashboardPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("runs an agent manually and changes the global kill switch for an admin", async () => {
    const fetchMock = jest.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("/dashboard")) return response(dashboard);
      if (url.includes("/agents/marketing-agent/run"))
        return response({ status: "accepted" });
      if (url.includes("/kill-switch/global"))
        return response({ enabled: true });
      return response({});
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<DashboardPage />, "admin");

    fireEvent.click(
      await screen.findByRole("button", { name: "Запустить анализ" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/run"),
      expect.objectContaining({ method: "POST" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить сбор данных" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/agents/marketing-agent/run"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const emergencyStop = screen.getByRole("button", {
      name: "Остановить действия",
    });
    await waitFor(() => expect(emergencyStop).toBeEnabled());
    fireEvent.click(emergencyStop);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить остановку" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/kill-switch/global"),
        expect.objectContaining({ method: "PUT" }),
      ),
    );
  });

  it("renders loading, error, and empty states", async () => {
    let resolveRequest: ((value: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    });
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(jest.fn<typeof fetch>(() => pending));
    const rendered = renderWithSession(<DashboardPage />, "viewer");
    expect(screen.getByRole("status")).toHaveTextContent("Загружаем обзор");
    expect(screen.queryByText("Агентов пока нет")).not.toBeInTheDocument();
    expect(rendered.container).not.toHaveTextContent("Разрешено политикой");

    resolveRequest?.(
      new Response(JSON.stringify({ detail: "Database unavailable" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(
      await screen.findByText(/Не удалось загрузить обзор/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Агентов пока нет")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Остановить действия" }),
    ).toBeDisabled();
  });

  it("refreshes stored data without launching an analysis and provides task links", async () => {
    const fetchMock = jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response(dashboard));
    renderWithSession(<DashboardPage />, "viewer");
    expect(
      await screen.findByRole("link", { name: /Рассмотреть согласования/ }),
    ).toHaveAttribute("href", "/approvals");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Обновить экран" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Обновить экран" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    for (const [url, options] of fetchMock.mock.calls) {
      expect(requestUrl(url)).toContain("/dashboard");
      expect(options?.method).toBe("GET");
    }
  });
});
