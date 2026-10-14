import { describe, expect, it } from "@jest/globals";
import {
  evidenceCollectionLabel,
  evidenceState,
  evidenceStateLabel,
} from "./evidenceDisplay";
import { formatDate } from "@/ui/format";

const source = {
  collected_at: "2026-10-08T00:00:00Z",
  fresh_until: "2026-10-08T06:00:00Z",
  refresh_status: "cached",
};
const now = Date.parse("2026-10-08T03:00:00Z");

describe("saved evidence display", () => {
  it.each(["cached", "live"])(
    "labels %s as within cache timing, not verified observation coverage",
    (refresh_status) => {
      const state = evidenceState({ ...source, refresh_status }, now);
      expect(state).toBe("recent");
      expect(evidenceStateLabel(state)).toBe("Срок кэша не истёк");
    },
  );

  it("expires at the exact cache deadline", () => {
    expect(evidenceState(source, Date.parse(source.fresh_until))).toBe("stale");
    expect(evidenceStateLabel("stale")).toBe("Устаревшие");
  });

  it("preserves an explicit stale classification even with absent dates", () => {
    expect(evidenceState({ refresh_status: "stale" }, now)).toBe("stale");
  });

  it.each([
    { collected_at: null },
    { collected_at: "invalid-date" },
    { collected_at: "2026-10-08T04:00:00Z" },
    { fresh_until: null },
    { fresh_until: "invalid-date" },
    { fresh_until: "2026-10-08T00:00:00Z" },
    { refresh_status: null },
    { refresh_status: "unknown" },
  ])("fails closed on unsupported timing %j", (fields) => {
    const state = evidenceState({ ...source, ...fields }, now);
    expect(state).toBe("unknown");
    expect(evidenceStateLabel(state)).toBe("Свежесть не подтверждена");
  });

  it.each([null, undefined, "", "invalid-date"])(
    "does not manufacture a collection date from %j",
    (date) => {
      expect(evidenceCollectionLabel(date)).toBe("Дата сбора неизвестна");
    },
  );

  it("states the role of an existing collection timestamp explicitly", () => {
    expect(evidenceCollectionLabel(source.collected_at)).toBe(
      `Сбор данных: ${formatDate(source.collected_at)}`,
    );
  });
});
