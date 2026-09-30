"use client";

import { useId, useRef } from "react";

interface ConfirmActionProps {
  className: string;
  confirmLabel: string;
  disabled?: boolean;
  label: string;
  onConfirm: () => void;
  description?: string;
}

export function ConfirmAction({
  className,
  confirmLabel,
  disabled = false,
  label,
  onConfirm,
  description = "Проверьте выбранное действие. Изменение будет отправлено только после подтверждения.",
}: ConfirmActionProps): React.JSX.Element {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const id = useId();

  function close(): void {
    dialog.current?.close();
    trigger.current?.focus();
  }

  return (
    <>
      <button
        ref={trigger}
        className={className}
        disabled={disabled}
        aria-haspopup="dialog"
        onClick={() => {
          dialog.current?.showModal();
          cancel.current?.focus();
        }}
        type="button"
      >
        {label}
      </button>
      <dialog
        ref={dialog}
        className="confirmation-dialog"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-description`}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const buttons =
            event.currentTarget.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            );
          const first = buttons[0];
          const last = buttons[buttons.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <p className="eyebrow">Подтверждение действия</p>
        <h2 id={`${id}-title`}>{label}</h2>
        <p id={`${id}-description`}>{description}</p>
        {disabled ? (
          <p role="status">
            Действие сейчас недоступно. Закройте окно и проверьте состояние.
          </p>
        ) : null}
        <div className="dialog-actions">
          <button
            ref={cancel}
            className="button secondary"
            onClick={close}
            type="button"
          >
            Отмена
          </button>
          <button
            className={className}
            disabled={disabled}
            onClick={() => {
              if (disabled || !dialog.current?.open) return;
              close();
              onConfirm();
            }}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </dialog>
    </>
  );
}
