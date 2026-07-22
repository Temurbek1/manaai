"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";

import { apiGet } from "@/api/client";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps): React.JSX.Element {
  return (
    <SWRConfig
      value={{
        fetcher: apiGet,
        revalidateOnFocus: true,
        revalidateOnReconnect: true,
        shouldRetryOnError: false,
      }}
    >
      {children}
    </SWRConfig>
  );
}
