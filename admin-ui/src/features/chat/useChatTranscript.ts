"use client";

import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { apiGet } from "@/api/client";
import type { components } from "@/api/schema";
import { CHAT_BASE } from "./agents";
import type { ChatViewDetail, ChatViewTurn } from "./contracts";

const WORKSPACE = "/api/v1/admin/operation/workspace";
type Page = Omit<components["schemas"]["TranscriptPage"], "turns"> & {
  turns: ChatViewTurn[];
};
type Key = readonly [string, string];
const active = (turn: ChatViewTurn): boolean =>
  ["reading", "thinking"].includes(turn.status);

export function useChatTranscript(
  topicId: string | null | undefined,
  owner: string,
  paged: boolean | undefined,
  sending: boolean,
): {
  data: ChatViewDetail | undefined;
  error: Error | undefined;
  isLoading: boolean;
  isValidating: boolean;
  hasMore: boolean;
  loadingOlder: boolean;
  refresh: () => Promise<unknown>;
  loadOlder: () => Promise<unknown>;
} {
  const legacy = useSWR<ChatViewDetail, Error>(
    topicId && paged === false
      ? ([`${CHAT_BASE}/topics/${topicId}`, owner] satisfies Key)
      : null,
    ([url]: Key) => apiGet<ChatViewDetail>(url),
    {
      refreshInterval: (current) =>
        sending || current?.turns.some(active) ? 2000 : 0,
    },
  );
  const pages = useSWRInfinite<Page, Error>(
    (index: number, previous: Page | null): Key | null => {
      if (!topicId || !paged || (previous && !previous.has_more)) return null;
      const cursor = index === 0 ? null : previous?.next_cursor;
      if (index > 0 && !cursor) return null;
      return [
        `${WORKSPACE}/topics/${topicId}/messages?limit=20${cursor ? `&before=${encodeURIComponent(cursor)}` : ""}`,
        owner,
      ];
    },
    async ([url]: Key) => {
      const page = await apiGet<Page>(url);
      if (
        page?.topic?.topic_id !== topicId ||
        !Array.isArray(page.turns) ||
        page.turns.length > 20 ||
        page.turns.some((turn) => turn.topic_id !== topicId) ||
        typeof page.has_more !== "boolean" ||
        (page.has_more
          ? !page.next_cursor || page.next_cursor !== page.turns[0]?.turn_id
          : page.next_cursor !== null) ||
        new Set(page.turns.map((turn) => turn.turn_id)).size !==
          page.turns.length
      )
        throw new Error("Не удалось проверить страницу переписки.");
      return page;
    },
    {
      persistSize: false,
      revalidateFirstPage: false,
      refreshInterval: (current) =>
        sending || current?.some((page) => page.turns.some(active)) ? 2000 : 0,
    },
  );
  const received = pages.data;
  const turns = new Map<string, ChatViewTurn>();
  // Newest pages win if a turn overlaps a revalidated cursor boundary.
  for (const page of [...(received ?? [])].reverse())
    for (const turn of page.turns) turns.set(turn.turn_id, turn);
  const data = received?.[0]
    ? {
        topic: received[0].topic,
        // SQL pages already have canonical microsecond/time/UUID ordering.
        // Do not lose timestamp precision by sorting with JavaScript Dates.
        turns: [...turns.values()],
      }
    : undefined;
  const loadingOlder = Boolean(
    received && pages.size > received.length && pages.isValidating,
  );
  return {
    data: paged ? data : legacy.data,
    error: paged ? pages.error : legacy.error,
    isLoading:
      Boolean(topicId && paged === undefined) ||
      (paged ? pages.isLoading : legacy.isLoading),
    isValidating: paged ? pages.isValidating : legacy.isValidating,
    hasMore: Boolean(paged && received?.at(-1)?.has_more),
    loadingOlder,
    refresh: async () => (paged ? pages.mutate() : legacy.mutate()),
    loadOlder: async () => {
      if (!paged || loadingOlder || !received?.at(-1)?.has_more) return;
      if (pages.error) return pages.mutate();
      return pages.setSize(pages.size + 1);
    },
  };
}
