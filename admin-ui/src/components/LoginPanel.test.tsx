import { afterEach, describe, expect, it, jest } from "@jest/globals";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { LoginPanel } from "./LoginPanel";

function jsonResponse(body: unknown, status = 202): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("LoginPanel", () => {
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("supports pasted OTP input, resend cooldown, expiry, and changing identity", async () => {
    jest.useFakeTimers({ now: new Date("2026-07-22T12:00:00Z") });
    const fetchMock = jest.fn<typeof fetch>(() =>
      jsonResponse({
        message: "Generic response",
        expires_in_seconds: 60,
        resend_after_seconds: 30,
        bot_url: "https://t.me/mana_test_bot",
      }),
    );
    jest.spyOn(globalThis, "fetch").mockImplementation(fetchMock);
    render(<LoginPanel notice={null} onAuthenticated={jest.fn()} />);

    fireEvent.change(screen.getByLabelText("Telegram ID"), {
      target: { value: "976835256" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Получить код" }));
    await act(async () => Promise.resolve());

    const codeInput = screen.getByLabelText("Код из Telegram");
    fireEvent.change(codeInput, { target: { value: "12a345678" } });
    expect(codeInput).toHaveValue("123456");
    expect(
      screen.getByRole("button", { name: /Отправить снова через 30/ }),
    ).toBeDisabled();

    act(() => jest.advanceTimersByTime(30_000));
    expect(
      screen.getByRole("button", { name: "Отправить новый код" }),
    ).toBeEnabled();

    act(() => jest.advanceTimersByTime(30_000));
    expect(screen.getByText("Срок действия кода истёк.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Войти" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    expect(screen.getByLabelText("Telegram ID")).toHaveValue("976835256");
    expect(screen.queryByLabelText("Код из Telegram")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows the same successful request state without relying on response identity details", async () => {
    jest.spyOn(globalThis, "fetch").mockImplementation(() =>
      jsonResponse({
        message: "If access is enabled, a login code was sent.",
        expires_in_seconds: 60,
        resend_after_seconds: 30,
        bot_url: null,
      }),
    );
    render(<LoginPanel notice={null} onAuthenticated={jest.fn()} />);
    fireEvent.change(screen.getByLabelText("Telegram ID"), {
      target: { value: "123456789" },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Получить код" }).closest("form")!,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Код из Telegram")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Бот пока не может/)).toBeInTheDocument();
  });
});
