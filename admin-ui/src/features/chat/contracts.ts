import type { components } from "@/api/schema";

// The UI accepts older deployed chat payloads while the additive Parent API and
// source-freshness fields roll out. Missing freshness is never treated as live.
type Source = Omit<
  components["schemas"]["ChatSource"],
  "scope_verified" | "product" | "refresh_status"
> & {
  scope_verified: boolean;
  product?: "mana" | "360rec" | null;
  refresh_status?: components["schemas"]["ChatSource"]["refresh_status"];
};

export type ChatViewTurn = Omit<
  components["schemas"]["ChatTurn"],
  "sources" | "next_action" | "model_choice" | "reasoning"
> & {
  model_choice?: components["schemas"]["ChatTurn"]["model_choice"];
  reasoning?: components["schemas"]["ChatTurn"]["reasoning"];
  sources?: Source[];
  next_action?:
    components["schemas"]["ChatTurn"]["next_action"] | "mana_parents";
};

export type ChatViewDetail = Omit<
  components["schemas"]["TopicDetail"],
  "turns"
> & {
  turns: ChatViewTurn[];
};

export type ChatViewAvailability = components["schemas"]["ChatAvailability"] & {
  parent_summary_enabled?: boolean;
};
