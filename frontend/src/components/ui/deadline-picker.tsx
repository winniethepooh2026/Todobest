"use client";

import {
  addDays,
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { ru } from "date-fns/locale";
import {
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
} from "lucide-react";
import {
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { calendarDateInTimeZone, toZonedDateTimeInput } from "@/lib/timezone";
import { cn } from "@/lib/utils";

const DEFAULT_TIME = "18:00";
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const POPOVER_GAP = 6;
const POPOVER_MARGIN = 8;

function DeadlinePickerPortal({
  container,
  children,
}: {
  container: HTMLElement | null;
  children: ReactNode;
}) {
  return container ? createPortal(children, container) : children;
}

function getPortalPosition(
  trigger: HTMLButtonElement,
  calendar: HTMLDivElement,
  align: "left" | "right",
  container: HTMLElement,
) {
  const triggerRect = trigger.getBoundingClientRect();
  const calendarRect = calendar.getBoundingClientRect();
  const width = Math.min(304, window.innerWidth - POPOVER_MARGIN * 2);
  const fitsBelow =
    triggerRect.bottom + POPOVER_GAP + calendarRect.height <=
    window.innerHeight - POPOVER_MARGIN;
  const top = fitsBelow
    ? triggerRect.bottom + POPOVER_GAP
    : Math.max(
        POPOVER_MARGIN,
        triggerRect.top - POPOVER_GAP - calendarRect.height,
      );
  const preferredLeft =
    align === "right" ? triggerRect.right - width : triggerRect.left;
  const left = Math.max(
    POPOVER_MARGIN,
    Math.min(preferredLeft, window.innerWidth - POPOVER_MARGIN - width),
  );

  if (container === document.body) return { top, left, width };

  const containerRect = container.getBoundingClientRect();
  return {
    top: top - containerRect.top + container.scrollTop,
    left: left - containerRect.left + container.scrollLeft,
    width,
  };
}

function parseLocalDateTime(value: string): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const [, year, month, day] = match.map(Number);
  const date = new Date(year, month - 1, day, 12, 0, 0, 0);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }
  return date;
}

function timeParts(value: string): [number, number] {
  const [rawHours, rawMinutes] = value.split(":").map(Number);
  const hours =
    Number.isInteger(rawHours) && rawHours >= 0 && rawHours <= 23
      ? rawHours
      : 18;
  const minutes =
    Number.isInteger(rawMinutes) && rawMinutes >= 0 && rawMinutes <= 59
      ? rawMinutes
      : 0;

  return [hours, minutes];
}

function padTime(value: number): string {
  return String(value).padStart(2, "0");
}

function weekendFrom(date: Date): Date {
  const weekday = date.getDay();
  if (weekday === 0 || weekday === 6) return date;
  return addDays(date, 6 - weekday);
}

export function toLocalDateTimeInput(
  value: Date | string | null,
  timeZone?: string,
): string {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  if (timeZone) return toZonedDateTimeInput(date, timeZone);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function DeadlinePicker({
  id,
  value,
  onChange,
  disabled = false,
  className,
  placeholder = "Без дедлайна",
  align = "left",
  defaultTime = DEFAULT_TIME,
  portal = false,
  timeZone,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
  align?: "left" | "right";
  defaultTime?: string;
  portal?: boolean;
  timeZone?: string;
}) {
  const generatedId = useId();
  const triggerId = id ?? `${generatedId}-trigger`;
  const calendarId = `${generatedId}-calendar`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const calendarRef = useRef<HTMLDivElement>(null);
  const [flipUp, setFlipUp] = useState(false);
  const selectedDate = useMemo(() => parseLocalDateTime(value), [value]);
  const effectiveTimeZone =
    timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC";
  const today = calendarDateInTimeZone(new Date(), effectiveTimeZone);
  const [open, setOpen] = useState(false);
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  const [portalPosition, setPortalPosition] = useState({
    top: 0,
    left: 0,
    width: 304,
  });
  const [visibleMonth, setVisibleMonth] = useState(() =>
    startOfMonth(selectedDate ?? today),
  );
  const quickOptions = useMemo(() => {
    return [
      { label: "Сегодня", date: today },
      { label: "Завтра", date: addDays(today, 1) },
      { label: "Выходные", date: weekendFrom(today) },
      {
        label: "След. неделя",
        date: addWeeks(startOfWeek(today, { weekStartsOn: 1 }), 1),
      },
    ];
  }, [today]);
  const days = useMemo(
    () =>
      eachDayOfInterval({
        start: startOfWeek(startOfMonth(visibleMonth), { weekStartsOn: 1 }),
        end: endOfWeek(endOfMonth(visibleMonth), { weekStartsOn: 1 }),
      }),
    [visibleMonth],
  );
  const selectedTime = selectedDate ? value.slice(11, 16) : defaultTime;

  function close({ restoreFocus = false } = {}) {
    setOpen(false);
    setFlipUp(false);
    setPortalTarget(null);
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus());
  }

  function openPicker() {
    setFlipUp(false);
    setVisibleMonth(startOfMonth(selectedDate ?? today));
    if (portal && typeof document !== "undefined") {
      setPortalTarget(
        (rootRef.current?.closest('[role="dialog"]') as HTMLElement | null) ??
          document.body,
      );
    }
    setOpen(true);
  }

  function chooseDate(day: Date) {
    const nextTime = selectedDate ? selectedTime : defaultTime;
    onChange(`${format(day, "yyyy-MM-dd")}T${nextTime}`);
    setVisibleMonth(startOfMonth(day));
  }

  function changeTime(nextTime: string) {
    if (!selectedDate) return;
    const [hours, minutes] = timeParts(nextTime);
    onChange(
      `${format(selectedDate, "yyyy-MM-dd")}T${padTime(hours)}:${padTime(minutes)}`,
    );
  }

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !rootRef.current?.contains(target) &&
        !calendarRef.current?.contains(target)
      ) {
        close();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close({ restoreFocus: true });
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      calendarRef.current
        ?.querySelector<HTMLButtonElement>("button:not(:disabled)")
        ?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, portalTarget]);

  useLayoutEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const calendar = calendarRef.current;
    if (!trigger || !calendar) return;

    if (portal && portalTarget) {
      setPortalPosition(
        getPortalPosition(trigger, calendar, align, portalTarget),
      );
      return;
    }

    const triggerRect = trigger.getBoundingClientRect();
    const calendarRect = calendar.getBoundingClientRect();
    const viewportHeight = window.innerHeight;

    if (
      calendarRect.bottom > viewportHeight &&
      triggerRect.top > calendarRect.height + 6
    ) {
      setFlipUp(true);
    } else {
      setFlipUp(false);
    }
  }, [align, open, portal, portalTarget, visibleMonth]);

  useEffect(() => {
    if (!open) return;
    const handleResize = () => {
      const trigger = triggerRef.current;
      const calendar = calendarRef.current;
      if (!trigger || !calendar) return;

      if (portal && portalTarget) {
        setPortalPosition(
          getPortalPosition(trigger, calendar, align, portalTarget),
        );
        return;
      }

      const triggerRect = trigger.getBoundingClientRect();
      const calendarRect = calendar.getBoundingClientRect();
      const viewportHeight = window.innerHeight;

      if (
        calendarRect.bottom > viewportHeight &&
        triggerRect.top > calendarRect.height + 6
      ) {
        setFlipUp(true);
      } else {
        setFlipUp(false);
      }
    };

    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleResize, true);
    return () => {
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleResize, true);
    };
  }, [align, open, portal, portalTarget]);

  const portalInBody =
    portal &&
    portalTarget !== null &&
    typeof document !== "undefined" &&
    portalTarget === document.body;

  return (
    <div
      ref={rootRef}
      className={cn("relative", className)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          close({ restoreFocus: true });
        }
      }}
    >
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={calendarId}
        disabled={disabled}
        onClick={() => (open ? close() : openPicker())}
        className={cn(
          "flex h-9 w-full items-center gap-2 rounded-lg border bg-background px-2.5 text-left text-sm outline-none transition hover:border-neutral-300 focus-visible:ring-2 focus-visible:ring-neutral-200 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:border-neutral-700 dark:focus-visible:ring-neutral-700",
          !selectedDate && "text-muted-foreground",
        )}
      >
        <CalendarDays className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate">
          {selectedDate
            ? `${format(selectedDate, "d MMM", { locale: ru })}, ${selectedTime}`
            : placeholder}
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        <DeadlinePickerPortal container={portal ? portalTarget : null}>
          <div
            ref={calendarRef}
            id={calendarId}
            role="dialog"
            aria-labelledby={triggerId}
            style={portal ? portalPosition : undefined}
            className={cn(
              "z-[70] max-h-[calc(100dvh-1rem)] w-[min(19rem,calc(100vw-1rem))] overflow-x-hidden overflow-y-auto rounded-xl border bg-card p-2 shadow-xl",
              portal
                ? portalInBody
                  ? "fixed pointer-events-auto"
                  : "absolute pointer-events-auto"
                : flipUp
                  ? "absolute bottom-[calc(100%+0.375rem)]"
                  : "absolute top-[calc(100%+0.375rem)]",
              !portal && (align === "right" ? "right-0" : "left-0"),
            )}
          >
            <div className="grid grid-cols-2 gap-1">
              {quickOptions.map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => chooseDate(option.date)}
                  className="flex items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 dark:focus-visible:ring-neutral-700"
                >
                  <span className="font-medium">{option.label}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {format(option.date, "d MMM", { locale: ru })}
                  </span>
                </button>
              ))}
            </div>

            <div className="mt-2 border-t pt-2">
              <div className="mb-2 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() =>
                    setVisibleMonth((month) => addMonths(month, -1))
                  }
                  className="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 dark:focus-visible:ring-neutral-700"
                  aria-label="Предыдущий месяц"
                >
                  <ChevronLeft className="size-4" />
                </button>
                <div className="text-sm font-medium">
                  {format(visibleMonth, "LLLL yyyy", { locale: ru })}
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setVisibleMonth((month) => addMonths(month, 1))
                  }
                  className="rounded-md p-1.5 text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 dark:focus-visible:ring-neutral-700"
                  aria-label="Следующий месяц"
                >
                  <ChevronRight className="size-4" />
                </button>
              </div>

              <div className="grid grid-cols-7 gap-1 text-center">
                {WEEKDAYS.map((weekday) => (
                  <div
                    key={weekday}
                    className="py-1 text-[10px] font-medium uppercase text-muted-foreground"
                  >
                    {weekday}
                  </div>
                ))}
                {days.map((day) => {
                  const selected =
                    selectedDate !== null && isSameDay(day, selectedDate);
                  return (
                    <button
                      key={day.toISOString()}
                      type="button"
                      onClick={() => chooseDate(day)}
                      className={cn(
                        "flex size-9 items-center justify-center rounded-lg text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 dark:focus-visible:ring-neutral-700",
                        selected
                          ? "bg-neutral-900 font-medium text-white dark:bg-neutral-100 dark:text-neutral-950"
                          : "hover:bg-accent",
                        !selected &&
                          isSameDay(day, today) &&
                          "border border-neutral-300 font-medium dark:border-neutral-700",
                        !isSameMonth(day, visibleMonth) &&
                          !selected &&
                          "text-neutral-300 dark:text-neutral-600",
                      )}
                    >
                      {format(day, "d")}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="mt-2 flex items-center gap-2 border-t pt-2">
              <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border bg-background px-2.5 py-1.5 text-xs text-muted-foreground">
                <Clock3 className="size-3.5" />
                <span>Время</span>
                <input
                  type="time"
                  value={selectedTime}
                  disabled={!selectedDate}
                  onChange={(event) => changeTime(event.target.value)}
                  className="ml-auto w-20 bg-transparent text-right text-xs text-foreground outline-none disabled:text-muted-foreground"
                />
              </label>
              <button
                type="button"
                onClick={() => {
                  onChange("");
                  close({ restoreFocus: true });
                }}
                className="rounded-lg px-2.5 py-2 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 dark:focus-visible:ring-neutral-700"
              >
                Без даты
              </button>
              <button
                type="button"
                onClick={() => close({ restoreFocus: true })}
                className="rounded-lg bg-neutral-900 px-2.5 py-2 text-xs font-medium text-white transition hover:bg-neutral-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-300 dark:bg-neutral-100 dark:text-neutral-950 dark:hover:bg-neutral-200"
              >
                Готово
              </button>
            </div>
          </div>
        </DeadlinePickerPortal>
      ) : null}
    </div>
  );
}
