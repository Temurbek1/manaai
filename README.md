# ManaAI API

Production-ready базовый backend на FastAPI для будущего API слоя ИИ-интеграций. В проекте уже есть Docker, типизированные Pydantic-схемы, health endpoints и тестовые OpenAI endpoints через Responses API.

## Что внутри

- FastAPI application factory: `app.main:create_app`
- Версионированный API prefix: `/api/v1`
- OpenAI интеграция через `AsyncOpenAI`
- Дефолтная модель: `gpt-5.4-nano`, самая дешевая GPT-5.4-class модель по цене токенов
- Конфигурация через env и `.env`
- Dockerfile + `docker-compose.yml`
- Базовые async tests
- Строгое разделение слоев: routes, schemas, services, core config

## API endpoints

- `GET /api/v1/health/live` - liveness probe
- `GET /api/v1/health/ready` - readiness probe
- `POST /api/v1/ai/chat` - тестовый чат-запрос к OpenAI
- `POST /api/v1/ai/summarize` - тестовая суммаризация текста

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

OpenAPI UI доступен локально на `http://localhost:8000/docs`. В `APP_ENV=production` docs отключаются.

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
- Docs UI отключается при `APP_ENV=production`.
