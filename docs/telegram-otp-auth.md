# Telegram OTP authentication

## Пользовательский вход

Admin panel использует индивидуальную серверную сессию вместо общего ключа в браузере:

1. Пользователь открывает Next.js admin panel и вводит числовой Telegram ID.
2. FastAPI возвращает одинаковый generic-ответ для разрешённого, неизвестного, отключённого и
   недоступного получателя. Это не позволяет проверять наличие пользователя по ответу.
3. Для активного пользователя Telegram Bot API `sendMessage` доставляет шестизначный код.
4. Пользователь вводит код в течение ровно 60 секунд. Код одноразовый; новый запрос делает старый
   недействительным.
5. После успешной проверки FastAPI создаёт opaque server-side session и отдаёт только HttpOnly
   session cookie плюс отдельную CSRF cookie. Refresh восстанавливает вход через
   `GET /api/v1/auth/session`.
6. Logout отзывает серверную сессию и очищает обе cookie.

Пароль не нужен. Технические role/API keys остаются только для автоматизации и совместимых
server-to-server клиентов; Next.js не принимает, не хранит и не отправляет их. Роль браузерного
пользователя всегда берётся из durable user record на backend.

## Как запустить бота и узнать ID

До первой доставки откройте ссылку на MANA Bot, нажмите **Start**, вернитесь в форму и запросите
новый код после cooldown. Telegram запрещает боту начинать диалог с пользователем, который ещё не
запустил его. UI всегда показывает это действие без раскрытия того, зарегистрирован ли ID.

Нужен числовой Telegram ID, а не `@username` или номер телефона. Его можно узнать через служебного
Telegram-бота для просмотра собственного ID и передать администратору MANA по доверенному каналу.
`@username` в user record — только отображаемый профиль и не используется как login identifier.

## Пользователи и роли

При старте API `MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS` идемпотентно сверяет начальных администраторов.
Default содержит `976835256,51456737`. Повторный запуск не создаёт дубликаты, сохраняет UUID и
профиль, но восстанавливает обоим активную роль `admin`.

Admin открывает `/users`, где может:

- добавить разрешённый Telegram ID и назначить `viewer`, `operator`, `approver` или `admin`;
- изменить display name и `@username`;
- изменить роль с подтверждением;
- отключить пользователя с обязательной причиной или включить снова;
- отозвать все сессии;
- просмотреть authentication audit.

Backend запрещает изменение собственной роли/статуса и атомарно не допускает удаления последнего
активного admin. Disable сразу отзывает все сессии. Self-approval сравнивает устойчивый внутренний
user UUID из сессии, а не заголовок браузера.

## OTP и защита от перебора

Код генерируется криптографическим RNG как строка из ровно шести цифр. В базе хранится только
HMAC-SHA-256 с привязкой к challenge UUID и Telegram ID; plaintext не попадает в response, audit,
лог или обычный local runtime. `MANA_OTP_HMAC_SECRET` должен быть отдельным сильным секретом.

Default policy:

| Policy | Значение |
| --- | ---: |
| OTP TTL | ровно 60 секунд |
| Resend cooldown | 30 секунд |
| Attempts per challenge | 5 |
| Requests per Telegram ID | 5 за 15 минут |
| Requests per IP | 20 за 15 минут |
| Verify requests per IP | 30 за 15 минут |
| Global requests | 1000 за 15 минут |
| Consecutive failures before lockout | 10 |
| Temporary lockout | 15 минут |

Rate events, challenge replacement и verification consume сериализуются через durable database
guard. Поэтому несколько API workers не могут одновременно выпустить два активных кода, дважды
consume один код или пройти rolling limit гонкой. Lockout не постоянный: после его истечения новая
ошибка начинает безопасную новую последовательность, а успешный вход обнуляет счётчик.

## Session и CSRF

Session ID и CSRF token генерируются независимо и сохраняются только как HMAC. Session expiration
fixed: 8 часов (`MANA_SESSION_TTL_SECONDS=28800`), без продления от активности. Успешный повторный
login отзывает прежнюю cookie-session, переданную браузером, что защищает от fixation.

Cookie policy:

- `mana_admin_session`: opaque, `HttpOnly`, `SameSite=Lax`, `Path=/`;
- `mana_csrf`: non-HttpOnly double-submit value, `SameSite=Lax`, `Path=/`;
- обе cookie получают `Secure` в staging/production;
- unsafe запрос с browser session требует совпадающие CSRF header/cookie, server-side HMAC и
  разрешённый `Origin`;
- logout, disable, explicit revoke и fixed expiration инвалидируют server-side session.

Все timestamps сохраняются как UTC. Сервер не доверяет `X-Forwarded-For` из интернета: rate limit
использует адрес, который предоставил ASGI server. На reverse proxy разрешайте forwarded headers
только от известного proxy и передавайте HTTPS scheme, иначе secure-cookie/origin диагностика будет
ошибочной. Browser должен обращаться к Next.js по HTTPS; Next.js same-origin `/api` rewrite идёт к
приватному FastAPI endpoint.

## Local setup

1. Скопируйте `.env.example` в игнорируемый `.env`.
2. Задайте `MANA_TELEGRAM_BOT_TOKEN`, `MANA_TELEGRAM_BOT_USERNAME` и сильный
   `MANA_OTP_HMAC_SECRET`. Legacy имя `BOT_TOKEN` принимается только для совместимости; новое имя
   предпочтительно.
3. Оставьте `MANA_AUTH_TEST_MODE=false`. Обычный local runtime использует реального бота.
4. Выполните `make migrate`, `make run`, затем `make admin-dev`.
5. Откройте `http://localhost:3000`, запустите бота и войдите по bootstrap ID.

Fake file sender включается только явными `MANA_AUTH_TEST_MODE=true` и
`MANA_AUTH_TEST_OTP_SINK_PATH` при `APP_ENV=local`. Staging/production отвергают этот режим. HTTP
endpoint для чтения OTP отсутствует.

## Production requirements

Production startup fail-closed, если отсутствуют token/username, сильный HMAC secret или
`MANA_TRUSTED_ORIGINS`. Используйте PostgreSQL, применяйте Alembic до запуска API, оставляйте
`OPERATION_AUTO_CREATE_SCHEMA=false`, храните секреты в secret manager и запускайте минимум
`make auth-verify`, `make admin-verify`, `make audit-verify` перед release.

`MANA_TRUSTED_ORIGINS` содержит публичные HTTPS origins Next.js без path. `CORS_ORIGINS` нужен только
для действительно cross-origin клиентов; стандартная topology оставляет browser → Next.js →
FastAPI same-origin. Не публикуйте FastAPI admin endpoints напрямую, если gateway policy этого не
требует.

## Audit, troubleshooting и incident response

Audit фиксирует bootstrap, code request/delivery failure, failed/successful login, rate limit,
logout, создание пользователя, изменения профиля/роли/статуса и отзыв сессий. Audit не содержит
OTP, session token, CSRF token или bot token.

Если сообщение не приходит:

1. Проверьте, что пользователь нажал Start у правильного bot username.
2. Проверьте active status и точный числовой Telegram ID в `/users`.
3. Дождитесь resend cooldown/lockout; не отключайте limits.
4. Проверьте sanitized audit category: bot-not-started, transient, permanent или unavailable.
5. Проверьте outbound HTTPS к `api.telegram.org`, не выводя URL с bot token.

При ротации bot token обновите secret manager и перезапустите API; старый token отзовите через
BotFather. При ротации HMAC secret все существующие challenges/sessions становятся недействительными,
поэтому планируйте её как принудительный logout. Для emergency disable отключите пользователя или
отзовите его сессии в `/users`; при компрометации всей auth-системы остановите доступ на gateway,
ротируйте bot/HMAC secrets и перезапустите API.

Manual real-bot smoke запускается только для явно указанного собственного тестового ID и не пишет
код в artifacts:

```bash
MANA_TELEGRAM_AUTH_SMOKE=1 \
MANA_TELEGRAM_AUTH_SMOKE_USER_ID=<explicit-id> \
make telegram-auth-smoke
```
