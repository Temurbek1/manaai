# Retention: production-проверка 28–29 сентября 2026

## Итог приёмки

29 сентября около `14:23 UTC` критерии восстановления Retention подтверждены: bounded canary
и пять последовательных штатных occurrence завершены успешно, четырёх шестичасовых интервалов
достаточно для требуемого контрольного цикла. Зацикливания, повторных occurrence и чтений между
слотами в сохранённых логах нет. Production здоров; перезапусков контейнеров не было.
Приложение остаётся на code SHA `4253e82`; последующие коммиты меняют только отчётные MD-файлы.

Приёмка относится к согласованному малому бюджету — пять документов на run. Расширение выборки,
подключение новых источников и сверка исторического Billing не входят в закрываемую цель.

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
Ruff/ESLint/Prettier, mypy/TypeScript, production build. На 28 сентября npm audit был чист.
Ранее на том же коде прошли отдельные `make lint`, `make typecheck`, `make test`, `ruff check .`,
`mypy .`, `pytest`, проверки схемы и изолированный PostgreSQL concurrency/migration audit.
Обычный backend-прогон пропускает PostgreSQL opt-in и исключает два live-теста.

Финальный `make verify` 29 сентября также завершился с кодом `0`: 275 backend-тестов,
24 frontend-теста и все остальные gates прошли. Обновлённая база npm advisories обнаружила одну
moderate-уязвимость `GHSA-3wwx-pv8p-q78v` в `undici@7.29.0`, установленном как dev-зависимость
через `jsdom`/Jest. Порог обязательного gate — high, поэтому gate проходит. Отдельный
`npm audit --omit=dev --audit-level=high` сообщил `0 vulnerabilities`. Обновление этой тестовой
зависимости — отдельная maintenance-задача; пакетный состав работающего релиза не менялся.

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

Отдельный монитор работал 28 сентября с `12:35 UTC` до `12:51 UTC`, проверяя только внутренние
health/run/schedule endpoints, без новых внешних чтений. По просьбе пользователя он остановлен;
production, worker и расписание продолжили работу. Непрерывное интерактивное наблюдение агента
после этого не заявляется: завершение полного цикла подтверждено read-only проверками сохранённых
run/audit/provider logs 29 сентября, включая финальную проверку около `14:23 UTC`.

### Подтверждённые штатные occurrence

| Слот UTC | Run ID | Статус | Firestore HTTP / документов | Manakids HTTP |
| --- | --- | --- | ---: | ---: |
| 28 сентября 12:20 | `1ab70489-0b19-4a36-9073-2e6a0c6caa61` | completed | 5 / 5 | 6 |
| 28 сентября 18:20 | `ad86c08b-341c-4e81-a56c-6676c33438ce` | completed | 5 / 5 | 11 |
| 29 сентября 00:20 | `69c2a001-8afd-4f7f-957d-894837e6b31d` | completed | 5 / 5 | 11 |
| 29 сентября 06:20 | `62911b50-fed8-47b7-bf00-44b0d6559a41` | completed | 5 / 5 | 11 |
| 29 сентября 12:20 | `56594008-f0c4-457f-8529-3be344467cef` | completed | 5 / 5 | 11 |

На каждой occurrence в audit ровно один `claimed` и один `success`; `next_run_at` передвигался
на следующий слот. В БД с момента релиза ровно шесть Retention runs, все `completed`: canary
и эти пять occurrence. Старый аварийный run остался `failed`, `retry_count=10619` не увеличился.
Последний run завершён `29 сентября 12:20:22 UTC`; следующий слот — `29 сентября 18:20 UTC`
(23:20 по Самарканду). `consecutive_permanent_failures=0`, `circuit_open=false`.

На четырёх последующих слотах пять параллельных Manakids GET получали `403` с сохранённым токеном.
Каждый раз выполнялся один общий login, затем каждый GET повторялся один раз и получал `200`.
Это не повторный запуск анализа: Firestore во всех случаях оставался на пяти запросах без retry.
Manakids login endpoint отвечал `200`, повторного отказа после переавторизации не было.

Итог за canary плюс пять штатных occurrence до финальной проверки:

- Firestore: **30 HTTP-попыток, 30 страниц, 30 полученных и зарезервированных документов**;
  все ответы `200`, retry отсутствуют.
- Manakids: **56 HTTP-попыток**, из них 36 ответов `200` и 20 первоначальных `403`;
  всего шесть login, четыре волны ограниченной переавторизации.
- Суммарно 86 source HTTP-попыток; это не сумма начислений Google Billing.
- Все четыре контейнера `healthy`, restart count `0`; API readiness и UI health — `200`.
- SHA-256 backend-файлов повторно совпали с deployed checkout `4253e82`; рабочий checkout чист.

Проверочный монитор не возобновлялся. Встроенный circuit breaker продолжает отключать Retention
после трёх последовательных permanent failures; для повторного включения требуется явное действие
администратора.

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
Остановленный монитор оставил `six-hour-control-4253e82.jsonl`; последний успешный poll —
`12:50:56 UTC`. Это неполное наблюдение, не доказательство прохождения шестичасового интервала.
Финальная проверка сохранена в `closure-worker-provider-20260929.json` и
`closure-scheduler-audit-20260929.json`: все пять штатных source runs и десять scheduler events.
Именно история run/audit/provider requests, а не остановленный монитор, подтверждает полный цикл.
Локальные копии завершённых проверок: `output/retention-release-20260928/`; в Git они не добавлены.

## Аудит требований цели

| Требование | Подтверждение выполнения |
| --- | --- |
| 401/403, один refresh, повторный отказ permanent | single-flight/same-token/repeated-failure regressions и четыре live-волны `403 → один login → 200` |
| Отмена параллельного сбора | nested cancellation/draining и in-flight HTTP regression-тесты; `gather_or_cancel` во всех source batches |
| Слот после success/failure | scheduler permanent/transient regression-тесты и фактический перенос `12:20 → 18:20 UTC` |
| Circuit breaker, audit, alert | persisted restart/stale-config regression-тесты, блокировка ручного запуска, UI-тест ScheduleEditor |
| Occurrence/idempotency/locks | два scheduler, stale due snapshot, SQLite/PostgreSQL contention; production duplicate key без новых HTTP-вызовов |
| Общий бюджет чтений | document/page/request/retry/shared-source regression-тесты и 5/5/5 в каждом из шести live runs |
| Privacy-safe telemetry | auth retry/redaction regression-тесты; сохранённые provider/budget/scheduler logs |
| Регрессионный набор | 275 backend-тестов плюс isolated PostgreSQL; 24 frontend-теста |
| Quality gates | все команды цели прошли; финальный `make verify` 29 сентября exit 0; отдельное moderate dev-advisory раскрыто выше |
| Commit/push | code SHA `4253e82`, опубликованная release-ветка |
| Точный deployment и сохранность | revision labels + SHA-256 файлов, сохранённые volumes/backups, unchanged nginx, read-only secret |
| Canary до включения | successful canary `12:09 UTC`, enable `12:10 UTC`, ограниченные фактические счётчики |
| Шестичасовой цикл | пять последовательных успешных occurrence за 24 часа, четыре полных шестичасовых интервала; без дублей и межслотовых provider requests |
