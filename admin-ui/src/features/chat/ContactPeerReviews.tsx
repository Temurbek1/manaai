"use client";

import useSWR from "swr";
import type { components } from "@/api/schema";
import { useI18n } from "@/i18n/LanguageProvider";
import { QueryState } from "@/components/QueryState";
import { PageHeader } from "@/components/PageHeader";
import { RetentionContactCard } from "./RetentionContactActions";

type Item = components["schemas"]["ContactReviewItem"];
type Page = components["schemas"]["ContactReviewPage"];
type Availability = components["schemas"]["ChatAvailability"];
const BASE = "/api/v1/admin/operation/workspace/retention-contact-reviews";

export function ContactPeerReviews({
  reviewId,
}: {
  reviewId?: string | undefined;
}): React.JSX.Element {
  const { t } = useI18n();
  const review = reviewId;
  const { data: availability, error: availabilityError } = useSWR<
    Availability,
    Error
  >("/api/v1/admin/operation/chat/availability");
  const enabled = availability?.retention_peer_reviews_enabled;
  const url = review ? `${BASE}/${encodeURIComponent(review)}` : BASE;
  const { data, error, isLoading, isValidating, mutate } = useSWR<
    Item | Page,
    Error
  >(enabled ? url : null);
  const items =
    data && !error && enabled ? ("items" in data ? data.items : [data]) : [];
  return (
    <section className="chat-page">
      <PageHeader
        eyebrow="MANA"
        title={t("Согласования Retention")}
        description={t("MANA · Только тестовые сообщения")}
      />
      {availability && !enabled ? (
        <p>{t("Согласование другим сотрудником отключено.")}</p>
      ) : (
        <QueryState
          error={error ?? availabilityError}
          loading={(!availability && !availabilityError) || isLoading}
          hasData={Boolean(data)}
          retrying={isValidating}
          onRetry={() => mutate()}
          subject={t("согласование")}
        />
      )}
      {items.map((item) => (
        <RetentionContactCard
          key={item.review_id}
          action={item.action}
          url={`${BASE}/${encodeURIComponent(item.review_id)}`}
          refresh={() => mutate()}
        />
      ))}
      {data && "more_omitted" in data && data.more_omitted && (
        <p>{t("Показаны только первые 20 согласований.")}</p>
      )}
      {data && !error && items.length === 0 && (
        <p>{t("Нет доступных согласований.")}</p>
      )}
    </section>
  );
}
