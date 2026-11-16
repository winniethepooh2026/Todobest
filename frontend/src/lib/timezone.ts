interface ZonedDateParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

const zonedPartsFormatters = new Map<string, Intl.DateTimeFormat>();

export function normalizeTimeZone(timeZone?: string | null): string {
  const candidates = [
    timeZone?.trim(),
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    "UTC",
  ];

  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: candidate }).format(0);
      return candidate;
    } catch {
      // Try the browser timezone and finally UTC when a stored profile value is invalid.
    }
  }

  return "UTC";
}

function zonedPartsFormatter(timeZone: string): Intl.DateTimeFormat {
  const safeTimeZone = normalizeTimeZone(timeZone);
  const cached = zonedPartsFormatters.get(safeTimeZone);
  if (cached) return cached;

  const formatter = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
    timeZone: safeTimeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  zonedPartsFormatters.set(safeTimeZone, formatter);
  return formatter;
}

function zonedParts(value: Date, timeZone: string): ZonedDateParts {
  const values: Partial<Record<Intl.DateTimeFormatPartTypes, number>> = {};
  for (const part of zonedPartsFormatter(timeZone).formatToParts(value)) {
    if (part.type !== "literal") values[part.type] = Number(part.value);
  }

  return {
    year: values.year ?? value.getUTCFullYear(),
    month: values.month ?? value.getUTCMonth() + 1,
    day: values.day ?? value.getUTCDate(),
    hour: values.hour ?? value.getUTCHours(),
    minute: values.minute ?? value.getUTCMinutes(),
    second: values.second ?? value.getUTCSeconds(),
  };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function calendarDayKey(day: Date): string {
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

function sameZonedMinute(
  value: Date,
  target: ZonedDateParts,
  timeZone: string,
): boolean {
  const actual = zonedParts(value, timeZone);
  return (
    actual.year === target.year &&
    actual.month === target.month &&
    actual.day === target.day &&
    actual.hour === target.hour &&
    actual.minute === target.minute
  );
}

/** A local Date used only as a calendar-day value, expressed in `timeZone`. */
export function calendarDateInTimeZone(value: Date, timeZone: string): Date {
  const parts = zonedParts(value, timeZone);
  return new Date(parts.year, parts.month - 1, parts.day, 12, 0, 0, 0);
}

export function toZonedDateTimeInput(
  value: Date | string | null,
  timeZone: string,
): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = zonedParts(date, timeZone);
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}

/** Converts a calendar day and wall-clock time in `timeZone` to a UTC instant. */
export function zonedDateTimeToDate(
  day: Date,
  hours: number,
  minutes: number,
  timeZone: string,
): Date {
  return zonedDateTimeInputToDate(
    `${calendarDayKey(day)}T${pad(hours)}:${pad(minutes)}`,
    timeZone,
  );
}

export function zonedDateTimeInputToDate(
  value: string,
  timeZone: string,
): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new RangeError("Invalid local date and time");

  const [, year, month, day, hours, minutes] = match.map(Number);
  const nominal = Date.UTC(year, month - 1, day, hours, minutes, 0, 0);
  const normalized = new Date(nominal);
  if (
    normalized.getUTCFullYear() !== year ||
    normalized.getUTCMonth() !== month - 1 ||
    normalized.getUTCDate() !== day ||
    normalized.getUTCHours() !== hours ||
    normalized.getUTCMinutes() !== minutes
  ) {
    throw new RangeError("Invalid local date and time");
  }

  const target = { year, month, day, hour: hours, minute: minutes, second: 0 };
  const offsets = new Set<number>();
  for (let sampleHours = -48; sampleHours <= 48; sampleHours += 6) {
    const sample = new Date(nominal + sampleHours * 60 * 60 * 1000);
    const parts = zonedParts(sample, timeZone);
    const wallTimestamp = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      0,
    );
    offsets.add(wallTimestamp - sample.getTime());
  }

  const candidates = [...offsets]
    .map((offset) => new Date(nominal - offset))
    .filter((candidate) => sameZonedMinute(candidate, target, timeZone))
    .sort((left, right) => left.getTime() - right.getTime());
  if (candidates.length === 0) {
    throw new RangeError(
      "This local time does not exist in the selected timezone",
    );
  }
  return candidates[0];
}

export function zonedDateTimeInputToISOString(
  value: string,
  timeZone: string,
): string {
  return zonedDateTimeInputToDate(value, timeZone).toISOString();
}

export function formatInTimeZone(
  value: Date,
  timeZone: string,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("ru-RU", {
    ...options,
    timeZone: normalizeTimeZone(timeZone),
  }).format(value);
}
