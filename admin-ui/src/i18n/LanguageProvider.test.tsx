import { fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import {
  LANGUAGE_STORAGE_KEY,
  LanguageProvider,
  useI18n,
} from "./LanguageProvider";
import { LanguageSelect } from "./LanguageSelect";
import { translate, UZ } from "./catalog";
import { LoginPanel } from "@/components/LoginPanel";
import { GoalReport } from "@/features/chat/GoalReport";

function Example(): React.JSX.Element {
  const { t } = useI18n();
  return (
    <>
      <LanguageSelect />
      <h1>{t("Над чем поработаем?")}</h1>
      <GoalReport text="Сохранённое доказательство: 17/99" />
    </>
  );
}

describe("Russian and Uzbek interface", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    localStorage.clear();
    document.documentElement.lang = "ru";
  });

  it("switches, persists, restores and never translates stored evidence", () => {
    const first = render(
      <LanguageProvider>
        <Example />
      </LanguageProvider>,
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Язык интерфейса" }),
      { target: { value: "uz" } },
    );
    expect(
      screen.getByRole("heading", { name: "Nima ustida ishlaymiz?" }),
    ).toBeVisible();
    expect(document.documentElement.lang).toBe("uz");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("uz");
    expect(screen.getByText("Сохранённое доказательство: 17/99")).toBeVisible();
    first.unmount();
    render(
      <LanguageProvider>
        <Example />
      </LanguageProvider>,
    );
    expect(
      screen.getByRole("combobox", { name: "Interfeys tili" }),
    ).toHaveValue("uz");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ru" } });
    expect(
      screen.getByRole("heading", { name: "Над чем поработаем?" }),
    ).toBeVisible();
  });

  it("keeps selection usable when browser storage is blocked", () => {
    jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Blocked");
    });
    render(
      <LanguageProvider>
        <Example />
      </LanguageProvider>,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "uz" } });
    expect(
      screen.getByRole("heading", { name: "Nima ustida ishlaymiz?" }),
    ).toBeVisible();
  });

  it("localizes login and validation without changing Telegram authentication", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "uz");
    const fetch = jest.spyOn(globalThis, "fetch");
    render(
      <LanguageProvider>
        <LoginPanel notice={null} onAuthenticated={() => undefined} />
      </LanguageProvider>,
    );
    expect(
      screen.getByRole("heading", { name: "MANA’ga kirish" }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Telegram ID"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Kod olish" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Telegram ID noto‘g‘ri kiritilgan.",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("has Uzbek translations for every owned Cyrillic UI literal", () => {
    const root = path.resolve(process.cwd(), "src");
    function files(directory: string): string[] {
      return fs
        .readdirSync(directory, { withFileTypes: true })
        .flatMap((item) =>
          item.isDirectory()
            ? files(path.join(directory, item.name))
            : [path.join(directory, item.name)],
        );
    }
    const missing = new Set<string>();
    for (const file of files(root)) {
      if (
        !/\.tsx?$/.test(file) ||
        file.includes(".test.") ||
        file.includes("/i18n/") ||
        file.includes("/api/") ||
        file.endsWith("/layout.tsx")
      )
        continue;
      const tree = ts.createSourceFile(
        file,
        fs.readFileSync(file, "utf8"),
        ts.ScriptTarget.Latest,
        true,
      );
      function visit(node: ts.Node): void {
        if (
          ts.isStringLiteral(node) &&
          /[А-Яа-яЁё]/.test(node.text) &&
          !Object.hasOwn(UZ, node.text)
        )
          missing.add(node.text);
        if (ts.isJsxText(node) && /[А-Яа-яЁё]/.test(node.text))
          missing.add(node.text.trim());
        ts.forEachChild(node, visit);
      }
      visit(tree);
    }
    expect([...missing]).toEqual([]);
  });

  it("retains every interpolation argument and leaves unknown text untouched", () => {
    for (const [source, translated] of Object.entries(UZ)) {
      const placeholders = (text: string): string[] =>
        [...text.matchAll(/\{\d+\}/g)].map((match) => match[0]).sort();
      expect(placeholders(translated)).toEqual(placeholders(source));
      expect(translated.trim()).not.toBe("");
      expect(/[А-Яа-яЁё]/.test(translated)).toBe(false);
    }
    expect(translate("Чат: {0}", "uz", { 0: "MANA" })).toBe("Chat: MANA");
    expect(translate("Original user text <script>", "uz")).toBe(
      "Original user text <script>",
    );
  });
});
