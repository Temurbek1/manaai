"use client";

import Link from "next/link";
import useSWR from "swr";
import type { components } from "@/api/schema";
import { CHAT_AGENTS, CHAT_BASE } from "./agents";

type Topic = components["schemas"]["ChatTopic"];

export function TopicNavigation({
  pathname,
  onNavigate,
}: {
  pathname: string;
  onNavigate: () => void;
}): React.JSX.Element {
  const { data, error } = useSWR<Topic[], Error>(`${CHAT_BASE}/topics`);
  return (
    <>
      <p className="nav-section-label">Ваши агенты</p>
      {CHAT_AGENTS.map((agent) => {
        const selected =
          pathname.includes(`/chat/${agent.id}`) ||
          (pathname === "/" && agent.id === "growth-agent");
        const topics =
          data?.filter((topic) => topic.agent_id === agent.id) ?? [];
        return (
          <div className="agent-nav-group" key={agent.id}>
            <Link
              className={`nav-item agent-nav ${selected ? "active" : ""}`}
              href={`/chat/${agent.id}`}
              onClick={onNavigate}
              aria-current={
                selected && !pathname.includes("/topic/") ? "page" : undefined
              }
            >
              <span className={`agent-avatar ${agent.id}`} aria-hidden="true">
                {agent.short}
              </span>
              <span>
                {agent.name}
                {agent.planned && <small>Планирование</small>}
              </span>
            </Link>
            {selected &&
              (topics.length > 0 || error || pathname.includes("/topic/")) && (
                <div className="topic-navigation">
                  <Link
                    href={`/chat/${agent.id}`}
                    className="new-topic-link"
                    onClick={onNavigate}
                  >
                    ＋ Новая тема
                  </Link>
                  {error ? (
                    <p className="nav-hint">Не удалось загрузить темы</p>
                  ) : (
                    topics.map((topic) => (
                      <Link
                        key={topic.topic_id}
                        title={topic.title}
                        href={`/chat/${agent.id}/topic/${topic.topic_id}`}
                        onClick={onNavigate}
                        aria-current={
                          pathname.endsWith(topic.topic_id) ? "page" : undefined
                        }
                        className={
                          pathname.endsWith(topic.topic_id)
                            ? "topic-link active"
                            : "topic-link"
                        }
                      >
                        <span>{topic.title}</span>
                        <small>
                          {topic.product === "mana" ? "MANA" : "360REC"}
                        </small>
                      </Link>
                    ))
                  )}
                </div>
              )}
          </div>
        );
      })}
    </>
  );
}
