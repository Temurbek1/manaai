import "@testing-library/jest-dom/jest-globals";

import { cleanup } from "@testing-library/react";
import { afterEach, jest } from "@jest/globals";
import fetch, { Headers, Request, Response } from "cross-fetch";

Object.assign(globalThis, { fetch, Headers, Request, Response });

// JSDOM does not implement the browser's modal top layer. Keyboard containment
// and inert background behavior are verified by the real-browser audit.
Object.defineProperties(HTMLDialogElement.prototype, {
  showModal: {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  },
  close: {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    },
  },
});

afterEach(() => {
  cleanup();
  jest.restoreAllMocks();
});

Object.defineProperty(globalThis.crypto, "randomUUID", {
  configurable: true,
  value: () => "00000000-0000-4000-8000-000000000001",
});
