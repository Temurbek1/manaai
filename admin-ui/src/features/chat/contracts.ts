import type { components } from "@/api/schema";

// Optional fields from the forthcoming Parent API release. The UI also supports
// the deployed chat API without changing its generated public contract.
type Source = Omit<
  components["schemas"]["ChatSource"],
  "scope_verified" | "product"
> & {
  scope_verified: boolean;
  product?: "mana" | "360rec" | null;
};

export type ChatViewTurn = Omit<
  components["schemas"]["ChatTurn"],
  "sources" | "next_action"
> & {
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
