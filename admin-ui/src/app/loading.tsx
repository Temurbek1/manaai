"use client";
import { useI18n } from "@/i18n/LanguageProvider";
export default function Loading(): React.JSX.Element {
  const { t } = useI18n();

  return (
    <div aria-live="polite" className="loading-state" role="status">
      {t("Загружаем данные…")}{" "}
    </div>
  );
}
