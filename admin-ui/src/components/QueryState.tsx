"use client";

import { useI18n } from "@/i18n/LanguageProvider";

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
  const { t } = useI18n();

  if (error) {
    return (
      <div className="error-banner query-state" role="alert">
        <div>
          <strong>
            {t("Не удалось загрузить")} {subject}.
          </strong>
          <p>
            {hasData
              ? t(
                  "Показаны ранее полученные данные. Они могут быть устаревшими.",
                )
              : t("Данные недоступны — это не означает, что записей нет.")}
          </p>
        </div>
        <button
          className="button secondary"
          disabled={retrying}
          onClick={() => void onRetry().catch(() => undefined)}
          type="button"
        >
          {retrying ? t("Обновляем…") : t("Повторить загрузку")}
        </button>
      </div>
    );
  }
  if (loading && !hasData) {
    return (
      <p className="notice" role="status">
        {t("Загружаем")} {subject}…
      </p>
    );
  }
  return null;
}
