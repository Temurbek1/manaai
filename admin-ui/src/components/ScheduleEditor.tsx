"use client";
import { useI18n } from "@/i18n/LanguageProvider";
import { useState } from "react";

import type { Schedule } from "../api/client";
import { StatusBadge } from "./StatusBadge";
import { labelFor } from "../ui/labels";

interface ScheduleEditorProps {
  disabled: boolean;
  schedule: Schedule;
  onSave: (schedule: Schedule, values: ScheduleValues) => Promise<void>;
}

export interface ScheduleValues {
  cron_expression: string;
  timezone: string;
  enabled: boolean;
}

export function ScheduleEditor({
  disabled,
  schedule,
  onSave,
}: ScheduleEditorProps): React.JSX.Element {
  const { t } = useI18n();

  const [values, setValues] = useState<ScheduleValues>({
    cron_expression: schedule.cron_expression,
    timezone: schedule.timezone,
    enabled: schedule.enabled,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onSave(schedule, values);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("Не удалось сохранить расписание"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="schedule-editor" disabled={disabled || busy}>
      <legend>{t(labelFor(schedule.job_type))}</legend>
      {schedule.circuit_open ? (
        <p className="error-banner" role="alert">
          {t("Автоматически остановлено после")}{" "}
          {schedule.consecutive_permanent_failures}{" "}
          {t(
            "постоянных ошибок подряд. Исправьте подключение перед включением расписания. Сохранение включённого расписания сбрасывает защитную остановку.",
          )}{" "}
        </p>
      ) : null}
      <label>
        <span>{t("Расписание (cron)")}</span>
        <input
          aria-label={`${schedule.job_type} cron expression`}
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              cron_expression: event.target.value,
            }))
          }
          value={values.cron_expression}
        />
      </label>
      <label>
        <span>{t("Часовой пояс")}</span>
        <input
          aria-label={`${schedule.job_type} timezone`}
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              timezone: event.target.value,
            }))
          }
          value={values.timezone}
        />
      </label>
      <label className="checkbox-field">
        <input
          checked={values.enabled}
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              enabled: event.target.checked,
            }))
          }
          type="checkbox"
        />
        {t("Включено")}{" "}
      </label>
      <StatusBadge status={schedule.enabled ? "enabled" : "disabled"} />
      <button
        className="button compact"
        onClick={() => void save()}
        type="button"
      >
        {t("Сохранить расписание")}{" "}
      </button>
      {error ? (
        <p className="error-banner" role="alert">
          {t(error)}
        </p>
      ) : null}
    </fieldset>
  );
}
