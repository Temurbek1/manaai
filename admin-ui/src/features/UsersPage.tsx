"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  apiGet,
  apiPatch,
  apiPost,
  type AdminUser,
  type AdminUserPage,
  type AuthAuditPage,
} from "@/api/client";
import { useSession } from "@/auth/SessionContext";
import { PageHeader } from "@/components/PageHeader";

type UserRole = AdminUser["role"];

const ROLES: readonly UserRole[] = ["viewer", "operator", "approver", "admin"];

export function UsersPage(): React.JSX.Element {
  const { session } = useSession();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(session.user.role === "admin");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [telegramId, setTelegramId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<UserRole>("viewer");
  const [disableId, setDisableId] = useState<string | null>(null);
  const [disableReason, setDisableReason] = useState("");
  const [audit, setAudit] = useState<AuthAuditPage | null>(null);
  const [auditUserId, setAuditUserId] = useState<string | null>(null);

  const loadUsers = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const page = await apiGet<AdminUserPage>("/api/v1/admin/users");
      setUsers(page.items);
      setError(null);
    } catch (loadError) {
      setError(userErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (session.user.role === "admin") {
      void Promise.resolve().then(loadUsers);
    }
  }, [loadUsers, session.user.role]);

  async function createUser(): Promise<void> {
    setBusyId("create");
    setError(null);
    try {
      await apiPost<AdminUser>("/api/v1/admin/users", {
        telegram_id: Number(telegramId),
        role,
        display_name: displayName.trim() || null,
        username: username.trim().replace(/^@/, "") || null,
      });
      setTelegramId("");
      setDisplayName("");
      setUsername("");
      setRole("viewer");
      await loadUsers();
    } catch (createError) {
      setError(userErrorMessage(createError));
    } finally {
      setBusyId(null);
    }
  }

  async function updateUser(userId: string, body: object): Promise<void> {
    setBusyId(userId);
    setError(null);
    try {
      await apiPatch<AdminUser>(`/api/v1/admin/users/${userId}`, body);
      setDisableId(null);
      setDisableReason("");
      await loadUsers();
    } catch (updateError) {
      setError(userErrorMessage(updateError));
    } finally {
      setBusyId(null);
    }
  }

  async function revokeSessions(userId: string): Promise<void> {
    setBusyId(userId);
    setError(null);
    try {
      await apiPost(`/api/v1/admin/users/${userId}/sessions/revoke`, {});
    } catch (revokeError) {
      setError(userErrorMessage(revokeError));
    } finally {
      setBusyId(null);
    }
  }

  async function showAudit(userId: string): Promise<void> {
    setBusyId(userId);
    try {
      setAudit(
        await apiGet<AuthAuditPage>(`/api/v1/admin/users/${userId}/audit`),
      );
      setAuditUserId(userId);
    } catch (auditError) {
      setError(userErrorMessage(auditError));
    } finally {
      setBusyId(null);
    }
  }

  if (session.user.role !== "admin") {
    return (
      <section>
        <PageHeader
          description="Управление доступом доступно только администраторам."
          eyebrow="Access control"
          title="Недостаточно прав"
        />
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        description="Выдавайте доступ по Telegram ID, меняйте роли и немедленно отзывайте сессии."
        eyebrow="Access control"
        title="Пользователи"
      />

      <form
        className="panel user-create-form"
        onSubmit={(event) => {
          event.preventDefault();
          void createUser();
        }}
      >
        <div>
          <strong>Добавить пользователя</strong>
          <small>
            Пользователь сможет запросить код сразу после сохранения.
          </small>
        </div>
        <label className="field">
          <span>Telegram ID</span>
          <input
            inputMode="numeric"
            onChange={(event) =>
              setTelegramId(event.target.value.replace(/\D/g, "").slice(0, 16))
            }
            required
            value={telegramId}
          />
        </label>
        <label className="field">
          <span>Имя</span>
          <input
            maxLength={160}
            onChange={(event) => setDisplayName(event.target.value)}
            value={displayName}
          />
        </label>
        <label className="field">
          <span>@username</span>
          <input
            maxLength={64}
            onChange={(event) => setUsername(event.target.value)}
            value={username}
          />
        </label>
        <label className="field">
          <span>Роль</span>
          <select
            onChange={(event) => setRole(event.target.value as UserRole)}
            value={role}
          >
            {ROLES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <button className="button" disabled={busyId === "create"} type="submit">
          {busyId === "create" ? "Сохраняем…" : "Добавить"}
        </button>
      </form>

      {error ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="panel auth-loading" role="status">
          Загружаем пользователей…
        </p>
      ) : (
        <div className="user-list">
          {users.map((user) => {
            const isSelf = user.user_id === session.user.user_id;
            const busy = busyId === user.user_id;
            return (
              <article className="panel user-card" key={user.user_id}>
                <div className="user-card-heading">
                  <div>
                    <strong>{user.display_name ?? "Без имени"}</strong>
                    <span>
                      {user.username ? `@${user.username} · ` : ""}
                      Telegram {String(user.telegram_id)}
                    </span>
                  </div>
                  <span className={`user-status ${user.status}`}>
                    {user.status}
                  </span>
                </div>
                <div className="user-fields">
                  <label className="field">
                    <span>Имя</span>
                    <input
                      defaultValue={user.display_name ?? ""}
                      disabled={busy}
                      key={`${user.user_id}-name-${user.updated_at}`}
                      onBlur={(event) => {
                        const next = event.target.value.trim() || null;
                        if (next !== user.display_name) {
                          void updateUser(user.user_id, { display_name: next });
                        }
                      }}
                    />
                  </label>
                  <label className="field">
                    <span>@username</span>
                    <input
                      defaultValue={user.username ?? ""}
                      disabled={busy}
                      key={`${user.user_id}-username-${user.updated_at}`}
                      onBlur={(event) => {
                        const next =
                          event.target.value.trim().replace(/^@/, "") || null;
                        if (next !== user.username) {
                          void updateUser(user.user_id, { username: next });
                        }
                      }}
                    />
                  </label>
                  <label className="field">
                    <span>Роль</span>
                    <select
                      disabled={busy || isSelf}
                      onChange={(event) => {
                        if (
                          window.confirm(
                            `Изменить роль пользователя на ${event.target.value}?`,
                          )
                        ) {
                          void updateUser(user.user_id, {
                            role: event.target.value,
                          });
                        } else {
                          event.target.value = user.role;
                        }
                      }}
                      value={user.role}
                    >
                      {ROLES.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="user-meta">
                    <span>Последний вход</span>
                    <strong>{formatDate(user.last_login_at)}</strong>
                    <span>Создан</span>
                    <strong>{formatDate(user.created_at)}</strong>
                    <span>Кем создан</span>
                    <strong>{user.created_by}</strong>
                  </div>
                </div>
                {disableId === user.user_id ? (
                  <div className="disable-reason">
                    <label className="field">
                      <span>Причина отключения</span>
                      <input
                        autoFocus
                        maxLength={500}
                        onChange={(event) =>
                          setDisableReason(event.target.value)
                        }
                        value={disableReason}
                      />
                    </label>
                    <button
                      className="button danger compact"
                      disabled={!disableReason.trim() || busy}
                      onClick={() =>
                        void updateUser(user.user_id, {
                          status: "disabled",
                          disabled_reason: disableReason.trim(),
                        })
                      }
                      type="button"
                    >
                      Подтвердить
                    </button>
                    <button
                      className="button secondary compact"
                      onClick={() => setDisableId(null)}
                      type="button"
                    >
                      Отмена
                    </button>
                  </div>
                ) : null}
                <div className="button-row user-actions">
                  {user.status === "active" ? (
                    <button
                      className="button danger compact"
                      disabled={busy || isSelf}
                      onClick={() => setDisableId(user.user_id)}
                      type="button"
                    >
                      Отключить
                    </button>
                  ) : (
                    <button
                      className="button compact"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Снова разрешить вход этому пользователю?",
                          )
                        ) {
                          void updateUser(user.user_id, { status: "active" });
                        }
                      }}
                      type="button"
                    >
                      Включить
                    </button>
                  )}
                  <button
                    className="button secondary compact"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "Отозвать все активные сессии пользователя?",
                        )
                      ) {
                        void revokeSessions(user.user_id);
                      }
                    }}
                    type="button"
                  >
                    Отозвать сессии
                  </button>
                  <button
                    className="button secondary compact"
                    disabled={busy}
                    onClick={() => void showAudit(user.user_id)}
                    type="button"
                  >
                    Аудит
                  </button>
                </div>
                {user.disabled_reason ? (
                  <p className="disabled-reason">
                    Причина: {user.disabled_reason}
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}

      {audit !== null ? (
        <div
          className="audit-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Аудит доступа"
        >
          <div className="audit-drawer-heading">
            <div>
              <strong>Аудит доступа</strong>
              <small>{auditUserId}</small>
            </div>
            <button
              onClick={() => setAudit(null)}
              type="button"
              aria-label="Закрыть аудит"
            >
              ×
            </button>
          </div>
          {audit.items.length === 0 ? <p>Событий пока нет.</p> : null}
          <ol>
            {audit.items.map((event) => (
              <li key={event.event_id}>
                <strong>{event.event_type}</strong>
                <span>{event.summary}</span>
                <time>{formatDate(event.occurred_at)}</time>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

function formatDate(value: string | null): string {
  if (value === null) return "Ещё не входил";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function userErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Не удалось обновить пользователя.";
  }
  const messages: Record<string, string> = {
    last_active_admin:
      "Нельзя отключить или понизить последнего активного администратора.",
    self_access_change_forbidden:
      "Нельзя изменить собственную роль или отключить себя.",
    telegram_id_already_exists:
      "Пользователь с таким Telegram ID уже существует.",
    user_not_found: "Пользователь не найден.",
  };
  return messages[error.message] ?? "Не удалось обновить пользователя.";
}
