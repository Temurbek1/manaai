import type { Metadata } from "next";
import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";

export const metadata: Metadata = { title: "Аналитика и данные" };

export default function AnalyticsRoute(): React.JSX.Element {
  return <AnalyticsPage />;
}
