import type { Metadata } from "next";

import { RunsPage } from "@/features/RunsPage";

export const metadata: Metadata = { title: "Runs & audit" };

export default function RunsRoute(): React.JSX.Element {
  return <RunsPage />;
}
