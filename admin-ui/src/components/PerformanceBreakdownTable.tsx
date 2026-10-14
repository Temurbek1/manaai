"use client";
import { useI18n } from "@/i18n/LanguageProvider";
import type { BreakdownPerformance, Metric } from "../api/client";
import { DataTable } from "./DataTable";
import { EmptyState } from "./EmptyState";
import { labelFor } from "../ui/labels";

interface PerformanceBreakdownTableProps {
  rows: readonly BreakdownPerformance[];
}

function metricValue(metric: Metric): string {
  return metric.availability === "available" && metric.value !== null
    ? metric.value
    : "Нет данных";
}

export function PerformanceBreakdownTable({
  rows,
}: PerformanceBreakdownTableProps): React.JSX.Element {
  const { t } = useI18n();

  return (
    <DataTable
      columns={[
        {
          key: "dimension",
          label: t("Разрез данных"),
          render: (item) => t(labelFor(item.dimension)),
        },
        { key: "value", label: t("Значение"), render: (item) => item.value },
        {
          key: "spend",
          label: t("Расходы"),
          render: (item) => metricValue(item.metrics.spend),
        },
        {
          key: "leads",
          label: t("Заявки"),
          render: (item) => metricValue(item.metrics.leads),
        },
        {
          key: "ctr",
          label: "CTR",
          render: (item) => metricValue(item.metrics.ctr),
        },
        {
          key: "cpl",
          label: "CPL",
          render: (item) => metricValue(item.metrics.cpl),
        },
        {
          key: "roas",
          label: "ROAS",
          render: (item) => metricValue(item.metrics.roas),
        },
      ]}
      items={rows}
      getKey={(item) => `${item.dimension}:${item.value}`}
      empty={
        <EmptyState
          title={t("Нет данных по разрезам")}
          detail={t(
            "Данные по времени, регионам, площадкам и демографии появятся после сбора.",
          )}
        />
      }
    />
  );
}
