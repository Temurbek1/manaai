# MANA AI boundary

MANA AI is the product-facing API context for the mobile application. Its eleven analysis
capabilities retain the contract:

`endpoint payload -> validation -> AI processing -> structured response`.

The complete request/response inference contract lives in `app/mana_ai`.
`/api/v1/mana-ai/capabilities` exposes the implemented catalog and
Eleven endpoint-specific routes under `/api/v1/mana-ai` perform product analysis. The capability
is selected by the route and is never supplied in the request body. The generic
`/api/v1/mana-ai/analyze` route intentionally does not exist.

## Allowed

- Data supplied in the current endpoint payload.
- Typed request and response schemas.
- Safe common settings, model gateway, observability, errors, and policy definitions.
- Stateless AI inference and structured validation.
- The separately opted-in `/mana-ai/chat` uses typed application ports for its own
  durable conversation/quota store and a read-only ownership-filtered child-profile
  source. Concrete persistence/HTTP/model adapters stay in `app/services/`, outside
  `app/mana_ai`. This exception does not grant the eleven analysis capabilities DB access.

## Prohibited

- Arbitrary application DB access, operational repository access or source scans.
  Only the explicit parent-chat ports above may access parent-owned chat state and
  the documented filtered profile source; model text cannot select a query or target.
- Imports from `app.mana_operation_ai`.
- Meta Ads, CRM, analytics warehouse, action executor, or operational repository access.
- Arbitrary background work or changes to company data.
- Treating a mobile inference request as authority to perform an action. Every action is returned
  as a non-executed proposal and is policy-checked by the application.

The boundary test scans every Python file in `app/mana_ai`. Other product inference must accept
needed evidence in its request, minimize sensitive content, return only a typed result, and follow
the privacy and parent/child disclosure rules designed for that feature.

The transport and OpenAI adapter live outside the bounded context. The existing `/api/v1/ai`
endpoints are retained for backward compatibility. New mobile product inference work belongs to
`app/mana_ai`, not the operation platform. The client integration contract is documented in
`docs/mana-ai-api.md`.

The independent stateful chat contract, including backend identity responsibility,
exact replays, daily input/output quota, bounded historical model context and source
coverage limits, is in [mana-parent-chat.md](mana-parent-chat.md). It is not an
administrative agent, a new operational topic or part of the paused workspace goal.
