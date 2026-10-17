import type { components } from "@/api/schema";

type Prepare = components["schemas"]["WorkspaceContactPrepare"];
export type PreparationAttempt = {
  version: 1;
  scope: string;
  request: Prepare;
  state: "unknown" | "refused" | "recorded";
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function preparationScope(
  owner: string,
  topic: string,
  turn: string,
): string {
  return `mana:contact-preparation:v1:${JSON.stringify([owner, topic, turn])}`;
}

function validate(value: unknown, scope: string): PreparationAttempt {
  if (typeof value !== "object" || value === null)
    throw Error("Invalid attempt");
  const v = value as Record<string, unknown>;
  const request = v.request;
  if (
    v.version !== 1 ||
    v.scope !== scope ||
    typeof v.state !== "string" ||
    !["unknown", "refused", "recorded"].includes(v.state) ||
    Object.keys(v).some(
      (k) => !["version", "scope", "request", "state"].includes(k),
    ) ||
    typeof request !== "object" ||
    request === null
  )
    throw Error("Invalid attempt");
  const r = request as Record<string, unknown>;
  if (
    typeof r.request_id !== "string" ||
    !UUID.test(r.request_id) ||
    r.confirmed !== true ||
    typeof r.recipient !== "string" ||
    !["sample_ru", "sample_uz"].includes(r.recipient) ||
    typeof r.template !== "string" ||
    !["onboarding_help", "renewal_reminder"].includes(r.template) ||
    (r.selection_fingerprint !== undefined &&
      (typeof r.selection_fingerprint !== "string" ||
        !/^[a-f0-9]{64}$/.test(r.selection_fingerprint))) ||
    Object.keys(r).some(
      (k) =>
        ![
          "request_id",
          "confirmed",
          "recipient",
          "template",
          "selection_fingerprint",
        ].includes(k),
    )
  )
    throw Error("Invalid request");
  return value as PreparationAttempt;
}

export function loadPreparationAttempt(
  scope: string,
): PreparationAttempt | null {
  const raw = sessionStorage.getItem(scope);
  return raw === null ? null : validate(JSON.parse(raw), scope);
}

export function savePreparationAttempt(attempt: PreparationAttempt): void {
  validate(attempt, attempt.scope);
  const raw = JSON.stringify(attempt);
  sessionStorage.setItem(attempt.scope, raw);
  if (sessionStorage.getItem(attempt.scope) !== raw)
    throw Error("Attempt was not retained");
}
