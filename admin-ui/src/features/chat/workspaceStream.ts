import { ApiError, ApiStreamProtocolError, apiOpenStream } from "@/api/client";
import type { components } from "@/api/schema";

export type WorkspaceEvent = components["schemas"]["WorkspaceEvent"];

class StreamProtocolError extends Error {}

export function parseWorkspaceFrame(
  frame: string,
  topicId: string,
): WorkspaceEvent | null {
  const lines = frame.split("\n");
  const name = lines
    .find((line) => line.startsWith("event:"))
    ?.slice(6)
    .trim();
  if (name === "access_revoked") {
    if (typeof window !== "undefined")
      window.dispatchEvent(new Event("mana:unauthorized"));
    throw new ApiError(401, "Доступ отозван.");
  }
  if (name === "unavailable")
    throw new StreamProtocolError("Workspace access or stream unavailable");
  if (name !== "workspace") return null;
  const value: unknown = JSON.parse(
    lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n"),
  );
  const id = Number(
    lines
      .find((line) => line.startsWith("id:"))
      ?.slice(3)
      .trim(),
  );
  const item = value as WorkspaceEvent;
  if (
    !value ||
    typeof value !== "object" ||
    !Number.isSafeInteger(id) ||
    id <= 0 ||
    item.event_id !== id ||
    item.topic_id !== topicId ||
    typeof item.goal_id !== "string" ||
    !Number.isSafeInteger(item.revision) ||
    item.revision < 0 ||
    ![
      "queued",
      "running",
      "paused",
      "waiting",
      "completed",
      "cancelled",
    ].includes(item.status) ||
    !["plan", "investigate", "review"].includes(item.phase) ||
    typeof item.message !== "string" ||
    Array.from(item.message).length > 2000 ||
    !Number.isFinite(Date.parse(item.at)) ||
    !Array.isArray(item.plan) ||
    item.plan.length > 8 ||
    item.plan.some(
      (task) =>
        !task ||
        typeof task.title !== "string" ||
        Array.from(task.title).length > 300 ||
        !["pending", "active", "done", "blocked"].includes(task.status),
    ) ||
    !Array.isArray(item.tools) ||
    item.tools.length > 12 ||
    item.tools.some(
      (tool) =>
        !tool ||
        typeof tool.call_id !== "string" ||
        ![
          "inspect_sources",
          "read_saved_report",
          "request_source_read",
          "ask_user",
        ].includes(tool.name) ||
        ![
          "started",
          "completed",
          "awaiting_approval",
          "waiting_for_user",
          "denied",
          "unknown",
        ].includes(tool.status),
    )
  )
    throw new StreamProtocolError("Invalid workspace event");
  return item;
}

async function consume(
  response: Response,
  topicId: string,
  received: (event: WorkspaceEvent) => void,
  activity: () => void,
): Promise<void> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      activity();
      buffer += decoder.decode(chunk.value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        if (boundary > 65536)
          throw new StreamProtocolError("Workspace frame too large");
        const event = parseWorkspaceFrame(buffer.slice(0, boundary), topicId);
        if (event) received(event);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
      if (buffer.length > 65536)
        throw new StreamProtocolError("Workspace frame too large");
    }
    // Incomplete frames are not acknowledged: reconnect from the last committed cursor.
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function watchWorkspace({
  topicId,
  owner,
  received,
  connection,
}: {
  topicId: string;
  owner: string;
  received: (event: WorkspaceEvent) => void;
  connection: (connected: boolean) => void;
}): () => void {
  const key = `mana:workspace-cursor:v1:${owner}:${topicId}`;
  let cursor = 0;
  try {
    cursor = Number(sessionStorage.getItem(key) ?? 0);
  } catch {
    /* Optional storage. */
  }
  if (!Number.isSafeInteger(cursor) || cursor < 0) cursor = 0;
  let disposed = false;
  let retry = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  const activity = () => {
    if (watchdog) clearTimeout(watchdog);
    watchdog = setTimeout(() => controller?.abort(), 25000);
  };
  async function connect(): Promise<void> {
    await Promise.resolve();
    if (disposed) return;
    connection(false);
    controller = new AbortController();
    activity();
    try {
      const response = await apiOpenStream(
        `/api/v1/admin/operation/workspace/topics/${encodeURIComponent(topicId)}/stream?after=${cursor}`,
        controller.signal,
      );
      if (disposed) return;
      connection(true);
      retry = 0;
      await consume(
        response,
        topicId,
        (event) => {
          if (disposed || event.event_id <= cursor) return;
          received(event);
          cursor = event.event_id;
          try {
            sessionStorage.setItem(key, String(cursor));
          } catch {
            /* Optional storage. */
          }
        },
        activity,
      );
    } catch (error) {
      if (disposed) return;
      if (error instanceof ApiError && error.status === 409) {
        cursor = 0;
        try {
          sessionStorage.removeItem(key);
        } catch {
          /* Optional storage. */
        }
      } else if (
        error instanceof StreamProtocolError ||
        error instanceof ApiStreamProtocolError ||
        error instanceof SyntaxError ||
        (error instanceof ApiError && [401, 403, 404].includes(error.status))
      ) {
        connection(false);
        return;
      }
    } finally {
      if (watchdog) clearTimeout(watchdog);
    }
    if (disposed) return;
    connection(false);
    const delay =
      Math.min(10000, 500 * 2 ** Math.min(retry++, 5)) + Math.random() * 250;
    timer = setTimeout(() => void connect(), delay);
  }
  void connect();
  return () => {
    disposed = true;
    controller?.abort();
    if (timer) clearTimeout(timer);
    if (watchdog) clearTimeout(watchdog);
  };
}
