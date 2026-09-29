import type { Metadata } from "next";

import { ApprovalsPage } from "@/features/ApprovalsPage";

export const metadata: Metadata = { title: "Согласования" };

export default function ApprovalsRoute(): React.JSX.Element {
  return <ApprovalsPage />;
}
