"use client";
import { useI18n } from "@/i18n/LanguageProvider";
import { useEffect, useRef, useState } from "react";
import { LanguageSelect } from "@/i18n/LanguageSelect";

import {
  ApiError,
  apiPost,
  type AuthSession,
  type AuthenticatedSession,
  isAuthenticatedSession,
  type RequestCodeResponse,
} from "../api/client";

interface LoginPanelProps {
  notice: string | null;
  onAuthenticated: (session: AuthenticatedSession) => void;
}

const MAX_TELEGRAM_ID = 9_007_199_254_740_991;

export function LoginPanel({
  notice,
  onAuthenticated,
}: LoginPanelProps): React.JSX.Element {
  const { t } = useI18n();

  const [stage, setStage] = useState<"identity" | "code">("identity");
  const [telegramId, setTelegramId] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestInfo, setRequestInfo] = useState<RequestCodeResponse | null>(
    null,
  );
  const [expiresAt, setExpiresAt] = useState(0);
  const [resendAt, setResendAt] = useState(0);
  const [now, setNow] = useState(0);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (stage !== "code") return;
    codeInput.current?.focus();
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [stage]);

  const secondsLeft = Math.max(0, Math.ceil((expiresAt - now) / 1000));
  const resendLeft = Math.max(0, Math.ceil((resendAt - now) / 1000));

  async function requestCode(): Promise<void> {
    const normalized = telegramId.trim();
    if (!/^\d+$/.test(normalized)) {
      setError(t("Введите Telegram ID цифрами."));
      return;
    }
    const numericId = Number(normalized);
    if (
      !Number.isSafeInteger(numericId) ||
      numericId <= 0 ||
      numericId > MAX_TELEGRAM_ID
    ) {
      setError(t("Telegram ID указан неверно."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<RequestCodeResponse>(
        "/api/v1/auth/telegram/request-code",
        { telegram_id: numericId },
      );
      const timestamp = Date.now();
      setRequestInfo(result);
      setExpiresAt(timestamp + result.expires_in_seconds * 1000);
      setResendAt(timestamp + result.resend_after_seconds * 1000);
      setNow(timestamp);
      setCode("");
      setStage("code");
    } catch (requestError) {
      setError(t(authErrorMessage(requestError)));
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(): Promise<void> {
    if (!/^\d{6}$/.test(code)) {
      setError(t("Введите код из шести цифр."));
      return;
    }
    if (secondsLeft === 0) {
      setError(t("Срок действия кода истёк. Запросите новый код."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<AuthSession>(
        "/api/v1/auth/telegram/verify-code",
        { telegram_id: Number(telegramId), code },
      );
      if (!isAuthenticatedSession(result)) {
        throw new Error(t("Сервер не создал сессию."));
      }
      onAuthenticated(result);
    } catch (verifyError) {
      setError(t(authErrorMessage(verifyError)));
      setCode("");
      window.requestAnimationFrame(() => codeInput.current?.focus());
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <form
        className="login-panel"
        onSubmit={(event) => {
          event.preventDefault();
          void (stage === "identity" ? requestCode() : verifyCode());
        }}
      >
        <div className="brand login-brand">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>MANA</strong>
            <small>Operation AI</small>
          </div>
        </div>
        <p className="eyebrow">{t("Защищённый вход")}</p>
        <LanguageSelect />
        <h1>{stage === "identity" ? t("Вход в MANA") : t("Введите код")}</h1>
        {stage === "identity" ? (
          <>
            <p className="page-description">
              {t(
                "Укажите числовой Telegram ID. Если доступ разрешён, бот MANA отправит одноразовый код.",
              )}{" "}
            </p>
            <label className="field">
              <span>Telegram ID</span>
              <input
                autoComplete="username"
                autoFocus
                inputMode="numeric"
                onChange={(event) =>
                  setTelegramId(
                    event.target.value.replace(/\D/g, "").slice(0, 16),
                  )
                }
                placeholder={t("Например, 976835256")}
                required
                value={telegramId}
              />
            </label>
            <p className="bot-hint">
              {t(
                "Числовой ID можно узнать через служебного Telegram-бота и передать администратору MANA для выдачи доступа.",
              )}{" "}
            </p>
          </>
        ) : (
          <>
            <p className="page-description">
              {t(
                "Проверьте сообщения от бота MANA. Код действует ровно 60 секунд и используется только один раз.",
              )}{" "}
            </p>
            <div className="identity-summary">
              <span>Telegram ID</span>
              <strong>{telegramId}</strong>
              <button
                disabled={busy}
                onClick={() => {
                  setStage("identity");
                  setCode("");
                  setError(null);
                }}
                type="button"
              >
                {t("Изменить")}{" "}
              </button>
            </div>
            <label className="field otp-field">
              <span>{t("Код из Telegram")}</span>
              <input
                aria-describedby="otp-timer"
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                }
                pattern="[0-9]{6}"
                placeholder="000000"
                ref={codeInput}
                required
                value={code}
              />
            </label>
            <div
              className={secondsLeft === 0 ? "otp-timer expired" : "otp-timer"}
              id="otp-timer"
            >
              {secondsLeft > 0
                ? t("Код действителен ещё {0} сек.", {
                    "0": String(secondsLeft),
                  })
                : t("Срок действия кода истёк.")}
            </div>
            <div className="auth-secondary-actions">
              <button
                className="text-button"
                disabled={busy || resendLeft > 0}
                onClick={() => void requestCode()}
                type="button"
              >
                {resendLeft > 0
                  ? t("Отправить снова через {0} сек.", {
                      "0": String(resendLeft),
                    })
                  : t("Отправить новый код")}
              </button>
              {requestInfo?.bot_url ? (
                <a href={requestInfo.bot_url} rel="noreferrer" target="_blank">
                  {t("Открыть бота")}{" "}
                </a>
              ) : null}
            </div>
            <p className="bot-hint">
              {t(
                "Бот пока не может отправить сообщение? Откройте MANA Bot, нажмите Start и повторите отправку кода.",
              )}{" "}
            </p>
          </>
        )}
        {(error ?? notice) ? (
          <p className="error-banner" role="alert">
            {t(error ?? notice ?? "")}
          </p>
        ) : null}
        <button
          className="button login-button"
          disabled={busy || (stage === "code" && secondsLeft === 0)}
          type="submit"
        >
          {busy
            ? t("Подождите…")
            : stage === "identity"
              ? t("Получить код")
              : t("Войти")}
        </button>
        <small className="credential-note">
          {t(
            "Пароль не требуется. Доступ подтверждается одноразовым кодом.",
          )}{" "}
        </small>
      </form>
    </main>
  );
}

function authErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error
      ? error.message
      : "Не удалось выполнить вход.";
  }
  const messages: Record<string, string> = {
    attempts_exhausted: "Попытки исчерпаны. Запросите новый код.",
    expired_code: "Срок действия кода истёк. Запросите новый код.",
    invalid_code: "Неверный код. Проверьте сообщение в Telegram.",
    invalid_or_expired_code: "Код неверен или уже истёк. Запросите новый код.",
    invalid_or_reused_code: "Этот код уже использован. Запросите новый код.",
    rate_limited: "Слишком много запросов. Подождите и попробуйте снова.",
    temporarily_locked: "Вход временно заблокирован. Попробуйте позже.",
  };
  if (error.status === 503) {
    return "Вход через Telegram временно недоступен.";
  }
  return (
    messages[error.message] ?? "Не удалось выполнить вход. Попробуйте снова."
  );
}
