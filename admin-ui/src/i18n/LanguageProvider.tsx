"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";
import { translate, type Locale, type TranslationValues } from "./catalog";

export const LANGUAGE_STORAGE_KEY = "mana:interface-language";
const LANGUAGE_CHANGED = "mana:language-changed";
function storedLocale(): Locale {
  try {
    return localStorage.getItem(LANGUAGE_STORAGE_KEY) === "uz" ? "uz" : "ru";
  } catch {
    return "ru";
  }
}
function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(LANGUAGE_CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(LANGUAGE_CHANGED, onChange);
  };
}
const LanguageContext = createContext<{
  locale: Locale;
  setLocale: (value: Locale) => void;
}>({ locale: "ru", setLocale: () => undefined });

export function LanguageProvider({
  children,
}: {
  children: ReactNode;
}): React.JSX.Element {
  const saved = useSyncExternalStore(
    subscribe,
    storedLocale,
    () => "ru" as Locale,
  );
  const [volatileLocale, setVolatileLocale] = useState<Locale | null>(null);
  const locale = volatileLocale ?? saved;
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  const setLocale = useCallback((value: Locale) => {
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, value);
      setVolatileLocale(null);
      window.dispatchEvent(new Event(LANGUAGE_CHANGED));
    } catch {
      // Do not block work when browser storage is unavailable.
      setVolatileLocale(value);
    }
  }, []);
  return (
    <LanguageContext.Provider value={{ locale, setLocale }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useI18n(): {
  locale: Locale;
  setLocale: (value: Locale) => void;
  t: (source: string, values?: TranslationValues) => string;
} {
  const { locale, setLocale } = useContext(LanguageContext);
  const t = useCallback(
    (source: string, values?: TranslationValues) =>
      translate(source, locale, values),
    [locale],
  );
  return { locale, setLocale, t };
}
