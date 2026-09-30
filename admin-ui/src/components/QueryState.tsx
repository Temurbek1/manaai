"use client";

interface QueryStateProps {
  error?: Error | undefined;
  loading: boolean;
  hasData: boolean;
  retrying?: boolean;
  onRetry: () => Promise<unknown>;
  subject: string;
}

/** Keep a failed or pending request distinct from a successful empty result. */
export function QueryState({
  error,
  loading,
  hasData,
  retrying,
  onRetry,
  subject,
}: QueryStateProps): React.JSX.Element | null {
  if (error) {
    return (
      <div className="error-banner query-state" role="alert">
        <div>
          <strong>Не удалось загрузить {subject}.</strong>
          <p>
            {hasData
              ? "Показаны ранее полученные данные. Они могут быть устаревшими."
              : "Данные недоступны — это не означает, что записей нет."}
          </p>
        </div>
        <button
          className="button secondary"
          disabled={retrying}
          onClick={() => void onRetry().catch(() => undefined)}
          type="button"
        >
          {retrying ? "Обновляем…" : "Повторить загрузку"}
        </button>
      </div>
    );
  }
  if (loading && !hasData) {
    return (
      <p className="notice" role="status">
        Загружаем {subject}…
      </p>
    );
  }
  return null;
}
