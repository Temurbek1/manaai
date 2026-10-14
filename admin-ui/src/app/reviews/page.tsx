import { ContactPeerReviews } from "@/features/chat/ContactPeerReviews";

export default async function ReviewsRoute({
  searchParams,
}: {
  searchParams: Promise<{ review?: string | string[] }>;
}): Promise<React.JSX.Element> {
  const params = await searchParams;
  return (
    <ContactPeerReviews
      reviewId={typeof params.review === "string" ? params.review : undefined}
    />
  );
}
