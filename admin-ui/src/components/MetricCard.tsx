interface MetricCardProps {
  label: string;
  value: string | number;
  detail?: string;
  accent?: "mint" | "amber" | "blue" | "rose";
}

export function MetricCard({
  label,
  value,
  detail,
  accent = "mint",
}: MetricCardProps): React.JSX.Element {
  return (
    <article className={`metric-card metric-${accent}`}>
      <p>{label}</p>
      <strong>
        {typeof value === "number"
          ? new Intl.NumberFormat("ru-RU").format(value)
          : value}
      </strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}
