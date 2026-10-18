"use client";

import useSWR, { useSWRConfig } from "swr";
import useSWRInfinite, { unstable_serialize } from "swr/infinite";
import { useRef } from "react";
import { apiGet } from "@/api/client";
import type { components } from "@/api/schema";
import { CHAT_BASE } from "./agents";
import type { ChatViewDetail, ChatViewTurn } from "./contracts";
import type { ChatTextEvent } from "./workspaceStream";

export function applyChatText(
  turn: ChatViewTurn,
  event: ChatTextEvent,
): ChatViewTurn | null {
  if (turn.topic_id !== event.topic_id || turn.turn_id !== event.turn_id)
    return null;
  if (event.revision <= (turn.preview_revision ?? 0) || !active(turn))
    return turn;
  const preview = turn.preview ?? "";
  if (event.status === "thinking") {
    if (
      event.revision !== (turn.preview_revision ?? 0) + 1 ||
      event.offset !== Array.from(preview).length ||
      Array.from(preview + event.delta).length > 16000
    )
      return null;
    return {
      ...turn,
      preview: preview + event.delta,
      preview_revision: event.revision,
    };
  }
  return {
    ...turn,
    status: event.status,
    answer: event.final_answer ?? "",
    preview_revision: event.revision,
  };
}

const WORKSPACE = "/api/v1/admin/operation/workspace";
type Page = Omit<components["schemas"]["TranscriptPage"], "turns"> & {
  turns: ChatViewTurn[];
};
type Key = readonly [string, string];
const active = (turn: ChatViewTurn): boolean =>
  ["reading", "thinking"].includes(turn.status);

function validatePage(page: Page, topicId: string): Page {
  if (
    page?.topic?.topic_id !== topicId ||
    !Array.isArray(page.turns) ||
    page.turns.length > 20 ||
    page.turns.some((turn) => turn.topic_id !== topicId) ||
    typeof page.has_more !== "boolean" ||
    (page.has_more
      ? !page.next_cursor || page.next_cursor !== page.turns[0]?.turn_id
      : page.next_cursor !== null) ||
    new Set(page.turns.map((turn) => turn.turn_id)).size !== page.turns.length
  )
    throw new Error("Не удалось проверить страницу переписки.");
  return page;
}

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
  refreshTopic: (target: string) => Promise<unknown>;
  loadOlder: () => Promise<unknown>;
  applyText: (event: ChatTextEvent) => void;
} {
  const { mutate } = useSWRConfig();
  const repairing = useRef(false);
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
      return validatePage(page, topicId!);
    },
    {
      persistSize: false,
      // SWR's interval otherwise reuses the cached head without an HTTP read.
      // Observe newly admitted/active turns even while their POST is pending.
      revalidateFirstPage: true,
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
    refreshTopic: async (target) => {
      // A newly created topic may have an empty cached first page while this
      // submission still holds the pre-creation hook closure. Refresh its exact
      // owner-scoped SQL key, not that obsolete/null topic or model dispatch.
      const key: Key = [
        paged
          ? `${WORKSPACE}/topics/${target}/messages?limit=20`
          : `${CHAT_BASE}/topics/${target}`,
        owner,
      ];
      if (target === topicId) return paged ? pages.mutate() : legacy.mutate();
      if (!paged) return mutate(key);
      // A new topic has no older admitted pages in this hook's closure:
      // load and validate its exact first SQL page, without another generation.
      const page = validatePage(await apiGet<Page>(key[0]), target);
      return mutate(
        unstable_serialize(() => key),
        [page],
        { revalidate: false },
      );
    },
    loadOlder: async () => {
      if (!paged || loadingOlder || !received?.at(-1)?.has_more) return;
      if (pages.error) return pages.mutate();
      return pages.setSize(pages.size + 1);
    },
    applyText: (event) => {
      if (event.topic_id !== topicId) return;
      const update = (turn: ChatViewTurn): ChatViewTurn =>
        applyChatText(turn, event) ?? turn;
      const existing = (paged ? data : legacy.data)?.turns.find(
        (turn) => turn.turn_id === event.turn_id,
      );
      if (!existing || applyChatText(existing, event) === null) {
        if (!repairing.current) {
          repairing.current = true;
          void (paged ? pages.mutate() : legacy.mutate())
            .catch(() => undefined)
            .finally(() => {
              repairing.current = false;
            });
        }
        return;
      }
      if (paged)
        void pages.mutate(
          (current) =>
            current?.map((page) => ({
              ...page,
              turns: page.turns.map(update),
            })),
          { revalidate: false },
        );
      else
        void legacy.mutate(
          (current) =>
            current
              ? { ...current, turns: current.turns.map(update) }
              : current,
          { revalidate: false },
        );
    },
  };
}
