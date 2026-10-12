import { useEffect, useState, useRef } from "react";
import { useSWRConfig } from "swr";
import { CHAT_BASE } from "./agents";
import {
  watchWorkspace,
  type WorkspaceEvent,
  type ChatTextEvent,
} from "./workspaceStream";

export interface WorkspaceStreamState {
  connected: boolean;
  event: WorkspaceEvent | null;
}

export function useWorkspaceStream(
  topicId: string | null | undefined,
  owner: string,
  enabled: boolean,
  onChat?: (event: ChatTextEvent) => void,
): WorkspaceStreamState {
  const { mutate } = useSWRConfig();
  const scope = `${owner}:${topicId ?? ""}`;
  const chatCallback = useRef(onChat);
  useEffect(() => {
    chatCallback.current = onChat;
  }, [onChat]);
  const [state, setState] = useState<WorkspaceStreamState & { scope: string }>({
    connected: false,
    event: null,
    scope,
  });
  useEffect(() => {
    if (!enabled || !topicId) return;
    let refresh: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const stop = watchWorkspace({
      topicId,
      owner,
      chatReceived: (event) => {
        if (!disposed) chatCallback.current?.(event);
      },
      connection: (connected) => {
        if (!disposed)
          setState((prior) => ({
            connected,
            event: prior.scope === scope ? prior.event : null,
            scope,
          }));
      },
      received: (event) => {
        setState({ connected: true, event, scope });
        if (refresh) clearTimeout(refresh);
        refresh = setTimeout(() => {
          void mutate(`/api/v1/admin/operation/goals/topics/${topicId}`).catch(
            () => undefined,
          );
          void mutate(`${CHAT_BASE}/topics/${topicId}`).catch(() => undefined);
        }, 100);
      },
    });
    return () => {
      disposed = true;
      stop();
      if (refresh) clearTimeout(refresh);
    };
  }, [topicId, owner, enabled, scope, mutate]);
  // Do not display another topic's queued effect update during navigation.
  return enabled && topicId && state.scope === scope
    ? state
    : { connected: false, event: null };
}
