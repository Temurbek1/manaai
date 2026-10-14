import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";
import type { components } from "@/api/schema";
import { renderWithSession } from "@/test/render";
import { requestUrl } from "@/test/http";
import { ContactReviewAssignment } from "./ContactReviewAssignment";
import { ContactPeerReviews } from "./ContactPeerReviews";

const action: components["schemas"]["WorkspaceContactView"] = {
  action_id: "action-1",
  topic_id: "private-topic",
  turn_id: "private-turn",
  recipient: "sample_uz",
  product: "mana",
  synthetic: true,
  provider: "fake_retention_contact",
  message: {
    template: "onboarding_help",
    version: "retention-contact-uz-v1",
    language: "uz",
    text: "MANA: sozlashda yordam kerakmi?",
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
const reviewer = {
  user_id: "00000000-0000-4000-8000-000000000002",
  label: "Second employee",
};
const grant = {
  review_id: "review-1",
  reviewer,
  expires_at: action.expires_at,
  revoked: false,
};

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("single-action peer review", () => {
  it("shares only the exact action, then permits a separate explicit revocation", async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    let current: typeof grant | null = null;
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.method === "POST") {
        posts.push({
          url: requestUrl(input),
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        });
        current = { ...grant, revoked: requestUrl(input).endsWith("/revoke") };
        return response(current);
      }
      return response({
        reviewers: [reviewer],
        more_omitted: false,
        review: current,
      });
    });
    renderWithSession(
      <ContactReviewAssignment action={action} url="/selected-action" />,
    );
    fireEvent.change(await screen.findByLabelText("Согласующий сотрудник"), {
      target: { value: reviewer.user_id },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Передать на согласование" }),
    );
    expect(posts).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить передачу" }),
    );
    await screen.findByRole("link", {
      name: "Ссылка для выбранного сотрудника",
    });
    expect(posts).toHaveLength(1);
    expect(posts[0]!.body).toMatchObject({
      reviewer_id: reviewer.user_id,
      confirmed: true,
      fingerprint: action.fingerprint,
    });
    expect(posts[0]!.body).not.toHaveProperty("topic_access");
    fireEvent.click(screen.getByRole("button", { name: "Отозвать доступ" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить отзыв" }));
    await screen.findByText("Доступ к согласованию отозван.");
    expect(posts).toHaveLength(2);
    expect(posts[1]!.url).toMatch(/\/review\/revoke$/);
  });

  it("a lost share response cannot issue another disclosure", async () => {
    let posts = 0;
    jest.spyOn(globalThis, "fetch").mockImplementation((_, init) => {
      if (init?.method === "POST") {
        posts++;
        return Promise.reject(new Error("Lost reply"));
      }
      return response({
        reviewers: [reviewer],
        more_omitted: false,
        review: null,
      });
    });
    renderWithSession(
      <ContactReviewAssignment action={action} url="/selected-action" />,
    );
    fireEvent.change(await screen.findByLabelText("Согласующий сотрудник"), {
      target: { value: reviewer.user_id },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Передать на согласование" }),
    );
    const confirm = screen.getByRole("button", {
      name: "Подтвердить передачу",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await screen.findByText(
      "Ответ не подтверждён. Повтор не отправлен. Обновите статус.",
    );
    expect(posts).toBe(1);
    expect(
      screen.getByRole("button", { name: "Передать на согласование" }),
    ).toBeDisabled();
  });

  it("the selected reviewer confirms the unchanged message at the scoped endpoint", async () => {
    const posts: string[] = [];
    let saved = action;
    jest.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("availability"))
        return response({ retention_peer_reviews_enabled: true });
      if (init?.method === "POST") {
        posts.push(url);
        saved = { ...action, status: "verified", decision_recorded: true };
        return response(saved);
      }
      return response({ review_id: grant.review_id, action: saved });
    });
    renderWithSession(<ContactPeerReviews reviewId="review-1" />);
    expect(await screen.findByText(action.message.text)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Причина решения"), {
      target: { value: "Reviewed exact Uzbek text" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Отправить в sandbox" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подтвердить тестовую отправку" }),
    );
    await screen.findByText("Принято тестовым получателем");
    expect(posts).toEqual([
      "/api/v1/admin/operation/workspace/retention-contact-reviews/review-1/action-1/decision",
    ]);
    expect(screen.getByText(action.message.text)).toHaveAttribute("lang", "uz");
    expect(
      screen.queryByRole("button", { name: "Передать на согласование" }),
    ).not.toBeInTheDocument();
  });

  it("disabled availability never loads a private review", async () => {
    const requests: string[] = [];
    jest.spyOn(globalThis, "fetch").mockImplementation((input) => {
      requests.push(requestUrl(input));
      return response({ retention_peer_reviews_enabled: false });
    });
    renderWithSession(<ContactPeerReviews />);
    await screen.findByText("Согласование другим сотрудником отключено.");
    await waitFor(() =>
      expect(requests.every((url) => url.endsWith("availability"))).toBe(true),
    );
  });
});
