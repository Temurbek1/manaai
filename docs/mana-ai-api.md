# MANA AI API: контракт интеграции

## Назначение

MANA AI - независимый синхронный API-слой анализа. Приложение само получает разрешённые данные,
проверяет доступ parent-child, минимизирует payload и вызывает один специализированный endpoint.
В production вызов выполняет только доверенный backend/BFF приложения по server-to-server каналу.
Мобильный или browser-клиент не должен получать `APP_API_KEY` и обращаться к MANA AI напрямую.

```text
приложение собирает разрешённые данные
  -> доверенный backend выбирает endpoint по задаче
  -> MANA AI валидирует и анализирует payload
  -> возвращает typed findings/details/action proposals
  -> приложение применяет собственную authorization/policy
  -> приложение при необходимости выполняет подтверждённое действие
```

MANA AI:

- не подключается к Firebase или другой базе приложения;
- не получает данные самостоятельно по `child_id`;
- не проверяет связь родителя и ребёнка;
- не отправляет уведомления, не блокирует ресурсы и не меняет лимиты;
- вызывает Responses API с `store=false`, то есть не создаёт application state для response;
- удаляет точные `latitude`/`longitude` перед вызовом OpenAI; геолокационные действия
  ссылаются на локальный `evidence_id`, по которому приложение само получает координаты;
- удаляет credentials, query-параметры и fragment из HTTP(S) URL перед вызовом OpenAI;
- не возвращает исходные координаты, URL или приватный текст;
- всегда возвращает `read_only=true` и `executed=false` для proposals.

## Выбор endpoint

Все операции используют `POST`. Capability не передаётся в body: её однозначно задаёт URL.

| Задача приложения | Endpoint | Request | Capability-specific details |
| --- | --- | --- | --- |
| Проверить доступные safety-сигналы | `/api/v1/mana-ai/safety-monitor` | `SafetyMonitorRequest` | `SafetyMonitorDetails` |
| Сформировать дневной/недельный digest | `/api/v1/mana-ai/family-digest` | `FamilyDigestRequest` | `FamilyDigestDetails` |
| Оценить экранное время и лимиты | `/api/v1/mana-ai/adaptive-screen-time` | `AdaptiveScreenTimeRequest` | `AdaptiveScreenTimeDetails` |
| Оценить маршрут, ETA и геособытия | `/api/v1/mana-ai/location-intelligence` | `LocationIntelligenceRequest` | `LocationIntelligenceDetails` |
| Проверить URL/domain/QR/APK | `/api/v1/mana-ai/smart-content-filter` | `SmartContentFilterRequest` | `SmartContentFilterDetails` |
| Найти scam/privacy patterns | `/api/v1/mana-ai/scam-privacy-shield` | `ScamPrivacyShieldRequest` | `ScamPrivacyShieldDetails` |
| Оценить AI/game usage metadata | `/api/v1/mana-ai/ai-gaming-safety` | `AIGamingSafetyRequest` | `AIGamingSafetyDetails` |
| Ответить родителю по переданному контексту | `/api/v1/mana-ai/parent-copilot` | `ParentCopilotRequest` | `ParentCopilotDetails` |
| Ответить ребёнку безопасным языком | `/api/v1/mana-ai/child-safety-assistant` | `ChildSafetyAssistantRequest` | `ChildSafetyAssistantDetails` |
| Создать/проверить семейные правила | `/api/v1/mana-ai/family-agreement` | `FamilyAgreementRequest` | `FamilyAgreementDetails` |
| Объяснить отклонения от baseline | `/api/v1/mana-ai/behaviour-anomaly` | `BehaviourAnomalyRequest` | `BehaviourAnomalyDetails` |

`GET /api/v1/mana-ai/capabilities` возвращает тот же machine-readable каталог с точными
`method` и `path`. Endpoint `/api/v1/mana-ai/analyze` намеренно отсутствует.

## Аутентификация

Bearer token. На каждый вызов `/api/v1/mana-ai/*` передавайте `APP_API_KEY`:

```
Authorization: Bearer <APP_API_KEY>
```

Отказ возвращает `401` с заголовком `WWW-Authenticate: Bearer`. Заголовок `X-API-Key` больше не
поддерживается. Аутентификация включена, когда `APP_ENV=production` либо когда задан `APP_API_KEY`;
в `APP_ENV=local` без заданного ключа она выключена, что удобно для разработки.

Токен предназначен только для связи backend приложения с этим API. Не встраивайте его в
mobile/browser bundle.

Действуют два независимых лимита, оба отвечают `429` с `Retry-After`: на неуспешные попытки
аутентификации (`AUTH_FAILURE_LIMIT`, по умолчанию 10 за 60 с) и на успешные запросы
(`API_RATE_LIMIT_REQUESTS`, по умолчанию 60 за 60 с). Оба считаются на процесс и на client IP.

`/api/v1/health/live` и `/api/v1/health/ready` остаются открытыми для orchestrator probes.

## Общий request envelope

У всех 11 request-моделей одинаковы только транспортные и privacy-поля:

```json
{
  "request_id": "req-location-20260807-001",
  "occurred_at": "2026-08-07T14:20:00+05:00",
  "locale": "ru",
  "subject": {
    "subject_id": "child_opaque_12",
    "age_band": "age_7_12",
    "timezone": "Asia/Samarkand",
    "policy_version": "family-policy-7"
  },
  "input": {},
  "data_minimized": true
}
```

Правила:

- `request_id` уникален для логического анализа; при HTTP retry используется тот же ID.
- `occurred_at` - единственный момент выполнения анализа; timezone offset обязателен.
- `subject_id` - непрозрачный scoped ID. ФИО, email и телефон передавать нельзя.
- `age_band` передаётся вместо точной даты рождения.
- `locale` поддерживает вид `ru`, `uz`, `en`, `ru-RU`.
- `data_minimized` обязан быть `true`; иначе request отклоняется с `422`.
- неизвестные поля запрещены на каждом уровне (`extra=forbid`).
- `capability` и `schema_version` в body отсутствуют: endpoint уже версионирован `/api/v1`.

## Evidence contract

Сигналы, на которые может ссылаться finding, имеют уникальный `evidence_id`. Один ID нельзя
повторять внутри request. Модель не может создать новый evidence ID: такие findings/actions
удаляются, а response получает `status=degraded` и пояснение в `data_quality_notes`.

Приложение должно передавать производные и минимизированные данные:

| Источник приложения | Поля MANA AI |
| --- | --- |
| `/api/v1/child/location/{child_id}/` | `LocationPoint`, `RouteContext`, `Geofence` |
| `/api/v1/child/website-list/?child_id=...` | `WebsiteActivitySignal` или текущий `ResourceSignal` |
| `/api/v1/child/app-usage-statistics/{child_id}/` | `AppUsageSignal`, `UsageBaseline`, `MetricComparison` |
| Firebase battery/connectivity | `BatterySignal` |
| Android notification access | `NotificationPreviewSignal` с коротким excerpt |
| Local VPN/DNS/reputation service | `ResourceSignal` с уже известной reputation/category |

MANA AI не вызывает эти endpoints. Приложение обязано проверить authorization до формирования
payload. `subject_id` не является credential и не доказывает связь parent-child.

## Endpoint contracts

### Safety Monitor

`POST /api/v1/mana-ai/safety-monitor`

`input` принимает хотя бы один из сигналов: `notifications`, `resources`, `websites`, `app_usage`,
`locations`, `battery`, `protection_state`.

Результат содержит parent-safe context, число значимых событий и только те all-clear категории,
для которых реально был необходимый тип сигнала. Допустимые proposals: notify/warn, check-in,
resource block, contact parent, incident report.

### Family Digest

`POST /api/v1/mana-ai/family-digest`

Обязательны `period_start` и `period_end`. Дополнительно передаются агрегаты usage/baselines,
notification counts, website categories, metrics, movement, battery, protection и safety events.
`period_end` должен быть позже `period_start`.

Результат: `period_summary`, `highlights`, `positive_changes`, `minor_anomalies`. Исходная лента
уведомлений или координат не возвращается.

### Adaptive Screen Time

`POST /api/v1/mana-ai/adaptive-screen-time`

Обязателен непустой `app_usage`. Опционально: `usage_baselines`, `schedules`, `limits`,
`extra_time_requests`, `family_rules`.

Результат классифицирует только переданные package names и оценивает лимиты. Изменение лимита,
study mode, restriction и temporary access всегда остаются proposal; policy указывает, где нужно
подтверждение родителя.

### Location Intelligence

`POST /api/v1/mana-ai/location-intelligence`

```bash
curl -X POST http://localhost:8000/api/v1/mana-ai/location-intelligence \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer replace_with_internal_api_token' \
  -d '{
    "request_id": "req-location-20260807-001",
    "occurred_at": "2026-08-07T14:20:00+05:00",
    "locale": "ru",
    "subject": {
      "subject_id": "child_opaque_12",
      "age_band": "age_7_12",
      "timezone": "Asia/Samarkand"
    },
    "input": {
      "points": [{
        "evidence_id": "location-481",
        "observed_at": "2026-08-07T14:19:30+05:00",
        "source": "location",
        "latitude": 41.3111,
        "longitude": 69.2797,
        "accuracy_meters": 18,
        "location_source": "phone",
        "online": true
      }],
      "route": {
        "expected_arrival_at": "2026-08-07T13:45:00+05:00",
        "distance_from_usual_route_meters": 850,
        "unusual_route_threshold_meters": 500
      }
    },
    "data_minimized": true
  }'
```

Обязателен хотя бы один phone/tracker point. `route`, `geofences`, `battery` опциональны. Сервер
проверяет deviation, delay, long stop, unusual speed, spoofing, connectivity и battery anomalies.
Результат возвращает `route_status`, optional ETA/confidence и explanation, но не историю точек.

### Smart Content Filter

`POST /api/v1/mana-ai/smart-content-filter`

Принимает ровно один текущий `resource` (`url`, `domain`, `qr_code` или `apk`), optional notification
context, blocked categories и family rules. Известная reputation является доверенным фактом и не
может быть переопределена моделью. Результат: `decision=allow|observe|warn|block`, category,
reputation и краткое explanation.

### Scam & Privacy Shield

`POST /api/v1/mana-ai/scam-privacy-shield`

Нужен хотя бы один notification preview или checked resource. Анализируются fake prize/store/job,
phishing, password/document/card requests, suspicious bots, QR/APK patterns. Detection без
evidence-backed finding не возвращается клиенту.

### AI and Gaming Safety

`POST /api/v1/mana-ai/ai-gaming-safety`

Принимает только Android usage metadata: `app_usage`, baselines, limits, schedules и extra-time
requests. Содержание AI chats и игровых чатов не передаётся. `affected_packages` фильтруется по
package names из request.

### Parent Copilot

`POST /api/v1/mana-ai/parent-copilot`

Приложение передаёт `message` и только разрешённый родителю контекст: safety events, family rules,
usage и location. `allowed_action_kinds` может дополнительно сузить серверный allowlist.

Copilot может предложить только шесть типов действий: limit change, study mode, geofence, app
restriction, temporary access и family report. Он не исполняет их.

### Child Safety Assistant

`POST /api/v1/mana-ai/child-safety-assistant`

Принимает сообщение ребёнка, optional current resource, active rules и current usage. Ответ должен
быть age-appropriate. Допустимы только warn child, contact parent, extra-time request и incident
report proposals.

### Family Agreement

`POST /api/v1/mana-ai/family-agreement`

`mode`: `draft`, `review` или `child_request`. Передаются preferences, current rules и optional
child request. В режиме `child_request` поле `child_request` обязательно. Результат содержит draft
rules; их сохранение выполняет приложение только после подтверждения.

### Behaviour Anomaly

`POST /api/v1/mana-ai/behaviour-anomaly`

Принимает хотя бы один источник изменения: current-vs-baseline `metrics`, protection state, usage,
location или battery. Результат объясняет только наблюдаемое изменение и всегда содержит
`diagnosis_made=false`. Психологические и медицинские диагнозы запрещены.

## Общий response envelope

Каждый endpoint возвращает concrete response model, а не union:

```json
{
  "request_id": "req-location-20260807-001",
  "capability": "location_intelligence",
  "processed_at": "2026-08-07T09:20:01Z",
  "status": "completed",
  "verdict": "alert",
  "summary": "В доступных сигналах обнаружено значимое отклонение маршрута.",
  "details": {
    "route_status": "deviated",
    "estimated_arrival_at": null,
    "eta_confidence": null,
    "explanation": "Маршрут отклонился от переданного обычного маршрута."
  },
  "findings": [],
  "checks": [],
  "proposed_actions": [],
  "data_quality_notes": [],
  "model_name": "gpt-5.4-nano",
  "read_only": true,
  "privacy": {
    "application_data_mutated": false,
    "raw_input_returned": false,
    "provider_store_disabled": true
  }
}
```

### Status и verdict

- `status=completed`: model result и guardrails применены без потери данных.
- `status=degraded`: OpenAI был недоступен или часть model output отклонена guardrails.
- `no_risk_detected`: риск не найден только в доступных и успешно проверенных сигналах.
- `insufficient_data`: данных недостаточно; это не all-clear.
- `observe`, `warn`, `alert`, `block`: возрастающая требуемая реакция приложения.

Provider failure не превращается в HTTP 500: API возвращает typed `200 degraded` с результатом
детерминированных проверок и явными data-quality notes.

### Findings и checks

`findings` всегда ссылаются на существующие `evidence_ids`. `checks` показывают coverage отдельно
по категориям:

- `risk_detected`;
- `no_risk_detected`;
- `insufficient_data`;
- `not_applicable`.

Приложение не должно отображать общий зелёный статус, если хотя бы обязательный check имеет
`insufficient_data`.

### Action proposals

Каждый endpoint публикует в OpenAPI только допустимые для него action variants. Общие поля:

- `proposal_id` - стабильный для пары `request_id + identical proposal content`, независимо от
  порядка proposals;
- `execution_policy` - `information_only`, `application_policy_required` или
  `parent_confirmation_required`;
- `requires_parent_confirmation` вычисляется серверной policy, а не моделью;
- `proposal_only=true`;
- `executed=false`.

Перед выполнением приложение повторно проверяет authorization, актуальное состояние, policy и
parent confirmation. MANA AI не является источником разрешения на write.
Приложение не должно извлекать команды из `summary`, `details`, `finding.summary` или других
текстовых полей: автоматизируемой частью считаются только типизированные `proposed_actions`.

## HTTP, retry и ошибки

| Код | Значение |
| --- | --- |
| `200` | completed или degraded typed analysis |
| `401` | отсутствует/неверен bearer token; ответ содержит `WWW-Authenticate: Bearer` |
| `413` | body превышает `MANA_AI_MAX_REQUEST_BODY_BYTES` |
| `422` | request не соответствует конкретному endpoint schema |
| `429` | превышен лимит неуспешной аутентификации **или** лимит частоты запросов; учитывать `Retry-After` |

Retry допустим для timeout/network error и `429`. Используйте exponential backoff с jitter и тот
же `request_id`. API stateless: повтор запроса снова вызывает модель и сам по себе не является
идемпотентным по стоимости или результату. Приложение должно дедуплицировать бизнес-действия по
`request_id`, `proposal_id` и актуальному состоянию объекта.

## Swagger и SDK

В local/development/staging:

- Swagger UI: `/docs`;
- ReDoc: `/redoc`;
- OpenAPI 3.1: `/openapi.json`.

В production docs отключены. Генерируйте SDK из staging OpenAPI или из tracked
`admin-ui/openapi.json`. У каждого endpoint свой `operationId`, request schema, response schema,
details schema и ограниченный action union.

## OpenAI и production

`gpt-5.4-nano` выбран как самая дешёвая модель семейства GPT-5.4; она официально поддерживает
Responses API и Structured Outputs. Параметр модели остаётся конфигурируемым через `OPENAI_MODEL`.
Ссылки: [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Standalone factory: `app.product_ai_main:create_app`. Docker deployment:

```bash
docker compose -f docker-compose.mana-ai.yml config --quiet
docker compose -f docker-compose.mana-ai.yml up -d --build
```

Минимальные secrets/config:

```env
APP_ENV=production
APP_API_KEY=replace_with_high_entropy_internal_key
OPENAI_API_KEY=replace_with_rotated_project_key
OPENAI_MODEL=gpt-5.4-nano
OPENAI_REASONING_EFFORT=none
OPENAI_VERBOSITY=low
OPENAI_MAX_OUTPUT_TOKENS=2048
MANA_AI_MAX_REQUEST_BODY_BYTES=1048576
MANA_TELEGRAM_AUTH_ENABLED=false
OPERATION_AUTO_CREATE_SCHEMA=false
OPERATION_SCHEDULER_ENABLED=false
META_REAL_WRITES_ENABLED=false
```

Factory завершается при старте production без `APP_API_KEY` или `OPENAI_API_KEY`. Перед rollout
нужен отдельный eval dataset на русском и узбекском языках с false-positive/false-negative
метриками по каждому endpoint.

Для ручной проверки реального провайдера есть отдельный opt-in прогон на синтетических данных:

```bash
MANA_AI_LIVE_EVAL=1 make mana-ai-live-eval
```

Он делает один read-only model-access запрос и не более одного Structured Output запроса на каждый
из 11 endpoints. При `credit_balance_exhausted` прогон сразу прекращает последующие вызовы модели.
Отчет дописывается в `docs/artifacts/mana-ai-live-evaluation.md`: API payload, минимизированный
provider payload, raw Structured Output, итог после guardrails, response ID, latency, token usage,
автоматические проверки и пустой чек-лист для ручной оценки. Ключи, HTTP headers, Firebase и
данные приложения в отчет не попадают. Обычные `make test` и `make verify` реальный OpenAI не
вызывают.

`store=false` отключает сохранение response как application state, но само по себе не означает
Zero Data Retention: по стандартным правилам OpenAI abuse-monitoring logs могут хранить customer
content ограниченное время. Для соответствующего юридического требования владельцу проекта нужно
отдельно согласовать и включить Zero Data Retention или Modified Abuse Monitoring в OpenAI project.
Актуальные условия описаны в официальном разделе
[Data controls](https://developers.openai.com/api/docs/guides/your-data).
