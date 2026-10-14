"use client";
import { useI18n } from "@/i18n/LanguageProvider";
import Link from "next/link";

export default function NotFound(): React.JSX.Element {
  const { t } = useI18n();

  return (
    <section className="panel route-error">
      <p className="eyebrow">404</p>
      <h1>{t("Страница не найдена")}</h1>
      <Link className="button" href="/">
        {t("Вернуться к обзору")}{" "}
      </Link>
    </section>
  );
}
