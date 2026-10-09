# Проверка цели оптимизации расходов

Уточнение владельца 09.10.2026: 360REC работает по запросам, данных в application DB
для этой работы нет; большая часть данных относится к MANA. Поэтому для текущего
подключения не требуется искать/подтверждать БД 360REC или строить её collector.
Это снимает именно этот внешний вопрос, но не подтверждает весь состав потоков
MANA или parent/child cohorts. Обновлены canonical model, Goals/data docs и
[лист подтверждения](source-ownership-confirmation.md). Runtime, `.env`, scheduler,
аудиофильтрация и production не изменялись. Прежние двухпродуктовые fake/capacity
сценарии остаются историческими проверками изоляции/допущениями, а не текущим
планом двух live-сборщиков; их результаты и QA receipts не переписаны.
Docs-only checkpoint: `make verify` повторно прошёл lint/typecheck, 655 backend/91 UI
tests и production build, но завершился exit 2 из-за ошибки внешнего npm audit
endpoint. Один отдельный ограниченный повтор `npm audit --audit-level=high
--fetch-retries=0 --fetch-timeout=15000` завершился exit 0, 0 vulnerabilities.
Это не переписывает exit исходной команды; её лог:
`output/cost-forecast-goals-20261009/mana-scope-clarification-verify.log`.
Whitespace и secret scan (740 files) прошли. Новых model/source вызовов нет.

Пересчёт MANA-only с `--products 1` после этого уточнения:
[новый checkpoint](cost-optimization-implementation.md#mana-only-planning-checkpoint--2026-10-09).
Будущая capacity с теми же data/chat/complex допущениями: $64.447884/30 дней без
Goals; $78.163884 с одним шестишаговым Goal/день; $105.595884 с тремя, все с 25%
резервом. Отдельная chat/Goal capacity без Firestore и scheduled/complex model work:
$44.076000/30 дней ($536.258000/365 дней). Это разные нагрузки, не same-load экономия
и не current invoice/активация модели. Первые scenarios сохраняют data-only
$2.197884 с резервом, выше $2. Четыре новые regression cases проверяют, что data,
чат и Goals не делятся пополам вместе с числом приложений; 28 forecast tests passed.
Старые двухпродуктовые JSON, модельные receipts и счётчики не переписаны.
Новый полный `make verify` **exit 0: 659 backend / 91 UI**, mypy259, build и npm audit0:
`output/mana-cost-scope-20261009/make-verify.log`. Это успешный новый gate, не исправление
счётчика exit у прежнего временного отказа npm endpoint. Secret scan746 и whitespace
прошли; runtime/persistence/UI не менялись, новых PG/browser/source проверок нет.

Обновление 09.10.2026: пользователь отдельно запросил Goals; это локальная общая
среда анализа, не пятый агент или реализация отсутствующих action capabilities.
Работа с целью теперь отдельно включается в проверяемый offline прогноз:
[Goals capacity checkpoint](cost-optimization-implementation.md#goals-capacity-checkpoint--2026-10-09).
Один шестишаговый Goal/день при указанных токенах добавляет $13.716/30 дней с
резервом к исходному сценарию; $85.447884 превращаются в $99.163884, выше $90.
Прогноз v2 показывает insufficient per-goal budgets без занижения цены и не меняет
runtime. Тестовый один Goal завершил три synthetic calls/$0.064916; общий known
диагностический итог $0.304192 плюс прежний unknown hold $0.050128, не invoice.
Он **не заменяет** фиксированную приёмку обычного чата или подтверждение владельцем
реальных source mappings. Источники и production не включены. Нижеследующие
исторические QA checkpoint/счётчики 08.10 сохраняются; новые доказательства не
переписывают старые результаты. Новый `make verify` **exit 0: 655 backend/91 UI**,
mypy259, full npm audit0; 24 offline forecast tests. Лог:
`output/cost-forecast-goals-20261009/make-verify.log`. Schema/migration/PG/browser
проверки ранее законченного Goals checkpoint указаны в `operation-goals.md`; они
не превращены в новый live/production аудит. Качество общей модели всё ещё не принято.

Дата: 2026-10-08. Это проверка локального кандидата, не отчёт о внедрении или
фактических расходах production. Источники данных не вызывались; двенадцать разрешённых
партий завершены: 184 settled OpenAI вызова/$0.239276 по usage/rate card.
Одна GPT-5.4 партия остановилась на первом таймауте: всего 185 попыток, одна unknown
hold $0.050128. Известное плюс удержанный резерв $0.289404 — не подтверждённый invoice.
Последняя завершённая Sol проверка стоит $0.032552: 7/8, zero unambiguous critical,
utility15/16, но Parent control не раскрывает scope/cooldown/budget. Fixed gate требует
обе полные controls и не принят; рабочая nano/none и prompt не менялись.
Предыдущая required-reply проверка стоит $0.025220;
production-качество **не принято**. После исправления metadata
[regression rerun](../output/operation-chat-evaluation/standing-approved-20261008-validation-v2/review.md)
показал правильную engagement-карточку и temporal order у mini. Последнее
[mini none/low сравнение](../output/operation-chat-evaluation/standing-approved-20261008-mini-reasoning/review.md)
выделило low как локального кандидата: none предлагает запрещённое Parent чтение
в плане. Это не репрезентативная приёмка; schema/HTTP успех не доказывает качество.
Новый [fresh profile set](../output/operation-chat-evaluation/standing-approved-20261008-fresh-comparison/review.md)
проверен по заранее записанной рубрике: mini low лучше соблюдает ограничения, но
6/8 functional passes недостаточно для локального recommendation gate. Это не human-owner приёмка.
После этого локально уточнены инструкции и Parent-card metadata;
[post-fix checkpoint](operation-chat-output-contract-checkpoint.md) проверен на фейках,
затем выполнена [отдельная платная regression-партия](../output/operation-chat-evaluation/standing-approved-20261008-postfix-comparison/review.md).
У всех ответов пустые планы, mini даёт расчёт полностью, но пропускает stale/admission
оговорки: снова 6/8 и неполный Parent control. Новые UI-оговорки детерминированы по
серверным полям, но не делают model gate passed задним числом.
Последующая [required-reply партия](../output/operation-chat-evaluation/standing-approved-20261008-required-reply-comparison/review.md)
проверила перестановку обязательных оговорок при том же контексте: nano 5/8,
mini 4/8, оба ниже gate и с регрессиями. Кандидат отклонён; только его prompt-правка
откачена к предыдущему точному hash. Детерминированные UI-предупреждения сохранены.
Новый [flagship diagnostic](../output/operation-chat-evaluation/standing-approved-20261008-flagship-quality/review.md)
не дал semantic score: `APITimeoutError` после 45 с, семь случаев не отправлялись,
резерв сохранён и повторов нет. Это не доказательство отсутствия доступа или
плохого качества модели. Расчёт стоимости профиля и измеренная QA стоимость различаются.
Отдельный [reviewed Sol diagnostic](../output/operation-chat-evaluation/standing-approved-20261008-sol-quality/review.md)
получил все восемь ответов без новых unknown charges; это другой ограниченный profile
selection, не повтор старого запроса. Старый hold сохранён. Результат улучшает reused
regression set, но не заменяет обе полные controls/owner labels/representative acceptance.
Следующий [server-owned contract checkpoint](operation-chat-read-confirmation-checkpoint.md)
добавил типизированные условия доступа/scope/cooldown/budget в ответ API и карточку.
Они вычисляются из текущей конфигурации и доступности, не сохраняются как consent,
не попадают в model schema/context и не вызывают provider I/O. Viewer не может
подтвердить чтение; отключённый Parent source отказывает оператору. Это проверенная
workflow защита, не ретроспективная смена Sol score или отдельная model-приёмка.
Последующий [офлайн delivery replay](operation-chat-delivery-replay-results.md)
проверяет эти же известные ответы через реальный слой истории с фейковыми портами:
Sol8/8 на уровне доставки, mini7/8, nano3/8. Raw scores не переписаны; новый платный
вызов, representative evaluation или приёмка production не выполнялись. Текущий
полный gate того checkpoint: **605 backend/80 UI**, mypy248, npm audit0; 33 новых офлайн теста.
Последующий аудит PostgreSQL подтвердил 5 интеграционных тестов и полный цикл
миграций на отдельном временном контейнере. Скрипт теперь отказывает удалённым
Docker endpoints, закрепляет локальный сокет и удаляет только созданный им container
ID (12 тестов защит). Текущий полный gate: **617 backend/80 UI**, mypy249, npm audit0;
связанные логи приведены в implementation checkpoint. Live источники не читались.
Итоговые команды и их результаты приведены в
[implementation checkpoint](cost-optimization-implementation.md#verification-checkpoint--2026-10-08).

## Требования и доказательства

| Требование | Проверяемая реализация / доказательство | Статус и граница доказательства |
| --- | --- | --- |
| Только `manaai`; четыре владельца возможностей, без реализации отсутствующих агентов | Каноническая модель в `operation-agent-model.md`; существующий registry и `test_architecture_boundaries.py`; композиция в `app/main.py` | Локальные изменения не добавляют агента или семейство действий. Продакшен не обновлён. |
| Общий сбор GA4 и backend, а не отдельный сбор каждым агентом | `application/shared_data.py`, `shared_sources.py`, `persistence/shared_data_store.py`; реальные порты обёрнуты в `app/main.py`; `test_operation_data_runtime.py`, `test_operation_google_auth.py` | С настоящей композицией и фейковым HTTP повтор/перезапуск не создаёт новые запросы. Это не проверка доступности live API. |
| Общие четыре обновления за сутки | Сохраняемая source/app lease и интервал минимум 21 600 с; `test_four_daily_cycles_are_shared_across_consumers_and_restart` | За 24 часа 192 логических обращения дают восемь загрузок: четыре на каждое приложение. Новое расписание не включено; cooldown ограничивает допущенные попытки, а не гарантирует успешные данные. |
| MANA и 360REC не смешиваются | `SourceBinding`, product в ключах сводок/анализов; подтверждаемая source revision, фильтры GA4 `streamId`; проверки отчётов в чате | Тесты разделения источников, persisted cache, анализов, ответов и fallback проходят на фейках. Реальные stream/product/cohort соответствия ещё должны принять владельцы источников. Один настроенный bundle не обеспечивает оба приложения. |
| Firestore: надёжные изменения, поздние события, обновления старых документов и удаления | Канонический запрос использует `occurred_at`; текущие маски operational collections не устанавливают queryable update/deletion contract. В `app/main.py` автоматические Firestore readers не создаются | Ограничение установлено и явно показывается. Delta/cursor/замена вклада текущего состояния **не реализованы**: без контракта они не были бы достоверными. Автоматический полный обход не используется как замена. |
| Восстановление после прерванного сбора и перезапуска | SQL lease/cooldown, fencing publisher; `test_operation_shared_data.py`; отдельные соединения PostgreSQL | Прерванная попытка сохраняет slot; старый publisher не публикует поверх новой lease. Это доказательство shared acquisition, не доказательство Firestore delta replay. |
| Детерминированные метрики и повторное использование одинакового анализа | Реальный Retention assessment и `retention/assessment_cache.py`; `test_operation_assessment_cache.py` | Совпадают метрики/findings, сохраняется исходная дата вычисления. Изменения фактов, ограничений, конфигурации, версии правил, приложения и истечение срока исключают reuse. Эти вычисления и раньше не вызывали модель: экономию AI-токенов им не приписываем. |
| Минимизированный и ограниченный AI-контекст | `_bounded_context`, budgeted conversation gateway; `test_operation_chat_costs.py`, реальные HTTP-тесты с fake model в `test_operation_chat_grounding.py` | Устранено предварительное усечение истории до 3000 chars; длинные user constraints доходят до общего byte bound. Initial summary/notes сокращение явно помечено. Сначала сокращается assistant text; текущий v5 сохраняет шесть user messages при 23 933 bytes (раньше 23 861). Card purpose называет реальную default capability. Последняя партия сохраняет свой candidate hash, но после регрессий prompt восстановлен к предыдущему точному hash; manifests не переписаны. $23 и запреты сохраняются, общий model gate не пройден. UI показывает stale/unknown источник вне свёрнутых деталей, включая бюджетный отказ, и предупреждает об условном допуске чтения. Вне шести turns полной памяти нет. |
| Сохраняемые дневные и месячные лимиты | `cost_control.py`, `persistence/cost_ledger.py`; миграция `e76b2d1c904a`; тесты независимых SQLite/PostgreSQL соединений | Admission до I/O; оба периода атомарны; учитываются параллельные requests, retries, in-flight/unknown; settlement однократен и относится к исходным периодам. Это операционный контроль по rate cards, а не полный Cloud Billing счёт. |
| Лимит тела ответа не недооценивает detection block | `infrastructure/metered_http.py`; async-stream тесты в `test_operation_metered_http.py` | Резерв payload + 64 KiB для pinned transport; raw identity, раннее закрытие, compressed refusal до итерации, known EOF refund, observed overrun записывается полностью. Не измеряет headers/TLS и не обещает физический предел произвольному transport. |
| После 401/403 не начинается новый полный сбор | Backend collection перед другими источниками; durable permanent-source gate; metered OAuth | Runtime 403-тест использует новые run keys и перезапуск: auth остаётся единственным запросом, другие источники не читаются. Quota exhaustion отдельно не превращается в вечную credential failure. |
| При лимите — старая сводка с давностью; действия на устаревших фактах запрещены | `test_operation_chat_fallback.py`, UI source-detail tests; `test_operation_evidence_freshness.py` | Fallback без source/model I/O, original date и age, request replay, без другого приложения. Реальные approval/execute HTTP-маршруты блокируют stale fake action до provider read/write, в том числе после restart; fresh контроль проходит. Это existing fake advertising lifecycle, не реализованные Retention actions. |
| Проверяемый прогноз день/месяц/год, отдельные статьи и резерв | `scripts/operation_cost_forecast.py`, `test_operation_cost_forecast.py`, исходный JSON и explicit-profile capacity artifacts | Чистый offline Decimal-расчёт с typed rate card, counts, отдельным `data_only_with_reserve_usd`. $2/$90 — ориентиры; объёмы/payload/нагрузка — допущения. Data-only $1.758307/30d before reserve, **$2.197884 with reserve — выше $2**. GPT-5.4: 20 чатов $34.477884/30d, прежняя 53-call future capacity $99.727884. Sol/2048: 20 чатов $32.557884, исходные 53 calls **$85.807884**, все суммы incl.25%. Уменьшение нагрузки не выдаётся за same-load экономию, модели не приняты; прогноз не enabled runtime или счёт. |
| Модель выбирается по качеству на наших задачах | Текущая `gpt-5.4-nano`/`none` не заменена; 184 settled receipts/$0.239276, один old timeout/unknown hold. Required-reply prompt-правка откачена по точному hash. Optional chat model/effort/rate card изолированы от public/audio model; fake-SDK/route tests | **Не принято.** Post-fix mini6/8, required-reply nano5/8/mini4/8 с регрессиями. GPT-5.4/low quality не оценено из-за первого timeout; запрос не повторён. Отдельный reviewed Sol/low profile — **7/8, utility15/16**, zero unambiguous critical/no regressions на прежних mini passes; Growth control проходит, Parent condition всё ещё неполный. Gate требует обе полные controls; UI не заменяет model acceptance. Ни один профиль не включён, следующей партии после Sol нет; source-owner/representative acceptance отсутствуют. |
| Firebase/ключи/IAM/SSH/audio/client services не меняются | Изменения ограничены локальным операционным кодом, UI freshness, документацией, зависимостями и фейковыми тестами; rollout/rollback в implementation document | Для этой цели не было deployment, push, external backend write или чтения live data sources. Единственное live I/O — разрешённые синтетические OpenAI checks. Production-этап требует отдельного согласования. |
| Тесты, `make verify`, документация и план отката | Полные quality gates, isolated migration audits, OpenAPI sync, secret scan; implementation/runbook и предложенный rollout | Текущий `make verify`: **exit 0**, **617 backend/80 UI**, mypy249 files, TS/lint, 34 dependency checks/Next16.3.8 build; `postgres-safety-accepted-make-verify-20261008.log`. 12 новых audit safety tests; прежние offline replay33/focused ASGI61. Отдельный текущий PostgreSQL17 migration round trip/no drift и **5 integration tests passed**: `pinned-postgres-cost-audit-20261008.log`. Обычный suite PG5 пропускает. Full npm audit: **0 findings**, waiver нет. Clean npm ci/Node24 Docker/browser/schema — предыдущие явно отдельные checkpoints, не новая проверка production. Secret/whitespace/shell syntax проходят. UI в этом аудите не менялся. |

## Что реально показывает экономию

- 24-часовая модель нагрузки: восемь source loads вместо 192 отдельных обращений
  при почасовом запросе четырёх потребителей для двух приложений. Числа чтений и
  payload в этом тесте синтетические; это проверка отсутствия дублирующего I/O.
- Реальный runtime с фейковым backend: первый цикл — шесть HTTP-попыток, повтор
  после перезапуска — ноль дополнительных. С GA4 и OAuth — 21 первоначальная
  попытка, повтор — ноль дополнительных. Health polling не делает внешних чтений.
- Ошибка backend auth останавливает остальные источники; replay, новый ключ run
  и restart не превращают отказ в бесконечный повторный сбор.
- При отказе AI admission fallback не вызывает SDK и не обновляет источники.

Это воспроизводимые свойства кода. Снижение фактического production счёта и
равенство качества модели ими не доказаны. Выключенный Firestore не означает,
что отсутствующие показатели были получены бесплатно: они помечены недоступными.

## Отдельная приёмка качества модели

Подготовленный инструмент и критерии описаны в
[operation-chat-quality-evaluation.md](operation-chat-quality-evaluation.md).
Его обычный запуск — чистый офлайн-план с нулём model/source calls. Выполненный v1
потерял старое ограничение; v2/v3 сохраняют и используют его в данном synthetic
случае. Это не доказывает произвольную память или равную полезность свободного
ответа модели; другие ошибки остались в ответах и планах.

Первые одиннадцать синтетических smoke выполнены; production-качество нельзя считать passed.
Отдельный двенадцатый flagship diagnostic остановлен на первой попытке: неизвестный
charge удержан, оставшиеся семь не отправлялись. Не превращать этот stop в score
или повторную партию без reviewed recovery; стоимость по периоду включает резерв,
а не только известные charges. JSON `null` правильно декодируется как unknown.
Первое nano reasoning сравнение не подтвердило полезность low. После model/validation
проверок уточнена metadata; post-fix rerun показал правильные temporal/card ответы
mini. Последующее mini none/low сравнение выделяет low как локального кандидата,
но none нарушает запрет Parent чтения в плане, а у low остаются UX/admission
оговорки. Эти задачи — regression set, не unseen production benchmark. В рабочей
конфигурации осталась nano; согласование модели/привязок и приёмка не заменены
успешными HTTP-ответами или самооценкой.
Отдельная required-reply правка не устранила проблему надёжно: появились
регрессии карточек и evidence checks. Она отклонена и локально откачена; повторов
до случайного passing ответа или paid judge не было.
Следующий reviewed Sol-профиль использует тот же восстановленный prompt/regression
contexts, low/2048 и стандартные цены: 8/8 responses, $0.032552. Старый timeout не
повторён/списан, новых unknown нет. **7/8** — улучшение на reused случаях, но Parent
описание «доступ и лимиты» не называет scope/cooldown/budget. Обе полные controls
не выполнены; model gate не принят. После Sol нового tuning/party/switch не было.
Пользователь
разрешил проверки дешевле $0.50 без отдельного вопроса. До новой партии всё равно
зафиксировать ограниченный обезличенный набор, критерии и бюджет в применимом scope
для **имеющихся** возможностей: разбор подтверждённых engagement
фактов, объяснение ограничений, планирование без заявления о выполненных действиях,
MANA/360REC separation, stale evidence, отсутствие доступных данных, длинный диалог
и недоверенные инструкции в source text. Не оценивать ещё не созданного агента
как уже работающего исполнителя.

Проверять на одинаковых исходных задачах старую и ограниченную передачу контекста,
а при предложении сменить модель — также текущую и кандидатную модели. Измерять:

- правильность чисел, выводов и ссылок на факты;
- отсутствие смешивания приложений и выдуманных данных/выполненных действий;
- явное соблюдение stale/unavailable/truncated ограничений;
- полезность ответа и сохранение необходимых ограничений из истории;
- actual input/output usage, известную стоимость, задержку и долю отказов.

Критические ошибки по данным, scope или выдуманным действиям неприемлемы.
Остальные критерии полезности, объём примеров, число повторов и предел расходов
определяются **до** запуска в рамках явного либо standing permission. Если scope
или предел выходят за разрешение, требуется новое согласие. Не вызывать модель-судью автоматически; это
добавочная стоимость, и её вывод не заменяет проверку владельца продукта.
Никаких production/Firebase данных в такой тест не передавать без отдельного scope.

## Вывод о завершении

Повторная проверка после возобновления 09.10.2026 прочитала текущие Settings через
`get_settings()` без запуска приложения/SDK или запросов источников. Sanitized
projection: provider `fake`, scope `unverified`, GA4 stream count `0`, scheduler
`false`, обычный чат `gpt-5.4-nano`, Goals `gpt-6.1-sol`. `.env` и ключи не менялись
и не выводились. Текущий latest gate подтверждён по логу: exit0, 659 backend/91 UI,
mypy259, npm audit0. Это доказательство локального состояния, не production preflight.

Свежая blocked audit после пользовательского уточнения включает три последовательных
шага: фиксация request-only 360REC/MANA focus, MANA-only forecast/tests и эту проверку
Settings/quality evidence. Уточнение снимает поиск БД 360REC, но на каждом шаге остаются
неподтверждённые точные MANA parent/child bindings и непрошедшая общая приёмка качества.
Raw Sol7/8 и known delivery8/8 не переписаны; новая representative evaluation отсутствует.
Без ответа владельца по MANA-строкам готового листа безопасная автоподстановка состава
невозможна. Новые fake повторы/прогнозы не являются устранением этой зависимости;
автопродолжения общей цели останавливаются со статусом blocked, не complete.

Дополнительная проверка 09.10.2026 сверила сохранённые Firebase metadata от 29.09,
успешный GA4 API report от 05.10, текущий `SourceBinding`/runtime gate, raw Sol review,
delivery replay и последний полный verification log. Известные IDs/названия собраны
в [лист подтверждения источников](source-ownership-confirmation.md): пользователю не
нужно искать их заново. Устаревшая фраза runbook про доступность public Firestore
«сейчас» удалена; historical instructions не разрешают новые сборы. Это изменение
документации, не новый live preflight. Whitespace/secret scan проходят (740 files).

Подтверждение реального product/parent-child состава и качественная приёмка
остались теми же внешними стоп-условиями в Goals checkpoint, последующем forecast
checkpoint и текущей проверке. Код, тесты, прогноз и безопасная памятка подготовлены;
повтор известных fake/model задач или предположение состава источников не разрешит
эти условия. Нужен ответ владельца по готовому листу; production rollout остаётся
отдельным согласованным этапом. Закрытие общей цели по текущим доказательствам
не обосновано.

Цель не закрыта. Локальные механизмы и негативные сценарии проверены,
полный dependency gate теперь проходит. Остаются реальное подтверждение source mappings и приёмка
исправленного качества. Nano сохраняет смысловые ошибки; mini на дополнительных
задачах также не прошла evidence/utility критерии. Новая рубрика зафиксировала
проблемы ответов mini и nano. После коррекции планы пусты и расчёт mini полнее,
но остаются stale/admission оговорки; nano использует процентные пункты для числа.
Последующая перестановка инструкций показала другие регрессии и не принята;
показатели предыдущей партии не переписаны, рабочий prompt восстановлен.
Детерминированные UI-оговорки защищают workflow независимо от текста модели,
но исходная fixed model-приёмка не пройдена. Sol raw score остаётся7/8; серверный
контракт теперь закрывает Parent control в приложении, что проверено на сохранённых
ответах (delivery8/8). Это не новая оценка модели и не доказательство стабильности
будущих ответов. Рабочая конфигурация не переключена; нужна репрезентативная приёмка
владельца, а не очередной повтор известных задач.
Согласие на дешёвые проверки не подтверждает
фактические stream/product/cohort IDs вместо владельцев источников.
Надёжный Firestore delta contract отсутствует; ограничение
зафиксировано без внедрения недостоверной синхронизации. Deployment и проверка
расходов production — отдельный, ещё не разрешённый этап.
