# Retention: production-проверка 28 сентября 2026

## Развёрнутый релиз

- Сервер: `209.38.78.125`, Compose project: `mana-ai`.
- Код: `4253e828e9a5bacf0cacce31cad6ce520de7332e`, ветка
  `fix/retention-incident-20260928`, опубликованная в `Temurbek1/manaai`.
- Checkout: `/opt/manaai-releases/4253e82`, чистый worktree.
- Backend image: `mana-ai-backend:4253e82`, image ID
  `sha256:de3f157c87f939eaf4536e686dd74aba564a70bcb5fc9cbc0f4fc102d43efef7`.
- Admin image: `mana-ai-admin:4253e82`, image ID
  `sha256:9643f4390937dc8e12a094f55c3ccbd6893b805123075069bf362f9744da0c90`.
- Revision label API, worker и admin совпадает с SHA кода. SHA-256 backend-файлов внутри
  контейнера сверены с чистым checkout; `.env` в образе отсутствует.

Приложение было остановлено до релиза: контейнеров не было. Восстановлены API, admin и worker
с существующими PostgreSQL/data volumes, а не с новой пустой БД. Это восстановление остановленного
приложения, не zero-downtime обновление работавшего сервиса.

## Резервные копии и конфигурация

Перед запуском PostgreSQL сохранены и проверены архивы обоих остановленных томов. После
восстановления дополнительно сделан `pg_dump`, проверенный через `pg_restore --list`.
Каталог: `/var/backups/mana-ai/retention-release-20260928T120500Z`; доступ ограничен root.
Предыдущие образы сохранены с тегом `pre-retention-20260928`. Версия Alembic:
`c41d9e7a2f30`; новая миграция для полей circuit breaker не потребовалась.

Предоставленный service account JSON находится вне Git/образов, имеет права `0600` и смонтирован
read-only. Публичный fallback выключен. SSH-конфигурация, Firebase rules/IAM и документы Firebase
не менялись. Старые ключи не удалялись. Конфигурация nginx совпадает с резервной копией.

Активные Compose overrides находятся в `/etc/manaai/deploy/`:

- `retention-4253e82.yml`: immutable images, закрытый secret mount и малые бюджеты;
- `retention-worker-enabled.yml`: scheduler только в worker; в API он выключен;
- `retention-rollback.yml`: предыдущие образы, scheduler выключен, источники fake.

Для действующего релиза нужно использовать новый checkout и оба активных override-файла.
Нельзя запускать старый `/root/mana-ai/docker-compose.yml` как самостоятельный deployment:
он не содержит новых предохранителей и остаётся архивным runtime-каталогом.

## Проверки API и качества

Повторный `make verify` после развёртывания прошёл: 275 backend-тестов, 24 frontend-теста,
Ruff/ESLint/Prettier, mypy/TypeScript, production build, npm audit без уязвимостей.
Ранее на том же коде прошли отдельные `make lint`, `make typecheck`, `make test`, `ruff check .`,
`mypy .`, `pytest`, проверки схемы и изолированный PostgreSQL concurrency/migration audit.
Обычный backend-прогон пропускает PostgreSQL opt-in и исключает два live-теста.

Практически проверены localhost и `https://ai.360rec.uz`:

- liveness: `200`;
- admin session без ключа: `401`, с действующим ключом: `200`, роль admin;
- авторизованный `/api/v1/mana-ai/capabilities`: `200`;
- `/api/v1/audio-moderation/jobs` без token: `401`;
- тот же audio endpoint с token и пустым payload: `422`, без постановки аудио в очередь;
- readiness сообщает `audio_moderation=ready`;
- `https://ai-frontend.360rec.uz/healthz`: `200`.

Эти проверки не отправляли реальное аудио и не вызывали OpenAI. Они подтверждают доступность
и контракт аудиосервиса, но не являются повторным end-to-end тестом распознавания/классификации.
Ошибки 401/403, отмена sibling-задач, circuit breaker и отказ при превышении бюджета проверены
регрессионными тестами с fake/mock источниками, а не искусственными сбоями реальной базы.

## Ограниченный live-canary

Run ID: `0f9c5a4d-37fd-460c-a8d7-bc9122504c97`.
Начало: `2026-09-28 12:09:34 UTC`, завершение: `12:09:41 UTC`, статус `completed`.
Сохранён один агрегированный snapshot и семь audit-событий переходов стадий.

Фактические source HTTP-попытки:

| Источник / endpoint | Запросов |
| --- | ---: |
| Firestore `documents/battery` | 1 |
| Firestore `documents/children_location` | 1 |
| Firestore `documents/internet` | 1 |
| Firestore `documents/monitoring` | 1 |
| Firestore `documents/screen-commands` | 1 |
| Manakids `/api/v1/admin-panel-auth/login/` | 1 |
| Manakids `/api/v1/admin-panel-common/account/` | 2 |
| Manakids `/api/v1/admin-panel-child/child-list/` | 1 |
| Manakids `/api/v1/admin-panel-child/app-usage-statistics/` | 1 |
| Manakids `/api/v1/admin-panel-child/camera-audio-usage-logs/` | 1 |

Все 11 ответов — HTTP `200`. Firestore: 5 страниц, 5 полученных документов,
5 зарезервированных document reads, 0 retry, `stop_reason=success`.

Повтор HTTP-запуска с тем же idempotency key в `12:09:42 UTC` вернул тот же run.
До конца проверки в `12:09:45 UTC` ни одного нового provider request не появилось;
времена выполнения и `retry_count=0` не изменились.

Счётчики относятся к source HTTP-запросам адаптеров. Обмен OAuth-токена через Google SDK
в них не входит. Document counters не являются выпиской Billing и не измеряют все возможные
index/network/storage charges; денежная стоимость здесь не заявляется.

## Контроль расписания

После успешного canary в `12:10:24 UTC` включено расписание `20 */6 * * *`, timezone `UTC`.
Worker запущен отдельно; автоматического scheduler в API нет.

Первая штатная occurrence `12:20 UTC` выполнена один раз:

- run ID: `1ab70489-0b19-4a36-9073-2e6a0c6caa61`;
- выполнение: `12:20:07.417–12:20:15.673 UTC`, статус `completed`, `retry_count=0`;
- ключ: `schedule:retention-engagement-analysis:2026-09-28T12:20:00+00:00:attempt:1`;
- Firestore: ровно 5 HTTP-попыток, 5 страниц, 5 полученных/зарезервированных документов;
- Manakids: 6 HTTP-попыток по тем же endpoints, что в canary; все 11 ответов — `200`;
- `stop_reason=success`, `circuit_open=false`, `consecutive_permanent_failures=0`;
- сохранены snapshot, семь run audit-событий, scheduler claim и terminal audit;
- `next_run_at=2026-09-28T18:20:00Z`, обновление расписания применено;
- последующие проверки каждые 30 секунд до `12:23:45 UTC` не обнаружили повторного запуска.

Повторная проверка в `12:34 UTC` подтвердила те же счётчики, здоровые контейнеры и неизменность
старого аварийного run (`retry_count=10619`, новых попыток нет). Итого для canary и первой
штатной occurrence: 10 Firestore HTTP-запросов/полученных документов и 12 Manakids HTTP-запросов.

**Полный шестичасовой интервал пока не завершён.** С `12:35 UTC` работает отдельный монитор
до следующей штатной occurrence `18:20 UTC` и проверок после неё до `18:24 UTC`
(23:24 по Самарканду). Монитор читает только внутренние health/run/schedule endpoints;
дополнительные обращения к Firebase или Manakids он не инициирует. При failed/cancelled
контрольном run монитор отключает Retention schedule. Задача не считается окончательно
закрытой до проверки этого интервала и его source-счётчиков.

На первый контрольный цикл оставлены:

```text
FIREBASE_OPERATIONAL_MAX_DOCUMENTS_PER_COLLECTION=1
FIREBASE_MAX_DOCUMENT_READS_PER_RUN=5
FIREBASE_MAX_PAGES_PER_RUN=5
FIREBASE_MAX_REQUESTS_PER_RUN=5
FIREBASE_MAX_RETRIES=0
MANAKIDS_MAX_RETRIES=0
MANAKIDS_MAX_PAGES=1
OPERATION_SCHEDULER_MAX_ATTEMPTS=1
OPERATION_SCHEDULER_PERMANENT_FAILURE_THRESHOLD=3
FIREBASE_PUBLIC_READ_ENABLED=false
```

Это небольшая контрольная выборка, не полная аналитическая выгрузка. GA4 и canonical mobile events
в этом релизе не включались. Расширение выборки/бюджетов требует отдельного согласования.

При восстановлении общего worker также возобновились уже включённые задачи Growth. Их прежний
provider — live Meta read-only — не переключался; разрешения на Meta writes не включались.
Это отдельные штатные задачи, не часть Retention-canary или его Firestore-счётчиков.

## Сохранённые свидетельства

На сервере `/etc/manaai/deploy/` сохранены `smoke-4253e82.jsonl`, `canary-4253e82.jsonl`,
`canary-provider-evidence-4253e82.json`, `schedule-enabled-4253e82.jsonl`,
`control-cycle-4253e82.jsonl`, `control-provider-evidence-4253e82.json`.
Продолжающийся монитор пишет `six-hour-control-4253e82.jsonl`.
Локальные копии завершённых проверок: `output/retention-release-20260928/`; в Git они не добавлены.

## Аудит требований цели

| Требование | Подтверждение / оставшаяся проверка |
| --- | --- |
| 401/403, один refresh, повторный отказ permanent | `tests/test_retention_failure_safety.py`: single-flight, same-token, refresh failure, no network retry |
| Отмена параллельного сбора | nested cancellation/draining и in-flight HTTP regression-тесты; `gather_or_cancel` во всех source batches |
| Слот после success/failure | scheduler permanent/transient regression-тесты и фактический перенос `12:20 → 18:20 UTC` |
| Circuit breaker, audit, alert | persisted restart/stale-config regression-тесты, блокировка ручного запуска, UI-тест ScheduleEditor |
| Occurrence/idempotency/locks | два scheduler, stale due snapshot, SQLite/PostgreSQL contention; production duplicate key без новых HTTP-вызовов |
| Общий бюджет чтений | document/page/request/retry/shared-source regression-тесты и 5/5/5 в обоих live runs |
| Privacy-safe telemetry | auth retry/redaction regression-тесты; сохранённые provider/budget/scheduler logs |
| Регрессионный набор | 275 backend-тестов плюс isolated PostgreSQL; 24 frontend-теста |
| Quality gates | все команды цели прошли; `make verify` повторно выполнен после развёртывания |
| Commit/push | code SHA `4253e82`, опубликованная release-ветка |
| Точный deployment и сохранность | revision labels + SHA-256 файлов, сохранённые volumes/backups, unchanged nginx, read-only secret |
| Canary до включения | successful canary `12:09 UTC`, enable `12:10 UTC`, ограниченные фактические счётчики |
| Шестичасовой цикл | первая occurrence и polling проверены; наблюдение до `18:24 UTC` ещё выполняется |
