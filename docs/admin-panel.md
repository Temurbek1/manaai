# Operation admin panel

The admin UI is a separate Next.js 16 App Router application with React 19 and strict TypeScript in
`admin-ui`. Vite was replaced so nested operational views are real routes with layouts, route
metadata, loading/error boundaries, direct-refresh support, and a reproducible standalone Node
runtime. FastAPI remains the only business backend.

## Rendering and module boundaries

- `src/app/layout.tsx` is a Server Component that owns document metadata, global CSS, and the
  stable application boundary.
- Route `page.tsx` files are Server Components for `/`, `/growth`, `/approvals`, `/runs`,
  `/agents`, and admin-only `/users`. They compose feature clients without duplicating transport
  logic.
- `AdminShell`, `AuthenticatedShell`, and `Providers` are Client Components because session
  restoration, route navigation, mobile state, SWR refresh, forms, and mutations are interactive.
- `src/features/` contains bounded client features. Operational keys use finite SWR intervals plus
  focus/reconnect revalidation; approvals and the global kill switch are explicitly re-read before
  mutation.
- `src/api/client.ts` is browser-safe and uses synchronized FastAPI OpenAPI types. It sends
  same-origin cookies and CSRF headers, but never accepts or sends a user-selected actor, role,
  API key, bearer token, bot token, or OTP outside the explicit verify request.
- `next.config.ts` owns the server-side FastAPI rewrite, security headers, and standalone output.
  `FASTAPI_BASE_URL` is private server configuration; no key or token uses `NEXT_PUBLIC_*`.

## Migrated responsibilities

| Original Vite responsibility | Next.js result |
| --- | --- |
| `main.tsx` bootstrap and global SWR config | Server root layout plus the focused `Providers` Client Component |
| monolithic `App.tsx` view switcher | real App Router pages, `AdminShell` authentication, and `AuthenticatedShell` navigation |
| `SessionContext` role helpers | uses the minimal backend session user and permissions; no browser-asserted role |
| typed API client | same-origin cookies, `no-store`, CSRF for mutations, controlled errors, and 401 session expiry |
| dashboard/marketing/approvals/runs/agents pages | moved to `src/features/` and retained as interactive client leaves |
| tables, cards, badges, schedule editor, formatting/redaction | reused; focus, overflow, confirmation, and effect-derived-state issues were corrected |
| Vitest/Vite test runtime | migrated to Jest + jsdom through `next/jest`, preserving and expanding all flows |
| nginx static image and SPA fallback | replaced by the Next.js standalone Node image and native nested routes |

## Pages and safety behavior

- Overview: registry-derived agents, status, integration health, last/next run, duration, success
  rate, approvals/incidents, manual run, and a confirmed global emergency stop.
- Growth & Conversion: one capability selector for advertising and funnel analysis. Advertising
  retains Meta health, inventory, KPIs, findings, actions, and reports; funnel shows deterministic
  findings, hypotheses, approval-gated sandbox experiments, and outcomes. `/marketing` redirects
  to `/growth` for compatibility.
- Approvals: evidence, reasoning, old/new typed values, risk, expiration, reasoned approve/reject,
  safe bulk decisions, decision history, self-approval denial, and a fresh queue read before action.
- Runs & audit: stage timeline, sanitized details, errors, retries, duration, correlation/initiator,
  snapshots, findings, recommendations, proposals, verification, and report audit events.
- Agent management: registry entries, status, health, capabilities/permissions, typed configuration
  validation/versioning, independent schedules, confirmed per-agent and per-capability kill
  switches, capability-filtered history, and reports.
- Users: admin-only Telegram identity grant, profile/role/status, last-login/creation metadata,
  disable/re-enable, session revocation, and authentication audit.

The navigation uses generic platform sections; newly registered agents appear in the dashboard and
agent-management registry without a copied administrative stack. A specialized feature route is
only needed when an agent has genuinely different presentation requirements.

Human login is Telegram ID → six-digit bot code → opaque HttpOnly server session. `AdminShell`
restores the session on refresh, shows a Russian two-step form when anonymous, supports one-time-code
paste, 60-second countdown, resend cooldown, bot Start guidance, keyboard submission, controlled
errors, and mobile layout. The browser stores no identity secret in local/session storage. FastAPI
is authoritative for role, user UUID, RBAC, CSRF, self-approval, policy, staleness, idempotency, and
write safety. The full security model is in `docs/telegram-otp-auth.md`.

## Local, production, and Docker commands

```bash
# terminal 1
make run

# terminal 2; defaults FASTAPI_BASE_URL to http://127.0.0.1:8000
make admin-dev
```

Configure the real local bot and HMAC secret in ignored `.env`, press Start in the bot, then open
`http://localhost:3000`. Build and run the production server with:

```bash
cd admin-ui
npm run build
FASTAPI_BASE_URL=http://127.0.0.1:8000 npm run start
```

`docker compose up --build` builds standalone output with the internal API destination and exposes
the admin server at `http://localhost:3000`. `/healthz` is the admin container health endpoint;
FastAPI liveness remains `/api/v1/health/live`.

## Verification

`make auth-verify` checks migrations, strict backend/frontend auth tests, production build,
cookie/security rules, fake-Telegram browser E2E, dependency/secret audits, and both images.
`make admin-verify` checks generated API synchronization, Prettier, ESLint, strict TypeScript,
Jest integration tests, the production build, standalone nested-route smoke, dependency and secret
audits, the fake-provider browser lifecycle/mobile smoke, absence of Vite runtime material, and the
Docker image build. `META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify` additionally opens
the actual Marketing page in enforced live read-only mode without clicking or exposing an execute
control.

Known limitation: Telegram delivery requires each user to start the bot and depends on Telegram
availability. Sessions are fixed at eight hours and do not roll. A trusted gateway remains required
for TLS termination, safe proxy-header handling, distributed edge protection, and centralized
monitoring; durable in-app OTP/rate/session state is shared through PostgreSQL.
