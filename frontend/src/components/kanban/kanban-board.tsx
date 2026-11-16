"use client";

import {
  closestCorners,
  DndContext,
  DragEndEvent,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { format, isPast } from "date-fns";
import { ru } from "date-fns/locale";
import { CalendarDays, Filter, Plus, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { BoardSettingsDialog } from "@/components/kanban/board-settings";
import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import { priorityLabel } from "@/lib/priority-label";
import type {
  Board,
  BoardColumn,
  TaskCard as TaskCardType,
  TaskCardPage,
  TaskPriority,
} from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

function TaskCard({
  task,
  draggable,
  overlay = false,
  onClick,
}: {
  task: TaskCardType;
  draggable: boolean;
  overlay?: boolean;
  onClick?: () => void;
}) {
  const sortable = useSortable({
    id: task.id,
    data: { type: "task", task },
    disabled: overlay || !draggable,
  });
  const overdue = task.deadline ? isPast(new Date(task.deadline)) : false;
  const style = overlay
    ? undefined
    : {
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      };
  // Normal pointer at rest (a click opens the task page) — the grab cursor
  // only shows once a drag is actually in progress.
  const cursorClass =
    overlay || sortable.isDragging ? "cursor-grabbing" : "cursor-pointer";

  return (
    <article
      ref={overlay ? undefined : sortable.setNodeRef}
      style={style}
      onClick={onClick}
      className={cn(
        "group rounded-xl border bg-card p-3.5 text-card-foreground shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-[border-color,box-shadow] hover:border-neutral-300 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring dark:hover:border-neutral-700",
        cursorClass,
        sortable.isDragging && "opacity-30",
        overlay && "w-[286px] shadow-xl",
      )}
      {...(!overlay && draggable
        ? { ...sortable.attributes, ...sortable.listeners }
        : {})}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-medium text-neutral-600 dark:text-neutral-300">
          {task.code}
        </span>
      </div>
      <h3 className="mt-2 text-sm font-medium leading-5">{task.title}</h3>
      <div className="mt-2 flex flex-wrap gap-1">
        {task.priority !== "none" ? (
          <Badge variant="outline" className="text-[10px] capitalize">
            {priorityLabel[task.priority]}
          </Badge>
        ) : null}
        {task.labels.map((label) => (
          <span
            key={label.id}
            className="rounded-full px-2 py-0.5 text-[10px] text-white"
            style={{ backgroundColor: label.color }}
          >
            {label.name}
          </span>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between">
        {task.deadline ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 text-[11px] text-neutral-600 dark:text-neutral-300",
              overdue && "text-red-600 dark:text-red-400",
            )}
          >
            <CalendarDays className="size-3" />
            {format(new Date(task.deadline), "d MMM", { locale: ru })}
          </span>
        ) : (
          <span />
        )}
        {task.assignee ? (
          <UserAvatar
            user={task.assignee}
            size="xs"
            alt={`Исполнитель: ${task.assignee.name}`}
            title={task.assignee.name}
          />
        ) : (
          <div
            title="Без исполнителя"
            className="flex size-6 items-center justify-center rounded-full border border-dashed text-neutral-400 dark:text-neutral-500"
          >
            <UserRound className="size-3" />
          </div>
        )}
      </div>
    </article>
  );
}

function KanbanColumn({
  column,
  tasks,
  canManage,
  onTaskClick,
  onCreate,
  hasMore,
  onLoadMore,
}: {
  column: BoardColumn;
  tasks: TaskCardType[];
  canManage: boolean;
  onTaskClick: (task: TaskCardType) => void;
  onCreate: () => void;
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: column.id,
    data: { type: "column", columnId: column.id },
    disabled: !canManage,
  });
  return (
    <section className="w-[310px] shrink-0">
      <header className="mb-3 flex h-8 items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span
            className="size-2.5 rounded-full"
            style={{ backgroundColor: column.color ?? "#a1a1aa" }}
          />
          <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-600 dark:text-neutral-400">
            {column.name}
          </h2>
          <Badge>{tasks.length}</Badge>
        </div>
        {canManage ? (
          <button
            type="button"
            onClick={onCreate}
            className="rounded p-1 text-neutral-400 transition hover:bg-neutral-200 hover:text-neutral-900 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
          >
            <Plus className="size-3.5" />
          </button>
        ) : null}
      </header>
      <div
        ref={setNodeRef}
        className={cn(
          "min-h-[130px] space-y-2.5 rounded-xl p-1 transition-colors",
          canManage && isOver && "bg-neutral-100 dark:bg-neutral-800",
        )}
      >
        <SortableContext
          items={tasks.map((task) => task.id)}
          strategy={verticalListSortingStrategy}
        >
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              draggable={canManage}
              onClick={() => onTaskClick(task)}
            />
          ))}
        </SortableContext>
        {tasks.length === 0 && canManage ? (
          <button
            type="button"
            onClick={onCreate}
            className="flex h-24 w-full items-center justify-center rounded-xl border border-dashed text-xs text-neutral-400 transition hover:border-neutral-400 hover:text-neutral-700 dark:text-neutral-500 dark:hover:border-neutral-700 dark:hover:text-neutral-300"
          >
            <Plus className="mr-1.5 size-3.5" />
            Добавить задачу
          </button>
        ) : tasks.length === 0 ? (
          <div className="flex h-24 w-full items-center justify-center rounded-xl border border-dashed text-xs text-neutral-400 dark:text-neutral-500">
            Нет задач
          </div>
        ) : null}
        {hasMore ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            onClick={onLoadMore}
          >
            Показать ещё
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export function KanbanBoard({ initialBoard }: { initialBoard: Board }) {
  const router = useRouter();
  const [board, setBoard] = useState(initialBoard);
  const [activeTask, setActiveTask] = useState<TaskCardType | null>(null);
  const [assigneeFilter, setAssigneeFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState<TaskPriority | "all">(
    "all",
  );
  const [deadlineFilter, setDeadlineFilter] = useState("all");
  const [labelFilter, setLabelFilter] = useState("all");
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const tasksByColumn = useMemo(() => {
    const result = new Map<string, TaskCardType[]>();
    for (const column of board.columns) result.set(column.id, []);
    for (const task of board.tasks) {
      if (
        assigneeFilter !== "all" &&
        (task.assignee?.id ?? "none") !== assigneeFilter
      )
        continue;
      if (priorityFilter !== "all" && task.priority !== priorityFilter)
        continue;
      if (
        labelFilter !== "all" &&
        !task.labels.some((label) => label.id === labelFilter)
      )
        continue;
      const deadline = task.deadline ? new Date(task.deadline) : null;
      if (deadlineFilter === "none" && deadline) continue;
      if (deadlineFilter === "overdue" && (!deadline || !isPast(deadline)))
        continue;
      if (deadlineFilter === "upcoming" && (!deadline || isPast(deadline)))
        continue;
      result.get(task.status_id)?.push(task);
    }
    for (const tasks of result.values()) {
      tasks.sort((a, b) => a.position - b.position);
    }
    return result;
  }, [assigneeFilter, board, deadlineFilter, labelFilter, priorityFilter]);
  const assignees = useMemo(
    () =>
      Array.from(
        new Map(
          board.tasks
            .filter((task) => task.assignee)
            .map((task) => [task.assignee!.id, task.assignee!]),
        ).values(),
      ).sort((left, right) => left.name.localeCompare(right.name)),
    [board.tasks],
  );

  function openCreate(statusId?: string) {
    if (!board.can_create_tasks) return;
    const query = new URLSearchParams({ returnTo: `/app/boards/${board.id}` });
    if (statusId) query.set("status", statusId);
    router.push(`/app/boards/${board.id}/tasks/new?${query}`);
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

  async function loadMore(columnId: string) {
    const offset = board.tasks.filter(
      (task) => task.status_id === columnId,
    ).length;
    const page = await api.get<TaskCardPage>(
      `/boards/${board.id}/tasks?column_id=${columnId}&offset=${offset}&limit=100`,
    );
    setBoard((current) => ({
      ...current,
      tasks: [
        ...current.tasks,
        ...page.items.filter(
          (item) => !current.tasks.some((task) => task.id === item.id),
        ),
      ],
      has_more_by_column: {
        ...current.has_more_by_column,
        [columnId]: offset + page.items.length < page.total,
      },
    }));
  }

  async function dragEnd(event: DragEndEvent) {
    setActiveTask(null);
    if (!board.can_manage_tasks) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const moving = board.tasks.find((task) => task.id === active.id);
    if (!moving) return;

    const overData = over.data.current;
    const targetColumnId =
      overData?.type === "task"
        ? (overData.task as TaskCardType).status_id
        : overData?.type === "column"
          ? (overData.columnId as string)
          : null;
    if (!targetColumnId) return;

    const previous = board;
    const withoutMoving = board.tasks.filter((task) => task.id !== moving.id);
    const rebuilt: TaskCardType[] = [];

    for (const column of [...board.columns].sort(
      (a, b) => a.position - b.position,
    )) {
      const items = withoutMoving
        .filter((task) => task.status_id === column.id)
        .sort((a, b) => a.position - b.position);
      if (column.id === targetColumnId) {
        const overIndex =
          overData?.type === "task"
            ? items.findIndex((task) => task.id === over.id)
            : items.length;
        items.splice(overIndex < 0 ? items.length : overIndex, 0, {
          ...moving,
          status_id: targetColumnId,
        });
      }
      rebuilt.push(
        ...items.map((task, position) => ({
          ...task,
          status_id: column.id,
          position,
        })),
      );
    }

    const optimistic = { ...board, tasks: rebuilt };
    setBoard(optimistic);
    try {
      const saved = await api.put<Board>(`/boards/${board.id}/task-order`, {
        columns: board.columns.map((column) => ({
          column_id: column.id,
          task_ids: rebuilt
            .filter((task) => task.status_id === column.id)
            .sort((a, b) => a.position - b.position)
            .map((task) => task.id),
        })),
      });
      setBoard(saved);
    } catch (error) {
      setBoard(previous);
      toast.error(formatError(error));
    }
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex min-h-16 items-center justify-between border-b px-3 md:px-8">
        <div className="flex min-w-0 items-center gap-2">
          <MobileMenuButton />
          <div className="flex min-w-0 items-center gap-3">
            <Badge variant="outline" className="font-mono">
              {board.key}
            </Badge>
            <h1 className="truncate font-semibold">{board.name}</h1>
          </div>
        </div>
        {board.can_create_tasks ? (
          <div className="flex items-center gap-2">
            {board.can_manage_tasks ? (
              <BoardSettingsDialog board={board} onSaved={setBoard} />
            ) : null}
            <Button size="sm" onClick={() => openCreate()}>
              <Plus className="size-4" />
              Новая задача
              <kbd className="ml-1 rounded border px-1 text-[10px]">C</kbd>
            </Button>
          </div>
        ) : null}
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2 md:px-8">
        <Filter className="size-3.5 text-muted-foreground" />
        <select
          value={assigneeFilter}
          onChange={(event) => setAssigneeFilter(event.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-xs"
        >
          <option value="all">Все исполнители</option>
          <option value="none">Без исполнителя</option>
          {assignees.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
        <select
          value={priorityFilter}
          onChange={(event) =>
            setPriorityFilter(event.target.value as TaskPriority | "all")
          }
          className="h-8 rounded-md border bg-background px-2 text-xs"
        >
          <option value="all">Все приоритеты</option>
          <option value="urgent">Срочный</option>
          <option value="high">Высокий</option>
          <option value="medium">Средний</option>
          <option value="low">Низкий</option>
          <option value="none">Без приоритета</option>
        </select>
        <select
          value={deadlineFilter}
          onChange={(event) => setDeadlineFilter(event.target.value)}
          className="h-8 rounded-md border bg-background px-2 text-xs"
        >
          <option value="all">Все дедлайны</option>
          <option value="overdue">Просроченные</option>
          <option value="upcoming">Предстоящие</option>
          <option value="none">Без дедлайна</option>
        </select>
        {board.labels.length ? (
          <select
            value={labelFilter}
            onChange={(event) => setLabelFilter(event.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="all">Все метки</option>
            {board.labels.map((label) => (
              <option key={label.id} value={label.id}>
                {label.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={({ active }) => {
          if (!board.can_manage_tasks) return;
          setActiveTask(
            board.tasks.find((task) => task.id === active.id) ?? null,
          );
        }}
        onDragCancel={() => setActiveTask(null)}
        onDragEnd={dragEnd}
      >
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="flex min-w-max gap-5 px-6 py-7 md:px-8">
            {[...board.columns]
              .sort((a, b) => a.position - b.position)
              .map((column) => (
                <KanbanColumn
                  key={column.id}
                  column={column}
                  tasks={tasksByColumn.get(column.id) ?? []}
                  canManage={board.can_manage_tasks}
                  onTaskClick={(task) =>
                    router.push(
                      `/app/tasks/${task.id}?returnTo=${encodeURIComponent(`/app/boards/${board.id}`)}`,
                    )
                  }
                  onCreate={() => openCreate(column.id)}
                  hasMore={board.has_more_by_column[column.id] ?? false}
                  onLoadMore={() => void loadMore(column.id)}
                />
              ))}
          </div>
        </div>
        <DragOverlay>
          {activeTask ? <TaskCard task={activeTask} draggable overlay /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
