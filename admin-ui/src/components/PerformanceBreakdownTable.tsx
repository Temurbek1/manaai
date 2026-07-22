import type { BreakdownPerformance, Metric } from "../api/client";
import { DataTable } from "./DataTable";
import { EmptyState } from "./EmptyState";

interface PerformanceBreakdownTableProps {
  rows: readonly BreakdownPerformance[];
}

function metricValue(metric: Metric): string {
  return metric.availability === "available" && metric.value !== null
    ? metric.value
    : "unavailable";
}

export function PerformanceBreakdownTable({
  rows,
}: PerformanceBreakdownTableProps): React.JSX.Element {
  return (
    <DataTable
      columns={[
        { key: "dimension", label: "Breakdown", render: (item) => item.dimension },
        { key: "value", label: "Value", render: (item) => item.value },
        { key: "spend", label: "Spend", render: (item) => metricValue(item.metrics.spend) },
        { key: "leads", label: "Leads", render: (item) => metricValue(item.metrics.leads) },
        { key: "ctr", label: "CTR", render: (item) => metricValue(item.metrics.ctr) },
        { key: "cpl", label: "CPL", render: (item) => metricValue(item.metrics.cpl) },
        { key: "roas", label: "ROAS", render: (item) => metricValue(item.metrics.roas) },
      ]}
      items={rows}
      getKey={(item) => `${item.dimension}:${item.value}`}
      empty={<EmptyState title="No breakdown data" detail="Hourly, daily, region, placement, and demographic slices appear after collection." />}
    />
  );
}
