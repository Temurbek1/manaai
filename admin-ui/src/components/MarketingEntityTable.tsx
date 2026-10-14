"use client";
import { useI18n } from "@/i18n/LanguageProvider";
import type { AdEntity } from "../api/client";
import { compactId } from "../ui/format";
import { DataTable } from "./DataTable";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";

interface MarketingEntityTableProps {
  entities: readonly AdEntity[];
  label: string;
}

export function MarketingEntityTable({
  entities,
  label,
}: MarketingEntityTableProps): React.JSX.Element {
  const { t } = useI18n();

  return (
    <DataTable
      columns={[
        {
          key: "name",
          label,
          render: (item) => (
            <div className="primary-cell">
              <strong>{item.name}</strong>
              <code>{compactId(item.provider_id)}</code>
            </div>
          ),
        },
        {
          key: "status",
          label: t("Показы"),
          render: (item) => <StatusBadge status={item.effective_status} />,
        },
        {
          key: "budget",
          label: t("Дневной бюджет"),
          render: (item) => item.daily_budget ?? "—",
        },
        {
          key: "currency",
          label: t("Валюта"),
          render: (item) => item.currency,
        },
      ]}
      items={entities}
      getKey={(item) => item.provider_id}
      empty={
        <EmptyState
          title={t("Нет подходящих объектов")}
          detail={t("В последнем сборе нет подходящих объектов.")}
        />
      }
    />
  );
}
