import { notFound } from "next/navigation";
import { ChatPage } from "@/features/chat/ChatPage";
import { CHAT_AGENTS } from "@/features/chat/agents";

export default async function ChatRoute({
  params,
}: {
  params: Promise<{ agentId: string; topic?: string[] }>;
}): Promise<React.JSX.Element> {
  const { agentId, topic } = await params;
  const agent = CHAT_AGENTS.find((item) => item.id === agentId);
  if (!agent || (topic && (topic.length !== 2 || topic[0] !== "topic")))
    notFound();
  return (
    <ChatPage
      key={`${agentId}-${topic?.[1] ?? "new"}`}
      agentId={agent.id}
      topicId={topic?.[1]}
    />
  );
}
