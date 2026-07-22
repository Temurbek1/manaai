import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Providers } from "@/components/Providers";

import "../styles.css";

export const metadata: Metadata = {
  description: "Internal control room for MANA OPERATION AI agents.",
  title: {
    default: "MANA Operation AI",
    template: "%s · MANA Operation AI",
  },
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({
  children,
}: RootLayoutProps): React.JSX.Element {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AdminShell>{children}</AdminShell>
        </Providers>
      </body>
    </html>
  );
}
