"use client";
import { useI18n } from "@/i18n/LanguageProvider";
interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps): React.JSX.Element {
  const { t } = useI18n();

  const tone =
    status.includes("fail") ||
    status === "unhealthy" ||
    status === "rejected" ||
    status === "critical" ||
    status === "high"
      ? "danger"
      : status.includes("pending") ||
          status.includes("waiting") ||
          status === "degraded" ||
          status === "medium"
        ? "warning"
        : status === "enabled" || status === "completed" || status === "healthy"
          ? "success"
          : "neutral";
  return (
    <span className={`status-badge status-${tone}`}>{t(labelFor(status))}</span>
  );
}
import { labelFor } from "../ui/labels";
