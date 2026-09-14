# 360REC child audio moderation

## Contract

The service implements the push/callback protocol in the backend handoff document. It does not
poll 360REC for a call list.

The backend submits a job to:

```text
POST /api/v1/audio-moderation/jobs
Authorization: Bearer <AI_AUDIO_MODERATION_AUTH_TOKEN>
Content-Type: application/json
```

```json
{
  "audio_id": 123,
  "audio_url": "https://private-space.digitaloceanspaces.com/audio.mp3?presigned-query",
  "duration": "42",
  "callback_url": "https://api.360rec.uz/api/v1/child/audios/123/moderation/",
  "callback_token": "one-time-backend-jwt"
}
```

The response is `202`:

```json
{"status":"accepted","audio_id":123,"disposition":"queued"}
```

An active or recently completed duplicate returns the same `202` with
`"disposition":"duplicate"`. A full queue returns `503` and `Retry-After: 60`, which activates the
backend-owned retry flow.

After downloading and analyzing the audio, the service calls the exact supplied callback URL with
the supplied one-time token:

```json
{"status":"APPROVED","reason":"child_safety_risk:threat_or_violence:high"}
```

or:

```json
{"status":"REJECTED","reason":"no_child_safety_risk_detected"}
```

The status names follow the 360REC visibility contract, not ordinary content-moderation wording:

- `APPROVED` means dangerous, suspicious, or uncertain audio that requires guardian attention and
  is therefore visible to the parent;
- `REJECTED` means confidently safe audio or no meaningful speech and is hidden from the parent.

Low-confidence safe classifications and permanently unprocessable media fail toward guardian
visibility (`APPROVED` with a `manual_review_required:*` reason). Temporary download, OpenAI, and
callback failures do not produce a verdict; the backend retries with a fresh asset URL and callback
token according to its own state machine.

## Analysis and privacy

The live pipeline downloads the private object into memory, transcribes the completed recording,
and classifies bounded transcript chunks for child-safety risk. It recognizes Uzbek, Russian,
English, and mixed speech. Supported upload formats are `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`,
and `webm`, with a hard maximum of 25,000,000 bytes.

Audio bytes, presigned URLs, callback JWTs, and transcripts are never persisted or logged. The
callback contains only a bounded reason code, never a quote, name, phone number, address, or
transcript. OpenAI requests set `store=false`; provider data controls still require a separate
legal/privacy review for child audio.

## Security boundaries

- The intake token is compared in constant time and must contain at least 32 characters.
- The request body is capped independently before FastAPI/Pydantic processing.
- Validation responses omit submitted values so signed URLs and callback tokens cannot be echoed.
- Audio and callback destinations must use HTTPS on port 443 and match independent host allowlists.
- Redirects are disabled. The callback path must contain the same `audio_id` as the job.
- The default audio allowlist accepts DigitalOcean Spaces subdomains; replace it with the exact
  production bucket hostname when known.
- The callback allowlist defaults to the exact `api.360rec.uz` host.
- Queue capacity and maximum queue delay prevent accepting work that is likely to outlive the
  30-minute presigned asset URL.

## Production configuration

Install the token and OpenAI key through the deployment secret manager. Never add their values to
Git or a Docker image.

```dotenv
APP_ENV=production
MANA_TELEGRAM_AUTH_ENABLED=false
APP_API_KEY=<secret-managed-general-product-api-key>
OPENAI_API_KEY=<secret-managed-project-key>
OPENAI_MODEL=<configured-structured-output-model>

AUDIO_MODERATION_ENABLED=true
AI_AUDIO_MODERATION_AUTH_TOKEN=<rotated-shared-service-token>
AUDIO_MODERATION_TRANSCRIPTION_MODEL=gpt-transcribe
AUDIO_MODERATION_OPENAI_TIMEOUT_SECONDS=300
AUDIO_MODERATION_MODEL=
AUDIO_MODERATION_ALLOWED_AUDIO_HOSTS=["private-space.nyc3.digitaloceanspaces.com"]
AUDIO_MODERATION_ALLOWED_CALLBACK_HOSTS=["api.360rec.uz"]
```

Use the standalone MANA AI deployment for this endpoint:

```bash
docker compose -f docker-compose.mana-ai.yml up -d --build
```

After TLS/reverse-proxy deployment, give the backend team:

```text
AI_AUDIO_MODERATION_URL=https://<mana-ai-public-host>/api/v1/audio-moderation/jobs
```

Run one replica for the initial production rollout. Idempotency is process-local because the
backend intentionally owns durable state and retry. Multiple replicas remain callback-safe because
the backend accepts only its first verdict, but they can duplicate AI work until a shared intake
queue is introduced.

## Release gate

Before enabling historical backlog moderation:

1. Rotate the shared token if it has appeared in chat, logs, screenshots, or tickets.
2. Confirm the exact DigitalOcean Spaces hostname and narrow the audio allowlist.
3. Run `make verify` and build `Dockerfile.mana-ai`.
4. Submit one synthetic safe recording and verify a `REJECTED` callback.
5. Submit one synthetic threat fixture and verify an `APPROVED` callback.
6. Evaluate labeled Uzbek/Russian/English calls and approve explicit false-negative and
   false-positive thresholds with the child-safety owner.
7. Monitor `503`, download expiry, provider failure, callback rejection, latency, and queue depth.
8. Only then enable the backend legacy-backlog reset.

The implementation is production-oriented but cannot be called production-proven until the live
OpenAI account has credits, the public TLS URL exists, callback canary tests pass, and a labeled
multilingual child-safety evaluation establishes acceptable error rates.
