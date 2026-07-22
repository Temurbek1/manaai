interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps): React.JSX.Element {
  const tone =
    status.includes("fail") || status === "unhealthy" || status === "rejected"
      ? "danger"
      : status.includes("pending") ||
          status.includes("waiting") ||
          status === "degraded"
        ? "warning"
        : status === "enabled" || status === "completed" || status === "healthy"
          ? "success"
          : "neutral";
  return (
    <span className={`status-badge status-${tone}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}
