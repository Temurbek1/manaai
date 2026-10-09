# Goals — рабочая среда для анализа

## Что работает

В чате оркестратора, роста или удержания выберите **Цель**, опишите задачу и ожидаемый
результат. Backend сохраняет цель в SQL и продолжает работу без открытой страницы:
план → исследование → отдельная проверка → результат или ожидание недостающих данных.
Можно поставить работу на паузу, продолжить, уточнить задачу или отменить её. План,
ограничения, уточнения, исходные сводки, промежуточный результат и журнал сохраняются.
История и источники свёрнуты; основной экран показывает только задачу, прогресс и результат.

Пример: «Проанализируй текущее положение пользователей: где отпадают, где платят,
что делают. Подготовь рекомендации для увеличения удержания. Не меняй данные».
Отсутствие платежей или единой когорты должно стать явным ограничением/ожиданием,
а не выдуманной конверсией. Готовый анализ не означает, что удержание действительно выросло.

Это общий инфраструктурный workspace существующих четырёх комнат, **не пятый агент**
и не заявление о готовности всего Operations Orchestrator. Реестр доменных агентов не
изменён; Technical Reliability и Retention customer-contact/action handlers не реализованы.
Goals технического агента пока не запускаются. В обычном чате прежние ограничения сохранены.

## Данные и разрешения

Уточнение владельца 09.10.2026: 360REC работает по входящим запросам и не имеет
данных в БД для этой аналитики; большая часть существующих данных относится к MANA.
Текущий план подключения Goals/операционной аналитики ориентирован на MANA.
Для 360REC нельзя запускать предполагаемый DB-сбор или подставлять MANA-сводки:
если нужных подтверждённых данных нет, цель честно остаётся в ожидании.
Это не изменение независимого 360REC API и не подтверждение всех GA4-потоков как MANA.

- По умолчанию читаются только локально сохранённые минимизированные отчёты с проверенной
  привязкой к выбранному приложению. MANA и 360REC не объединяются. Родители и дети —
  разные сущности; тариф не доказывает оплату. Raw audio, GPS, сообщения детей и списки
  контактов не передаются модели.
- Новое внешнее чтение — отдельный запрос и явная кнопка согласия. Сейчас доступно только
  `retention.engagement.analyze` для Retention/Orchestrator при подтверждённой live-привязке
  источников именно к приложению цели. Growth funnel остаётся fake, поэтому live-сбор не
  предлагается. Parent API не включён в автоматический Goals-сбор.
- Один read-only анализ на цель: разрешение расходуется в SQL **до** I/O, запуск имеет
  постоянный idempotency key. Используются существующие admission, source-wide cooldown,
  бюджеты, run locks и kill switches. 401/403/сбой не запускает обход заново.
- Создание цели не является разрешением на чтение или бизнес-действие. SDK не получает
  сеть, SQL, shell, provider payloads или интеграционные ключи как инструменты модели.
- Завершение требует отдельного review, непустого результата, выполненного плана и
  существующих свежих цитируемых источников без сокращения. Это защитная граница,
  не математическая гарантия качества любого LLM-вывода; арифметику/охват проверяет review.

## Сохранение, конкуренция и восстановление

Новые таблицы: `operation_goals`, `operation_goal_commands`; миграция `a19d38f610ac`.
Создание идемпотентно по owner/request_id; команды — по goal/request_id и expected_revision.
Только владелец видит и управляет целью. Выполнение/чтение требует operator; production
Telegram-user access перепроверяется перед каждым шагом (disabled/viewer останавливает работу).
Историю можно читать при отключённом AI. Максимум 20 незавершённых целей на владельца,
одна на тему; closed goals не расходуют лимит активных целей.

SQL claim сериализуется между API/worker-процессами; revision fence защищает результаты от
гонки с паузой/отменой. Очередь проверяется локально, без source/model requests при отсутствии
задач. При нормальном перезапуске queued цель продолжает сохранённую фазу. Если процесс
потерян во время I/O, lease через 5 минут переводит цель в ожидание: неизвестный расход
остаётся зарезервирован, **автоматического повтора нет**. Explicit resume допускает новый
ограниченный шаг, но не снимает прошлые расходы и не повторяет использованный source read.
При паузе в обработке ответ устаревшего worker не перезаписывает управление; уже отправленный
AI-запрос может быть оплачен. Goal-local hold может остаться консервативным, даже если общий
ledger уже получил usage: это не счёт провайдера и не основание автоматически возвращать деньги.

## Модель и расходы

Отдельный `OPERATION_GOALS_MODEL=gpt-6.1-sol`, reasoning `medium`; обычный чат,
публичный MANA AI и аудиофильтрация не меняют модель. Responses structured output,
`store=false`, standard tier, `max_retries=0`, timeout 120 s; приложение ограничивает шаг 180 s.
На задачу по умолчанию до 6 модельных шагов и $0.50 учтённых AI-расходов **включая неизвестные
резервы**. Ограничение вывода 4096 токенов, контекста 64000 байт. Byte-based admission
консервативен; большой контекст может остановиться раньше 6 шагов. Контекст не обрезает
незаметно критерии/ограничения; полный журнал хранится отдельно от повторяемого model input.
Модель/прайс можно менять только явной полной rate card; цены и tier проверяются в ответе.
Все Goals разделяют дневной/месячный atomic ledger с чатом и источниками.

Это дополнительная ручная нагрузка, **не входит автоматически** в прежний прогноз 53 вызовов.
При N целях в день консервативный дополнительный предел AI: N × $0.50/день,
N × $15/30 дней, N × $182.50/365 дней — до применения более строгого общего бюджета.
Это лимит, не прогноз фактического счёта; неизвестные usage учитываются резервом.
Saved reports не создают новых Firebase/GA4 расходов. Подтверждённый внешний анализ
расходует существующие data limits; в Goals нет нового расписания сбора каждые 6 часов.
Сервер/хранение/прочие сервисы не включены в эти суммы.

Официальная основа: [Agents ownership, continuation and approvals](https://developers.openai.com/cookbook/examples/agents_sdk/migrate-from-claude-agent-sdk/readme),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[standard pricing](https://developers.openai.com/api/docs/pricing). Runtime, state, approvals,
secrets и admission остаются в доверенном backend, а не в текстовых обещаниях модели.

## API

Base: `/api/v1/admin/operation/goals`; прежние Telegram session/CSRF и RBAC.

- `GET /availability`
- `GET /topics/{topic_id}` — последние 100 целей своей темы.
- `POST /topics/{topic_id}` — `GoalCreate`, 202 означает очередь, а не готовый отчёт.
- `GET /{goal_id}` — сохранённое состояние.
- `POST /{goal_id}/commands` — pause/resume/cancel/steer/approve_read.

Request поля objective, success_criteria, constraints, max_steps, budget_microusd;
read permission нельзя передать при создании. Defaults из `.env.example`; реальный `.env`
не редактировался. Worker стартует в lifespan независимо от старого operation scheduler;
можно выделить его в существующий worker process через `OPERATION_GOALS_WORKER_ENABLED`:
false на API, true на worker. Одинаковые replica-настройки и общий SQL обязательны.

## Проверка и выпуск

Стоимость многошаговых целей отдельно учитывает чистый offline calculator
`scripts/operation_cost_forecast.py --goals-per-day N`. По умолчанию N=0: старые
сценарии не меняют нагрузку молча. Параметры шагов, токенов, бюджета и Goals rate card
явные; источник настроек/ключи не загружаются. Все output tokens, включая reasoning,
считаются платными. Rate card обычного чата не подменяет Goals rate card.
При nominal cost выше admission budget результат расчёта не обрезается: он показывает,
что бюджет может остановить цель до завершения. Это не обещание качества/полного анализа
и не физический предел invoice при неизвестном charge или observed overrun.
См. [сценарии с Goals](cost-optimization-implementation.md#goals-capacity-checkpoint--2026-10-09).

Fake tests покрывают HTTP ownership/RBAC, idempotency, optimistic controls, persistent restart,
single-flight claims, unknown holds, global/per-goal limits, паузу в I/O, отсутствующие/stale
источники, fabricated citations, consent/scope и background completion. SDK в тестах подменён.
UI tests и browser audit проверяют create/progress/reload/steer/cancel, 320px и accessibility.
Полный gate: `make verify`; миграции — `make audit-migrations`, `make audit-postgres`.

Локальный checkpoint 09.10.2026:

- `make verify`: PASS — 643 backend tests, 6 PostgreSQL tests skipped here and run below,
  2 opt-in live tests excluded; 91 UI tests / 19 suites, mypy 259 files, lint/format,
  production Next.js build, npm audit 0 vulnerabilities.
- SQLite additive migration, clean upgrade/downgrade/upgrade, existing-copy upgrade and
  schema drift: PASS. Production DB не изменялась.
- Isolated PostgreSQL 17 audit: PASS — 6 tests, включая Goals create/claims/controls,
  version fencing и recovery; migration drift отсутствует. Временные тестовые контейнеры
  удалены после проверки, существующие сервисы не изменялись.
- Browser fake E2E: PASS — create → progress → reload → steering → freshness refusal →
  cancel, единый композер, ownership/auth, 320px overflow и axe WCAG A/AA.
- Secret scan: PASS (733 files); whitespace diff check: PASS.
- Артефакты и просмотренные desktop/mobile screenshots:
  `output/operation-goals-20261009/`. Новых production/source schedules нет.

Одна отдельно запущенная синтетическая проверка 09.10.2026 (локальное время):
GPT-6.1 Sol/medium прошёл plan → investigate → review за 3 calls. D1=60%, D7=35%,
предыдущий D7=30%, разница +5 п.п.; разные когорты не превращены в индивидуальный
эффект, дети/родители и тарифы/оплаты не смешаны, источники и ограничения обозначены.
Первичный план имел неудачное слово, в итоговом review оно исправлено.
Usage: 6896 input, 4768 output tokens; все 3 reservations settled,
подтверждённый usage-based расчёт **$0.064916**, cap $0.49, неизвестных holds в этой
проверке нет. Daily/monthly записи отражают одни расходы, их нельзя складывать.
Это одна ограниченная задача, не широкая приёмка качества и не invoice провайдера.
Артефакты: `output/operation-goals-20261009/synthetic-quality/`; новых партий не запускалось.

Production, Firebase, права, SSH и действующая аудиофильтрация в этом изменении не трогались.
Нужен отдельный согласованный выпуск: DB backup → additive migration → backend/worker → UI,
проверка на fake источниках и ограниченный real-model evaluation. При откате отключить Goals
worker, вернуть старый код/UI, **сохранить goal tables и cost reservations**; destructive
downgrade не выполнять на production. Реальная качество/стоимость зависят от задач и данных.
