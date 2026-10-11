import { describe, expect, it } from "@jest/globals";
import config from "../../next.config";

describe("agent backend routing", () => {
  it("routes workspace through the same scoped backend as chat and Goals", async () => {
    const rules = await config.rewrites!();
    if (!Array.isArray(rules))
      throw new Error("Expected explicit ordered rewrites");
    const goal = rules.find(
      (rule) => rule.source === "/api/v1/admin/operation/goals/:path*",
    );
    const workspace = rules.find(
      (rule) => rule.source === "/api/v1/admin/operation/workspace/:path*",
    );
    expect(goal).toBeDefined();
    expect(workspace).toBeDefined();
    const chatTarget = (
      process.env.OPERATION_CHAT_BASE_URL ??
      process.env.FASTAPI_BASE_URL ??
      "http://127.0.0.1:8000"
    ).replace(/\/+$/, "");
    expect(workspace?.destination).toBe(
      `${chatTarget}/api/v1/admin/operation/workspace/:path*`,
    );
    expect(
      workspace?.destination.replace("workspace/:path*", "goals/:path*"),
    ).toBe(goal?.destination);
    expect(rules.indexOf(workspace!)).toBeLessThan(
      rules.findIndex((rule) => rule.source === "/api/:path*"),
    );
  });
});
