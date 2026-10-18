import { describe, expect, it } from "@jest/globals";
import { applyChatText } from "./useChatTranscript";
import { parseWorkspaceFrame, type ChatTextEvent } from "./workspaceStream";
import type { ChatViewTurn } from "./contracts";

const turn: ChatViewTurn = {
  turn_id: "turn",
  topic_id: "topic",
  request_id: "00000000-0000-4000-8000-000000000001",
  message: "Question",
  status: "thinking",
  answer: "",
  analysis_requested: false,
  analysis_kind: "default",
  created_at: "2026-10-12T00:00:00Z",
  preview: "Привет 🧒",
  preview_revision: 1,
};
const event: ChatTextEvent = {
  kind: "chat_text",
  event_id: 2,
  topic_id: "topic",
  turn_id: "turn",
  revision: 2,
  at: "2026-10-12T00:00:01Z",
  status: "thinking",
  offset: Array.from(turn.preview!).length,
  delta: "!",
  final_answer: null,
};
const frame = (value: ChatTextEvent) =>
  `id: ${value.event_id}\nevent: chat_text\ndata: ${JSON.stringify(value)}\n\n`;

describe("durable chat text", () => {
  it.each(["reading", "thinking"] as const)(
    "applies Unicode offsets once from %s without promoting a preview to a result",
    (status) => {
      const changed = applyChatText({ ...turn, status }, event)!;
      expect(changed.preview).toBe("Привет 🧒!");
      expect(changed.answer).toBe("");
      expect(changed.status).toBe("thinking");
      expect(applyChatText(changed, event)).toBe(changed);
      expect(
        applyChatText(changed, { ...event, revision: 3, offset: 999 }),
      ).toBeNull();
      expect(applyChatText(turn, { ...event, topic_id: "foreign" })).toBeNull();
      const done = applyChatText(changed, {
        ...event,
        revision: 3,
        status: "completed",
        delta: "",
        final_answer: "Final verified text",
      })!;
      expect(done.answer).toBe("Final verified text");
      expect(done.status).toBe("completed");
      expect(applyChatText(done, { ...event, revision: 4 })).toBe(done);
    },
  );
  it("validates chat frames separately and leaves the legacy Goal parser compatible", () => {
    expect(parseWorkspaceFrame(frame(event), "topic")).toBeNull();
    expect(parseWorkspaceFrame(frame(event), "topic", true)).toEqual(event);
    expect(() =>
      parseWorkspaceFrame(frame({ ...event, revision: 131 }), "topic", true),
    ).toThrow();
    expect(() =>
      parseWorkspaceFrame(
        frame({ ...event, final_answer: "not complete" }),
        "topic",
        true,
      ),
    ).toThrow();
    expect(() =>
      parseWorkspaceFrame(
        frame({ ...event, status: "completed" }),
        "topic",
        true,
      ),
    ).toThrow();
    expect(() => parseWorkspaceFrame(frame(event), "other", true)).toThrow();
  });
});
