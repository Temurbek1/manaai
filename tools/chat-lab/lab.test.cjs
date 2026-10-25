"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { setImmediate: nextTick } = require("node:timers/promises");

class Element {
  constructor() {
    this.value = "";
    this.textContent = "";
    this.hidden = true;
    this.disabled = false;
    this.scrollHeight = 0;
    this.scrollTop = 0;
    this.clientHeight = 0;
    this.children = [];
    this.listeners = {};
    this.classList = { toggle() {} };
  }
  addEventListener(kind, callback) {
    this.listeners[kind] = callback;
  }
  append(child) {
    this.children.push(child);
  }
  replaceChildren() {
    this.children = [];
  }
  setAttribute() {}
  focus() {}
}

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

async function environment({
  failure,
  resume = false,
  phase = "completed",
  scenarios = [],
  sourceStatus = "completed",
  confirmation = null,
  question = null,
} = {}) {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const saved = new Map(
    resume ? [["mana-lab-pending", "fake-original-id"]] : [],
  );
  const requests = [],
    timers = [];
  const state = {
    mode: "simulation",
    history: {
      messages: [],
      active_question: question,
      active_confirmation: confirmation,
      quota: { used_tokens: 0, daily_limit: 2000, reserved_tokens: 0 },
    },
    safety_budget: {
      server_used_tokens: 0,
      server_daily_limit: 2000,
      server_reserved_tokens: 0,
    },
    assessments: { assessments: [] },
    conversions: { proposals: [] },
  };
  const context = {
    document: {
      visibilityState: "visible",
      getElementById: element,
      querySelector: () => ({ content: "fake-csrf" }),
      querySelectorAll: () => [],
      createElement: () => new Element(),
    },
    sessionStorage: {
      getItem: (key) => saved.get(key) || null,
      setItem: (key, value) => saved.set(key, value),
      removeItem: (key) => saved.delete(key),
    },
    crypto: { randomUUID: () => "fake-original-id" },
    setTimeout: (callback) => timers.push(callback),
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (url === "/lab/bootstrap")
        return response(200, {
          mode: "simulation",
          parent_id: "900001",
          scenarios,
        });
      if (url === "/lab/state") return response(200, state);
      if (options.method === "POST") {
        if (url === "/lab/child-battery")
          return response(200, { status: sourceStatus, cache_hit: true });
        if (failure === "network")
          throw new TypeError("Synthetic lost response after admission");
        if (typeof failure === "number")
          return response(failure, { detail: { code: "fake_refusal" } });
        return response(202, { phase: "awaiting_review" });
      }
      if (typeof failure === "number")
        return response(404, { detail: { code: "message_not_found" } });
      return response(200, { phase });
    },
    console,
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "lab.js"), "utf8"),
    context,
  );
  await nextTick();
  const submit = async () => {
    element("message").value = "Synthetic parent text";
    await element("composer").listeners.submit({ preventDefault() {} });
  };
  return { element, saved, requests, timers, submit };
}

test("local source scenario uses the isolated lab route, not a product endpoint", async () => {
  const env = await environment({
    scenarios: [
      {
        key: "battery",
        title: "Source",
        path: "/lab/child-battery",
        local: true,
        body: {},
      },
    ],
  });
  await env.element("scenarios").children[0].listeners.click();
  const posts = env.requests.filter((item) => item.options.method === "POST");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, "/lab/child-battery");
  assert.match(env.element("status").textContent, /сохранённый снимок/);
});

test("unknown source receipt is an error, not a promise of an incoming message", async () => {
  const env = await environment({
    sourceStatus: "unknown",
    scenarios: [
      {
        key: "battery",
        title: "Source",
        path: "/lab/child-battery",
        local: true,
        body: {},
      },
    ],
  });
  await env.element("scenarios").children[0].listeners.click();
  assert.equal(env.element("error").hidden, false);
  assert.equal(
    env.requests.filter((item) => item.options.method === "POST").length,
    1,
  );
  assert.equal(env.element("send").disabled, false);
});

test("one admitted message completes without a replacement request", async () => {
  const env = await environment();
  await env.submit();
  await env.timers.shift()();
  assert.equal(
    env.requests.filter((r) => r.options.method === "POST").length,
    1,
  );
  assert.equal(env.element("send").disabled, false);
  assert.equal(env.saved.has("mana-lab-pending"), false);
});

test("lost acknowledgement observes the original UUID and clears only its completed text", async () => {
  const env = await environment({ failure: "network" });
  await env.submit();
  assert.equal(
    env.requests.filter((r) => r.options.method === "POST").length,
    1,
  );
  assert.ok(
    env.requests.some((r) => r.url.includes("messages/fake-original-id?")),
  );
  assert.equal(env.element("message").value, "");
  assert.equal(env.element("error").hidden, true);
  assert.equal(env.element("send").disabled, false);
});

test("definitive validation refusal plus absent SQL state unlocks UI without replay", async () => {
  const env = await environment({ failure: 422 });
  await env.submit();
  assert.equal(env.element("send").disabled, false);
  assert.equal(env.element("message").value, "Synthetic parent text");
  assert.equal(env.saved.has("mana-lab-pending"), false);
  assert.equal(
    env.requests.filter((r) => r.options.method === "POST").length,
    1,
  );
});

test("an unclassified failure never discards the pending UUID or starts another POST", async () => {
  const env = await environment({ failure: 503 });
  await env.submit();
  await env.submit();
  await env.timers.shift()();
  assert.equal(env.element("send").disabled, true);
  assert.equal(env.saved.get("mana-lab-pending"), "fake-original-id");
  assert.equal(
    env.requests.filter((r) => r.options.method === "POST").length,
    1,
  );
});

test("reload with a pending identity only reads its status", async () => {
  const env = await environment({ resume: true });
  assert.equal(
    env.requests.filter((r) => r.options.method === "POST").length,
    0,
  );
  assert.equal(env.saved.has("mana-lab-pending"), false);
  assert.equal(env.element("send").disabled, false);
});

test("the single composer binds a parent confirmation separately from child questions", async () => {
  const env = await environment({
    confirmation: { confirmation_id: "parent-confirmation" },
  });
  await env.submit();
  const body = JSON.parse(
    env.requests.find((r) => r.options.method === "POST").options.body,
  );
  assert.equal(body.reply_to_confirmation_id, "parent-confirmation");
  assert.equal(body.reply_to_question_id, undefined);
});

test("an active child question has priority over an assistant confirmation", async () => {
  const env = await environment({
    confirmation: { confirmation_id: "parent-confirmation" },
    question: { question_id: "child-question" },
  });
  await env.submit();
  const body = JSON.parse(
    env.requests.find((r) => r.options.method === "POST").options.body,
  );
  assert.equal(body.reply_to_question_id, "child-question");
  assert.equal(body.reply_to_confirmation_id, undefined);
});
