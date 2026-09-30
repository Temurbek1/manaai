import type { Metadata } from "next";

import { RunsPage } from "@/features/RunsPage";

export const metadata: Metadata = { title: "Запуски и журнал" };

export default async function RunsRoute({
  searchParams,
}: {
  searchParams: Promise<{ run?: string }>;
}): Promise<React.JSX.Element> {
  const { run } = await searchParams;
  return (
    <RunsPage
      initialRunId={run && /^[a-zA-Z0-9-]{1,80}$/.test(run) ? run : null}
    />
  );
}
