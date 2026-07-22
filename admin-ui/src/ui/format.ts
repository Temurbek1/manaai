export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) {
    return "—";
  }
  if (milliseconds < 1_000) {
    return `${String(milliseconds)} ms`;
  }
  return `${(milliseconds / 1_000).toFixed(1)} s`;
}

export function compactId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function displayValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "unavailable";
}

const SECRET_KEY = /(?:authorization|api[_-]?key|access[_-]?token|client[_-]?secret|password)/i;
const SECRET_VALUE = /\b(?:Bearer\s+|EAA)[A-Za-z0-9._~-]{8,}/gi;

export function redactForDisplay(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(redactForDisplay);
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SECRET_KEY.test(key) ? "[REDACTED]" : redactForDisplay(item),
      ]),
    );
  }
  if (typeof value === "string") {
    return value.replaceAll(SECRET_VALUE, "[REDACTED]");
  }
  return value;
}
