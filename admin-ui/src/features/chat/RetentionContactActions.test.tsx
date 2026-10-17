import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { renderWithSession } from "@/test/render";
import { requestUrl } from "@/test/http";
import { RetentionContactActions } from "./RetentionContactActions";
import type { components } from "@/api/schema";

type Contact = components["schemas"]["WorkspaceContactView"];
const contact: Contact = {
  action_id: "action-1",
  topic_id: "topic-1",
  turn_id: "turn-1",
  recipient: "sample_uz",
  product: "mana",
  synthetic: true,
  provider: "fake_retention_contact",
  message: {
    template: "onboarding_help",
    version: "retention-contact-uz-v1",
    language: "uz",
    text: "Exact fictional approved text",
    sha256: "a".repeat(64),
  },
  fingerprint: "b".repeat(64),
  expires_at: "2099-10-01T12:00:00Z",
  status: "proposed",
  revision: 0,
  result_code: "awaiting_human_decision",
  policy_reasons: [],
  self_approval_forbidden: false,
  decision_recorded: false,
  business_outcome: "not_measured",
};
const recipients = [
  { key: "sample_ru", language: "ru", synthetic: true },
  { key: "sample_uz", language: "uz", synthetic: true },
];
function response(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("Retention contact chat lane", () => {
  beforeEach(() => sessionStorage.clear());
  const basePage = {
    items: [],
    recipients,
    more_omitted: false,
    preparation_availability: { state: "requires_confirmation" },
  };
  async function confirmPreparation(): Promise<void> {
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Подготовить тестовое сообщение",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить подготовку" }),
    );
  }

  it("requires a fresh observation and another human confirmation after a closed stop, retaining exact request", async () => {
    const posts: Array<Record<string, unknown>> = [];
    let armed = false;
    const saved = { ...contact, recipient: "sample_ru" };
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return posts.length === 1
          ? Promise.resolve(
              new Response(
                JSON.stringify({
                  detail: {
                    code: "contact_preparation_stopped",
                    message:
                      "Подготовка контактных действий Retention остановлена.",
                  },
                }),
                { status: 423 },
              ),
            )
          : response(saved);
      }
      if (requestUrl(input).includes("/preparation?"))
        return response({
          request_id: posts[0]!.request_id,
          state: "absent",
          action: null,
        });
      return response({
        ...basePage,
        preparation_availability: {
          state: posts.length && !armed ? "stopped" : "requires_confirmation",
        },
      });
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    await confirmPreparation();
    await screen.findByText(
      "Подготовка контактных действий Retention остановлена.",
    );
    expect(
      screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
    ).toBeDisabled();
    armed = true;
    fireEvent.click(
      screen.getByRole("button", { name: "Проверить подготовку" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
      ).toBeEnabled(),
    );
    expect(posts).toHaveLength(1);
    await confirmPreparation();
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
  });

  it("retains an unknown request across reload and observes an absent/recorded row without another POST", async () => {
    const posts: Array<Record<string, unknown>> = [];
    let recorded = false;
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return Promise.reject(new Error("Synthetic lost acknowledgement"));
      }
      if (requestUrl(input).includes("/preparation?"))
        return response({
          request_id: posts[0]!.request_id,
          state: recorded ? "recorded" : "absent",
          action: recorded ? { ...contact, recipient: "sample_ru" } : null,
        });
      return response(basePage);
    });
    const first = renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    await confirmPreparation();
    await screen.findByText(
      "Результат подготовки неизвестен. Новый запрос не отправляется.",
    );
    await screen.findByText(
      "Ответ не подтверждён. Повтор не отправлен. Обновите статус.",
    );
    first.unmount();
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    await screen.findByText(
      "Результат подготовки неизвестен. Новый запрос не отправляется.",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Проверить подготовку" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Проверить подготовку" }),
      ).toBeEnabled(),
    );
    expect(
      screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
    ).toBeDisabled();
    recorded = true;
    fireEvent.click(
      screen.getByRole("button", { name: "Проверить подготовку" }),
    );
    expect(await screen.findByText(contact.message.text)).toBeVisible();
    expect(posts).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
    ).toBeDisabled();
  });

  it("refuses before POST when browser recovery storage cannot persist the frozen choice", async () => {
    const fetch = jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response(basePage));
    jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw Error("Synthetic storage denial");
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    await confirmPreparation();
    expect(
      await screen.findByText(
        "Не удалось сохранить запрос подготовки. Подготовка заблокирована.",
      ),
    ).toBeVisible();
    expect(fetch.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(
      true,
    );
  });

  it("does not prepare against an older server missing admission metadata", async () => {
    jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => response({ items: [], recipients }));
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    expect(
      await screen.findByRole("button", {
        name: "Подготовить тестовое сообщение",
      }),
    ).toBeDisabled();
  });
  it.each([false, true])(
    "continues one frozen SQL result and only observes a lost answer (%s)",
    async (lost) => {
      const posts: Array<Record<string, unknown>> = [];
      const onContinued = jest
        .fn<() => Promise<void>>()
        .mockResolvedValue(undefined);
      let claimed = false;
      jest.spyOn(globalThis, "fetch").mockImplementation((_, init) => {
        if (init?.method === "POST") {
          posts.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          claimed = true;
          return lost
            ? Promise.reject(new Error("Lost response"))
            : response({ turn_id: "child-1", status: "completed" });
        }
        return response({
          items: [contact],
          recipients,
          more_omitted: false,
          continuation_available: !claimed,
          continuation: claimed
            ? {
                turn_id: "child-1",
                status: lost ? "failed" : "completed",
                answer: "Saved result",
              }
            : null,
        });
      });
      renderWithSession(
        <RetentionContactActions
          topicId="topic-1"
          turnId="turn-1"
          onContinued={onContinued}
        />,
      );
      const button = await screen.findByRole("button", {
        name: "Продолжить с агентом",
      });
      expect(posts).toHaveLength(0);
      fireEvent.click(button);
      expect(
        await screen.findByRole("link", { name: "Продолжение в чате" }),
      ).toHaveAttribute("href", "#turn-child-1");
      expect(posts).toHaveLength(1);
      expect(posts[0]).toMatchObject({
        confirmed: true,
        action_id: contact.action_id,
        action_fingerprint: contact.fingerprint,
        revision: contact.revision,
      });
      expect(posts[0]).not.toHaveProperty("output");
      expect(
        screen.queryByRole("button", { name: "Продолжить с агентом" }),
      ).not.toBeInTheDocument();
      await waitFor(() => expect(onContinued).toHaveBeenCalledTimes(1));
    },
  );
  it("confirms the frozen native selection without replacing it with manual fields", async () => {
    const posts: Array<Record<string, unknown>> = [];
    const preparation = {
      recipient: "sample_uz",
      template: "renewal_reminder",
      selection_fingerprint: "c".repeat(64),
    };
    jest.spyOn(globalThis, "fetch").mockImplementation((_, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return response(contact);
      }
      return response({
        items: [],
        recipients,
        more_omitted: false,
        preparation_request: preparation,
        preparation_availability: { state: "requires_confirmation" },
      });
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    await screen.findByText(/Агент выбрал тестовое действие/);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
    );
    expect(posts).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить подготовку" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ ...preparation, confirmed: true });
  });
  it("prepares an explicit fictional recipient without dispatching its decision", async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    let saved = false;
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        posts.push({
          url,
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        });
        saved = true;
        return response(contact);
      }
      return response({
        items: saved ? [contact] : [],
        recipients,
        templates: ["onboarding_help", "renewal_reminder"],
        preparation_availability: { state: "requires_confirmation" },
        more_omitted: false,
      });
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    const recipient = await screen.findByLabelText("Вымышленный получатель");
    fireEvent.change(recipient, { target: { value: "sample_uz" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Подготовить тестовое сообщение" }),
    );
    expect(posts).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить подготовку" }),
    );
    expect(await screen.findByText(contact.message.text)).toBeVisible();
    expect(posts).toHaveLength(1);
    expect(posts[0]!.url).toMatch(/retention-contacts\/prepare$/);
    expect(posts[0]!.body).toMatchObject({
      confirmed: true,
      recipient: "sample_uz",
      template: "onboarding_help",
    });
    expect(posts[0]!.body).not.toHaveProperty("language");
    expect(posts[0]!.body).not.toHaveProperty("account_ref");
  });

  it("records exact approval once and never resends a lost response", async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts.push({
          url: requestUrl(input),
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        });
        return Promise.reject(new Error("Lost acknowledgement"));
      }
      return response({ items: [contact], recipients, more_omitted: false });
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    fireEvent.change(
      await screen.findByRole("textbox", { name: "Причина решения" }),
      { target: { value: "Reviewed exact text" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить в sandbox" }),
    );
    expect(posts).toHaveLength(0);
    const confirm = screen.getByRole("button", {
      name: "Подтвердить тестовую отправку",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await screen.findByText(
      "Ответ не подтверждён. Повтор не отправлен. Обновите статус.",
    );
    expect(posts).toHaveLength(1);
    expect(posts[0]!.body).toMatchObject({
      confirmed: true,
      approve: true,
      reason: "Reviewed exact text",
      fingerprint: contact.fingerprint,
    });
    expect(
      screen.getByRole("button", { name: "Отправить в sandbox" }),
    ).toBeDisabled();
  });

  it("reconciliation observes a receipt, never repeats a send", async () => {
    const posts: string[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") posts.push(requestUrl(input));
      return response({
        items: [{ ...contact, status: "uncertain", decision_recorded: true }],
        recipients,
        more_omitted: false,
      });
    });
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Проверить квитанцию" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить проверку квитанции" }),
    );
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(/\/reconcile$/);
    expect(
      screen.queryByRole("button", { name: "Отправить в sandbox" }),
    ).not.toBeInTheDocument();
  });

  it("viewers cannot prepare or confirm customer actions", async () => {
    const fetch = jest
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        response({ items: [contact], recipients, more_omitted: false }),
      );
    renderWithSession(
      <RetentionContactActions topicId="topic-1" turnId="turn-1" />,
      "viewer",
    );
    await screen.findByText(contact.message.text);
    expect(
      screen.getByRole("button", { name: "Отправить в sandbox" }),
    ).toBeDisabled();
    expect(fetch.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(
      true,
    );
  });
});
