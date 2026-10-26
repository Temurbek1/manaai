# Location and monitoring contracts — bounded read-only observation, 2026-10-25

This observation advances source integration for the full autonomous single-chat
objective. It is not a new implemented source, permission change, live collector
or proof that all child data is available. The application remains at `ced2964`.

## Location

One new, exclusive diagnostic performed exactly three HTTP attempts:

1. Login through the existing MANA Admin API — known successful response.
2. `GET /api/v1/admin-panel-parent/parent-list/?parent_id=4&limit=1&offset=0`
   through the existing ownership adapter — the designated test parent and its
   connected child relationship were verified freshly.
3. `GET /api/v1/child/location/{verified_own_child}/` — **403**, JSON response.

The third path is referenced in `docs/mana-ai-api.md`. No alternative route,
credential, family, retry or Firestore query was tried after the rejection. The
diagnostic stores only response shape/status, not the token, child's identity,
coordinates or raw error prose. A 403 here establishes rejection of this request;
it does not by itself establish its exact upstream policy reason or absence of
data in Firestore. It is not a Cloud IAM/GA4 diagnosis.

At this diagnostic checkpoint, the earlier October-12 sampled Firestore schema established location coordinates
and metadata but does not establish an authoritative numeric child-profile join.
Do not infer ownership from a coincidentally equal document/device ID. Missing
mapping does not mean every location record lacks ownership or that the data
does not exist. A precise family tool requires the actual mobile/backend binding
or another authorized exact-child source. A short question about that binding is
pending with the owner; unrelated implementation work need not wait for it.
The owner subsequently supplied the mobile source: the numeric binding and one
direct Firestore GET are now verified in
[the later binding checkpoint](mana-mobile-location-binding.md). The point is
stale, and a GPS runtime adapter is still unimplemented. This later evidence
does not rewrite or repeat the known application-API rejection below.

Original receipt: `output/child-location-contract-20261025` and
`output/child-location-contract-once-20261025.log`. Do not replay this old party
or turn its known 403 into a new admission/fallback loop.

## Camera/audio/screen monitoring logs

A separate new diagnostic used the supplied `manakids-ai-docs.md` contract:

1. One login and one fresh ownership-filtered test-parent profile read.
2. `GET /api/v1/admin-panel-child/camera-audio-usage-logs/{verified_own_child}/`
   with `limit=2&offset=0` — **200**.

The known envelope contains `count`, `next`, `previous`, `results`; this selected
child returned `count=0`, no next/previous cursor and an empty results list.
No pagination or alternative period/family was followed. This proves exact-child
API access for that observed test case, not the shape of a populated event,
whole-population coverage, child inactivity, absence of recordings elsewhere or
parent app churn. Dates, actors, units and event meanings are still needed before
introducing a typed analytical source. Do not fabricate that contract from the
empty list or mix parental monitoring commands with child behaviour.

Original receipt: `output/child-monitoring-contract-20261025` and
`output/child-monitoring-contract-once-20261025.log`. This was three HTTP attempts,
with response bytes capped at 64 KiB. Saved output contains only shapes and safe
date/duration/count examples; there were no populated examples in this response.

Across both parties: **six direct MANA HTTP attempts**, no direct Firebase/GA4 or
model requests, no contacts, tariff grants, payment, production configuration or
schedule change. Backend resource costs are not measured by those counts. No
working GPS/monitoring adapter or broad source readiness is claimed.
