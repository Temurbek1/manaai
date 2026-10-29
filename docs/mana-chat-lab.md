# MANA: тестовый веб-чат

Локальная песочница для одного вымышленного родителя `900001` и его ребёнка
`900002`. Это не история настоящего клиента и не operational/admin чат.

## Запуск

Из checkout `/mnt/ssd2/mana-conversion-agent-20261021`:

```bash
make chat-lab
```

Откройте <http://127.0.0.1:8092>. Ключи не нужны. По умолчанию ответы модели
**симулируются**, но используются настоящие HTTP-маршруты, Parent-Touch,
Child-Safety, очередь и SQLite. Это проверка механики, не качества нейросети.

Обычный запуск теперь выбирает единый профиль `workspace-simulation`: менеджер
Parent-Touch, уточнения, Child-Safety, датированные источники приложений/заряда/
последней геопозиции, напоминания, Retention и тарифный каталог. Общая история,
вопросы и лимиты используются совместно. Старые специальные профили и их данные
сохранены; базовый прежний чат запускается через `make chat-lab-basic`.

Для быстрой проверки в одном чате: спросите «Как настроить MANA?», запустите
тестовый тревожный сигнал, затем ответьте на исходный вопрос. После этого
«Покажи тарифы на 90 дней до 200000» → `UZS`, «Какой заряд у ребёнка?» и
«Напомни завтра в 9 купить тетради» → подтверждение в чате. Напоминание отправится
только в подтверждённое время; обновление страницы не ускоряет и не повторяет его.

Общий профиль проверяет свежий статус оплаты перед конверсионным предложением.
Его исходный вымышленный профиль платный: событие о бесплатном статусе не должно
обойти эту проверку. Кнопки изменения профиля меняют только тестовый факт, не
настоящий тариф. Отдельные песочницы действий/пробных дней и фиксированных окон
сбора сохраняют собственные профили; в обычном чате реальные выдачи и сборы не
включаются. Referral ожидает контракт API и готовым не считается.

Для осознанного теста **реальных платных моделей**:

```bash
make chat-lab-live CHAT_LAB_ENV_FILE=/mnt/ssd2/Projects/manaai/.env
```

Ключ читается существующим `get_settings()` только на сервере, не попадает в
браузер. Используются уже настроенные модели Parent-Touch/Child-Safety, без
миграции SDK или смены общих настроек. Данные семьи остаются вымышленными.
Текущие лимиты — **5000 raw input+output токенов чата в день и отдельно 2000
Child-Safety на всю песочницу**. Это небольшие лимиты: реальный контекст может
не поместиться, тогда будет отказ без автоматического повтора/увеличения бюджета.
Реальный режим не проверяется платными вызовами в автоматических тестах.

Чтобы модель сама выбирала чтение заряда из вымышленного источника, используйте
отдельный режим:

```bash
make chat-lab-native
# Или осознанно включите реальные платные модели:
make chat-lab-native-live CHAT_LAB_ENV_FILE=/mnt/ssd2/Projects/manaai/.env
```

Напишите в обычное поле «Какой заряд у ребёнка?» или
«Farzandim telefonining quvvatini tekshiring». В симуляции выбор инструмента
тоже симулируется; в платном режиме его делает настоящая модель. SQL, проверка
принадлежности, общий кэш и передача ответа через Parent-Touch — те же рабочие
механизмы. Нажимать отдельную кнопку чтения для этого сценария не нужно.
Каталоги `data/chat-lab/native-simulation` и `data/chat-lab/native-real-model`
изолированы от двух прежних режимов; старые истории не получают инструменты
задним числом. Лимиты по 2000 токенов остаются, Firebase/Manakids/push/выдача
тарифов не подключаются. Подробности и оговорки реального теста — в
[checkpoint](mana-native-source-workflow.md).

Общий тестовый профиль хранит данные в `data/chat-lab/workspace-simulation`;
прежняя базовая симуляция и прежний платный профиль используют
`data/chat-lab/simulation` и `data/chat-lab/real-model`. Платная команда выше
сохраняет прежний базовый набор возможностей, а не включает общий профиль.
История и расходы сохраняются
после перезапуска. Новая страница не создаёт ещё один чат и не сбрасывает лимиты.
Каталог без маркера песочницы, с другим режимом или симлинком не открывается.
Существующие production БД/тома не используются и не восстанавливаются поверх.

Для выбора между зарядом и статистикой приложений доступен новый режим:

```bash
make chat-lab-observations
# Платная модель, данные по-прежнему вымышленные:
make chat-lab-observations-live CHAT_LAB_ENV_FILE=/mnt/ssd2/Projects/manaai/.env
```

Напишите «В каких приложениях ребёнок проводит время?» или
«Farzandim qaysi ilovalardan foydalanadi?». Одна неполная страница счётчиков —
это не подтверждённое экранное время за день. Режим использует отдельные каталоги
`observation-simulation` / `observation-real-model`, private family v12/source v3;
старые режимы не получают новые инструменты. Лимиты и запрет live-источников/
push/выдачи тарифов сохранены. Проверки, исходная ошибка фонового обработчика
и её исправление описаны в [checkpoint](mana-child-app-usage-source.md).

## Что проверять

- «Низкий заряд (тестовый источник)» — чтение вымышленного источника проходит
  через общий кэш, журнал изменения, Child-Safety и Parent-Touch. Агент пишет
  в тот же чат, даже без первого сообщения родителя. Это обычное уведомление,
  не доказательство угрозы ребёнку и не команда устройству. Повторное нажатие
  использует тот же снимок без повторного анализа.
- Напишите о сне ребёнка: Child-Safety анализирует сообщение, Parent-Touch
  задаёт один вопрос. Ответ автоматически привязывается к показанному вопросу.
- «Вопрос от Child-Safety» — агент начинает переписку без первого текста родителя.
- «Тестовый тревожный сигнал» — датированное событие проходит safety-анализ,
  а уведомление появляется от Parent-Touch в том же чате.
- «7 дней бесплатного доступа» — вымышленный backend event запускает конверсию.
  Оффер строго тестовый: его условия/ссылка не являются реальным billing-оффером.
  Обычные тихие часы 20:00–09:00, пауза после активной переписки и safety-приоритет
  не отключаются: предложение может остаться в очереди.
- «Аккаунт стал платным» — новый тестовый статус останавливает предложения.
  Платёж/транзакция не создаётся и оплаченная конверсия этим не доказывается.
- «Не присылай предложения» — отписка; полное состояние видно в «Под капотом».
- Обновите страницу — переписка и подтверждённые результаты сохраняются.

**Все режимы лишены live-адаптеров Firebase, GA4, Manakids, push, бесплатных
тарифов и платежей.** Родителя нельзя заменить произвольным ID, в том числе `4`.
Выдача бесплатных дней возвращает `503 trial_grants_disabled`. Нельзя подключить
production URL через поле в браузере: такого прокси/настройки здесь нет.

Страница защищена loopback-проверкой, Trusted Host, отдельной HttpOnly/SameSite
cookie и CSRF/Origin-проверкой. Технический backend bearer и ключ модели в браузер
не передаются. Не публикуйте эту dev-песочницу через nginx/ngrok как production.

UI опрашивает **только локальный SQL**. GET/reload не запускает модель или источник.
Неизвестный результат отправки наблюдается по исходному UUID: автоматической
повторной отправки с новым nonce нет. Неизвестные расходы сохраняют SQL hold.

Источник добавляет отдельный `sources.sqlite3` v2 и `source-fixture.json` внутри
того же каталога песочницы. Измерение фикстуры сохраняет свою дату после
перезапуска; позднее открытие страницы не делает его новым. Снимок старше шести
часов или без подтверждённой даты не становится автоматическим предупреждением.
Причина пропуска и состояние передачи видны в «Под капотом».
Исторические события v1 и изменения, записанные при выключенном потребителе,
не получают разрешение на анализ задним числом. Старый v1-reader отказывается
от нового source-файла; текущий закрытый reader сохраняет его без исполнения.
Не откатывайте заполненные файлы поверх новой истории.

Полный исходный objective остаётся незавершённым: native-режим подключает один
инструмент модели к вымышленному источнику, но не реальный Firebase, расписания
или остальные функции.
См. [точную границу и проверки](mana-source-safety-checkpoint.md).

## Какие API действительно нужны чату

### Independent Parent-Touch manager (local)

Run `make chat-lab-manager` for the current fictional single-chat manager profile.
Use the ordinary composer for a greeting, a 90-day price enquiry, a child question
or an explicit reminder. General conversation/catalogue enquiries do not consume
Child-Safety's separate global quota. Child requests retain the same pending
message until the specialist review and sole-speaker reply. Reminder proposals
still require the parent's exact confirmation. This simulation has its own
`manager-simulation` history; it attaches no real source, push or tariff grant.
See [the exact implementation and qualified actual-model evidence](mana-parent-touch-manager.md).

Для нового интерфейса достаточно трёх операций:

| Операция | Назначение |
| --- | --- |
| `POST /api/v1/mana-ai/parent-touch/messages` | Принять текст, дождаться внутреннего review перед ответом |
| `GET /api/v1/mana-ai/parent-touch/messages/{request_id}?parent_id=...` | Наблюдать результат, не повторяя генерацию |
| `GET /api/v1/mana-ai/parent-touch/chat?parent_id=...` | Единая история, вопрос для ответа и лимит |

Отдельные endpoint-ы **не означают отдельные чаты**:

| Группа Swagger | Кто вызывает и зачем |
| --- | --- |
| `mana-chat` | Три операции интерфейса выше |
| `mana-child-safety` | Backend передаёт новые данные ребёнка; результаты приходят через Parent-Touch |
| `mana-conversion` | Backend передаёт изменения доступа/активности и подтверждённые исходы; отдельного чата нет |
| `mana-coordination` | Запросы специалистов, ручная доставка, диагностика — не кнопки обычного клиента |
| `mana-notifications` | Проверенные контактные настройки и наблюдение push — не второй канал общения агента |
| `mana-chat-compatibility` | Старые синхронные `/chat` и POST `/parent-touch/chat`; помечены deprecated, но продолжают работать |
| `mana-ai` | Независимые stateless-анализы; сами по себе не пишут в историю чата |

Три синхронные операции помечены как совместимые, а не удалены. Их поведение,
история, авторизация и схемы сохранены. В самой песочнице синхронная отправка
блокируется, чтобы тест случайно не обходил Child-Safety review.
Для безопасного удаления старых API сначала нужны подтверждение владельца
интеграции и учёт фактических клиентов; в этой задаче такой миграции нет.

Песочница не доказывает настоящее покрытие всех родителей, их активность/разрешения
или согласованные billing-условия. По текущей цели доступные факты подключаем
напрямую из существующих источников; новые webhook-и не являются обязательным
условием. Неизвестные разрешения/условия нельзя выдумывать. Работающий симулятор
не доказывает paid conversion.

### Shared source-review mode

`make chat-lab-source-reviews` uses its own simulation directory. Trigger the app
and battery sources within three seconds; one qualified Child-Safety overview
should reach the single Parent-Touch chat. Repeating a cached read does not create
another overview. A later RU/Uzbek message is a separate conversational request.
See [source-review semantics and evidence](mana-source-reviews.md). The `-live`
variant explicitly uses paid configured models with fictional sources, never a
real family data, push or tariff adapter. Neither variant belongs on production.

### Parent assistant reminders

`make chat-lab-reminders` runs the fictional family with reminders and the full
native/source-review profile. Write `Напомни позже купить тетради`, answer the
pending date question with `YYYY-MM-DD HH:mm`, then confirm `Да`. The browser binds
that parent-level confirmation automatically. Choose a time at least one minute
ahead; the worker uses the real clock. Use `отмени последнее напоминание` to cancel.

`make chat-lab-reminders-live CHAT_LAB_ENV_FILE=/path/to/server.env` is a separate,
explicit paid-model mode with its own durable directory. It still cannot access
live family data, send push or grant tariffs. Never reset its quotas/history to
repeat diagnostics or run a paid model with an artificial clock. The simulator's
known notebook phrases are fixtures, not evidence of general language quality.
See [the actual qualified model and lifecycle checkpoint](mana-parent-reminders.md).

### Retention / Win-back

Run `make chat-lab-retention`. The “Возврат после паузы” button in an empty history
prepares one fictional historical conversation and test opt-in. Parent-Touch then
initiates one check-in. Reply normally, or write `не пиши первым` /
`birinchi bo‘lib yozmang` to stop these check-ins. No clock is accelerated, source
is read, tariff is granted or push is sent. Repeating the button does not recreate
history or repeat work. It is unavailable in the explicit paid-model mode.
See [the supported flow and actual acceptance](mana-client-retention.md).
