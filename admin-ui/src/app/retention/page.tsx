import type { Metadata } from "next";

import { RetentionPage } from "@/features/RetentionPage";

export const metadata: Metadata = { title: "Удержание и лояльность" };

export default function RetentionRoute(): React.JSX.Element {
  return <RetentionPage />;
}
