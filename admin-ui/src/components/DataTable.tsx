import type { ReactNode } from "react";

interface DataTableColumn<Item> {
  key: string;
  label: string;
  render: (item: Item) => ReactNode;
}

interface DataTableProps<Item> {
  columns: readonly DataTableColumn<Item>[];
  items: readonly Item[];
  getKey: (item: Item) => string;
  empty: ReactNode;
}

export function DataTable<Item>({
  columns,
  items,
  getKey,
  empty,
}: DataTableProps<Item>): React.JSX.Element {
  if (items.length === 0) {
    return <>{empty}</>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={getKey(item)}>
              {columns.map((column) => (
                <td key={column.key}>{column.render(item)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
