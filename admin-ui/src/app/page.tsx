import type { Metadata } from "next";

import { ChatPage } from "@/features/chat/ChatPage";

export const metadata: Metadata = { title: "Чаты с агентами" };

export default function OverviewRoute(): React.JSX.Element {
  return <ChatPage agentId="growth-agent" />;
}
