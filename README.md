# ManaAI API

Production-ready backend на FastAPI для API слоя ИИ-интеграций и маркетинговой аналитики. В проекте есть Docker, типизированные Pydantic-схемы, Swagger/OpenAPI, OpenAI Responses API, Meta Marketing API sync, raw-data storage и структурированный AI output для аналитики.

## Что внутри

- FastAPI application factory: `app.main:create_app`
- Версионированный API prefix: `/api/v1`
- OpenAI интеграция через `AsyncOpenAI`
- Дефолтная модель: `gpt-5.4-nano`, самая дешевая GPT-5.4-class модель по цене токенов
- Meta Marketing API слой через официальный Graph API `v25.0`
- Append-only raw storage в SQLite, чтобы не терять исходные данные Meta/экспортов
- Детерминированные KPI до вызова AI: spend, impressions, clicks, conversions, CTR, CPC, CPM, CPA, ROAS
- AI analytics output через OpenAI Structured Outputs
- Swagger UI/OpenAPI docs по рекомендациям FastAPI: metadata, tag descriptions, summaries, request duration и фильтр операций
- Конфигурация через env и `.env`
- Dockerfile + `docker-compose.yml`
- Базовые async tests
- Строгое разделение слоев: routes, schemas, services, core config

## API endpoints

- `GET /api/v1/health/live` - liveness probe
- `GET /api/v1/health/ready` - readiness probe
- `POST /api/v1/ai/chat` - тестовый чат-запрос к OpenAI
- `POST /api/v1/ai/summarize` - тестовая суммаризация текста
- `GET /api/v1/marketing/config` - non-secret статус Meta/OpenAI конфигурации
- `POST /api/v1/marketing/raw` - загрузка raw marketing JSON records
- `GET /api/v1/marketing/raw` - просмотр сохраненных raw records
- `POST /api/v1/marketing/meta/discover` - сбор app/ad account metadata через Meta Graph API
- `POST /api/v1/marketing/meta/sync` - сбор данных через Meta Marketing API
- `POST /api/v1/marketing/meta/insights/jobs` - создание Meta async Insights job
- `GET /api/v1/marketing/meta/insights/jobs/{report_run_id}` - статус async job
- `POST /api/v1/marketing/meta/insights/jobs/{report_run_id}/ingest` - загрузка результатов async job в raw storage
- `POST /api/v1/marketing/graph` - граф связей app/business/ad account/campaign/adset/ad/creative/insight
- `POST /api/v1/marketing/patterns` - детерминированный поиск закономерностей в raw insights
- `POST /api/v1/marketing/analyze` - KPI + структурированный AI отчет

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
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

Через Docker:

```bash
docker compose up --build
```

Swagger UI доступен локально на `http://localhost:8000/docs`, ReDoc на `http://localhost:8000/redoc`, OpenAPI schema на `http://localhost:8000/openapi.json`. В `APP_ENV=production` документация отключается.

## Env configuration

Секреты читаются только из окружения. Локальный `.env` уже добавлен в `.gitignore`; для прода используйте `.env.example` как шаблон.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `APP_ENV` | yes | `local` | `local`, `development`, `staging` или `production` |
| `APP_NAME` | no | `manaai-api` | Название сервиса |
| `APP_VERSION` | no | `0.1.0` | Версия сервиса |
| `OPENAI_API_KEY` | yes | - | API key OpenAI |
| `OPENAI_MODEL` | no | `gpt-5.4-nano` | Модель OpenAI |
| `OPENAI_TIMEOUT_SECONDS` | no | `30` | Timeout запросов к OpenAI |
| `OPENAI_MAX_OUTPUT_TOKENS` | no | `512` | Максимум output tokens |
| `OPENAI_TEMPERATURE` | no | `0.2` | Температура генерации |
| `CORS_ORIGINS` | no | `[]` | JSON список разрешенных origins |
| `MARKETING_DATABASE_PATH` | no | `data/manaai.db` | SQLite path для raw records и reports |
| `MARKETING_CONVERSION_ACTION_TYPES` | no | JSON list | Meta `actions.action_type`, которые считаются conversions |
| `MARKETING_VALUE_ACTION_TYPES` | no | JSON list | Meta `action_values.action_type`, которые считаются revenue/value |
| `META_GRAPH_BASE_URL` | no | `https://graph.facebook.com` | Graph API base URL |
| `META_GRAPH_API_VERSION` | no | `v25.0` | Версия Graph/Marketing API |
| `META_APP_ID` | yes for Meta sync | - | Meta app id из Meta for Developers |
| `META_BUSINESS_ID` | no | - | Business id для owned/client ad accounts |
| `META_ACCESS_TOKEN` | yes for Meta sync | - | System user access token |
| `META_AD_ACCOUNT_IDS` | no | `[]` | JSON list ad account ids, например `["act_123"]` |
| `META_*_FIELDS` | no | JSON lists | Явные fields для campaigns/adsets/ads/ad accounts/insights |
| `META_ACTION_ATTRIBUTION_WINDOWS` | no | `["1d_click","7d_click"]` | Attribution windows для insights |

## Meta Marketing workflow

Для production sync используйте system user access token из Meta Business Manager. Это официальный серверный путь для автоматических API calls к assets бизнеса.

Минимальный `.env` для Meta:

```env
META_GRAPH_API_VERSION=v25.0
META_APP_ID=replace_with_meta_app_id
META_BUSINESS_ID=replace_with_business_id
META_ACCESS_TOKEN=replace_with_system_user_access_token
META_AD_ACCOUNT_IDS=["act_123456789"]
MARKETING_DATABASE_PATH=/data/manaai.db
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

Для больших отчетов используйте async Insights job, как рекомендует Meta:

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

Patterns endpoint ищет spend concentration, spend without conversions, efficiency opportunities, CPC/CTR outliers, простые тренды и data quality gaps. Это deterministic слой до AI, чтобы закономерности были проверяемыми.

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

Graph endpoint строит nodes/edges из raw records: business owns ad account, account contains campaigns/adsets/ads, ads point to creatives, insight rows measure account/campaign/adset/ad objects.

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

Ответ содержит `kpi_summary`, список KPI rows, deterministic `patterns`, `graph`, `source_record_ids` для аудита и typed `report`: summary, health score, findings, prioritized actions, data quality notes, raw-data followups.

## Прод-распаковка на сервере

Ниже вариант для обычного Linux VPS с Docker. Команды выполняются на сервере.

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

Минимально проверьте:

```env
APP_ENV=production
OPENAI_API_KEY=replace_with_real_secret
OPENAI_MODEL=gpt-5.4-nano
CORS_ORIGINS=["https://your-frontend-domain.com"]
MARKETING_DATABASE_PATH=/data/manaai.db
META_GRAPH_API_VERSION=v25.0
META_APP_ID=replace_with_meta_app_id
META_BUSINESS_ID=replace_with_business_id
META_ACCESS_TOKEN=replace_with_system_user_access_token
```

4. Соберите и запустите контейнер:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

5. Проверьте health endpoint:

```bash
curl http://127.0.0.1:8000/api/v1/health/live
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

## Nginx reverse proxy пример

```nginx
server {
    listen 80;
    server_name api.example.com;

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
pip install -e ".[dev]"
ruff check .
mypy .
pytest
```

## Security notes

- Не коммитьте `.env` и реальные API keys.
- В проде храните секреты в secret manager, CI/CD variables или server-only `.env`.
- После передачи ключа в чат лучше перевыпустить OpenAI key в dashboard и заменить значение на сервере.
- Meta access token храните только server-side; не отдавайте его frontend-клиентам и не пишите в логи.
- Docs UI отключается при `APP_ENV=production`.
