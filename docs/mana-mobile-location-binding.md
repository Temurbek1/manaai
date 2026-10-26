# MANA child-location binding — source evidence, 2026-10-25

The owner supplied `https://github.com/Bosstracker-Team/bosstracker_parent` and
`/mnt/ssd2/Downloads/bosstracker_parent-develop.zip` in response to the numeric
child/GPS identity question. The archive was inspected read-only; no app code,
dependencies, listeners, build scripts or cloud mutations were executed.

Archive SHA256:
`5794cfce882876aaee57e163a793ec7b4d864e6c27d9fcde5eb23a9c64114036`.
This is evidence about the supplied revision, not proof of every deployed mobile
version or a live GitHub branch state. Keys/configuration from the source archive
were not copied to this repository, images, model requests or diagnostics.

## Authoritative identity and field path

Paths below are relative to `bosstracker_parent-develop/`:

- `lib/src/features/child/data/Models/child_model.dart:8` declares integer
  `childId`, with JSON field `id`; generated `child_model.g.dart:10` reads
  `childId: (json['id'] as num).toInt()`.
- `lib/src/features/child/presentation/screens/child_features_screen.dart:374`
  reads `collection('children_location').doc(child.childId.toString())`.
- `lib/src/features/fence/fence_map_screen.dart:299` and
  `lib/src/features/movement_history/history_map.dart:152` use the same collection
  and selected child's numeric ID. The latter also uses it at lines 506–507.
- `lib/src/data/repositories/firebase_repository.dart:26` performs the direct
  document read with its supplied `childId`.
- `lib/data/models/child_location_model.dart:29` reads `coords.longitude`,
  `coords.latitude` and `DateTime.parse(location.timestamp)`.
- `lib/src/data/firebase_messaging/firebase_options.dart:45,54` identifies project
  `bosstracker-dev`. No key value is needed to establish that project binding.

The exact family source is therefore
`bosstracker-dev/(default)/children_location/{canonical_numeric_child_id}`,
after a fresh MANA parent/profile ownership check. A model must never select a
different document/device ID or supply a path. An unverified matching string is
not ownership. These are child locations; GA4 parent activity is a separate scope.

## One direct, ownership-bound observation

The exclusive local party first logged in and freshly verified the designated
test parent 4's connected child through the existing Parent API adapter. It then
obtained a token with the existing key (2) and made **one direct document GET**,
using a fixed projection of coordinate pair, accuracy/speed and location
timestamp/mock/sample/movement/age fields. It validated the exact returned
document name and numeric coordinate ranges.

Result: **200**, valid coordinate pair, `mock=false`, `sample=false`, accuracy and
movement fields present, **1021 response bytes**, **four total HTTP attempts**
(MANA login/profile, OAuth, Firestore). No query/list/scan/listener/pagination,
retry, model call, grant, contact, source refresh or production mutation occurred.
No precise coordinates, child ID or family content appear in the saved public
receipt. Original evidence: `output/mobile-location-live-20261025/result.json`
and `output/mobile-location-document-once-20261025.log`. Do not replay the party
merely to obtain another successful receipt.

The point is dated **2026-10-14**. Collection on October 25 does not make it the
child's current position. Future integration must preserve the observation date,
accuracy/mock/sample qualifications and unavailable/stale states; one stored
point is not a route, location history, geofence event or evidence of danger.
No reverse-geocoded address, measured sensor units or current-presence claim is
established by this party.

The earlier application `/child/location/...` **403 remains valid historical
evidence**. It did not establish absence of Firestore data; this new owner-supplied
source revision resolves the previously missing identity binding without
retrying that rejected API or guessing another family.

## Next implementation boundary

The autonomous runtime **does not yet load this GPS source**. Add a typed exact-
child adapter through the existing shared request meter/cache/change journal,
fresh ownership and immutable native tool capture. Reuse existing window/targeted
read ceilings rather than a parallel refresh loop; unknown reads retain holds and
auth failures stop only this source. Do not expose raw GPS to OpenAI or parent
push lock screens. Separate deterministic local location processing from model
summaries and do not declare route analysis implemented from one point.
