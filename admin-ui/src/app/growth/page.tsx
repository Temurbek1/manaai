import type { Metadata } from "next";

import { GrowthPage } from "@/features/GrowthPage";

export const metadata: Metadata = { title: "Рост и конверсия" };

export default function GrowthRoute(): React.JSX.Element {
  return <GrowthPage />;
}
