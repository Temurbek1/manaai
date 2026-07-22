"use client";

import { useState } from "react";

interface ConfirmActionProps {
  className: string;
  confirmLabel: string;
  disabled?: boolean;
  label: string;
  onConfirm: () => void;
}

export function ConfirmAction({
  className,
  confirmLabel,
  disabled = false,
  label,
  onConfirm,
}: ConfirmActionProps): React.JSX.Element {
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <button
        className={className}
        disabled={disabled}
        onClick={() => setConfirming(true)}
        type="button"
      >
        {label}
      </button>
    );
  }

  return (
    <span
      aria-label={`Confirm ${label}`}
      className="confirm-action"
      role="group"
    >
      <button
        className="button secondary compact"
        onClick={() => setConfirming(false)}
        type="button"
      >
        Cancel
      </button>
      <button
        className={className}
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
        type="button"
      >
        {confirmLabel}
      </button>
    </span>
  );
}
