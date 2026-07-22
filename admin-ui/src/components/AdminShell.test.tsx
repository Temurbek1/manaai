import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DashboardPage } from "@/features/DashboardPage";
import { requestBodyText, requestUrl } from "@/test/http";

import { AdminShell } from "./AdminShell";
import { Providers } from "./Providers";

jest.mock("next/navigation", () => ({ usePathname: () => "/" }));

const authenticatedSession = {
  authenticated: true,
  user: {
    user_id: "00000000-0000-4000-8000-000000000001",
    telegram_id: 976835256,
    display_name: "Test Admin",
    username: "test_admin",
    role: "admin",
    status: "active",
    created_at: "2026-07-22T08:00:00Z",
    updated_at: "2026-07-22T08:00:00Z",
    last_login_at: "2026-07-22T08:00:00Z",
    created_by: "bootstrap",
    disabled_reason: null,
    profile_metadata: {},
    auth_locked_until: null,
  },
  expires_at: "2026-07-22T16:00:00Z",
  ads_provider: "fake_meta",
  provider_mode: "fake_executable",
  live_meta_read_only: false,
};

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function renderShell(): void {
  render(
    <Providers>
      <AdminShell>
        <DashboardPage />
      </AdminShell>
    </Providers>,
  );
}

describe("AdminShell Telegram authentication", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    document.cookie = "mana_csrf=; Max-Age=0; path=/";
  });

  it("restores a server session, sends no identity headers, and logs out with CSRF", async () => {
    document.cookie = "mana_csrf=csrf-token; path=/";
    const storageSpy = jest.spyOn(Storage.prototype, "setItem");
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      const headers = new Headers(init?.headers);
      expect(headers.get("X-API-Key")).toBeNull();
      expect(headers.get("X-MANA-Actor-ID")).toBeNull();
      expect(headers.get("X-MANA-Role")).toBeNull();
      if (url.includes("/auth/session"))
        return jsonResponse(authenticatedSession);
      if (url.includes("/auth/logout")) {
        expect(init?.method).toBe("POST");
        expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
        expect(init?.credentials).toBe("same-origin");
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url.includes("/dashboard")) {
        return jsonResponse({
          agents: [],
          global_kill_switch: false,
          generated_at: "2026-07-22T08:00:00Z",
        });
      }
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderShell();

    expect(await screen.findByText("Test Admin")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Пользователи" })).toHaveAttribute(
      "href",
      "/users",
    );
    expect(storageSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(
      await screen.findByRole("heading", { name: "Вход в MANA" }),
    ).toBeInTheDocument();
  });

  it("requests and verifies a six-digit Telegram code with controlled errors", async () => {
    let verificationAttempts = 0;
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.includes("/auth/session")) {
        return jsonResponse({
          authenticated: false,
          user: null,
          expires_at: null,
          ads_provider: null,
          provider_mode: null,
          live_meta_read_only: false,
        });
      }
      if (url.includes("request-code")) {
        expect(JSON.parse(requestBodyText(init?.body)) as unknown).toEqual({
          telegram_id: 976835256,
        });
        return jsonResponse(
          {
            message: "If access is enabled, a code was sent.",
            expires_in_seconds: 60,
            resend_after_seconds: 30,
            bot_url: "https://t.me/mana_test_bot",
          },
          202,
        );
      }
      if (url.includes("verify-code")) {
        verificationAttempts += 1;
        expect(JSON.parse(requestBodyText(init?.body)) as unknown).toEqual({
          telegram_id: 976835256,
          code: verificationAttempts === 1 ? "111111" : "222222",
        });
        if (verificationAttempts === 1) {
          return jsonResponse({ detail: "invalid_code" }, 401);
        }
        document.cookie = "mana_csrf=csrf-token; path=/";
        return jsonResponse(authenticatedSession);
      }
      if (url.includes("/dashboard")) {
        return jsonResponse({
          agents: [],
          global_kill_switch: false,
          generated_at: "2026-07-22T08:00:00Z",
        });
      }
      return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderShell();

    fireEvent.change(await screen.findByLabelText("Telegram ID"), {
      target: { value: "976835256" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    const codeInput = await screen.findByLabelText("Код из Telegram");
    await waitFor(() => expect(codeInput).toHaveFocus());
    expect(screen.getByRole("link", { name: "Открыть бота" })).toHaveAttribute(
      "href",
      "https://t.me/mana_test_bot",
    );

    fireEvent.change(codeInput, { target: { value: "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный код");

    fireEvent.change(codeInput, { target: { value: "222222" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByText("Test Admin")).toBeInTheDocument();
    expect(verificationAttempts).toBe(2);
  });

  it("returns to Telegram login when an established session receives 401", async () => {
    document.cookie = "mana_csrf=csrf-token; path=/";
    jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input);
      if (url.includes("/auth/session"))
        return jsonResponse(authenticatedSession);
      return jsonResponse({ detail: "Authentication required" }, 401);
    });
    renderShell();
    expect(
      await screen.findByRole("heading", { name: "Вход в MANA" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Сессия завершена");
  });
});
