import { useState } from "react";

import type { ActorSession, ClientCredentials } from "../api/client";

interface LoginPanelProps {
  busy: boolean;
  error: string | null;
  onLogin: (credentials: ClientCredentials) => Promise<void>;
}

const ROLES: readonly ActorSession["role"][] = [
  "viewer",
  "operator",
  "approver",
  "admin",
];

export function LoginPanel({
  busy,
  error,
  onLogin,
}: LoginPanelProps): React.JSX.Element {
  const [apiKey, setApiKey] = useState("");
  const [actorId, setActorId] = useState("admin-ui");
  const [developmentRole, setDevelopmentRole] =
    useState<ActorSession["role"]>("viewer");

  return (
    <main className="login-page">
      <form
        className="login-panel"
        onSubmit={(event) => {
          event.preventDefault();
          void onLogin({
            apiKey: apiKey.trim(),
            actorId: actorId.trim(),
            developmentRole,
          });
        }}
      >
        <div className="brand login-brand">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>MANA</strong>
            <small>Operation AI</small>
          </div>
        </div>
        <p className="eyebrow">Internal access</p>
        <h1>Sign in to the control room</h1>
        <p className="page-description">
          Production permissions come only from the API key. Development
          identity headers are ignored by production.
        </p>
        <label className="field">
          <span>Internal API key</span>
          <input
            autoComplete="current-password"
            onChange={(event) => setApiKey(event.target.value)}
            type="password"
            value={apiKey}
          />
        </label>
        <label className="field">
          <span>Development actor ID</span>
          <input
            autoComplete="username"
            maxLength={120}
            onChange={(event) => setActorId(event.target.value)}
            required
            value={actorId}
          />
        </label>
        <label className="field">
          <span>Development role</span>
          <select
            onChange={(event) =>
              setDevelopmentRole(event.target.value as ActorSession["role"])
            }
            value={developmentRole}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </label>
        {error ? (
          <p className="error-banner" role="alert">
            {error}
          </p>
        ) : null}
        <button className="button login-button" disabled={busy} type="submit">
          {busy ? "Verifying…" : "Sign in"}
        </button>
        <small className="credential-note">
          Credentials stay in memory and are cleared on refresh or sign out.
        </small>
      </form>
    </main>
  );
}
