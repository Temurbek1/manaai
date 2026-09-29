import type { Metadata } from "next";

import { AgentsPage } from "@/features/AgentsPage";

export const metadata: Metadata = { title: "Агенты и настройки" };

export default function AgentsRoute(): React.JSX.Element {
  return <AgentsPage />;
}
