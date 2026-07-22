# Deployment topology

## Supported production shape

```text
                    +--------------------+
browser / gateway ->| Next.js admin :3000 |---- /api ----+
                    +--------------------+              |
                                                        v
                                               +-----------------+
                                               | API replicas    |
                                               | scheduler=false |
                                               +--------+--------+
                                                        |
                         +----------------------+-------+----------------+
                         |                      |                        |
                         v                      v                        v
                  +-------------+       +---------------+       +---------------+
                  | PostgreSQL  |<------| worker        |------>| Meta/OpenAI   |
                  | operation_* |       | scheduler=true|       | providers     |
                  +-------------+       +---------------+       +---------------+
                         ^
                         |
                  +-------------+
                  | migrate job |
                  | upgrade head|
                  +-------------+
```

Compose implements this shape with `postgres`, one-shot `migrate`, scheduler-disabled `api`, a
separate scheduler-enabled `worker`, and the standalone Next.js `admin` server. API and worker
start only after migration succeeds. Production sets `APP_ENV=production` and disables
application-time schema creation. `/api/v1/health/live` remains unauthenticated for API container
health checks; `/healthz` checks the admin Node process.

The admin build receives `ADMIN_FASTAPI_BASE_URL` as the private `FASTAPI_BASE_URL` build argument.
The default Compose value is `http://api:8000`, so browser requests remain same-origin and the
Next.js server performs the internal rewrite. This variable is a network destination, never a
credential, and is not exposed through `NEXT_PUBLIC_*`.

The included Compose file forces dry-run and disables real Meta writes for both API and worker.
Changing only one gate must not enable writes. The migration service also has writes disabled.

## Scaling rules

- API replicas may scale horizontally because they do not poll schedules. Their in-process
  authentication failure counters are not shared; enforce distributed throttling at the gateway.
- Multiple worker replicas are safe for duplicate occurrences through database occurrence leases,
  run idempotency, and provider-object leases. Start with one worker until provider capacity and
  alerts are measured.
- PostgreSQL is mandatory for production multi-process coordination. SQLite is local development
  only.
- The legacy marketing repository still uses `MARKETING_DATABASE_PATH`; in Compose it has a durable
  volume. It is not the operation lock/idempotency store.
- Use a managed secret store for all API/role/provider keys. `.env` is ignored and not copied into
  images; Compose `env_file` injects values at runtime.

## Release sequence

1. Back up and verify restore capability for both stores.
2. Build immutable API/admin images and run `make admin-verify` and `make audit-verify` in CI.
3. Run the migration job once against the target PostgreSQL database.
4. Start scheduler-disabled API replicas and verify liveness/authenticated readiness.
5. Start worker replicas and inspect schedule leases, run/audit events, and provider health.
6. Keep `OPERATION_DRY_RUN=true`, `META_LIVE_MODE=read_only`, and
   `META_REAL_WRITES_ENABLED=false`; live Meta execution is unsupported.

Never run multiple application instances with `OPERATION_AUTO_CREATE_SCHEMA=true` in production.
Do not put migration execution back in API startup.

## Failure and rollback

- If a release fails before workers start, stop API, restore the prior image, and use only a tested
  migration downgrade when the migration is explicitly reversible and data-safe.
- If a worker dies, leave the due schedule unchanged; another worker recovers after lease expiry.
- If an action is `executing/write_outcome_uncertain`, do not repeat the provider write. Reconcile
  provider state and retain the audit trail.
- If a mismatch/partial application appears, enable global or per-agent kill switch, preserve
  provider request IDs, and require human disposition.
- If PostgreSQL is unavailable, fail closed for new runs/actions. Do not fall back to a local
  SQLite file.

## External production requirements

The repository does not provide an individual identity provider, distributed edge rate limiter,
managed PostgreSQL backups, metrics/alert transport, centralized logs, or a queue. These are
deployment responsibilities and remain blockers for real financial writes. Static role keys are
appropriate only behind a trusted internal gateway that supplies individual identity.
