# Operation admin panel

The admin UI is a separate Vite/React/TypeScript strict project in `admin-ui`. Its API types are
generated from FastAPI OpenAPI by `npm run generate:api`.

## Pages

- Overview: registry-derived agents, status, integration health, last/next run, duration, success
  rate, approvals/incidents, manual run, and global emergency stop.
- Marketing Agent: integration health and sync time; KPIs; campaigns, ad sets, ads, creatives,
  audiences; region/placement/hour/day/demographic performance; findings, recommendations,
  approvals, executions, reports, active configuration, and schedules.
- Approvals: evidence, reasoning, old/new typed values, risk, expiration, reasoned approve/reject,
  safe bulk decisions, and decision history.
- Runs & audit: stage timeline, sanitized details, errors, retries, duration, correlation/initiator,
  snapshots, findings, recommendations, and proposals.
- Agent management: registry entries, status, health, capabilities/permissions, JSON-schema-backed
  configuration validation/versioning, schedules, per-agent kill switch, run history, and reports.

The navigation is based on generic platform pages; new registered agents appear without duplicating
dashboard, run, report, configuration, or control infrastructure. A specialized page is optional.

## Run locally

```bash
make run
make admin-dev
```

Open `http://localhost:5173`; Vite proxies `/api` to port 8000. Sign in through the login screen.
Production derives actor/role only from the supplied role key; development headers are ignored.
The key remains in memory and is cleared on refresh/sign-out—browser storage is not used. Docker
Compose serves the UI at `http://localhost:3000` through Nginx, which proxies `/api` to the API.

The frontend gates are `npm run lint`, `npm run typecheck`, `npm run test -- --run`, and
`npm run build`. Critical authentication/RBAC, action, configuration/schedule, observability,
failure, responsive, redaction, and accessibility paths have integration tests. The full fake
provider lifecycle is covered by `scripts/browser_e2e.sh`.
