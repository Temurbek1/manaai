import type { Report } from "@/api/client";
import { isRecord } from "@/ui/format";

export const ANALYTICS_SOURCES = {
  ga4: { label: "GA4", capability: "retention.parent_activity.analyze" },
  firestore: {
    label: "Firebase",
    capability: "retention.child_telemetry.analyze",
  },
  parents: { label: "Parent API", capability: "retention.parents.analyze" },
} as const;
export type AnalyticsSource = keyof typeof ANALYTICS_SOURCES;
export type SavedAnalytics = {
  report: Report;
  facts: Record<string, unknown>;
  collectedAt: string;
  demo: boolean;
};

export function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

export function measure(value: unknown): number | null {
  if (
    typeof value !== "number" &&
    !(typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value))
  )
    return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 1e18
    ? number
    : null;
}

function day(value: unknown): number | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
    return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) &&
    new Date(parsed).toISOString().slice(0, 10) === value
    ? parsed
    : null;
}

export function savedAnalytics(
  report: Report,
  source: AnalyticsSource,
  now = Date.now(),
): SavedAnalytics | null {
  const facts = report.structured;
  if (
    report.agent_id !== "retention-agent" ||
    report.capability_key !== ANALYTICS_SOURCES[source].capability ||
    !isRecord(facts) ||
    facts.scope_verified !== true ||
    facts.product !== "mana" ||
    facts.scope_basis !==
      (source === "parents"
        ? "owner_confirmed_parent_api"
        : "approved_source_binding") ||
    typeof facts.collected_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(
      facts.collected_at,
    ) ||
    !Number.isFinite(Date.parse(facts.collected_at)) ||
    Date.parse(facts.collected_at) > now
  )
    return null;
  if (source === "parents") {
    if (
      report.report_type !== "mana_parent_summary" ||
      !["demo", "live_read_only"].includes(String(facts.mode))
    )
      return null;
  } else if (
    report.report_type !== "mana_first_party_analytics" ||
    facts.product_scope !== "mana" ||
    facts.source !==
      (source === "ga4"
        ? "mana_ga4_parent_analytics"
        : "mana_firestore_child_telemetry") ||
    facts.population !==
      (source === "ga4"
        ? "parent_app_analytics_identities"
        : "child_device_prefix_sample")
  )
    return null;
  return {
    report,
    facts,
    collectedAt: facts.collected_at,
    demo: facts.mode === "demo",
  };
}

export type ActivityWindow = {
  days: 1 | 7 | 30;
  start: string;
  end: string;
  users: number;
  sessions: number;
  engaged: number;
  seconds: number;
};

export function activityWindows(
  facts: Record<string, unknown>,
): ActivityWindow[] {
  if (!Array.isArray(facts.windows) || facts.windows.length > 3) return [];
  const result: ActivityWindow[] = [];
  for (const row of facts.windows) {
    if (!isRecord(row) || ![1, 7, 30].includes(Number(row.days))) return [];
    const start = day(row.start_date),
      end = day(row.end_date);
    const users = count(row.active_users),
      sessions = count(row.sessions),
      engaged = count(row.engaged_sessions);
    const seconds = measure(row.engagement_seconds);
    if (
      typeof row.days !== "number" ||
      start === null ||
      end === null ||
      row.end_date !== facts.period_end ||
      end - start !== (row.days - 1) * 86400000 ||
      users === null ||
      sessions === null ||
      engaged === null ||
      engaged > sessions ||
      seconds === null ||
      result.some((item) => item.days === row.days)
    )
      return [];
    result.push({
      days: row.days as ActivityWindow["days"],
      start: String(row.start_date),
      end: String(row.end_date),
      users,
      sessions,
      engaged,
      seconds,
    });
  }
  return result;
}

export function eventCounts(
  facts: Record<string, unknown>,
): { name: string; value: number }[] {
  if (!isRecord(facts.event_counts)) return [];
  const entries = Object.entries(facts.event_counts);
  if (
    entries.length > 500 ||
    entries.some(
      ([name, value]) =>
        !/^[a-zA-Z0-9_]{1,80}$/.test(name) || count(value) === null,
    )
  )
    return [];
  return entries
    .map(([name, value]) => ({ name, value: Number(value) }))
    .sort((a, b) => b.value - a.value);
}

export type Cohort = {
  date: string;
  complete: boolean;
  returns: (string | null)[];
};
export function retentionCohorts(facts: Record<string, unknown>): Cohort[] {
  if (!Array.isArray(facts.cohorts) || facts.cohorts.length > 2) return [];
  return facts.cohorts
    .filter(isRecord)
    .filter((cohort) => day(cohort.first_session_date) !== null)
    .map((cohort) => {
      const rows = Array.isArray(cohort.days)
        ? cohort.days.filter(isRecord)
        : [];
      const complete =
        day(facts.period_end) !== null &&
        [30, 31].some(
          (offset) =>
            day(facts.period_end)! - day(cohort.first_session_date)! ===
            offset * 86400000,
        ) &&
        cohort.quality === "complete" &&
        rows.length === 31 &&
        new Set(rows.map((row) => row.day)).size === 31 &&
        rows.every(
          (row) =>
            count(row.day) !== null &&
            Number(row.day) <= 30 &&
            count(row.active_users) !== null &&
            count(row.total_users) !== null &&
            Number(row.total_users) > 0 &&
            Number(row.active_users) <= Number(row.total_users),
        ) &&
        new Set(rows.map((row) => row.total_users)).size === 1 &&
        rows.some(
          (row) => row.day === 0 && row.active_users === row.total_users,
        );
      return {
        date: String(cohort.first_session_date),
        complete,
        returns: [1, 7, 30].map((target) => {
          const row = rows.find((value) => value.day === target);
          return complete && row
            ? `${String(row.active_users)} / ${String(row.total_users)}`
            : null;
        }),
      };
    });
}

export function telemetrySamples(
  facts: Record<string, unknown>,
): Record<string, unknown>[] {
  if (
    !Array.isArray(facts.samples) ||
    facts.samples.length !== 2 ||
    !facts.samples.every(isRecord)
  )
    return [];
  const rows = facts.samples;
  if (
    rows[0]?.collection !== "battery" ||
    rows[1]?.collection !== "children_location"
  )
    return [];
  if (
    rows.some((row) => {
      const sampled = count(row.sampled_documents),
        valid = count(row.valid_observations),
        invalid = count(row.invalid_observations);
      return (
        sampled === null ||
        sampled > 100 ||
        valid === null ||
        invalid === null ||
        valid + invalid !== sampled ||
        count(row.recent_server_updates) === null ||
        Number(row.recent_server_updates) > sampled ||
        count(
          row.collection === "battery"
            ? row.low_battery_observations
            : row.precise_location_observations,
        ) === null ||
        Number(
          row.collection === "battery"
            ? row.low_battery_observations
            : row.precise_location_observations,
        ) > valid
      );
    })
  )
    return [];
  return rows;
}

export const BREAKDOWN_LABELS = {
  screens: "Экраны",
  devices: "Устройства",
  geography: "География",
  acquisition: "Источники привлечения",
  weekday_hour: "Дни и часы",
  notification_open_minutes: "Открытия уведомлений",
} as const;

export function breakdowns(
  facts: Record<string, unknown>,
): Record<string, unknown>[] {
  if (!Array.isArray(facts.breakdowns) || facts.breakdowns.length > 6)
    return [];
  return facts.breakdowns.filter(isRecord).filter(
    (group) =>
      typeof group.kind === "string" &&
      group.kind in BREAKDOWN_LABELS &&
      Array.isArray(group.rows) &&
      group.rows.length <= 10 &&
      ["complete", "partial", "missing", "sampled", "thresholded"].includes(
        String(group.quality),
      ) &&
      count(group.total_groups) !== null &&
      Number(group.total_groups) >= group.rows.length &&
      group.rows.every(
        (row) =>
          isRecord(row) &&
          isRecord(row.labels) &&
          isRecord(row.measures) &&
          Object.keys(row.labels).every((key) =>
            (
              ({
                screens: ["screen_name", "screen_class"],
                devices: [
                  "model",
                  "manufacturer",
                  "os",
                  "os_version",
                  "app_version",
                  "language",
                  "device_type",
                ],
                geography: ["country", "region", "city"],
                acquisition: [
                  "source",
                  "medium",
                  "campaign",
                  "platform",
                  "channel",
                ],
                weekday_hour: ["day_of_week", "hour"],
                notification_open_minutes: ["date_minute"],
              }) as Record<string, string[]>
            )[String(group.kind)]?.includes(key),
          ) &&
          Object.keys(row.measures).every((key) =>
            [
              "active_users",
              "event_count",
              "views",
              "new_users",
              "sessions",
              "engagement_seconds",
            ].includes(key),
          ) &&
          Object.values(row.labels).every(
            (value) =>
              value === null ||
              (typeof value === "string" &&
                value.length > 0 &&
                value.length <= 80),
          ) &&
          Object.values(row.measures).every((value) => measure(value) !== null),
      ) &&
      (group.quality !== "complete" ||
        (group.rows.length > 0 &&
          group.total_groups === group.rows.length &&
          (group.withheld_rows === undefined || group.withheld_rows === 0) &&
          group.rows.every(
            (row) =>
              isRecord(row) &&
              isRecord(row.labels) &&
              Object.values(row.labels).every((value) => value !== null),
          ))),
  );
}
