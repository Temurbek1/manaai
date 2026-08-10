# ManaAI API

Production-oriented FastAPI-платформа с двумя независимыми контурами: продуктовым
`MANA AI` и внутренним `MANA OPERATION AI`. Помимо совместимого legacy API проект содержит
универсальное ядро операционных агентов, законченный Marketing Agent для Meta Ads,
SQLAlchemy/Alembic persistence, безопасный action lifecycle, scheduler и Next.js admin panel.

Быстрая проверка полного vertical slice без внешних расходов:

```bash
make install
make migrate
make demo
make verify
```

Архитектура и эксплуатация описаны в `docs/architecture.md`,
`docs/operation-ai-platform.md`, `docs/marketing-agent.md`, `docs/action-safety.md` и
`docs/runbook.md`. Контракт продуктового AI API для разработчиков приложения описан в
`docs/mana-ai-api.md`. Индивидуальный вход в admin panel описан в
`docs/telegram-otp-auth.md`.

## Что внутри

- Standalone read-only MANA AI factory: `app.product_ai_main:create_app`
- Совместимая полная platform factory: `app.main:create_app`
- Версионированный API prefix: `/api/v1`
- OpenAI интеграция через `AsyncOpenAI`
- Настраиваемая через `OPENAI_MODEL` модель для существующего product AI gateway
- Meta Marketing API слой через официальный Graph API `v25.0`
- Append-only raw storage в SQLite, чтобы не терять исходные данные Meta/экспортов/developer-console evidence
- Детерминированные KPI до вызова AI: spend, impressions, reach, clicks, conversions, CTR, frequency, CPC, CPM, CPA, ROAS
- AI analytics output через OpenAI Structured Outputs
- Swagger UI/OpenAPI docs по рекомендациям FastAPI: metadata, tag descriptions, summaries, request duration и фильтр операций
- Trace headers: `X-Request-ID` и `X-Process-Time-Ms`
- Конфигурация через env и `.env`
- Dockerfile + `docker-compose.yml`
- Базовые async tests
- Строгое разделение слоев: routes, schemas, services, core config
- Строгая import-граница `app/mana_ai` и `app/mana_operation_ai`
- Generic agent registry, state machines, versioned configs/schedules и audit trail
- Provider-neutral AdsPlatform с безопасным live Meta и полноценным fake Meta
- Next.js 16 App Router admin UI с React 19 и strict TypeScript в `admin-ui`

## API endpoints

Внутренний operation API расположен под `/api/v1/admin/operation` и включает dashboard,
agents/status/run, runs/timeline, configurations/schema versions, schedules, findings,
recommendations, proposals, approvals/bulk decisions, executions, reports, integration health,
audit events и global/per-agent kill switches. Полный typed contract доступен в OpenAPI.

Browser authentication endpoints:

- `POST /api/v1/auth/telegram/request-code` — generic запрос шестизначного кода;
- `POST /api/v1/auth/telegram/verify-code` — одноразовая проверка и HttpOnly session;
- `GET /api/v1/auth/session` — минимальный session/user/RBAC contract;
- `POST /api/v1/auth/logout` — server-side revoke и очистка cookie;
- `/api/v1/admin/users` — admin-only управление разрешёнными Telegram users.

- `GET /api/v1/health/live` - liveness probe
- `GET /api/v1/health/ready` - readiness probe
- `POST /api/v1/ai/chat` - тестовый чат-запрос к OpenAI
- `POST /api/v1/ai/summarize` - тестовая суммаризация текста
- `GET /api/v1/mana-ai/capabilities` - каталог 11 read-only MANA AI capabilities
- `POST /api/v1/mana-ai/{capability}` - 11 отдельных typed endpoints без capability в body;
  точные paths возвращает `GET /api/v1/mana-ai/capabilities`
- `GET /api/v1/marketing/config` - non-secret статус Meta/OpenAI конфигурации
- `POST /api/v1/marketing/raw` - загрузка raw marketing JSON records
- `GET /api/v1/marketing/raw` - просмотр сохраненных raw records
- `POST /api/v1/marketing/raw/search` - поиск raw records по provider id и payload/dimension filters
- `POST /api/v1/marketing/meta/discover` - сбор app/ad account metadata через Meta Graph API
- `POST /api/v1/marketing/meta/sync` - сбор данных через Meta Marketing API
- `POST /api/v1/marketing/meta/insights/jobs` - fixture/legacy async job API; live Meta returns 403
- `GET /api/v1/marketing/meta/insights/jobs/{report_run_id}` - статус async job
- `POST /api/v1/marketing/meta/insights/jobs/{report_run_id}/ingest` - загрузка результатов async job в raw storage
- `POST /api/v1/marketing/graph` - граф связей app/business/pixel/custom conversion/ad account/custom audience/campaign/adset/ad/creative/insight
- `POST /api/v1/marketing/patterns` - детерминированный поиск закономерностей в raw insights
- `POST /api/v1/marketing/analyze` - KPI + структурированный AI отчет
- `GET /api/v1/marketing/reports` - список сохраненных AI отчетов
- `GET /api/v1/marketing/reports/{report_id}` - чтение сохраненного typed AI отчета
- `GET /api/v1/marketing/reports/{report_id}/evidence` - отчет + raw evidence bundle

Пример:

```bash
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Скажи коротко, что такое FastAPI"}'
```

## Локальный запуск

Требования:

- Python 3.12+
- Docker и Docker Compose для контейнерного запуска

Через Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[operation,dev]"
uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

Для независимого MANA AI без подключения к каким-либо базам используйте:

```bash
uvicorn app.product_ai_main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

Через Docker:

```bash
docker compose up --build
```

Standalone AI API без Postgres, migrations, worker и admin:

```bash
docker compose -f docker-compose.mana-ai.yml up --build
```

Admin panel: `http://localhost:3000` через `make admin-dev` или Docker Compose. Next.js проксирует
same-origin `/api` к FastAPI через private `FASTAPI_BASE_URL`; бизнес-логика остаётся в FastAPI. В
admin panel пользователь вводит Telegram ID и одноразовый шестизначный код от MANA Bot. Refresh
сохраняет fixed server session на 8 часов, logout отзывает её. Роли приходят только с backend;
технические role keys не доступны в пользовательском UI.

Swagger UI доступен локально на `http://localhost:8000/docs`, ReDoc на `http://localhost:8000/redoc`, OpenAPI schema на `http://localhost:8000/openapi.json`. В `APP_ENV=production` документация отключается.

## Env configuration

Секреты читаются только из окружения. Локальный `.env` уже добавлен в `.gitignore`; для прода используйте `.env.example` как шаблон.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `APP_ENV` | yes | `local` | `local`, `development`, `staging` или `production` |
| `APP_NAME` | no | `manaai-api` | Название сервиса |
| `APP_VERSION` | no | `0.1.0` | Версия сервиса |
| `APP_API_KEY` | yes in production | - | API key для `X-API-Key`; обязателен при `APP_ENV=production` |
| `MANA_TELEGRAM_BOT_TOKEN` | staging/production auth | - | Telegram Bot API token; secret, legacy alias `BOT_TOKEN` accepted |
| `MANA_TELEGRAM_BOT_USERNAME` | staging/production auth | - | Public bot username for the Start link |
| `MANA_OTP_HMAC_SECRET` | staging/production auth | - | Separate high-entropy HMAC key for OTP/session/CSRF digests |
| `MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS` | no | `976835256,51456737` | Idempotent initial admins |
| `MANA_OTP_TTL_SECONDS` | no | `60` | Fixed OTP lifetime; only 60 is accepted |
| `MANA_OTP_RESEND_COOLDOWN_SECONDS` | no | `30` | Cooldown before challenge replacement |
| `MANA_OTP_MAX_VERIFY_ATTEMPTS` | no | `5` | Wrong attempts per challenge |
| `MANA_SESSION_TTL_SECONDS` | no | `28800` | Fixed eight-hour server session |
| `MANA_TRUSTED_ORIGINS` | staging/production auth | - | JSON list of browser origins accepted for cookie mutations |
| `OPENAI_API_KEY` | yes | - | API key OpenAI |
| `OPENAI_MODEL` | no | `gpt-5.4-nano` | Модель OpenAI |
| `OPENAI_TIMEOUT_SECONDS` | no | `30` | Timeout запросов к OpenAI |
| `OPENAI_MAX_OUTPUT_TOKENS` | no | `2048` | Максимум output tokens structured response |
| `OPENAI_TEMPERATURE` | no | `0.2` | Температура генерации |
| `OPENAI_REASONING_EFFORT` | no | `none` | Reasoning effort для structured analysis |
| `OPENAI_VERBOSITY` | no | `low` | Детальность structured response |
| `MANA_AI_MAX_REQUEST_BODY_BYTES` | no | `1048576` | Максимальный JSON body standalone MANA AI API |
| `CORS_ORIGINS` | no | `[]` | JSON список разрешенных origins |
| `ADMIN_FASTAPI_BASE_URL` | Compose build | `http://api:8000` | Internal FastAPI destination for the Next.js server rewrite; never a credential |
| `MARKETING_DATABASE_PATH` | no | `data/manaai.db` | SQLite path для raw records и reports |
| `OPERATION_DATABASE_URL` | no | derived SQLite URL | Async SQLAlchemy URL для operation tables |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose | see `.env.example` | PostgreSQL database and credentials; use a secret manager in production |
| `OPERATION_SCHEDULER_ENABLED` | no | `false` | Persisted scheduler; Compose включает только в отдельном worker |
| `OPERATION_DATA_RETENTION_DAYS` | no | `90` | Retention для normalized provider snapshots и зависимых analyses/findings |
| `OPERATION_ADS_PROVIDER` | no | `fake_meta` | `fake_meta` or `meta` |
| `OPERATION_DRY_RUN` | no | `true` | Запрещает provider writes |
| `META_LIVE_MODE` | no | `read_only` | Единственный допустимый live Meta mode |
| `META_LIVE_READONLY_VERIFY` | no | `false` | Явный opt-in только для bounded GET validation |
| `META_LIVE_MAX_*` | no | conservative | Per-run requests/pages/retries/duration/account budgets |
| `OPERATION_*_API_KEY` | production | - | Viewer/operator/approver/admin internal keys |
| `OPERATION_ALLOW_INSECURE_DEV_HEADERS` | no | `false` | Test-only local compatibility; ordinary browser/local runtime must keep false |
| `OPERATION_*_EXECUTION_LIMIT_PER_DAY` | no | conservative | Global/per-agent action limits |
| `MARKETING_CONVERSION_ACTION_TYPES` | no | JSON list | Meta `actions.action_type`, которые считаются conversions |
| `MARKETING_VALUE_ACTION_TYPES` | no | JSON list | Meta `action_values.action_type`, которые считаются revenue/value |
| `MARKETING_MEASUREMENT_STALE_AFTER_DAYS` | no | `14` | Через сколько дней без `last_fired_time` pixel/custom conversion считается stale |
| `META_GRAPH_BASE_URL` | no | `https://graph.facebook.com` | Graph API base URL |
| `META_GRAPH_API_VERSION` | no | `v25.0` | Версия Graph/Marketing API |
| `META_APP_ID` | yes for Meta sync | - | Meta app id из Meta for Developers |
| `META_BUSINESS_ID` | no | - | Business id для owned/client ad accounts |
| `META_ACCESS_TOKEN` | yes for Meta sync | - | System user access token |
| `META_AD_ACCOUNT_IDS` | no | `[]` | JSON list ad account ids, например `["act_123"]` |
| `META_*_FIELDS` | no | JSON lists | Явные fields для business/pixels/custom conversions/custom audiences/campaigns/adsets/ads/ad creatives/ad accounts/insights |
| `META_ACTION_ATTRIBUTION_WINDOWS` | no | `["1d_click","7d_click"]` | Attribution windows для insights |
| `META_REAL_WRITES_ENABLED` | no | `false` | Must stay false; startup rejects true |

## Meta Marketing workflow

В `APP_ENV=production` все `/api/v1/ai/*` и `/api/v1/marketing/*` endpoints требуют header `X-API-Key`. `/api/v1/health/live` остается открытым для Docker/Kubernetes healthcheck.

```bash
curl -H "X-API-Key: $APP_API_KEY" http://localhost:8000/api/v1/marketing/config
```

Каждый ответ содержит `X-Request-ID` и `X-Process-Time-Ms`. Клиент может передать свой `X-Request-ID`, backend вернет его обратно; если header не передан, backend сгенерирует UUID.

Для production sync используйте system user access token из Meta Business Manager. Это официальный серверный путь для автоматических API calls к assets бизнеса.

Минимальный `.env` для Meta:

```env
OPERATION_ADS_PROVIDER=meta
OPERATION_DRY_RUN=true
META_GRAPH_API_VERSION=v25.0
META_LIVE_MODE=read_only
META_REAL_WRITES_ENABLED=false
META_APP_ID=replace_with_meta_app_id
META_BUSINESS_ID=replace_with_business_id
META_ACCESS_TOKEN=replace_with_system_user_access_token
META_AD_ACCOUNT_IDS=["act_123456789"]
MARKETING_DATABASE_PATH=/data/manaai.db
```

Live validation is separately opt-in and GET-only:

```bash
META_LIVE_READONLY_VERIFY=1 make meta-live-readonly-verify
```

Первичная проверка подключения и сбор доступных assets:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/meta/discover
```

Ответ сохранит app/ad account payloads в raw storage и вернет `record_ids`, которые можно дальше использовать для аудита.

Синхронизация структуры и insights:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/meta/sync \
  -H "Content-Type: application/json" \
  -d '{
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "levels": ["campaign", "adset", "ad"],
    "include_structure": true,
    "include_insights": true
  }'
```

Для поиска закономерностей по сегментам можно сразу синхронизировать granular
Insights rows с breakdowns. Эти строки сохраняются как raw payloads, а KPI rows
получают поле `dimensions`, например `publisher_platform` и `platform_position`:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/meta/sync \
  -H "Content-Type: application/json" \
  -d '{
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "levels": ["ad"],
    "breakdowns": ["publisher_platform", "platform_position"],
    "action_breakdowns": ["action_type"],
    "time_increment": 1,
    "include_structure": false,
    "include_insights": true
  }'
```

При `include_structure=true` backend сохраняет raw payloads для business, pixels, custom conversions, custom audiences, campaigns, ad sets, ads и ad creatives. Ad creatives подтягиваются через Meta ad account `adcreatives` edge; custom conversions - через `customconversions`; custom audiences - через `customaudiences`; pixels - через business `owned_pixels`. Наборы полей задаются через `META_CREATIVE_FIELDS`, `META_CUSTOM_CONVERSION_FIELDS`, `META_CUSTOM_AUDIENCE_FIELDS` и `META_PIXEL_FIELDS`.

`breakdowns`, `action_breakdowns` и `time_increment` сохраняются в insight payload как `_meta_breakdowns`, `_meta_action_breakdowns` и `_meta_time_increment`. Это помогает аудитить, каким отчетным срезом была получена каждая строка. Для breakdown rows `provider_record_id` получает compact dimension hash, чтобы разные сегменты одного entity/date не склеивались в графе.

Legacy/fixture integration retains the async Insights contract for compatibility. In live Meta
read-only mode the creation call below returns typed HTTP 403 because Meta async report creation is
POST and is intentionally forbidden:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/meta/insights/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "act_123456789",
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "level": "ad",
    "time_increment": 1
  }'
```

Проверка статуса:

```bash
curl http://localhost:8000/api/v1/marketing/meta/insights/jobs/{report_run_id}
```

После `Job Completed` загрузите результаты в raw storage:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/meta/insights/jobs/{report_run_id}/ingest \
  -H "Content-Type: application/json" \
  -d '{"account_id":"act_123456789","level":"ad","limit":100}'
```

Raw ingestion для экспортов из Ads Manager или будущих ETL:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/raw \
  -H "Content-Type: application/json" \
  -d '{
    "records": [
      {
        "source": "manual_upload",
        "entity_type": "insight",
        "account_id": "act_123456789",
        "observed_at": "2026-07-01T00:00:00+00:00",
        "payload": {
          "campaign_id": "1",
          "campaign_name": "Prospecting",
          "date_start": "2026-07-01",
          "date_stop": "2026-07-01",
          "spend": "100",
          "impressions": "10000",
          "clicks": "250",
          "actions": [{"action_type": "lead", "value": "20"}]
        }
      }
    ]
  }'
```

Raw ingestion также подходит для sanitized Meta Developer Console evidence:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/raw \
  -H "Content-Type: application/json" \
  -d '{
    "records": [
      {
        "source": "meta_developer_console",
        "entity_type": "app",
        "provider_record_id": "replace_with_meta_app_id",
        "parent_id": "replace_with_business_id",
        "payload": {
          "id": "replace_with_meta_app_id",
          "name": "MANA AI",
          "business_id": "replace_with_business_id",
          "business_name": "Mana App BM",
          "publication_status": "not_published",
          "use_cases": ["MARKETING_API_ADS_ANALYTICS"],
          "permissions": ["ads_read", "business_management"],
          "required_actions": ["business_verification", "app_review"]
        }
      }
    ]
  }'
```

Не загружайте в raw storage app secret, access token, cookies, `fb_dtsg` или browser session tokens. Developer-console records нужны как operational evidence: статус публикации, разрешения, review/business verification, use cases и ссылки на source pages.

Поиск raw строк после найденной закономерности:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/raw/search \
  -H "Content-Type: application/json" \
  -d '{
    "account_ids": ["act_123456789"],
    "entity_types": ["insight"],
    "payload_filters": {"_meta_level": "ad"},
    "dimension_filters": {"publisher_platform": "facebook", "platform_position": "feed"},
    "limit": 100
  }'
```

`payload_filters` и `dimension_filters` работают по точному совпадению top-level JSON fields. Это покрывает аудит segment patterns: из ответа `/patterns` можно взять `dimensions` и `evidence_record_ids`, затем открыть соответствующие raw payloads без повторного запроса к Meta. Для creative и custom audience patterns ищите raw creative/ad/adset/audience records по `provider_record_id` из `entity_id` pattern.

AI analytics report:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/patterns \
  -H "Content-Type: application/json" \
  -d '{
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "max_patterns": 20
  }'
```

Patterns endpoint ищет spend concentration, spend without conversions, efficiency opportunities, CPC/CTR outliers, high-frequency fatigue, segment waste/segment efficiency по breakdown dimensions, hierarchy waste/efficiency по связке raw campaign/adset/ad -> lower-level insights, creative waste/creative efficiency по связке raw ad -> creative, custom audience waste/efficiency по связке raw adset targeting -> ad/adset insights, delivery/status issues по `status`, `effective_status` и ad account `account_status`, unmapped action signals для проверки `MARKETING_CONVERSION_ACTION_TYPES`, measurement health issues по pixel/custom conversion (`is_unavailable`, `is_archived`, stale `last_fired_time`), простые тренды и data quality gaps. Fatigue threshold управляется request-полем `frequency_fatigue_threshold` (default `3.0`). Audience patterns - это targeting rollup, а delivery/measurement patterns - это ограничения доверия к действиям и трекингу: перед изменением бюджета проверяйте overlap, exclusions, frequency, current delivery status и состояние Events Manager.

Граф связей между raw сущностями:

```bash
curl -X POST http://localhost:8000/api/v1/marketing/graph \
  -H "Content-Type: application/json" \
  -d '{
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "include_insights": true
  }'
```

Graph endpoint строит nodes/edges из raw records: business owns app/ad account/pixel, pixel reports custom conversions, account contains campaigns/adsets/ads/creatives/custom conversions/custom audiences, ad sets target custom audiences, ads point to creatives, insight rows measure account/campaign/adset/ad objects.

```bash
curl -X POST http://localhost:8000/api/v1/marketing/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "date_start": "2026-07-01",
    "date_stop": "2026-07-21",
    "question": "Что масштабировать и где режется бюджет?",
    "include_raw_samples": false
  }'
```

Ответ содержит `kpi_summary`, список KPI rows с `dimensions` для breakdown-сегментов, deterministic `patterns`, `graph`, operational context, полный evidence-набор `source_record_ids` для аудита и typed `report`: summary, health score, findings, prioritized actions, data quality notes, raw-data followups. При `include_raw_samples=true` AI context получает raw samples из этого evidence-набора, включая structure/developer-console records, на которые ссылаются patterns/graph.

Каждый AI отчет сохраняется в SQLite вместе с полным typed response. Историю можно использовать для аудита, повторного чтения backend/frontend-клиентами и сверки выводов с raw source records:

```bash
curl http://localhost:8000/api/v1/marketing/reports
curl http://localhost:8000/api/v1/marketing/reports/{report_id}
curl http://localhost:8000/api/v1/marketing/reports/{report_id}/evidence
```

Evidence bundle возвращает сохраненный `report`, все найденные `raw_records`, на которые ссылаются `source_record_ids`, KPI rows, patterns и graph, плюс `missing_record_ids` для старых/неполных переносов.

## Прод-распаковка MANA AI API на сервере

Ниже основной вариант для независимого read-only AI API на обычном Linux VPS с Docker.
Он не запускает PostgreSQL, SQLite, migrations, scheduler, worker или admin UI. Команды
выполняются на сервере.

1. Установите Docker и Compose plugin:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

2. Создайте директорию приложения и распакуйте архив проекта:

```bash
sudo mkdir -p /opt/manaai-api
sudo chown "$USER":"$USER" /opt/manaai-api
cd /opt/manaai-api
tar -xzf manaai-api.tar.gz --strip-components=1
```

Если деплоите через Git:

```bash
git clone <your-repository-url> /opt/manaai-api
cd /opt/manaai-api
```

3. Создайте production `.env`:

```bash
cp .env.example .env
nano .env
```

Оставьте только необходимые standalone-настройки и сгенерируйте отдельный high-entropy
`APP_API_KEY`:

```env
APP_ENV=production
APP_API_KEY=replace_with_server_api_key
OPENAI_API_KEY=replace_with_real_secret
OPENAI_MODEL=gpt-5.4-nano
OPENAI_REASONING_EFFORT=none
OPENAI_VERBOSITY=low
OPENAI_MAX_OUTPUT_TOKENS=2048
MANA_AI_MAX_REQUEST_BODY_BYTES=1048576
CORS_ORIGINS=[]
MANA_TELEGRAM_AUTH_ENABLED=false
OPERATION_AUTO_CREATE_SCHEMA=false
OPERATION_SCHEDULER_ENABLED=false
META_REAL_WRITES_ENABLED=false
```

4. Соберите и запустите контейнер:

```bash
docker compose -f docker-compose.mana-ai.yml config --quiet
docker compose -f docker-compose.mana-ai.yml up -d --build
docker compose -f docker-compose.mana-ai.yml ps
docker compose -f docker-compose.mana-ai.yml logs -f mana-ai-api
```

5. Проверьте health endpoint:

```bash
curl http://127.0.0.1:8000/api/v1/health/live
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

Проверьте authenticated-каталог контрактов:

```bash
read -rsp "APP_API_KEY: " APP_API_KEY && echo
curl -H "X-API-Key: $APP_API_KEY" \
  http://127.0.0.1:8000/api/v1/mana-ai/capabilities
unset APP_API_KEY
```

В production Swagger отключён. Для просмотра и генерации клиентских SDK поднимите тот же factory
в доверенном staging с `APP_ENV=staging` и откройте `/docs` или `/openapi.json`. Полная platform
с БД и operation-модулями разворачивается отдельно через основной `docker-compose.yml` и не нужна
для MANA AI request/response integration.

`APP_API_KEY` используется только между доверенным backend приложения и MANA AI. Не встраивайте
его в mobile/browser bundle. Compose публикует порт только на `127.0.0.1`; для другого сервера
используйте приватную сеть/VPN либо TLS reverse proxy с сетевым allowlist.

## Nginx reverse proxy пример

```nginx
server {
    listen 80;
    server_name api.example.com;
    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

После настройки домена подключите TLS через Certbot или другой ACME client.

## Проверки качества

```bash
make verify
make admin-verify
make audit-verify
```

Реальный OpenAI не вызывается обычными тестами. Ограниченный ручной прогон всех MANA AI
capabilities на синтетических данных запускается отдельно:

```bash
MANA_AI_LIVE_EVAL=1 make mana-ai-live-eval
```

История запросов, ответов, latency, token usage и чек-листы ручной оценки сохраняются в
`docs/artifacts/mana-ai-live-evaluation.md`. После ошибки `credit_balance_exhausted` следующие
платные запросы не отправляются.

## Security notes

- Не коммитьте `.env` и реальные API keys.
- В проде храните секреты в secret manager, CI/CD variables или server-only `.env`.
- После передачи ключа в чат лучше перевыпустить OpenAI key в dashboard и заменить значение на сервере.
- Meta access token храните только server-side; не отдавайте его frontend-клиентам и не пишите в логи.
- Docs UI отключается при `APP_ENV=production`.
