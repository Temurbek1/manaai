import type { Metadata } from "next";

import { DashboardPage } from "@/features/DashboardPage";

export const metadata: Metadata = { title: "Overview" };

export default function OverviewRoute(): React.JSX.Element {
  return <DashboardPage />;
}
