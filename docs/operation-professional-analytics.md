# Professional analytics workspace

Local UI increment, 15 October 2026. This is not a production deployment record.
The later isolated UI-only deployment is recorded in
[the professional UI release](operation-professional-ui-release.md).

## Navigation and presentation

Chat remains the default entry point. Professional mode uses a compact light admin
layout: grouped sidebar, page location, summary metrics and detail tables. Its visual
reference was the local master-battery admin; that repository was read only. The new
`/analytics` page is available from the sidebar and the overview data card. Existing
Growth, Retention, approval, audit and configuration routes retain their controls.
Russian and Uzbek Latin remain selectable without translating saved evidence.

## Saved sources, not new collection

The page requests the existing authenticated SQL report endpoint once per source,
with `agent_id=retention-agent`, `limit=5`, `offset=0`, and these capability filters:

| View | Capability | Display boundary |
| --- | --- | --- |
| GA4 | `retention.parent_activity.analyze` | Parent app analytics identities, existing completed-day windows of 1/7/30 days, events, qualified breakdowns and mature exact-day return cohorts |
| Firebase | `retention.child_telemetry.analyze` | Two document-ID prefix samples, at most 100 documents each, from battery and children_location; no coordinates or identifiers |
| Parent API | `retention.parents.analyze` | API parent total separately from the bounded sampled account/tariff/child-link summary; tariffs are not payment evidence |

Only reports with matching agent/capability/type and verified MANA scope are shown.
Parent activity and child telemetry are never combined into a retention denominator.
Missing or invalid measurements are displayed as unavailable, not zero. Incomplete
cohorts never acquire fabricated D1/D7/D30 values; breakdown row caps remain visible.
The selected saved period is not a claim about current activity or full population.

Collection time, report creation and cache freshness remain distinct. Invalid/future
collection timestamps are refused. Scope and source validation here is defensive
presentation, not an authorization grant or an independent source audit.

Source/window/report selection is local. Opening the page does not call providers,
models or integration health endpoints. Focus/reconnect refresh and transport retries
are disabled for these report queries. **Refresh screen** revalidates only the selected
SQL report list. There is no pagination, listener, schedule or source activation.
The Retention chat link does not submit a request; any future collection still uses
its existing separately confirmed policy/cooldown/budget workflow.

## Verification

The fixture in `admin-ui/src/test/fixtures/analytics-reports.json` is explicitly
synthetic demo data. It is used by Jest and the opt-in isolated browser audit, not
imported into the production page or seeded into a source database.

```sh
MANA_PRO_BROWSER_TMP=$(mktemp -d /mnt/ssd2/mpb.XXXXXX)
TMPDIR="$MANA_PRO_BROWSER_TMP" AUDIT_PROFESSIONAL_UI=true \
  AUDIT_PROFESSIONAL_UI_ONLY=true bash scripts/browser_e2e.sh
```

The browser checks three views, saved GA4 window switching, RU/UZ, 320px layout and
axe accessibility. Browser report responses are intercepted synthetic payloads;
this is not live GA4/Firestore/Parent API or authenticated production acceptance.
The ordinary fake-backend overview and login paths are also exercised. Automated
accessibility checks are not a complete WCAG or screen-reader certification.

The local `make verify` run passed: **1344 backend tests**, **193 UI tests / 28
suites**, Ruff/ESLint, mypy (383 files), TypeScript, formatting, production build
and npm audit (zero vulnerabilities). The 28 PostgreSQL tests were skipped in the
SQLite run and two opt-in live tests were excluded. Static checks were also rerun
after final presentation-guard changes. Logs: `output/professional-ui-verify.log`
and `output/professional-ui-final2-static.log`.

The final full browser run passed, including the opt-in analytics views and existing
chat/Goal, approval/execution, Retention, agents/users, journal, session and logout
flows. Russian/Uzbek persistence, mobile layout, keyboard behavior and axe checks
passed on the exercised pages. Log: `output/professional-browser-final.log`;
screenshots: `output/professional-browser-final/`. The first isolated audit had found
two inherited dark-theme contrast conflicts; those were fixed before the successful
isolated rerun and this final full run. The new report views used intercepted synthetic
reports, not live analytics; source/policy/identity checks remain server-owned.

After browser cleanup, the production build was regenerated. Standalone health and
unauthenticated root/runs/analytics routes passed, including CSP headers. The client
bundle scan (28 text assets), secret/quality scans, no-Vite check, unchanged OpenAPI
comparison and Compose validation passed. See `output/professional-ui-final-build.log`,
`output/professional-ui-final-smoke.log` and `output/professional-ui-schema.log`.

At this local checkpoint production remained unchanged. No backend contracts, private contact feature flags,
migrations, existing Goal history, source settings, schedules, main/audio API, SSH
or keys are changed by this UI increment. The subsequent separately approved clean-baseline
UI release passed verification and deployment checks without local contact work; see the
release record above. This historical local test record is not a broader source/model acceptance.
