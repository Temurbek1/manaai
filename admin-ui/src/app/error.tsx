"use client";

import { useI18n } from "@/i18n/LanguageProvider";

import { useEffect } from "react";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function RouteError({
  error,
  reset,
}: RouteErrorProps): React.JSX.Element {
  const { t } = useI18n();

  useEffect(() => {
    // The server logs the full failure. Avoid echoing internal diagnostics into the browser UI.
  }, [error]);

  return (
    <section className="panel route-error" role="alert">
      <p className="eyebrow">{t("Страница недоступна")}</p>
      <h1>{t("Не удалось показать данные")}</h1>
      <p>
        {t(
          "Попробуйте открыть страницу ещё раз. Если ошибка повторяется, сообщите администратору.",
        )}{" "}
      </p>
      <button className="button" onClick={reset} type="button">
        {t("Повторить")}{" "}
      </button>
    </section>
  );
}
