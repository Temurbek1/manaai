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
        { key: "status", label: "Delivery", render: (item) => <StatusBadge status={item.effective_status} /> },
        { key: "budget", label: "Daily budget", render: (item) => item.daily_budget ?? "—" },
        { key: "currency", label: "Currency", render: (item) => item.currency },
      ]}
      items={entities}
      getKey={(item) => item.provider_id}
      empty={<EmptyState title={`No ${label.toLowerCase()}`} detail="The latest snapshot has no matching entities." />}
    />
  );
}
