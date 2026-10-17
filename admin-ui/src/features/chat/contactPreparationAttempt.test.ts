import { beforeEach, expect, it, jest } from "@jest/globals";
import { apiPost, ApiError } from "@/api/client";
import {
  loadPreparationAttempt,
  preparationScope,
  savePreparationAttempt,
  type PreparationAttempt,
} from "./contactPreparationAttempt";

beforeEach(() => sessionStorage.clear());
const scope = preparationScope("owner-a", "topic-a", "turn-a");
const attempt: PreparationAttempt = {
  version: 1,
  scope,
  state: "unknown",
  request: {
    request_id: "00000000-0000-4000-8000-000000000001",
    confirmed: true,
    recipient: "sample_uz",
    template: "onboarding_help",
  },
};

it("persists only a closed frozen fictional choice, scoped to owner/topic/turn", () => {
  savePreparationAttempt(attempt);
  expect(loadPreparationAttempt(scope)).toEqual(attempt);
  expect(
    loadPreparationAttempt(preparationScope("owner-b", "topic-a", "turn-a")),
  ).toBeNull();
  expect(Object.keys(JSON.parse(sessionStorage.getItem(scope)!))).toEqual([
    "version",
    "scope",
    "state",
    "request",
  ]);
});

it.each([
  { ...attempt, state: ["refused"] },
  { ...attempt, scope: preparationScope("other-owner", "topic-a", "turn-a") },
  { ...attempt, request: { ...attempt.request, account_ref: "forbidden" } },
  { ...attempt, request: { ...attempt.request, recipient: ["sample_uz"] } },
  { ...attempt, request: { ...attempt.request, confirmed: 1 } },
])("fails closed on malformed or foreign recovery metadata", (value) => {
  sessionStorage.setItem(scope, JSON.stringify(value));
  expect(() => loadPreparationAttempt(scope)).toThrow();
});

it.each([423, 403])(
  "recognizes the closed stopped code only at its exact status (%s)",
  async (status) => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "contact_preparation_stopped",
            message: "Synthetic refusal",
          },
        }),
        { status },
      ),
    );
    try {
      await apiPost("/fake/prepare", {});
      throw Error("Expected refusal");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).code).toBe(
        status === 423 ? "contact_preparation_stopped" : undefined,
      );
    }
  },
);
