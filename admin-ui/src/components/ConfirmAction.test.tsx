import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ConfirmAction } from "./ConfirmAction";

describe("ConfirmAction", () => {
  const props = {
    className: "button",
    label: "Запустить анализ",
    confirmLabel: "Подтвердить сбор данных",
    description: "Будут использованы внешние источники и квоты.",
  };

  it("focuses the safe choice and restores focus without executing on cancel", () => {
    const onConfirm = jest.fn();
    render(<ConfirmAction {...props} onConfirm={onConfirm} />);
    const trigger = screen.getByRole("button", { name: props.label });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: props.label });
    expect(dialog).toHaveAccessibleDescription(props.description);
    expect(
      within(dialog).getByRole("button", { name: "Отмена" }),
    ).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(
      within(dialog).getByRole("button", { name: props.confirmLabel }),
    ).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(
      within(dialog).getByRole("button", { name: "Отмена" }),
    ).toHaveFocus();
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("sends a single confirmation and prevents acting after permission changes", () => {
    const onConfirm = jest.fn();
    const rendered = render(<ConfirmAction {...props} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: props.label }));
    rendered.rerender(
      <ConfirmAction {...props} disabled onConfirm={onConfirm} />,
    );
    const confirm = screen.getByRole("button", { name: props.confirmLabel });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    rendered.rerender(<ConfirmAction {...props} onConfirm={onConfirm} />);
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
