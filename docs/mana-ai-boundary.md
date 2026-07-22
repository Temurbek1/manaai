# MANA AI boundary

MANA AI is the product-facing API context for the mobile application. Its contract is strictly:

`endpoint payload -> validation -> AI processing -> structured response`.

The foundation lives in `app/mana_ai`. `/api/v1/mana-ai/capabilities` exposes its current boundary
and makes clear that the product functions from `MANA AI.pdf` are planned, not implemented by this
vertical slice.

## Allowed

- Data supplied in the current endpoint payload.
- Typed request and response schemas.
- Safe common settings, model gateway, observability, errors, and policy definitions.
- Stateless AI inference and structured validation.

## Prohibited

- Direct user database access.
- Imports from `app.mana_operation_ai`.
- Meta Ads, CRM, analytics warehouse, action executor, or operational repository access.
- Arbitrary background work or changes to company data.
- Treating a mobile inference request as authority to perform an action.

The boundary test scans every Python file in `app/mana_ai`. A future product feature must accept all
needed evidence in its request, minimize sensitive content, return only a typed result, and follow
the privacy and parent/child disclosure rules designed for that feature.

The existing `/api/v1/ai` endpoints are retained for backward compatibility. New mobile product
work should be implemented under `app/mana_ai`, not added to the operation platform.
