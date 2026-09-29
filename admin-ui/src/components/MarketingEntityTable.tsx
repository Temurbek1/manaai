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
          label: "Показы",
          render: (item) => <StatusBadge status={item.effective_status} />,
        },
        {
          key: "budget",
          label: "Дневной бюджет",
          render: (item) => item.daily_budget ?? "—",
        },
        { key: "currency", label: "Валюта", render: (item) => item.currency },
      ]}
      items={entities}
      getKey={(item) => item.provider_id}
      empty={
        <EmptyState
          title="Нет подходящих объектов"
          detail="В последнем сборе нет подходящих объектов."
        />
      }
    />
  );
}
