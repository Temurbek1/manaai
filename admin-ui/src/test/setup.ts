import "@testing-library/jest-dom/jest-globals";

import { cleanup } from "@testing-library/react";
import { afterEach, jest } from "@jest/globals";
import fetch, { Headers, Request, Response } from "cross-fetch";

Object.assign(globalThis, { fetch, Headers, Request, Response });

afterEach(() => {
  cleanup();
  jest.restoreAllMocks();
});

Object.defineProperty(globalThis.crypto, "randomUUID", {
  configurable: true,
  value: () => "00000000-0000-4000-8000-000000000001",
});
