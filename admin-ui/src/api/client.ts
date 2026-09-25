import type { components } from "./schema";

export type Agent = components["schemas"]["AgentDefinition"];
export type AgentDetail = components["schemas"]["AgentDetailResponse"];
export type AgentPage = components["schemas"]["Page_AgentDefinition_"];
export type AgentRun = components["schemas"]["AgentRun"];
export type AgentRunResult = components["schemas"]["AgentRunResult"];
export type RunPage = components["schemas"]["Page_AgentRun_"];
export type Dashboard = components["schemas"]["DashboardResponse"];
export type Finding = components["schemas"]["Finding"];
export type FindingPage = components["schemas"]["Page_Finding_"];
export type Recommendation = components["schemas"]["Recommendation"];
export type RecommendationPage = components["schemas"]["Page_Recommendation_"];
export type Proposal = components["schemas"]["ActionProposal"];
export type ProposalPage = components["schemas"]["Page_ActionProposal_"];
export type Approval = components["schemas"]["ApprovalRequest"];
export type ApprovalPage = components["schemas"]["Page_ApprovalRequest_"];
export type ApprovalLifecycle =
  components["schemas"]["ApprovalLifecycleResponse"];
export type Execution = components["schemas"]["ActionExecution"];
export type ExecutionPage = components["schemas"]["Page_ActionExecution_"];
export type Report = components["schemas"]["AgentReport"];
export type ReportPage = components["schemas"]["Page_AgentReport_"];
export type Schedule = components["schemas"]["AgentSchedule"];
export type SchedulePage = components["schemas"]["Page_AgentSchedule_"];
export type Configuration = components["schemas"]["AgentConfiguration"];
export type ConfigurationPage =
  components["schemas"]["Page_AgentConfiguration_"];
export type IntegrationHealth = components["schemas"]["IntegrationHealth"];
export type RunDetail = components["schemas"]["RunDetailResponse"];
export type OutcomeEvaluation = components["schemas"]["OutcomeEvaluation"];
export type OutcomeEvaluationPage =
  components["schemas"]["Page_OutcomeEvaluation_"];
export type MarketingOverview = components["schemas"]["MarketingOverview"];
export type AdEntity = components["schemas"]["AdEntity"];
export type InsightRow = components["schemas"]["InsightRow"];
export type Creative = components["schemas"]["Creative"];
export type Audience = components["schemas"]["Audience"];
export type BreakdownPerformance =
  components["schemas"]["BreakdownPerformance"];
export type Metric = components["schemas"]["Metric"];
export type AuthSession = components["schemas"]["AuthSessionResponse"];
export type AdminUser = components["schemas"]["AdminUserResponse"];
export type AdminUserPage = components["schemas"]["UserPage"];
export type AuthAuditPage = components["schemas"]["AuthAuditPage"];
export type RequestCodeResponse = components["schemas"]["RequestCodeResponse"];
export type AuthenticatedSession = AuthSession & {
  authenticated: true;
  user: NonNullable<AuthSession["user"]>;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "GET" });
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}

async function apiRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Content-Type", "application/json");
  const csrfToken = readCookie("mana_csrf");
  if (!isSafeMethod(init.method) && csrfToken !== null) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers,
    redirect: "error",
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const rawDetail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as Record<string, unknown>).detail
        : null;
    const detail =
      typeof rawDetail === "string"
        ? rawDetail
        : typeof rawDetail === "object" &&
            rawDetail !== null &&
            "message" in rawDetail
          ? String((rawDetail as Record<string, unknown>).message)
          : `Request failed with status ${String(response.status)}`;
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      csrfToken !== null
    ) {
      window.dispatchEvent(new Event("mana:unauthorized"));
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function isAuthenticatedSession(
  session: AuthSession,
): session is AuthenticatedSession {
  return session.authenticated && session.user !== null;
}

function isSafeMethod(method: string | undefined): boolean {
  return method === undefined || ["GET", "HEAD", "OPTIONS"].includes(method);
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return item === undefined
    ? null
    : decodeURIComponent(item.slice(prefix.length));
}
