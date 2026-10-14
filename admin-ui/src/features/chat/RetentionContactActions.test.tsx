import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
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
