import { formatDate } from "@/ui/format";
import { translate, type Locale } from "@/i18n/catalog";

type EvidenceMetadata = {
  collected_at?: string | null;
  fresh_until?: string | null;
  refresh_status?: string | null;
};

export type EvidenceState = "stale" | "unknown" | "recent";

export function evidenceState(
  source: EvidenceMetadata,
  now: number,
): EvidenceState {
  if (source.refresh_status === "stale") return "stale";
  const collected = Date.parse(source.collected_at ?? "");
  const expires = Date.parse(source.fresh_until ?? "");
  if (
    !["live", "cached"].includes(source.refresh_status ?? "") ||
    !Number.isFinite(collected) ||
    !Number.isFinite(expires) ||
    collected > now ||
    expires <= collected
  )
    return "unknown";
  // Cache timing is not observation coverage or server-side action admission.
  return expires <= now ? "stale" : "recent";
}

export function evidenceCollectionLabel(
  collectedAt: string | null | undefined,
  locale: Locale = "ru",
): string {
  if (!Number.isFinite(Date.parse(collectedAt ?? "")))
    return translate("Дата сбора неизвестна", locale);
  return translate("Сбор данных: {0}", locale, {
    0: formatDate(collectedAt, locale),
  });
}

export function evidenceStateLabel(state: EvidenceState): string {
  switch (state) {
    case "stale":
      return "Устаревшие";
    case "unknown":
      return "Свежесть не подтверждена";
    case "recent":
      return "Срок кэша не истёк";
  }
}
