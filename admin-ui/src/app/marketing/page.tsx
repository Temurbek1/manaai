import type { Metadata } from "next";

import { MarketingPage } from "@/features/MarketingPage";

export const metadata: Metadata = { title: "Marketing Agent" };

export default function MarketingRoute(): React.JSX.Element {
  return <MarketingPage />;
}
