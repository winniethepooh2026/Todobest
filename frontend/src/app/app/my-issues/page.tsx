"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  addDays,
  addWeeks,
  eachDayOfInterval,
  endOfWeek,
  format,
  isPast,
  isSameDay,
  isToday,
  parseISO,
  startOfWeek,
} from "date-fns";
import { ru } from "date-fns/locale";
import {
  CalendarDays,
  CircleDot,
  Columns3,
  LayoutList,
  Plus,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import type { MyTaskPage, NavigationSpace, TaskCard } from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

type ViewMode = "list" | "calendar";

function weekStart(value: Date): Date {
  return startOfWeek(value, { weekStartsOn: 1 });
}

function deadlineForDay(day: Date, previous: string | null = null): string {
  const result = new Date(day);
  if (previous) {
    const prev = new Date(previous);
    result.setHours(prev.getHours(), prev.getMinutes());
  } else {
    result.setHours(9, 0, 0, 0);
  }
  return result.toISOString();
}

export default function MyIssuesPage() {
  const router = useRouter();
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [visibleWeek, setVisibleWeek] = useState(() => weekStart(new Date()));
  const [createDeadline, setCreateDeadline] = useState<string | null>(null);
  const [boardSelectOpen, setBoardSelectOpen] = useState(false);

  const query = useInfiniteQuery({
    queryKey: ["my-issues", "list"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api.get<MyTaskPage>(
        `/tasks/my/page?limit=50${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: viewMode === "list",
  });
  const listTasks: TaskCard[] =
    query.data?.pages.flatMap((page) => page.items) ?? [];
  const calendarQuery = useQuery({
    queryKey: ["my-issues", "calendar", visibleWeek.toISOString()],
    queryFn: () => {
      const params = new URLSearchParams({
        deadline_from: visibleWeek.toISOString(),
        deadline_before: addDays(visibleWeek, 7).toISOString(),
      });
      return api.get<TaskCard[]>(`/tasks/my/calendar?${params}`);
    },
    enabled: viewMode === "calendar",
  });
  const navigationQuery = useQuery({
    queryKey: ["navigation"],
    queryFn: () => api.get<NavigationSpace[]>("/navigation"),
  });

  const allBoards = useMemo(() => {
    return (
      navigationQuery.data?.flatMap((space) =>
        space.teams.flatMap((team) => team.boards),
      ) ?? []
    );
  }, [navigationQuery.data]);

  const days = useMemo(() => {
    return eachDayOfInterval({
      start: visibleWeek,
      end: endOfWeek(visibleWeek, { weekStartsOn: 1 }),
    });
  }, [visibleWeek]);

  const issuesByDay = useMemo(() => {
    const grouped = new Map<string, TaskCard[]>();
    for (const day of days) grouped.set(format(day, "yyyy-MM-dd"), []);
    for (const issue of calendarQuery.data ?? []) {
      if (!issue.deadline) continue;
      const deadline = parseISO(issue.deadline);
      const day = days.find((candidate) => isSameDay(candidate, deadline));
      if (day) grouped.get(format(day, "yyyy-MM-dd"))?.push(issue);
    }
    for (const group of grouped.values()) {
      group.sort((left, right) => {
        if (!left.deadline || !right.deadline)
          return left.position - right.position;
        return (
          new Date(left.deadline).getTime() - new Date(right.deadline).getTime()
        );
      });
    }
    return grouped;
  }, [calendarQuery.data, days]);

  function openCreate(day?: Date) {
    setCreateDeadline(day ? deadlineForDay(day) : null);
    setBoardSelectOpen(true);
  }

  function selectBoardAndCreate(boardId: string) {
    setBoardSelectOpen(false);
    const params = new URLSearchParams({ returnTo: "/app/my-issues" });
    if (createDeadline) params.set("deadline", createDeadline);
    router.push(`/app/boards/${boardId}/tasks/new?${params}`);
  }

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        event.key.toLowerCase() !== "c" ||
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

  return (
    <div className="mx-auto max-w-5xl px-6 py-12 md:px-10 md:py-16">
      <div className="flex items-center gap-2 md:hidden mb-4">
        <MobileMenuButton />
        <span className="text-sm font-medium">Мои задачи</span>
      </div>
      <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm text-muted-foreground">Назначено вам</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">
            Мои задачи
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border bg-card p-0.5">
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => setVisibleWeek((week) => addWeeks(week, -1))}
              aria-label="Предыдущая неделя"
            >
              <CalendarDays className="size-4" />
            </Button>
            <div className="min-w-36 px-2 text-center text-xs font-medium">
              {format(visibleWeek, "d MMM", { locale: ru })} —{" "}
              {format(addDays(visibleWeek, 6), "d MMM yyyy", { locale: ru })}
            </div>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => setVisibleWeek((week) => addWeeks(week, 1))}
              aria-label="Следующая неделя"
            >
              <CalendarDays className="size-4" />
            </Button>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setVisibleWeek(weekStart(new Date()))}
          >
            Текущая неделя
          </Button>
          <div className="flex rounded-lg border bg-card p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("list")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
                viewMode === "list"
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <LayoutList className="size-3.5" />
              Список
            </button>
            <button
              type="button"
              onClick={() => setViewMode("calendar")}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition",
                viewMode === "calendar"
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Columns3 className="size-3.5" />
              Календарь
            </button>
          </div>
          <Button onClick={() => openCreate()}>
            <Plus className="size-4" />
            Новая
            <kbd className="ml-1 rounded border px-1 text-[10px]">C</kbd>
          </Button>
        </div>
      </div>

      {viewMode === "list" ? (
        <div className="mt-10 overflow-hidden rounded-xl border bg-card">
          {query.isLoading
            ? Array.from({ length: 5 }).map((_, index) => (
                <div
                  key={index}
                  className="flex items-center gap-4 border-b p-4 last:border-0"
                >
                  <Skeleton className="h-5 w-14" />
                  <Skeleton className="h-5 flex-1" />
                  <Skeleton className="h-5 w-28" />
                </div>
              ))
            : null}

          {listTasks.map((task) => {
            const overdue = task.deadline
              ? isPast(new Date(task.deadline))
              : false;
            return (
              <button
                key={task.id}
                type="button"
                onClick={() => router.push(`/app/tasks/${task.id}`)}
                className="group flex w-full flex-col gap-3 border-b p-4 text-left transition last:border-0 hover:bg-neutral-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-200 sm:flex-row sm:items-center dark:hover:bg-neutral-800 dark:focus-visible:ring-neutral-700"
              >
                <Badge variant="outline" className="w-fit font-mono">
                  {task.code}
                </Badge>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {task.title}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {task.deadline ? (
                    <div
                      className={cn(
                        "flex items-center gap-1.5 text-xs text-muted-foreground",
                        overdue && "text-red-600 dark:text-red-400",
                      )}
                    >
                      <CalendarDays className="size-3.5" />
                      {format(new Date(task.deadline), "d MMM, HH:mm", {
                        locale: ru,
                      })}
                    </div>
                  ) : (
                    <span className="text-xs text-neutral-300 dark:text-neutral-600">
                      Без дедлайна
                    </span>
                  )}
                  {task.assignee ? (
                    <UserAvatar
                      user={task.assignee}
                      size="xs"
                      alt={`Исполнитель: ${task.assignee.name}`}
                      title={task.assignee.name}
                    />
                  ) : null}
                </div>
              </button>
            );
          })}

          {query.hasNextPage ? (
            <div className="p-4 text-center">
              <Button
                variant="outline"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? "Загрузка…" : "Показать ещё"}
              </Button>
            </div>
          ) : null}

          {!query.isLoading && listTasks.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <CircleDot className="mx-auto size-7 text-neutral-300 dark:text-neutral-600" />
              <h2 className="mt-4 font-medium">Нет назначенных задач</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Задачи, где вы указаны исполнителем, появятся здесь.
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-10 flex gap-5 overflow-x-auto pb-5">
          {days.map((day) => {
            const dayKey = format(day, "yyyy-MM-dd");
            const dayIssues = issuesByDay.get(dayKey) ?? [];
            return (
              <section key={dayKey} className="w-[300px] shrink-0">
                <header className="mb-3 flex min-h-10 items-center justify-between gap-2 px-1">
                  <div>
                    <div
                      className={cn(
                        "text-xs font-medium",
                        isToday(day) &&
                          "text-neutral-900 dark:text-neutral-100",
                      )}
                    >
                      {format(day, "EEEE", { locale: ru })}
                    </div>
                    <div
                      className={cn(
                        "text-lg font-semibold",
                        isToday(day) &&
                          "text-neutral-900 dark:text-neutral-100",
                      )}
                    >
                      {format(day, "d")}
                    </div>
                  </div>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => openCreate(day)}
                    aria-label={`Добавить задачу на ${format(day, "d MMMM", { locale: ru })}`}
                  >
                    <Plus className="size-3.5" />
                  </Button>
                </header>
                <div
                  className={cn(
                    "min-h-40 space-y-2.5 rounded-xl p-1 transition-colors",
                  )}
                >
                  {dayIssues.map((issue) => (
                    <button
                      key={issue.id}
                      type="button"
                      onClick={() => router.push(`/app/tasks/${issue.id}`)}
                      className="group w-full rounded-lg border bg-card p-3 text-left text-card-foreground shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] hover:border-neutral-300 hover:shadow-sm dark:hover:border-neutral-700"
                    >
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className="font-mono text-[10px]"
                        >
                          {issue.code}
                        </Badge>
                        {issue.deadline && isPast(new Date(issue.deadline)) ? (
                          <span className="text-[10px] text-red-600 dark:text-red-400">
                            Просрочено
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1.5 truncate text-sm font-medium">
                        {issue.title}
                      </div>
                      {issue.assignee ? (
                        <div className="mt-2 flex items-center gap-1.5">
                          <UserAvatar user={issue.assignee} size="xs" />
                          <span className="text-[11px] text-muted-foreground">
                            {issue.assignee.name}
                          </span>
                        </div>
                      ) : null}
                    </button>
                  ))}
                  {dayIssues.length === 0 ? (
                    <button
                      type="button"
                      onClick={() => openCreate(day)}
                      className="flex h-28 w-full items-center justify-center rounded-xl border border-dashed text-xs text-neutral-400 transition hover:border-neutral-400 hover:text-neutral-700 dark:text-neutral-500 dark:hover:border-neutral-700 dark:hover:text-neutral-300"
                    >
                      <Plus className="mr-1.5 size-3.5" />
                      Добавить задачу
                    </button>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {(viewMode === "list" ? query.isError : calendarQuery.isError) && (
        <div className="mt-10 rounded-xl border border-dashed px-6 py-14 text-center">
          <CircleDot className="mx-auto size-7 text-neutral-300" />
          <h3 className="mt-4 font-medium">Не удалось загрузить задачи</h3>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            {formatError(
              viewMode === "list" ? query.error : calendarQuery.error,
            )}
          </p>
          <Button
            className="mt-5"
            variant="outline"
            onClick={() =>
              void (viewMode === "list"
                ? query.refetch()
                : calendarQuery.refetch())
            }
          >
            Повторить
          </Button>
        </div>
      )}

      <Dialog open={boardSelectOpen} onOpenChange={setBoardSelectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Выберите доску задач</DialogTitle>
            <DialogDescription>
              Создайте задачу в одной из ваших досок.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>Доска</Label>
            <div className="max-h-60 overflow-y-auto space-y-1.5">
              {allBoards.map((board) => (
                <button
                  key={board.id}
                  type="button"
                  onClick={() => selectBoardAndCreate(board.id)}
                  className="flex w-full items-center justify-between rounded-lg border bg-card px-3 py-2 text-left text-sm transition hover:border-neutral-300 dark:hover:border-neutral-700"
                >
                  <span className="font-medium">{board.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {board.key}
                  </span>
                </button>
              ))}
              {allBoards.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Нет доступных досок
                </p>
              ) : null}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
