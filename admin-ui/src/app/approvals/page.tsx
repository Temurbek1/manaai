import type { Metadata } from "next";

import { ApprovalsPage } from "@/features/ApprovalsPage";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsRoute(): React.JSX.Element {
  return <ApprovalsPage />;
}
