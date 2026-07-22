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
      <p className="eyebrow">Route unavailable</p>
      <h1>Operational data could not be rendered</h1>
      <p>
        Retry the route. If the failure persists, check the sanitized server
        logs.
      </p>
      <button className="button" onClick={reset} type="button">
        Try again
      </button>
    </section>
  );
}
