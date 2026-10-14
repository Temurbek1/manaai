"use client";

import { useI18n } from "./LanguageProvider";

export function LanguageSelect(): React.JSX.Element {
  const { locale, setLocale } = useI18n();
  return (
    <select
      className="language-select"
      aria-label={locale === "uz" ? "Interfeys tili" : "Язык интерфейса"}
      value={locale}
      onChange={(event) => setLocale(event.target.value === "uz" ? "uz" : "ru")}
    >
      <option value="ru" lang="ru">
        Русский
      </option>
      <option value="uz" lang="uz">
        O‘zbekcha
      </option>
    </select>
  );
}
