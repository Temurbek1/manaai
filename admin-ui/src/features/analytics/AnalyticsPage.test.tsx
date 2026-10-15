import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, jest } from "@jest/globals";
import { AnalyticsPage } from "./AnalyticsPage";
import {
  activityWindows,
  eventCounts,
  retentionCohorts,
  savedAnalytics,
  telemetrySamples,
} from "./savedAnalytics";
import fixtures from "@/test/fixtures/analytics-reports.json";
import { requestUrl } from "@/test/http";
import { renderWithSession } from "@/test/render";
import {
  LanguageProvider,
  LANGUAGE_STORAGE_KEY,
} from "@/i18n/LanguageProvider";

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
});

it("views three isolated saved sources with GETs only and switches existing windows locally", async () => {
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation((input, init) => {
      const url = requestUrl(input);
      expect(init?.method ?? "GET").toBe("GET");
      expect(url).toMatch(/^\/api\/v1\/admin\/operation\/reports\?/);
      const body = url.includes("parent_activity")
        ? fixtures.ga4
        : url.includes("child_telemetry")
          ? fixtures.firestore
          : fixtures.parents;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
  renderWithSession(<AnalyticsPage />);
  expect(await screen.findByText("2 140")).toBeInTheDocument();
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  fireEvent.click(screen.getByRole("button", { name: "7 дней" }));
  expect(screen.getByText("860")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(screen.getByText("Неполные данные")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Firebase/ }));
  expect(
    await screen.findByRole("heading", {
      name: "Телеметрия детских устройств",
    }),
  ).toBeVisible();
  expect(
    screen.getByText("Две ограниченные выборки, не статистика всей базы"),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Parent API/ }));
  expect(await screen.findByText("4 500")).toBeInTheDocument();
  expect(screen.getByText("Не подтверждает оплату")).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("button", { name: "Обновить экран" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  expect(requestUrl(fetch.mock.calls[3]![0])).toContain(
    "capability_key=retention.parents.analyze",
  );
});

it("does not describe a failed refresh as an empty source or expose hidden stale metrics", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(fixtures.ga4), {
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  renderWithSession(<AnalyticsPage />);
  expect(await screen.findByText("2 140")).toBeInTheDocument();
  fetch.mockRejectedValue(new Error("Synthetic SQL outage"));
  fireEvent.click(screen.getByRole("button", { name: "Обновить экран" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Данные недоступны — это не означает, что записей нет.",
  );
  expect(screen.queryByText("2 140")).not.toBeInTheDocument();
  expect(
    screen.queryByText("Показаны ранее полученные данные.", { exact: false }),
  ).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(4);
});

it("shows no invented zeros for missing reports and supports Uzbek without extra reads", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "uz");
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ items: [], total: 0, limit: 5, offset: 0 }),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
  renderWithSession(
    <LanguageProvider>
      <AnalyticsPage />
    </LanguageProvider>,
  );
  expect(
    await screen.findByRole("heading", {
      name: "Tasdiqlangan saqlangan hisobot yo‘q",
    }),
  ).toBeVisible();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("rejects foreign scope, future dates and malformed numeric evidence", () => {
  const report = fixtures.ga4.items[0]!;
  expect(
    savedAnalytics(
      { ...report, structured: { ...report.structured, product: "360rec" } },
      "ga4",
    ),
  ).toBeNull();
  expect(
    savedAnalytics(
      {
        ...report,
        structured: { ...report.structured, scope_basis: "unknown" },
      },
      "ga4",
    ),
  ).toBeNull();
  expect(
    savedAnalytics(
      {
        ...report,
        structured: {
          ...report.structured,
          collected_at: "2099-01-01T00:00:00Z",
        },
      },
      "ga4",
    ),
  ).toBeNull();
  for (const collected_at of ["2026-09-30", "2026-09-30T12:00:00"]) {
    expect(
      savedAnalytics(
        { ...report, structured: { ...report.structured, collected_at } },
        "ga4",
      ),
    ).toBeNull();
  }
  expect(
    activityWindows({
      ...report.structured,
      windows: [{ ...report.structured.windows[0], active_users: -1 }],
    }),
  ).toEqual([]);
  expect(eventCounts({ event_counts: { button_click: "100" } })).toEqual([]);
  const sample = fixtures.firestore.items[0]!.structured;
  expect(
    telemetrySamples({
      ...sample,
      samples: [
        { ...sample.samples[0], sampled_documents: 1000 },
        sample.samples[1],
      ],
    }),
  ).toEqual([]);
});

it("only exposes exact return counts for complete, coherent mature cohorts", () => {
  const cohort = {
    first_session_date: "2026-08-29",
    quality: "complete",
    days: Array.from({ length: 31 }, (_, day) => ({
      day,
      active_users: day === 0 ? 100 : 25,
      total_users: 100,
    })),
  };
  expect(
    retentionCohorts({ period_end: "2026-09-29", cohorts: [cohort] })[0]
      ?.returns,
  ).toEqual(["25 / 100", "25 / 100", "25 / 100"]);
  expect(
    retentionCohorts({ cohorts: [{ ...cohort, quality: "sampled" }] })[0]
      ?.returns,
  ).toEqual([null, null, null]);
  expect(
    retentionCohorts({
      cohorts: [{ ...cohort, days: cohort.days.slice(0, 10) }],
    })[0]?.complete,
  ).toBe(false);
});
