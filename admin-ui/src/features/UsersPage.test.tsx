import { afterEach, describe, expect, it, jest } from "@jest/globals";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithSession } from "@/test/render";

import { UsersPage } from "./UsersPage";

const otherUser = {
  user_id: "00000000-0000-4000-8000-000000000002",
  telegram_id: 51456737,
  display_name: "Second Admin",
  username: "second_admin",
  role: "admin",
  status: "active",
  created_at: "2026-07-22T08:00:00Z",
  updated_at: "2026-07-22T08:00:00Z",
  last_login_at: null,
  created_by: "bootstrap",
  disabled_reason: null,
  profile_metadata: {},
  auth_locked_until: null,
};

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("UsersPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    document.cookie = "mana_csrf=; Max-Age=0; path=/";
  });

  it("creates users and exposes guarded access-management actions", async () => {
    document.cookie = "mana_csrf=csrf-token; path=/";
    jest.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = jest.fn<typeof fetch>((input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      const headers = new Headers(init?.headers);
      if (init?.method !== "GET") {
        expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
      }
      if (url.endsWith("/api/v1/admin/users") && init?.method === "POST") {
        expect(JSON.parse(String(init.body)) as unknown).toMatchObject({
          telegram_id: 777000111,
          role: "viewer",
          display_name: "Third User",
          username: "third_user",
        });
        return jsonResponse(
          { ...otherUser, user_id: "third", telegram_id: 777000111 },
          201,
        );
      }
      if (url.includes("/sessions/revoke")) {
        return jsonResponse({ revoked_sessions: 2 });
      }
      if (url.includes("/audit")) {
        return jsonResponse({
          items: [
            {
              event_id: "event-1",
              event_type: "user_created",
              occurred_at: "2026-07-22T08:00:00Z",
              actor_user_id: null,
              subject_user_id: otherUser.user_id,
              summary: "User created",
              details: {},
            },
          ],
          total: 1,
        });
      }
      if (init?.method === "PATCH") return jsonResponse(otherUser);
      return jsonResponse({ items: [otherUser], total: 1 });
    });
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    renderWithSession(<UsersPage />, "admin");

    expect(await screen.findByText("Second Admin")).toBeInTheDocument();
    const createForm = screen
      .getByText("Добавить пользователя")
      .closest("form");
    if (createForm === null) throw new Error("Create form is missing");
    fireEvent.change(within(createForm).getByLabelText("Telegram ID"), {
      target: { value: "777000111" },
    });
    fireEvent.change(within(createForm).getByLabelText("Имя"), {
      target: { value: "Third User" },
    });
    fireEvent.change(within(createForm).getByLabelText("@username"), {
      target: { value: "@third_user" },
    });
    fireEvent.click(
      within(createForm).getByRole("button", { name: "Добавить" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/admin/users"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Отключить" }));
    fireEvent.change(screen.getByLabelText("Причина отключения"), {
      target: { value: "Security review" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(otherUser.user_id),
        expect.objectContaining({ method: "PATCH" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Отозвать сессии" }));
    const auditButton = screen.getByRole("button", { name: "Аудит" });
    await waitFor(() => expect(auditButton).toBeEnabled());
    fireEvent.click(auditButton);
    expect(await screen.findByText("User created")).toBeInTheDocument();
  });

  it("does not expose management data to a non-admin session", () => {
    const fetchSpy = jest.spyOn(globalThis, "fetch");
    renderWithSession(<UsersPage />, "viewer");
    expect(
      screen.getByRole("heading", { name: "Недостаточно прав" }),
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
