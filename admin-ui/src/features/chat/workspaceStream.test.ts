import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { TextDecoder, TextEncoder } from "node:util";
import { ReadableStream } from "node:stream/web";
import { ApiError } from "@/api/client";
import {
  parseWorkspaceFrame,
  watchWorkspace,
  type WorkspaceEvent,
  type ChatTextEvent,
} from "./workspaceStream";

let open: jest.SpiedFunction<typeof fetch>;
const event: WorkspaceEvent = {
  event_id: 12,
  topic_id: "private-topic",
  goal_id: "goal",
  revision: 2,
  at: "2026-10-12T10:00:00Z",
  status: "running",
  phase: "investigate",
  message: "Читаю подтверждённую сводку",
  message_shortened: false,
  plan: [{ title: "Проверить источник", status: "active" }],
  tools: [{ call_id: "tool", name: "read_saved_report", status: "started" }],
};
const frame = (data: WorkspaceEvent = event) =>
  `id: ${data.event_id}\nevent: workspace\ndata: ${JSON.stringify(data)}\n\n`;
const response = (chunks: string[]) =>
  ({
    ok: true,
    status: 200,
    headers: new Headers({ "Content-Type": "text/event-stream" }),
    body: new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) =>
          controller.enqueue(new TextEncoder().encode(chunk)),
        );
        controller.close();
      },
    }),
  }) as unknown as Response;

beforeEach(() => {
  jest.useFakeTimers();
  open = jest.spyOn(globalThis, "fetch");
  sessionStorage.clear();
  Object.assign(globalThis, { TextDecoder });
});
afterEach(() => {
  jest.useRealTimers();
});

describe("workspace stream protocol", () => {
  it("replays chat notifications once through the same scoped cursor without resubmitting", async () => {
    const chat: ChatTextEvent = {
      kind: "chat_text",
      event_id: 13,
      topic_id: "private-topic",
      turn_id: "turn",
      revision: 1,
      at: event.at,
      status: "thinking",
      offset: 0,
      delta: "Ответ 🧒",
      final_answer: null,
    };
    const chatFrame = `id: 13\nevent: chat_text\ndata: ${JSON.stringify(chat)}\n\n`;
    open.mockResolvedValueOnce(
      response([
        frame(),
        chatFrame,
        chatFrame,
        "id: 14\nevent: chat_text\ndata: {",
      ]),
    );
    open.mockImplementationOnce(
      async () => new Promise<Response>(() => undefined),
    );
    const received = jest.fn<(item: WorkspaceEvent) => void>();
    const chatReceived = jest.fn<(item: ChatTextEvent) => void>();
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received,
      chatReceived,
      connection: () => undefined,
    });
    await jest.advanceTimersByTimeAsync(2000);
    expect(received).toHaveBeenCalledTimes(1);
    expect(chatReceived).toHaveBeenCalledTimes(1);
    expect(chatReceived).toHaveBeenCalledWith(chat);
    expect(open.mock.calls[1]?.[0]).toContain("after=13");
    expect(
      open.mock.calls.every(
        (call) => !call[1]?.method || call[1].method === "GET",
      ),
    ).toBe(true);
    stop();
  });
  it.each(["find_saved_tasks", "read_saved_task"] as const)(
    "accepts public %s progress without exposing its arguments",
    (name) => {
      const data = {
        ...event,
        tools: [{ call_id: "history", name, status: "completed" as const }],
      };
      expect(parseWorkspaceFrame(frame(data), "private-topic")).toEqual(data);
      expect(JSON.stringify(data)).not.toContain("query");
    },
  );
  it("validates typed public frames and Unicode without executing anything", () => {
    expect(parseWorkspaceFrame(frame(), "private-topic")).toEqual(event);
    expect(parseWorkspaceFrame(": heartbeat", "private-topic")).toBeNull();
    expect(
      parseWorkspaceFrame(
        frame({ ...event, message: "🧒".repeat(2000) }),
        "private-topic",
      )?.message,
    ).toHaveLength(4000);
    expect(() => parseWorkspaceFrame(frame(), "foreign-topic")).toThrow();
    expect(() =>
      parseWorkspaceFrame(frame({ ...event, revision: -1 }), "private-topic"),
    ).toThrow();
    expect(() =>
      parseWorkspaceFrame(
        frame({
          ...event,
          tools: [
            { call_id: "bad", name: "shell" as never, status: "started" },
          ],
        }),
        "private-topic",
      ),
    ).toThrow();
  });

  it("reconnects from the last complete event, deduplicates and ignores a cut frame", async () => {
    open.mockResolvedValueOnce(
      response([
        frame().slice(0, 20),
        frame().slice(20),
        frame(),
        "id: 13\nevent: workspace\ndata: {",
      ]),
    );
    open.mockImplementationOnce(
      async () => new Promise<Response>(() => undefined),
    );
    const received = jest.fn<(item: WorkspaceEvent) => void>();
    const connected = jest.fn<(value: boolean) => void>();
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received,
      connection: connected,
    });
    await jest.advanceTimersByTimeAsync(2000);
    expect(received).toHaveBeenCalledTimes(1);
    expect(received).toHaveBeenCalledWith(event);
    expect(open.mock.calls[1]?.[0]).toContain("after=12");
    expect(
      sessionStorage.getItem("mana:workspace-cursor:v1:alice:private-topic"),
    ).toBe("12");
    const signal = open.mock.calls[1]?.[1]?.signal;
    stop();
    expect(signal?.aborted).toBe(true);
  });

  it("keeps cursors separate by owner and stops permanently on denied access", async () => {
    sessionStorage.setItem(
      "mana:workspace-cursor:v1:alice:private-topic",
      "77",
    );
    open.mockRejectedValue(new ApiError(403, "denied"));
    const connection = jest.fn<(value: boolean) => void>();
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "bob",
      received: () => undefined,
      connection,
    });
    await jest.advanceTimersByTimeAsync(20000);
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.mock.calls[0]?.[0]).toContain("after=0");
    expect(connection).toHaveBeenLastCalledWith(false);
    stop();
  });

  it("drops a cursor invalidated by restoration and only retries observation", async () => {
    sessionStorage.setItem(
      "mana:workspace-cursor:v1:alice:private-topic",
      "77",
    );
    open.mockRejectedValueOnce(new ApiError(409, "cursor"));
    open.mockRejectedValueOnce(new ApiError(404, "disabled"));
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received: () => undefined,
      connection: () => undefined,
    });
    await jest.advanceTimersByTimeAsync(2000);
    expect(open.mock.calls[0]?.[0]).toContain("after=77");
    expect(open.mock.calls[1]?.[0]).toContain("after=0");
    stop();
  });

  it("revokes access without acknowledging private events or reconnecting", async () => {
    open.mockResolvedValue(
      response(["event: access_revoked\ndata: {}\n\n", frame()]),
    );
    const revoked = jest.fn<() => void>();
    window.addEventListener("mana:unauthorized", revoked);
    const received = jest.fn<(item: WorkspaceEvent) => void>();
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received,
      connection: () => undefined,
    });
    await jest.advanceTimersByTimeAsync(30000);
    expect(revoked).toHaveBeenCalledTimes(1);
    expect(received).not.toHaveBeenCalled();
    expect(open).toHaveBeenCalledTimes(1);
    stop();
    window.removeEventListener("mana:unauthorized", revoked);
  });

  it("stops on an incompatible response instead of retrying a permanent protocol error", async () => {
    const incompatible = response([]);
    incompatible.headers.set("Content-Type", "application/json");
    open.mockResolvedValue(incompatible);
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received: () => undefined,
      connection: () => undefined,
    });
    await jest.advanceTimersByTimeAsync(30000);
    expect(open).toHaveBeenCalledTimes(1);
    stop();
  });

  it("aborts stalled observation without starting, resuming or cancelling a task", async () => {
    open.mockImplementation(
      async (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new Error("Aborted observation")),
          );
        }),
    );
    const stop = watchWorkspace({
      topicId: "private-topic",
      owner: "alice",
      received: () => undefined,
      connection: () => undefined,
    });
    await jest.advanceTimersByTimeAsync(27000);
    expect(open.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(open.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(open.mock.calls.every((call) => call[1]?.method === "GET")).toBe(
      true,
    );
    expect(open.mock.calls[1]?.[0]).toContain("after=0");
    stop();
  });
});
