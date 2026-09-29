import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, jest } from "@jest/globals";

import type { Schedule } from "../api/client";
import { ScheduleEditor, type ScheduleValues } from "./ScheduleEditor";

describe("ScheduleEditor circuit breaker", () => {
  it("shows the failure alert and requires explicitly enabling before recovery", async () => {
    const schedule: Schedule = {
      schedule_id: "retention-engagement-analysis",
      agent_id: "retention-agent",
      capability_key: "retention.engagement.analyze",
      job_type: "analysis",
      cron_expression: "20 */6 * * *",
      timezone: "UTC",
      enabled: false,
      circuit_open: true,
      consecutive_permanent_failures: 3,
    };
    const save = jest
      .fn<(schedule: Schedule, values: ScheduleValues) => Promise<void>>()
      .mockResolvedValue(undefined);
    render(
      <ScheduleEditor disabled={false} schedule={schedule} onSave={save} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Автоматически остановлено после 3 постоянных ошибок подряд",
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "Сохранить расписание" }),
    );
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(schedule, {
        cron_expression: schedule.cron_expression,
        timezone: "UTC",
        enabled: true,
      }),
    );
  });
});
