import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, jest } from "@jest/globals";
import { ManualActionControls } from "./ManualActionControls";
import { renderWithSession } from "@/test/render";
import { requestUrl, requestBodyText } from "@/test/http";
import {
  LanguageProvider,
  LANGUAGE_STORAGE_KEY,
} from "@/i18n/LanguageProvider";

const state = {
  definition: {
    agent_id: "retention-agent",
    capability_key: "retention.contact.sandbox",
    product: "mana",
    provider: "fake_retention_contact",
    execution_mode: "human_review_sandbox",
  },
  capability_kill_switch: false,
  agent_kill_switch: false,
  global_kill_switch: true,
};
const response = (body: unknown): Response =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
});

it("does not discover action controls when an older or disabled server has no contact grant", async () => {
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(response({ enabled: true })));
  renderWithSession(<ManualActionControls />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(
    screen.queryByRole("heading", { name: "Ручные действия Retention" }),
  ).not.toBeInTheDocument();
  expect(requestUrl(fetch.mock.calls[0]![0])).toBe(
    "/api/v1/admin/operation/chat/availability",
  );
});

it("requires a scoped confirmation and reobserves SQL without changing the global stop", async () => {
  let stopped = false;
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (requestUrl(input).endsWith("chat/availability"))
        return response({ retention_contact_reviews_enabled: true });
      if (init?.method === "PUT") {
        expect(requestUrl(input)).toBe(
          "/api/v1/admin/operation/workspace/manual-action-controls/retention-agent/retention.contact.sandbox",
        );
        expect(JSON.parse(requestBodyText(init.body))).toEqual({
          confirmed: true,
          enabled: true,
        });
        stopped = true;
        return response({ ...state, capability_kill_switch: stopped });
      }
      return response({
        items: [{ ...state, capability_kill_switch: stopped }],
      });
    });
  renderWithSession(<ManualActionControls />);
  const stop = await screen.findByRole("button", {
    name: "Остановить sandbox",
  });
  expect(
    screen.getByText(
      "Дополнительно действует остановка агента или всей платформы.",
    ),
  ).toBeVisible();
  fireEvent.click(stop);
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === "PUT"),
  ).toHaveLength(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Подтвердить остановку" }),
  );
  expect(await screen.findByText("Остановка включена")).toBeVisible();
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === "PUT"),
  ).toHaveLength(1);
  expect(
    screen.getByText(
      "Дополнительно действует остановка агента или всей платформы.",
    ),
  ).toBeVisible();
});

it("blocks mutations after a lost acknowledgement until an explicit GET observation", async () => {
  let stopped = false;
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      if (requestUrl(input).endsWith("chat/availability"))
        return response({ retention_contact_reviews_enabled: true });
      if (init?.method === "PUT") {
        stopped = true;
        throw new Error("Synthetic lost acknowledgement");
      }
      return response({
        items: [{ ...state, capability_kill_switch: stopped }],
      });
    });
  renderWithSession(<ManualActionControls />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Остановить sandbox" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Подтвердить остановку" }),
  );
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Остановить sandbox" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Проверить состояние" }));
  expect(await screen.findByText("Остановка включена")).toBeVisible();
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === "PUT"),
  ).toHaveLength(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps observer-only Uzbek controls non-mutating", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "uz");
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation((input) =>
      Promise.resolve(
        response(
          requestUrl(input).endsWith("chat/availability")
            ? { retention_contact_reviews_enabled: true }
            : { items: [state] },
        ),
      ),
    );
  renderWithSession(
    <LanguageProvider>
      <ManualActionControls />
    </LanguageProvider>,
    "viewer",
  );
  expect(
    await screen.findByRole("heading", {
      name: "Retention qo‘lda boshqariladigan amallari",
    }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Sinov muhitini to‘xtatish" }),
  ).toBeDisabled();
  expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
    true,
  );
});
