// Shared number/date formatters — one source of truth so admin views (and
// anything else) don't each reinvent ru-RU formatting slightly differently.

export function formatCount(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

export function formatPct(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatDateTime(value: string | null): string {
  return value
    ? new Date(value).toLocaleString("ru-RU", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
}
