"use client";

import { useEffect } from "react";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function RouteError({
  error,
  reset,
}: RouteErrorProps): React.JSX.Element {
  useEffect(() => {
    // The server logs the full failure. Avoid echoing internal diagnostics into the browser UI.
  }, [error]);

  return (
    <section className="panel route-error" role="alert">
      <p className="eyebrow">Страница недоступна</p>
      <h1>Не удалось показать данные</h1>
      <p>
        Попробуйте открыть страницу ещё раз. Если ошибка повторяется, сообщите
        администратору.
      </p>
      <button className="button" onClick={reset} type="button">
        Повторить
      </button>
    </section>
  );
}
