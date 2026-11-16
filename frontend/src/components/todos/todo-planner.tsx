"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addDays,
  addWeeks,
  eachDayOfInterval,
  format,
  isBefore,
  isSameDay,
  parseISO,
  startOfDay,
  startOfWeek,
} from "date-fns";
import { ru } from "date-fns/locale";
import {
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Pencil,
  Plus,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { TodoDialog } from "@/components/todos/todo-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import {
  calendarDateInTimeZone,
  formatInTimeZone,
  normalizeTimeZone,
  zonedDateTimeToDate,
} from "@/lib/timezone";
import type { Todo, TodoStatus, User } from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

const VISIBLE_DAY_COUNT = 10;

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function dayKey(value: Date): string {
  return format(value, "yyyy-MM-dd");
}

function weekStart(value: Date): Date {
  return startOfWeek(value, { weekStartsOn: 1 });
}

function deadlineForDay(day: Date, timeZone: string): string {
  return zonedDateTimeToDate(day, 18, 0, timeZone).toISOString();
}

function compareTodos(left: Todo, right: Todo): number {
  if (left.deadline && right.deadline) {
    const deadlineDifference =
      parseISO(left.deadline).getTime() - parseISO(right.deadline).getTime();
    if (deadlineDifference !== 0) return deadlineDifference;
  } else if (left.deadline) {
    return -1;
  } else if (right.deadline) {
    return 1;
  }

  if (left.position !== right.position) return left.position - right.position;
  return (
    parseISO(left.created_at).getTime() - parseISO(right.created_at).getTime()
  );
}

function relativeDayLabel(day: Date, today: Date): string | null {
  if (isSameDay(day, today)) return "Сегодня";
  if (isSameDay(day, addDays(today, 1))) return "Завтра";
  if (isSameDay(day, addDays(today, -1))) return "Вчера";
  return null;
}

function sectionTitle(day: Date, today: Date): string {
  const relative = relativeDayLabel(day, today);
  return [
    format(day, "d MMMM", { locale: ru }),
    relative,
    capitalize(format(day, "EEEE", { locale: ru })),
  ]
    .filter(Boolean)
    .join(" · ");
}

function TodoCheck({
  todo,
  pending,
  onToggle,
}: {
  todo: Todo;
  pending: boolean;
  onToggle: (todo: Todo) => void;
}) {
  const completed = todo.status === "done";

  return (
    <button
      type="button"
      onClick={() => onToggle(todo)}
      disabled={pending}
      aria-label={
        completed
          ? `Вернуть задачу «${todo.title}»`
          : `Завершить задачу «${todo.title}»`
      }
      aria-pressed={completed}
      className={cn(
        "relative mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full border outline-none transition-colors after:absolute after:-inset-2 after:content-[''] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        completed
          ? "border-neutral-900 bg-neutral-900 text-white dark:border-neutral-100 dark:bg-neutral-100 dark:text-neutral-950"
          : "border-neutral-400 bg-background text-transparent hover:border-neutral-900 hover:bg-neutral-100 dark:border-neutral-600 dark:hover:border-neutral-200 dark:hover:bg-neutral-800",
        pending && "cursor-wait opacity-60",
      )}
    >
      {pending ? (
        <Loader2 className="size-3 animate-spin text-neutral-600 dark:text-neutral-300" />
      ) : (
        <Check className="size-3.5" strokeWidth={2.5} />
      )}
    </button>
  );
}

function TodoRow({
  todo,
  timeZone,
  showDate = false,
  pending,
  onToggle,
  onEdit,
}: {
  todo: Todo;
  timeZone: string;
  showDate?: boolean;
  pending: boolean;
  onToggle: (todo: Todo) => void;
  onEdit: (todo: Todo) => void;
}) {
  const deadline = todo.deadline ? parseISO(todo.deadline) : null;
  const overdue =
    deadline !== null &&
    isBefore(deadline, new Date()) &&
    todo.status !== "done";

  return (
    <article className="group relative flex items-start gap-3 py-3.5 after:absolute after:bottom-0 after:left-[34px] after:right-0 after:h-px after:bg-border/80 last:after:hidden">
      <TodoCheck todo={todo} pending={pending} onToggle={onToggle} />

      <button
        type="button"
        onClick={() => onEdit(todo)}
        className="min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <div className="flex min-w-0 items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3
              className={cn(
                "break-words text-sm font-medium leading-5 text-foreground",
                todo.status === "done" &&
                  "text-muted-foreground line-through decoration-neutral-400",
              )}
            >
              {todo.title}
            </h3>
          </div>
          <span className="mt-0.5 rounded-md p-1 text-neutral-300 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100 dark:text-neutral-600">
            <Pencil className="size-3.5" />
          </span>
        </div>

        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          {deadline ? (
            <span
              className={cn(
                "inline-flex items-center gap-1",
                overdue && "text-red-600 dark:text-red-400",
              )}
            >
              <CalendarDays className="size-3" />
              {showDate
                ? formatInTimeZone(deadline, timeZone, {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                    hourCycle: "h23",
                  })
                : formatInTimeZone(deadline, timeZone, {
                    hour: "2-digit",
                    minute: "2-digit",
                    hourCycle: "h23",
                  })}
            </span>
          ) : (
            <span>Без даты</span>
          )}
          {todo.status === "in_progress" ? (
            <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
              В работе
            </span>
          ) : null}
          <span className="ml-auto hidden truncate min-[360px]:inline">
            Личное
          </span>
        </div>
      </button>
    </article>
  );
}

function AddTodoButton({
  onClick,
  label = "Добавить задачу",
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group/add flex items-center gap-2 rounded-md py-2 pr-3 text-xs font-medium text-muted-foreground outline-none transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex size-[22px] items-center justify-center rounded-full text-neutral-400 transition group-hover/add:bg-neutral-900 group-hover/add:text-white dark:group-hover/add:bg-neutral-100 dark:group-hover/add:text-neutral-950">
        <Plus className="size-4" />
      </span>
      {label}
    </button>
  );
}

function TodoSection({
  day,
  today,
  todos,
  timeZone,
  pendingTodoIds,
  onCreate,
  onToggle,
  onEdit,
}: {
  day: Date;
  today: Date;
  todos: Todo[];
  timeZone: string;
  pendingTodoIds: Set<string>;
  onCreate: () => void;
  onToggle: (todo: Todo) => void;
  onEdit: (todo: Todo) => void;
}) {
  return (
    <section
      id={`todo-day-${dayKey(day)}`}
      className="group/day min-h-16 scroll-mt-32 border-b border-border/70 py-4 last:border-b-0 sm:min-h-24 sm:py-5"
    >
      <h2
        className={cn(
          "text-[15px] font-semibold tracking-[-0.01em] text-muted-foreground",
          isSameDay(day, today) && "text-foreground",
        )}
      >
        {sectionTitle(day, today)}
      </h2>

      {todos.length > 0 ? (
        <div className="mt-2">
          {todos.map((todo) => (
            <TodoRow
              key={todo.id}
              todo={todo}
              timeZone={timeZone}
              pending={pendingTodoIds.has(todo.id)}
              onToggle={onToggle}
              onEdit={onEdit}
            />
          ))}
        </div>
      ) : null}

      <div
        className={cn(
          "mt-1 hidden transition-opacity sm:block sm:opacity-0 sm:group-hover/day:opacity-100 sm:group-focus-within/day:opacity-100",
          todos.length > 0 && "sm:opacity-100",
        )}
      >
        <AddTodoButton onClick={onCreate} />
      </div>
    </section>
  );
}

function GroupedTodos({
  title,
  description,
  todos,
  timeZone,
  pendingTodoIds,
  showDates = true,
  onCreate,
  onToggle,
  onEdit,
}: {
  title: string;
  description?: string;
  todos: Todo[];
  timeZone: string;
  pendingTodoIds: Set<string>;
  showDates?: boolean;
  onCreate?: () => void;
  onToggle: (todo: Todo) => void;
  onEdit: (todo: Todo) => void;
}) {
  if (todos.length === 0 && !onCreate) return null;

  return (
    <section className="border-b border-border/70 py-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
            {title}
            {todos.length > 0 ? (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {todos.length}
              </span>
            ) : null}
          </h2>
          {description ? (
            <p className="mt-1 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </div>

      {todos.length > 0 ? (
        <div className="mt-2">
          {todos.map((todo) => (
            <TodoRow
              key={todo.id}
              todo={todo}
              timeZone={timeZone}
              showDate={showDates}
              pending={pendingTodoIds.has(todo.id)}
              onToggle={onToggle}
              onEdit={onEdit}
            />
          ))}
        </div>
      ) : null}

      {onCreate ? (
        <div className="mt-1">
          <AddTodoButton onClick={onCreate} />
        </div>
      ) : null}
    </section>
  );
}

function CalendarStrip({
  visibleWeek,
  selectedDay,
  today,
  todos,
  timeZone,
  onPreviousWeek,
  onNextWeek,
  onToday,
  onSelectDay,
}: {
  visibleWeek: Date;
  selectedDay: Date;
  today: Date;
  todos: Todo[];
  timeZone: string;
  onPreviousWeek: () => void;
  onNextWeek: () => void;
  onToday: () => void;
  onSelectDay: (day: Date) => void;
}) {
  const weekDays = eachDayOfInterval({
    start: visibleWeek,
    end: addDays(visibleWeek, 6),
  });
  const activeTodos = todos.filter(
    (todo) => todo.status !== "done" && todo.deadline !== null,
  );

  return (
    <div className="sticky top-0 z-20 -mx-1 border-b bg-background/95 px-1 pb-3 pt-3 backdrop-blur supports-[backdrop-filter]:bg-background/85 sm:pt-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <CalendarDays className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm font-semibold">
            {capitalize(format(selectedDay, "LLLL yyyy", { locale: ru }))}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onPreviousWeek}
            aria-label="Предыдущая неделя"
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="px-2.5"
            onClick={onToday}
          >
            Сегодня
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onNextWeek}
            aria-label="Следующая неделя"
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-7 gap-1 sm:gap-2">
        {weekDays.map((day) => {
          const selected = isSameDay(day, selectedDay);
          const taskCount = activeTodos.filter((todo) =>
            isSameDay(
              calendarDateInTimeZone(
                parseISO(todo.deadline as string),
                timeZone,
              ),
              day,
            ),
          ).length;

          return (
            <button
              key={dayKey(day)}
              type="button"
              onClick={() => onSelectDay(day)}
              aria-label={`${sectionTitle(day, today)}${taskCount ? `, задач: ${taskCount}` : ""}`}
              aria-pressed={selected}
              className="group/date flex min-w-0 flex-col items-center rounded-xl py-1 text-center outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500",
                  selected && "text-foreground",
                )}
              >
                {format(day, "EEEEEE", { locale: ru })}
              </span>
              <span
                className={cn(
                  "mt-1 flex size-9 items-center justify-center rounded-full text-sm font-medium transition-colors group-hover/date:bg-neutral-100 dark:group-hover/date:bg-neutral-800",
                  selected &&
                    "bg-neutral-900 text-white group-hover/date:bg-neutral-800 dark:bg-neutral-100 dark:text-neutral-950 dark:group-hover/date:bg-neutral-200",
                  !selected &&
                    isSameDay(day, today) &&
                    "border border-neutral-300 dark:border-neutral-700",
                )}
              >
                {format(day, "d")}
              </span>
              <span
                className={cn(
                  "mt-1 h-1 w-1 rounded-full",
                  taskCount > 0
                    ? selected
                      ? "bg-neutral-900 dark:bg-neutral-100"
                      : "bg-neutral-400 dark:bg-neutral-500"
                    : "bg-transparent",
                )}
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PlannerSkeleton() {
  return (
    <div className="py-6">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="border-b py-6 last:border-b-0">
          <Skeleton className="h-5 w-44" />
          {index < 2 ? (
            <div className="mt-4 flex items-start gap-3">
              <Skeleton className="size-[22px] rounded-full" />
              <div className="flex-1">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="mt-2 h-3 w-1/3" />
              </div>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function TodoPlanner() {
  const queryClient = useQueryClient();
  const todosQuery = useQuery({
    queryKey: ["my-todos"],
    queryFn: () => api.get<Todo[]>("/todos"),
  });
  const userQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });

  const user = userQuery.data;
  const initialDay = useMemo(() => startOfDay(new Date()), []);
  const [selectedDay, setSelectedDay] = useState(initialDay);
  const [visibleWeek, setVisibleWeek] = useState(() => weekStart(initialDay));
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedTodo, setSelectedTodo] = useState<Todo | null>(null);
  const [defaultDeadline, setDefaultDeadline] = useState<string | null>(null);
  const [pendingTodoIds, setPendingTodoIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [completedOpen, setCompletedOpen] = useState(false);
  const [currentInstant, setCurrentInstant] = useState(() => new Date());
  const previousStatusRef = useRef(new Map<string, TodoStatus>());
  const pendingTodoIdsRef = useRef(new Set<string>());
  const scrollAfterSelectionRef = useRef(false);
  const initialTimeZoneAppliedRef = useRef(false);
  const timeZone = useMemo(
    () => (user ? normalizeTimeZone(user.timezone) : null),
    [user],
  );
  const displayTimeZone = timeZone ?? "UTC";
  const today = useMemo(
    () =>
      timeZone
        ? calendarDateInTimeZone(currentInstant, timeZone)
        : startOfDay(currentInstant),
    [currentInstant, timeZone],
  );

  const todos = useMemo(() => todosQuery.data ?? [], [todosQuery.data]);
  const rangeDays = useMemo(
    () =>
      eachDayOfInterval({
        start: selectedDay,
        end: addDays(selectedDay, VISIBLE_DAY_COUNT - 1),
      }),
    [selectedDay],
  );
  const rangeEnd = rangeDays[rangeDays.length - 1];

  const groupedTodos = useMemo(() => {
    const byDay = new Map<string, Todo[]>();
    for (const day of rangeDays) byDay.set(dayKey(day), []);

    const earlier: Todo[] = [];
    const later: Todo[] = [];
    const unscheduled: Todo[] = [];
    const completed: Todo[] = [];
    const firstDay = startOfDay(selectedDay);
    const lastDay = startOfDay(rangeEnd);

    for (const todo of todos) {
      if (todo.status === "done") {
        completed.push(todo);
        continue;
      }
      if (!todo.deadline) {
        unscheduled.push(todo);
        continue;
      }

      const deadline = parseISO(todo.deadline);
      const deadlineDay = startOfDay(
        calendarDateInTimeZone(deadline, displayTimeZone),
      );
      if (isBefore(deadlineDay, firstDay)) {
        earlier.push(todo);
      } else if (isBefore(lastDay, deadlineDay)) {
        later.push(todo);
      } else {
        byDay.get(dayKey(deadlineDay))?.push(todo);
      }
    }

    for (const group of byDay.values()) group.sort(compareTodos);
    earlier.sort(compareTodos);
    later.sort(compareTodos);
    unscheduled.sort(compareTodos);
    completed.sort((left, right) =>
      right.updated_at.localeCompare(left.updated_at),
    );

    return { byDay, earlier, later, unscheduled, completed };
  }, [displayTimeZone, rangeDays, rangeEnd, selectedDay, todos]);

  useEffect(() => {
    const refreshCurrentInstant = () => setCurrentInstant(new Date());
    const handleVisibilityChange = () => {
      if (!document.hidden) refreshCurrentInstant();
    };
    const interval = window.setInterval(refreshCurrentInstant, 60_000);
    window.addEventListener("focus", refreshCurrentInstant);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshCurrentInstant);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!timeZone || initialTimeZoneAppliedRef.current) return;
    initialTimeZoneAppliedRef.current = true;
    const zonedToday = calendarDateInTimeZone(new Date(), timeZone);
    setSelectedDay(zonedToday);
    setVisibleWeek(weekStart(zonedToday));
  }, [timeZone]);

  useEffect(() => {
    if (!scrollAfterSelectionRef.current) return;
    scrollAfterSelectionRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      document
        .getElementById(`todo-day-${dayKey(selectedDay)}`)
        ?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selectedDay]);

  function openCreate(day: Date | null = selectedDay) {
    if (!timeZone) return;
    setSelectedTodo(null);
    setDefaultDeadline(day ? deadlineForDay(day, timeZone) : null);
    setDialogOpen(true);
  }

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        event.key.toLowerCase() !== "n" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      )
        return;
      if (target?.closest("input, textarea, select, [contenteditable=true]"))
        return;
      event.preventDefault();
      openCreate();
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  });

  function openEdit(todo: Todo) {
    setSelectedTodo(todo);
    setDefaultDeadline(null);
    setDialogOpen(true);
  }

  function selectDay(day: Date) {
    const normalized = startOfDay(day);
    scrollAfterSelectionRef.current = true;
    setSelectedDay(normalized);
    setVisibleWeek(weekStart(normalized));
  }

  function moveWeek(amount: number) {
    const nextSelected = addWeeks(selectedDay, amount);
    scrollAfterSelectionRef.current = true;
    setSelectedDay(nextSelected);
    setVisibleWeek(weekStart(nextSelected));
  }

  function selectToday() {
    const currentDay = timeZone
      ? calendarDateInTimeZone(new Date(), timeZone)
      : startOfDay(new Date());
    setCurrentInstant(new Date());
    scrollAfterSelectionRef.current = true;
    setSelectedDay(currentDay);
    setVisibleWeek(weekStart(currentDay));
  }

  async function refreshTodos() {
    await queryClient.invalidateQueries({ queryKey: ["my-todos"] });
  }

  async function toggleTodo(todo: Todo) {
    if (pendingTodoIdsRef.current.has(todo.id)) return;
    pendingTodoIdsRef.current.add(todo.id);
    setPendingTodoIds(new Set(pendingTodoIdsRef.current));

    await queryClient.cancelQueries({ queryKey: ["my-todos"] });

    const nextStatus: TodoStatus =
      todo.status === "done"
        ? (previousStatusRef.current.get(todo.id) ?? "todo")
        : "done";
    if (todo.status !== "done") {
      previousStatusRef.current.set(todo.id, todo.status);
    }

    queryClient.setQueryData<Todo[]>(["my-todos"], (current = []) =>
      current.map((item) =>
        item.id === todo.id ? { ...item, status: nextStatus } : item,
      ),
    );

    try {
      const updated = await api.patch<Todo>(`/todos/${todo.id}`, {
        status: nextStatus,
      });
      queryClient.setQueryData<Todo[]>(["my-todos"], (current = []) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (error) {
      queryClient.setQueryData<Todo[]>(["my-todos"], (current = []) =>
        current.map((item) => (item.id === todo.id ? todo : item)),
      );
      toast.error(formatError(error));
    } finally {
      try {
        await queryClient.invalidateQueries({ queryKey: ["my-todos"] });
      } finally {
        pendingTodoIdsRef.current.delete(todo.id);
        setPendingTodoIds(new Set(pendingTodoIdsRef.current));
      }
    }
  }

  const loading = todosQuery.isLoading || userQuery.isLoading;
  const error = todosQuery.error ?? userQuery.error;

  return (
    <div className="mx-auto min-h-full w-full max-w-[880px] px-4 pb-[calc(7rem+env(safe-area-inset-bottom))] pt-4 sm:px-8 sm:pb-16 sm:pt-9 lg:px-10">
      <header className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="md:hidden">
            <MobileMenuButton />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground sm:text-sm">
              Personal · только для вас
            </p>
            <h1 className="mt-0.5 truncate text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">
              My todos
            </h1>
          </div>
        </div>
        <Button
          className="hidden sm:inline-flex"
          onClick={() => openCreate()}
          disabled={!timeZone}
        >
          <Plus className="size-4" />
          Новая задача
          <kbd className="ml-1 rounded border px-1 text-[10px]">N</kbd>
        </Button>
      </header>

      <div className="mt-5 sm:mt-7">
        <CalendarStrip
          visibleWeek={visibleWeek}
          selectedDay={selectedDay}
          today={today}
          todos={todos}
          timeZone={displayTimeZone}
          onPreviousWeek={() => moveWeek(-1)}
          onNextWeek={() => moveWeek(1)}
          onToday={selectToday}
          onSelectDay={selectDay}
        />

        {loading ? <PlannerSkeleton /> : null}

        {!loading && (todosQuery.isError || userQuery.isError || !user) ? (
          <div className="py-16 text-center">
            <CheckCircle2 className="mx-auto size-8 text-neutral-300 dark:text-neutral-600" />
            <h2 className="mt-4 font-medium">Не удалось загрузить My todos</h2>
            <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
              {formatError(error)}
            </p>
            <Button
              className="mt-5"
              variant="outline"
              onClick={() => {
                void todosQuery.refetch();
                void userQuery.refetch();
              }}
            >
              Повторить
            </Button>
          </div>
        ) : null}

        {!loading && user && !todosQuery.isError && !userQuery.isError ? (
          <>
            <GroupedTodos
              title={isSameDay(selectedDay, today) ? "Просрочено" : "Ранее"}
              description={
                isSameDay(selectedDay, today)
                  ? "Незавершённые задачи с прошедшей датой"
                  : "Незавершённые задачи до выбранной даты"
              }
              todos={groupedTodos.earlier}
              timeZone={displayTimeZone}
              pendingTodoIds={pendingTodoIds}
              onToggle={toggleTodo}
              onEdit={openEdit}
            />

            {rangeDays.map((day) => (
              <TodoSection
                key={dayKey(day)}
                day={day}
                today={today}
                todos={groupedTodos.byDay.get(dayKey(day)) ?? []}
                timeZone={displayTimeZone}
                pendingTodoIds={pendingTodoIds}
                onCreate={() => openCreate(day)}
                onToggle={toggleTodo}
                onEdit={openEdit}
              />
            ))}

            <GroupedTodos
              title="Позже"
              description={`После ${format(rangeEnd, "d MMMM", { locale: ru })}`}
              todos={groupedTodos.later}
              timeZone={displayTimeZone}
              pendingTodoIds={pendingTodoIds}
              onToggle={toggleTodo}
              onEdit={openEdit}
            />

            <GroupedTodos
              title="Без даты"
              description="Задачи, которые ещё не запланированы"
              todos={groupedTodos.unscheduled}
              timeZone={displayTimeZone}
              pendingTodoIds={pendingTodoIds}
              showDates={false}
              onCreate={() => openCreate(null)}
              onToggle={toggleTodo}
              onEdit={openEdit}
            />

            {groupedTodos.completed.length > 0 ? (
              <section className="py-6">
                <button
                  type="button"
                  onClick={() => setCompletedOpen((open) => !open)}
                  aria-expanded={completedOpen}
                  className="flex w-full items-center gap-2 rounded-md text-left text-sm font-medium text-muted-foreground outline-none transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <ChevronDown
                    className={cn(
                      "size-4 transition-transform",
                      !completedOpen && "-rotate-90",
                    )}
                  />
                  Выполненные
                  <span className="text-xs font-normal">
                    {groupedTodos.completed.length}
                  </span>
                </button>
                {completedOpen ? (
                  <div className="mt-3 pl-0 sm:pl-6">
                    {groupedTodos.completed.map((todo) => (
                      <TodoRow
                        key={todo.id}
                        todo={todo}
                        timeZone={displayTimeZone}
                        showDate
                        pending={pendingTodoIds.has(todo.id)}
                        onToggle={toggleTodo}
                        onEdit={openEdit}
                      />
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        ) : null}
      </div>

      {!loading && user && !todosQuery.isError && !userQuery.isError ? (
        <button
          type="button"
          onClick={() => openCreate()}
          aria-label={`Добавить задачу на ${sectionTitle(selectedDay, today)}`}
          className="fixed bottom-[calc(1.5rem+env(safe-area-inset-bottom))] right-5 z-30 flex size-14 items-center justify-center rounded-full bg-neutral-900 text-white shadow-[0_10px_30px_rgba(0,0,0,0.22)] outline-none transition hover:scale-[1.03] hover:bg-neutral-800 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-95 sm:hidden dark:bg-neutral-100 dark:text-neutral-950 dark:hover:bg-neutral-200"
        >
          <Plus className="size-6" />
        </button>
      ) : null}

      {dialogOpen && user ? (
        <TodoDialog
          key={selectedTodo?.id ?? defaultDeadline ?? "new-todo"}
          open
          todo={selectedTodo}
          defaultDeadline={defaultDeadline}
          user={user}
          onOpenChange={setDialogOpen}
          onSaved={refreshTodos}
        />
      ) : null}
    </div>
  );
}
