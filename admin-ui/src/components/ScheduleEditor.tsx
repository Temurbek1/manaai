import { useState } from "react";

import type { Schedule } from "../api/client";
import { StatusBadge } from "./StatusBadge";

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
        caught instanceof Error ? caught.message : "Schedule update failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="schedule-editor" disabled={disabled || busy}>
      <legend>{schedule.job_type}</legend>
      <label>
        <span>Cron expression</span>
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
        <span>Timezone</span>
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
        Enabled
      </label>
      <StatusBadge status={schedule.enabled ? "enabled" : "disabled"} />
      <button
        className="button compact"
        onClick={() => void save()}
        type="button"
      >
        Save schedule
      </button>
      {error ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
