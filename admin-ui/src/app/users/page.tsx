import type { Metadata } from "next";

import { UsersPage } from "@/features/UsersPage";

export const metadata: Metadata = { title: "Пользователи" };

export default function UsersRoute(): React.JSX.Element {
  return <UsersPage />;
}
