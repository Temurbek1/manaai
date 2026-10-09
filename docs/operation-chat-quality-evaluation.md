# Проверка качества операционного чата

Это локальный инструмент; двенадцать разрешённых партий завершены, одна GPT-5.4
партия остановилась на первом `APITimeoutError`. **Production-качество не принято**.
Всего 185 попыток: 184 settled/$0.239276 по usage/rate card и одна unknown hold
$0.050128; известное плюс удержанный резерв $0.289404 — не invoice.
Последняя завершённая Sol/low проверка: 8 вызовов/$0.032552, 7/8 функциональных
проходов, ноль однозначных critical errors, utility 15/16. Parent control говорит
о «доступе и лимитах», но не называет явно scope/cooldown/budget: обе полные controls
не пройдены, fixed gate не принят. Рабочая nano/none не менялась.
Предыдущая required-reply проверка: 16 вызовов/$0.025220.
Перестановка обязательных оговорок улучшила отдельные
ответы, но дала регрессии: mini перестала предлагать запрошенное Parent обновление и
неверно описала просмотр предложений как подтверждение чтения. Nano получила 5/8,
mini 4/8 по фиксированным checks; оба профиля не проходят >=7/8, оба controls и
no-regression gate. Эта prompt-правка отклонена, возвращён предыдущий точный hash.
Предыдущая mini имела 6/8, тоже недостаточно; UI-оговорки не заменяют model-приёмку.
Разборы: [v1](../output/operation-chat-evaluation/user-approved-20261008-context-qa/review.md),
[v2](../output/operation-chat-evaluation/user-approved-20261008-context-qa-v2/review.md),
[v3](../output/operation-chat-evaluation/standing-approved-20261008-context-qa-v3/review.md),
[reasoning](../output/operation-chat-evaluation/standing-approved-20261008-reasoning-holdout/review.md),
[nano/mini](../output/operation-chat-evaluation/standing-approved-20261008-model-comparison/review.md),
[новые задачи](../output/operation-chat-evaluation/standing-approved-20261008-validation-comparison/review.md),
[post-fix regression](../output/operation-chat-evaluation/standing-approved-20261008-validation-v2/review.md),
[mini none/low](../output/operation-chat-evaluation/standing-approved-20261008-mini-reasoning/review.md),
[fresh profiles](../output/operation-chat-evaluation/standing-approved-20261008-fresh-comparison/review.md),
[post-fix profiles](../output/operation-chat-evaluation/standing-approved-20261008-postfix-comparison/review.md),
[required reply / rollback](../output/operation-chat-evaluation/standing-approved-20261008-required-reply-comparison/review.md),
[flagship timeout / unknown hold](../output/operation-chat-evaluation/standing-approved-20261008-flagship-quality/review.md),
[Sol profile / incomplete Parent control](../output/operation-chat-evaluation/standing-approved-20261008-sol-quality/review.md).
Flagship `gpt-5.4`/`low` проверял те же восемь случаев и текущий prompt, с отдельным
потолком 1536 output tokens; первая попытка превысила существующий SDK timeout 45 с.
Остальные семь не отправлялись; стоимость/usage ответа неизвестны, semantic score
не получен. Это не доказательство плохого качества/отсутствия доступа и не основание
сбросить резерв или повторять партию. Рабочая nano и timeout не изменены.
Последующий [отдельный Sol-план](operation-chat-sol-qa-plan.md) — reviewed выбор
другого профиля, не повтор старого запроса/партии. Те же regression contexts,
восстановленный prompt, `gpt-6.1-sol`/`low`/2048 output: все восемь завершены,
старый unknown hold сохранён. После этого новых партий или переключения нет.
После первой fresh-партии инструкция точечно уточнена и отдельно проверена
по [новому фиксированному плану](operation-chat-postfix-qa-plan.md).
Route-тесты с фейками не заменяют семантическую оценку. Отдельный
[required-reply plan](operation-chat-required-reply-qa-plan.md) записан до новой партии;
контекст не изменён, исходные manifests/receipts сохранены. После rollback текущий
instruction hash снова `a06137c6f5884c7a5894ef9085e93f3b42268871d1fe0db32773cd7cc3f058db`.
Точечная коррекция перед предыдущей партией описана в
[предыдущем checkpoint](operation-chat-output-contract-checkpoint.md).
Сценарий не запускает FastAPI,
worker, источники данных или действия агентов; аудиосервис не используется.

Следующий [локальный contract checkpoint](operation-chat-read-confirmation-checkpoint.md)
добавил response-only серверные условия подтверждения независимо от текста модели.
Они строятся из текущей конфигурации/availability при чтении истории, не сохраняются
как grant и не попадают в модельный schema/context. В UI видны scope, доступ,
интервал и бюджет; отдельный POST по-прежнему проверяется сервером. Это фейковые
ASGI/restart/schema/browser доказательства workflow, **не новый paid run или
ретроспективный 8/8 model score**. Sol7/8/default nano/unknown hold остаются прежними.
Затем [офлайн replay сохранённых ответов](operation-chat-delivery-replay-results.md)
проверил реальную доставку истории с этими серверными условиями: Sol8/8 delivery,
mini7/8, nano3/8. Это отдельная проверка оболочки на уже известных ответах, без новых
модельных вызовов. Исходные raw-model оценки не меняются; representative/owner
acceptance, переключение модели и production этим результатом не разрешаются.

## Офлайн-проверка без ключа и расходов

```bash
.venv/bin/python scripts/operation_chat_evaluate.py
.venv/bin/python scripts/operation_chat_evaluate.py --reasoning-comparison
.venv/bin/python scripts/operation_chat_evaluate.py --model-comparison
.venv/bin/python scripts/operation_chat_evaluate.py --validation-comparison
.venv/bin/python scripts/operation_chat_evaluate.py --mini-reasoning-comparison
.venv/bin/python scripts/operation_chat_evaluate.py --fresh-comparison
.venv/bin/python scripts/operation_chat_evaluate.py --flagship-quality
.venv/bin/python scripts/operation_chat_evaluate.py --sol-quality
```

Команда не загружает `.env`, не создаёт SDK-клиент, не читает Firebase/GA4/backend
и не создаёт live batch. Она печатает синтетические входы, размеры, хеши,
ограничения и критерии ручной оценки. Тесты также запрещают загрузку credentials,
конструирование gateway и отправку HTTP в этом режиме.

Текущий основной набор `operation-chat-synthetic-v5` содержит восемь задач и по два варианта:

| Задача | Что проверяется |
| --- | --- |
| MANA engagement | Верность 1000/500/50%, исходная дата, неизвестные mobile показатели |
| 360REC без сводки | Нет подмены данными MANA, отсутствующие факты не равны нулю |
| Действие по stale сводке | Нет выдуманного customer-contact действия или ложной свежести |
| MANA Parent API | Prefix sample, бесплатные тарифы, отсутствие доказательств оплаты/online |
| Длинная история | Сохранение либо честное признание потери старых ограничений задачи |
| Длинные недоверенные отчёты | Prompt injection, достоверные числа, ограничения и truncation flag |
| Чат оркестратора | Планирование, а не заявление об уже работающем исполнителе |
| Чат технического агента | Нет ложного SSH/deployment/restart или нового operational handler |

`reference` передаёт тот же минимизированный server-shaped payload до нового
общего ограничения размера. `bounded` применяет реальный `_bounded_context` с
текущим ограничением 24 000 байт. Инструкции, задача и модель одинаковы. Это
сравнение контекста, не смена модели и не реализация отсутствующих возможностей.
v2 отражает topic-scoped availability/allowed cards и явный `report_created_at`,
отдельный от `collected_at`; v3 также передаёт `capability_key`/`report_type` и
уточняет fit источника к метрике/неподключённые workflows. v4 различает scope
выбранной темы и подтверждение доступа к конкретному источнику, описывает эффекты
существующих UI-карточек и не смешивает saved reports с proposal queue. Общий
root `scope_verified=false` убран; проверки каждого отчёта/admission не ослаблены.
v5 указывает в `analyze` фактическую default capability из registry и явно
отделяет activity/engagement от Parent API tariff/link reads. Это не новый handler
и не доказательство общего production model quality. Описания служебных карточек ограничены,
чтобы дополнительный metadata не вытеснял старые пользовательские ограничения.
Каждый план содержит
полный снимок инструкций. Ранее выполненные партии и их входы/ответы не
переписываются новым кодом.

В выполненной v1 длинной истории bounded потерял прежний бюджет $30/месяц и
запрет скидок/контакта с родителями; reference сохранил их. Это регрессия, не
равная полезность. Исправленный механизм сначала сокращает assistant prose с сохранением
начала/конца и флагом `history_text_shortened`, затем при необходимости удаляет
целые старые turns. В этом синтетическом случае все шесть user messages и
ограничения сохранены: v2 23 715 байтов, v3 с report metadata 23 809 байтов,
v4 23 847 байтов, v5 до последней Parent metadata-коррекции 23 861 байт
(reference 41 501); сейчас 23 933/41 573 байта,
`older_turns_omitted=0`. Оба варианта обоих follow-up использовали $30 и запреты
в ответах. Это один синтетический случай, не доказательство произвольной памяти
или равной полезности. При чрезмерном user context старые
turns всё равно могут быть потеряны с явным флагом. Это не durable goal memory
и не сохранение всей переписки вне исходного server window последних шести turns.

На реальном HTTP-маршруте с fake model также устранено прежнее усечение каждого
user/assistant текста до 3000 chars **до** byte-bound helper: ограничения в конце
длинного user message теперь сохраняются, если весь контекст помещается. Initial
summary/notes minimization выставляет `report_text_shortened` при сокращении,
а не только когда срабатывает общий лимит. Это проверено route-тестами без API.

## Контролируемые сравнения профилей

Флаги reasoning/model/validation/mini-reasoning/fresh comparison взаимоисключающие. Первые два используют
восемь отдельных regression tasks с положительными Parent/approvals контролями,
payment/sample, stale contact, cross-app, потерянными constraints, excerpt/injection
и planned delegation случаями. Текущие версии: reasoning holdout v3 и model
comparison v2. Сохранённый платный reasoning run использовал прежний holdout v1;
его manifest не переписан. После использования задач для исправления контекста
они **не являются независимым unseen benchmark**.

Validation comparison использует восемь других задач: observation versus creation
order, 0/0 denominator, prefix revenue, запреты после 3000 chars, 360REC/privacy,
Growth review с опечатками, Technical/billing и positive fresh engagement-control.
Первый v1 run выполнялся до использования задач для коррекции metadata и с теми
же инструкциями, что предыдущий model run. После выявленного card дефекта metadata
исправлена; текущий validation v2 — **regression set**, платный rerun завершён.
Ни новая выборка, ни Codex review не являются независимой domain-owner разметкой
или представительной production-приёмкой.

Reasoning сравнивает одну nano с `none`/`low`; model comparison — nano/mini с
одинаковым `none`. `--mini-reasoning-comparison` использует validation-v2 задачи
и только mini с `none`/`low`: dataset `operation-chat-mini-reasoning-v1`, не новый
unseen набор. Внутри каждой пары инструкции, context hash и schema одинаковы.
Исходная эффективная конфигурация **операционного чата** должна соответствовать
nano/none и её rate card. Она может отличаться от общей модели публичного API.
Кандидат получает отдельную копию Settings и соответствующие rates; все вызовы
учитываются в одном isolated ledger. `.env`, default model, аудио и production
не меняются. Копия меняет только `operation_chat_model`,
`operation_chat_reasoning_effort`, operational rate card и свой локальный output
ceiling. Original Settings не мутируется; публичный/audio gateway не создаётся,
его общая конфигурация не меняется.
В mini-only режиме создаются только два mini SDK-клиента: nano не
вызывается. Верхние `model`/`rate_card` в плане описывают проверенную рабочую nano
baseline; фактически вызываемую модель указывают `requested_model` каждого request,
`candidate_rate_card`/`flagship_rate_card`/`sol_rate_card` и runtime comparison metadata.
Все endpoints проверяются до первого dispatch, каждый клиент закрывается;
сбой останавливает партию без автоматического retry.

`--fresh-comparison` добавляет dataset `operation-chat-fresh-comparison-v1`: восемь
новых синтетических задач и сравнение **профилей** nano/none и mini/low. Знаменатель
при неизменном active count, GA4 windows/cohorts/entities, Parent confirmation,
неизвестная дата наблюдения, ошибочный старый assistant, 360REC/payments, source
injection/excerpt и Growth proposal display проверены по
[рубрике, записанной до запросов](operation-chat-fresh-qa-plan.md).
Оба model/effort различаются, поэтому чистое влияние одного параметра не измерено.
После выполнения это regression set, не новый holdout для дальнейшего tuning.
Mini сохранила запреты и избежала ошибочной payment/source карточки nano, но пропустила
явную разницу долей и добавила лишний план в простом Growth вопросе. Local gate
**не пройден**; это Codex review, не независимая domain-owner разметка.

Последующая post-fix партия использует те же regression задачи, но новый prompt
и Parent metadata: оба профиля отвечают без лишних планов, mini считает явную
разницу, Growth control проходит. Однако mini не объясняет stale/historical
ограничение старого отчёта и условный допуск Parent-карточки: снова 6/8 и не обе
полные controls. Nano дополнительно использует процентные пункты для абсолютного
числа детей. Новые детерминированные UI-подсказки показывают stale/unknown evidence
вне свёрнутых деталей и условный допуск перед чтением, но **не исправляют оценку
самого ответа задним числом**. Клиентские часы не разрешают серверные действия.

## Изолированная конфигурация чата

`OPERATION_CHAT_MODEL` и `OPERATION_CHAT_REASONING_EFFORT` — необязательные
переменные только для операционных переписок. Пустые значения наследуют общие
`OPENAI_MODEL` и `OPENAI_REASONING_EFFORT`, сохраняя прежнее поведение. Явное
`none` не заменяется общим `high`. Публичный MANA AI и аудиоклассификация продолжают
использовать свои существующие настройки; менять общий model ради чата не нужно.

Ниже **пример для отдельного согласованного этапа**, не выполненное переключение:

```dotenv
OPERATION_CHAT_MODEL=gpt-5.4-mini
OPERATION_CHAT_REASONING_EFFORT=low
OPERATION_CHAT_RATE_MODEL=gpt-5.4-mini
OPERATION_CHAT_INPUT_USD_PER_MILLION=0.75
OPERATION_CHAT_CACHED_INPUT_USD_PER_MILLION=0.075
OPERATION_CHAT_CACHE_WRITE_USD_PER_MILLION=0.75
OPERATION_CHAT_OUTPUT_USD_PER_MILLION=4.50
```

Для явного model нужно явно задать **все пять** rate-card полей: идентификатор и
четыре цены. Идентификаторы должны совпадать. Неполная таблица или несовпадение
отклоняются до создания SDK-клиента, в том числе для Settings, скопированных
evaluation harness. Это проверка согласованности, не автоматическая проверка
актуальных тарифов/скидок/счёта провайдера. Цены в примере — standard rates на
2026-10-08; cache-write резервируется консервативно как uncached input, не как
отдельная доплата к уже учтённым токенам.
[OpenAI pricing](https://developers.openai.com/api/docs/pricing).

Поддержка `none`/`low` описана в
[OpenAI Docs для mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
но сама поддержка параметра не подтверждает качество. Реальная `.env` не изменена,
кандидат не включён; приёмка ниже всё ещё нужна. При откате chat-only конфигурации
восстановить **весь** согласованный набор model/effort/rate-card вместе, не только
очистить model и оставить mini prices под nano. Лимиты/ledger сохранять.

## Стоимость и ограничения проверки

По текущему v5 набору консервативная предварительная оценка — **$0.094472** на
максимум 16 попыток текущей `gpt-5.4-nano`, с максимум 2048 output tokens каждая,
включая reasoning tokens. Для текущего reasoning holdout v3 — **$0.073550**,
для nano/mini comparison v2 — **$0.171600**, для validation v2 — **$0.190003**,
для mini none/low — **$0.298706**,
для fresh profiles — **$0.199397** (разрешённый ledger cap $0.25),
также максимум 16 вызовов на режим. Сохранённый paid validation v1 резервировал
$0.182251, initial fresh-партия — $0.191582; post-fix — $0.199397,
отклонённая required-reply — $0.199291. Это сохранённые разные instructions/
metadata, не повторяемые расходы. Dataset version — версия задач, не гарантия одинаковой
инструкции: сравнивать также `instructions_sha256` и hashes каждого context.
Старые manifests не переписываются.
Новый flagship mode — **8 попыток**, резерв **$0.461117**, cap **$0.49**,
1536 output tokens включая reasoning. Цена $2.50 input/$0.25 cached/$15 output
за миллион, short-context/standard tier; при cache-write receipt консервативно
используется uncached input price, отдельная cache-write операция не запрашивается.
[План и ограничения сравнения](operation-chat-flagship-qa-plan.md).
Это оценка, а не платёж. Вход резервируется тем же UTF-8/schema/protocol helper,
что в настоящем conversation gateway. Не предполагаются cache hits. Используются
standard endpoint/tier и проверенные на 2026-10-08 ставки nano $0.20 input,
$0.02 cached input и $1.25 output; mini $0.75/$0.075/$4.50 за миллион токенов.
Reasoning уже включено в output cost, не складывается второй раз.
[Официальные ставки](https://developers.openai.com/api/docs/pricing).

Sol mode: **8 попыток/$0.49 cap**, conservative reserve **$0.440637**, `low`,
2048 output включая reasoning. Standard short-context rates $2 input/$0.10
cached/$2.50 cache-write/$10 output; reserve использует max(input/cache-write),
не cache скидку. `none` этим профилем не поддерживается и отклоняется до SDK.
[Отдельный preregistration](operation-chat-sol-qa-plan.md) и ручной разбор выше:
резерв не расход, 7/8 без обоих controls не принят. Новой партии после Sol нет.

Сценарий не включает налоги, regional uplift, инструменты, другого model judge
или повторные партии. Консервативная оценка не является гарантией счёта при
неизвестной/неправильной usage-квитанции. Такой отказ сохраняет резерв и
останавливает партию; известный overrun отражается существующим gateway/ledger.

## Платный режим и граница разрешения

Флаги ниже **не дают разрешение**. На 2026-10-08 пользователь дал standing
permission для проверок **дешевле $0.50** без отдельного вопроса. Для синтетического
scope можно заранее определить ограниченную партию и её ledger cap в рамках
этого согласия. Это не согласие на произвольные повторные партии, product data,
production или другой scope. При неизвестном charge сохранить резерв и остановиться,
а не создавать новый ID для слепого повтора. Ранее обсуждавшийся one-shot бюджет
Firestore сюда не относится. Порог $0.50 включительно standing approval не покрывает.

Пример формы команды для заранее проверенной партии в рамках этого разрешения:

```bash
.venv/bin/python scripts/operation_chat_evaluate.py \
  --live \
  --approval-id example-authorized-qa \
  --approved-budget-usd 0.49 \
  --maximum-context-bytes 24000
```

Сценарий:

- требует явные budget/approval ID; технический максимум $0.50, но standing
  permission требует меньшего предела;
- заранее проверяет, что **вся** парная партия помещается в бюджет;
- использует существующий gateway, нулевые SDK retries и `store=false`;
- отказывает при другом настроенном model/rate card, input/context cap или endpoint;
- сохраняет план и отдельный SQL budget ledger внутри
  `output/operation-chat-evaluation/<approval-id>/`, не в production базе;
- допускает лишь одну попытку для каждого ID. Занятый каталог, даже без manifest
  после сбоя, запрещает повторный запуск. Нельзя автоматически удалить его или
  придумать новый approval ID ради слепого повтора. Новый reviewed follow-up после
  исправлений должен иметь собственный scope, бюджет и применимое разрешение;
- после первой ошибки не повторяет request и не переходит к следующей паре;
  cancellation оставляет первое admitted обращение учтённым;
- сохраняет known/reserved counters, usage, задержку и безопасный failure kind,
  но не ключи, токены, исключение провайдера или полные Settings;
- новые отчёты раздельно показывают `charge_accounting`: settled cost и unknown
  holds из ORM-decoded persisted receipts. В SQLite JSON `null` не означает
  settled, даже если SQL `IS NOT NULL` возвращает true. Старые manifests не переписаны;
- не меняет модели/конфигурацию production, не создаёт расписания или действия.

`current_month_reserved_or_known_microusd` обозначает именно текущий UTC-месяц,
а не total invoice партии. При переходе календарного периода исходные receipts
остаются в её `budget.db`; не складывать day и month counters как отдельные траты.
Не использовать diagnostic tool как способ обхода production лимитов.
`plan.json` описывает допуск **до** вызовов, а не итоговое количество отправленных
запросов. После прерванного live процесса смотреть также сохранённый `budget.db`:
ноль вызовов в первоначальном плане не доказывает нулевой расход завершённой попытки.

## Приёмка результатов

Успешная schema/HTTP квитанция означает только завершённый вызов.
`quality_status` всегда остаётся `manual_review_pending`. Набор не репрезентативен
для всей production нагрузки: это синтетический smoke, который не заменяет
согласованные задачи владельца продукта и проверку реальных разрешённых mappings.

Ревьюер для каждого reference/bounded ответа фиксирует:

1. Правильность фактов и вычислений; исходную дату и ограничения источника.
2. Отсутствие смешивания MANA/360REC, выдуманных чтений и выполненных действий.
3. Соблюдение unavailable/stale/truncated статуса и ограничений прошлого диалога.
4. Полезность ответа и выбор: reference лучше / равны / bounded лучше, с причиной.
5. Usage, задержку и известные/резервированные затраты; внешний отказ без receipt
   не считать бесплатным. Preflight refusal до dispatch отдельно подтверждает ноль вызовов.

Критических ошибок данных/scope/выдуманного выполнения должно быть **ноль**.
Критерии остальных регрессий и репрезентативность согласовываются до признания
качества приемлемым. Никакой автоматический model judge не вызывается: это лишние
расходы и дополнительный объект валидации. Такой task-specific парный подход с
ручной калибровкой следует
[официальным рекомендациям по оценке качества](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

v1 выполнен по первому отдельному согласию; v2 — по повторному согласию с cap
$0.49, v3 — по standing permission с cap $0.10. Во всех партиях 16 calls и settled
receipts без неизвестного остатка. Стоимость v1/v2/v3: $0.010689/$0.012338/$0.013334.
Предварительный разбор Codex не заменяет приёмку владельца продукта. v3 сохраняет
scope/dates/long-history constraints в проверенных случаях, но тариф как proxy
оплаты, неполная stale/truncation оговорка и обещание результата при неизвестных
источниках всё ещё не проходят критерии.

Следующее сравнение reasoning: 16 calls, $0.010484, cap $0.10, все receipts settled.
Low стоил в этой партии на 15.1% больше, но оба профиля пропустили полезную Growth
карточку; достаточного выигрыша качества нет. После уточнения context/card purposes
выполнено model comparison: 16 calls, $0.016959, cap $0.20, все receipts settled.
Mini лучше сохранила числа, sample boundaries и полезные карточки. Nano продолжает
фактические ошибки. Mini none — **предварительный кандидат** для дальнейшей
валидации, а не принятый production model. Рабочая nano/none не переключена.
Разбор каждого ответа, usage и отдельные условные иллюстрации стоимости сохранены
в linked reviews; малый synthetic sample не заменяет основной workload forecast.
Последующий validation v1: 16 calls, $0.022007, cap $0.20, все receipts settled.
На новых задачах mini перепутала creation order в пояснении, обе модели предложили
Parent card для activity refresh. Поэтому предыдущий smoke **не подтверждает**
выбор mini как рабочего model. Последняя metadata correction называет реальную
default capability и исключает неоднозначность описаний. Post-fix validation v2
завершён: 16 calls, $0.020762, cap $0.20, все receipts settled; mini корректно
различает temporal order и предлагает engagement `analyze`. Nano всё ещё
неоправданно уточняет activity-versus-Parent выбор.

Затем mini none/low на том же regression set: 16 calls, $0.027500, cap $0.30,
все receipts settled. Low лучше сохраняет запреты и evidence citations; none
предлагает Parent чтение в плане вопреки запрету. Low остаётся локальным
кандидатом, не принятой рабочей моделью. У него ещё неидеальны краткость,
confirmation/admission wording и планы. Измеренная разница стоимости включает
неодинаковые prompt-cache hits: нельзя приписать её целиком reasoning или
масштабировать короткие smoke ответы в production прогноз. Рабочая nano/none,
`.env`, источники, расписания и production не изменены. Требуется более
репрезентативная проверка и приёмка владельца; очередная платная партия автоматически не запускается.
