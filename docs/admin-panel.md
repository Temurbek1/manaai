# Operation admin panel

The admin UI is a separate Next.js 16 App Router application with React 19 and strict TypeScript in
`admin-ui`. Vite was replaced so nested operational views are real routes with layouts, route
metadata, loading/error boundaries, direct-refresh support, and a reproducible standalone Node
runtime. FastAPI remains the only business backend.

## Rendering and module boundaries

- `src/app/layout.tsx` is a Server Component that owns document metadata, global CSS, and the
  stable application boundary.
- Route `page.tsx` files are Server Components for `/`, `/marketing`, `/approvals`, `/runs`, and
  `/agents`. They compose feature clients without duplicating transport logic.
- `AdminShell`, `AuthenticatedShell`, and `Providers` are Client Components because authentication
  credentials, route navigation, mobile state, SWR refresh, forms, and mutations are interactive.
- `src/features/` contains bounded client features. Operational keys use finite SWR intervals plus
  focus/reconnect revalidation; approvals and the global kill switch are explicitly re-read before
  mutation.
- `src/api/client.ts` is browser-safe and uses synchronized FastAPI OpenAPI types. It sends the
  in-memory role key to same-origin `/api` paths and never reads server-only configuration.
- `next.config.ts` owns the server-side FastAPI rewrite, security headers, and standalone output.
  `FASTAPI_BASE_URL` is private server configuration; no key or token uses `NEXT_PUBLIC_*`.

## Migrated responsibilities

| Original Vite responsibility | Next.js result |
| --- | --- |
| `main.tsx` bootstrap and global SWR config | Server root layout plus the focused `Providers` Client Component |
| monolithic `App.tsx` view switcher | real App Router pages, `AdminShell` authentication, and `AuthenticatedShell` navigation |
| `SessionContext` role helpers | reused as a small Client Context; credentials still remain only in module memory |
| typed API client | reused with a same-origin base, `no-store` requests, controlled errors, and 401 session expiry |
| dashboard/marketing/approvals/runs/agents pages | moved to `src/features/` and retained as interactive client leaves |
| tables, cards, badges, schedule editor, formatting/redaction | reused; focus, overflow, confirmation, and effect-derived-state issues were corrected |
| Vitest/Vite test runtime | migrated to Jest + jsdom through `next/jest`, preserving and expanding all flows |
| nginx static image and SPA fallback | replaced by the Next.js standalone Node image and native nested routes |

## Pages and safety behavior

- Overview: registry-derived agents, status, integration health, last/next run, duration, success
  rate, approvals/incidents, manual run, and a confirmed global emergency stop.
- Marketing Agent: Meta health, API version, permissions, safe account alias, currency/timezone,
  request budget/freshness, inventory, KPIs, quality states, findings, recommendations, reports,
  active configuration, and schedules.
- Approvals: evidence, reasoning, old/new typed values, risk, expiration, reasoned approve/reject,
  safe bulk decisions, decision history, self-approval denial, and a fresh queue read before action.
- Runs & audit: stage timeline, sanitized details, errors, retries, duration, correlation/initiator,
  snapshots, findings, recommendations, proposals, verification, and report audit events.
- Agent management: registry entries, status, health, capabilities/permissions, typed configuration
  validation/versioning, schedules, a confirmed per-agent kill switch, history, and reports.

The navigation uses generic platform sections; newly registered agents appear in the dashboard and
agent-management registry without a copied administrative stack. A specialized feature route is
only needed when an agent has genuinely different presentation requirements.

Production permissions are resolved by FastAPI from the submitted role key. Development identity
headers are ignored in production. The key is never written to cookies, local storage, session
storage, Server Component props, logs, or generated HTML; refresh/sign-out clears it. FastAPI is
authoritative for RBAC, self-approval, policy, staleness, idempotency, and write safety.

## Local, production, and Docker commands

```bash
# terminal 1
make run

# terminal 2; defaults FASTAPI_BASE_URL to http://127.0.0.1:8000
make admin-dev
```

Open `http://localhost:3000`. Build and run the production server with:

```bash
cd admin-ui
npm run build
FASTAPI_BASE_URL=http://127.0.0.1:8000 npm run start
```

`docker compose up --build` builds standalone output with the internal API destination and exposes
the admin server at `http://localhost:3000`. `/healthz` is the admin container health endpoint;
FastAPI liveness remains `/api/v1/health/live`.

## Verification

`make admin-verify` checks generated API synchronization, Prettier, ESLint, strict TypeScript,
Jest integration tests, the production build, standalone nested-route smoke, dependency and secret
audits, the fake-provider browser lifecycle/mobile smoke, absence of Vite runtime material, and the
Docker image build. `META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify` additionally opens
the actual Marketing page in enforced live read-only mode without clicking or exposing an execute
control.

Known limitation: role keys are memory-only shared credentials, not individual SSO sessions. A
trusted production gateway/identity provider is still required for individual attribution. The
memory-only design intentionally requires re-authentication after a direct refresh.
