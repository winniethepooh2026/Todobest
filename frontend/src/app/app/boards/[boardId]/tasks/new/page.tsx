"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Button } from "@/components/ui/button";
import {
  DeadlinePicker,
  toLocalDateTimeInput,
} from "@/components/ui/deadline-picker";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { UserPicker, type UserPickerOption } from "@/components/ui/user-picker";
import { api } from "@/lib/api";
import type { Board, Task, TaskPriority, TeamMembers } from "@/lib/types";
import { formatError, safeAppReturnTo } from "@/lib/utils";

export default function NewTaskPage() {
  const { boardId } = useParams<{ boardId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const returnTo = safeAppReturnTo(
    searchParams.get("returnTo"),
    `/app/boards/${boardId}`,
  );
  const parentTaskId = searchParams.get("parentTaskId");
  const boardQuery = useQuery({
    queryKey: ["board", boardId],
    queryFn: () => api.get<Board>(`/boards/${boardId}`),
    staleTime: 30_000,
  });
  const board = boardQuery.data;
  const membersQuery = useQuery({
    queryKey: ["team-members", board?.team_id],
    queryFn: () => api.get<TeamMembers>(`/teams/${board?.team_id}/members`),
    enabled: !!board,
    staleTime: 30_000,
  });
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [statusId, setStatusId] = useState(searchParams.get("status") || "");
  const [assigneeId, setAssigneeId] = useState<string | null>(null);
  const [deadline, setDeadline] = useState(() =>
    toLocalDateTimeInput(searchParams.get("deadline")),
  );
  const [priority, setPriority] = useState<TaskPriority>("none");
  const [estimate, setEstimate] = useState("");
  const [labelIds, setLabelIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const assignees: UserPickerOption[] = useMemo(
    () =>
      (membersQuery.data?.members ?? [])
        .filter((member) => member.is_active)
        .map((member) => ({
          id: member.user_id,
          name: member.name,
          email: member.email,
          avatar_url: member.avatar_url,
        })),
    [membersQuery.data],
  );

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!board || !title.trim() || saving) return;
    setSaving(true);
    try {
      const task = await api.post<Task>(`/boards/${board.id}/tasks`, {
        title: title.trim(),
        description,
        status_id: statusId || null,
        assignee_id: assigneeId,
        deadline: deadline ? new Date(deadline).toISOString() : null,
        priority,
        estimate: estimate ? Number(estimate) : null,
        label_ids: labelIds,
        parent_task_id: parentTaskId,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["board", board.id] }),
        queryClient.invalidateQueries({ queryKey: ["my-issues"] }),
      ]);
      sessionStorage.setItem("noki:last-task-origin", returnTo);
      toast.success("Задача создана");
      router.replace(
        `/app/tasks/${task.id}?returnTo=${encodeURIComponent(returnTo)}`,
      );
    } catch (error) {
      toast.error(formatError(error));
      setSaving(false);
    }
  }

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        void submit();
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  });

  if (!board) {
    return (
      <div className="p-8">
        <Skeleton className="h-8 w-72" />
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex min-h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3 md:px-8">
        <MobileMenuButton />
        <Link
          href={returnTo}
          className="grid size-8 place-items-center rounded-lg text-muted-foreground hover:bg-muted"
          aria-label="Назад"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
          <Link
            href={`/app/boards/${board.id}`}
            className="truncate hover:underline"
          >
            {board.name}
          </Link>
          <ChevronRight className="size-3.5" />
          <span className="text-foreground">
            {parentTaskId ? "Новая подзадача" : "Новая задача"}
          </span>
        </div>
      </header>
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10 lg:flex-row">
        <div className="min-w-0 flex-1">
          <textarea
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Название задачи"
            maxLength={200}
            rows={2}
            autoFocus
            className="block w-full resize-none break-words border-none bg-transparent text-3xl font-semibold outline-none placeholder:text-muted-foreground/50"
          />
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={5000}
            rows={10}
            placeholder="Добавьте описание…"
            className="mt-5 resize-none border-none px-0 shadow-none focus-visible:ring-0"
          />
        </div>
        <aside className="w-full shrink-0 space-y-5 lg:w-72">
          <div>
            <Label>Статус</Label>
            <select
              value={statusId}
              onChange={(event) => setStatusId(event.target.value)}
              className="mt-1.5 h-9 w-full rounded-lg border bg-background px-3 text-sm"
            >
              <option value="">По умолчанию</option>
              {board.columns.map((column) => (
                <option key={column.id} value={column.id}>
                  {column.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label>Приоритет</Label>
            <select
              value={priority}
              onChange={(event) =>
                setPriority(event.target.value as TaskPriority)
              }
              className="mt-1.5 h-9 w-full rounded-lg border bg-background px-3 text-sm"
            >
              <option value="none">Без приоритета</option>
              <option value="low">Низкий</option>
              <option value="medium">Средний</option>
              <option value="high">Высокий</option>
              <option value="urgent">Срочный</option>
            </select>
          </div>
          <div>
            <Label>Исполнитель</Label>
            <div className="mt-1.5">
              <UserPicker
                ariaLabel="Исполнитель"
                value={assigneeId}
                onChange={setAssigneeId}
                options={assignees}
                allowEmpty
                loading={membersQuery.isLoading}
              />
            </div>
          </div>
          <div>
            <Label>Дедлайн</Label>
            <div className="mt-1.5">
              <DeadlinePicker value={deadline} onChange={setDeadline} />
            </div>
          </div>
          <div>
            <Label htmlFor="estimate">Оценка</Label>
            <input
              id="estimate"
              type="number"
              min="0"
              max="100000"
              value={estimate}
              onChange={(event) => setEstimate(event.target.value)}
              className="mt-1.5 h-9 w-full rounded-lg border bg-background px-3 text-sm"
              placeholder="Story points"
            />
          </div>
          {board.labels.length ? (
            <div>
              <Label>Метки</Label>
              <div className="mt-2 flex flex-wrap gap-2">
                {board.labels.map((label) => (
                  <button
                    key={label.id}
                    type="button"
                    onClick={() =>
                      setLabelIds((current) =>
                        current.includes(label.id)
                          ? current.filter((id) => id !== label.id)
                          : [...current, label.id],
                      )
                    }
                    className="rounded-full border px-2.5 py-1 text-xs"
                    style={
                      labelIds.includes(label.id)
                        ? { backgroundColor: label.color, color: "white" }
                        : undefined
                    }
                  >
                    {label.name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="flex gap-2 pt-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => router.push(returnTo)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={!title.trim() || saving}>
              {saving ? <Loader2 className="size-4 animate-spin" /> : null}
              Создать{" "}
              <kbd className="ml-1 rounded border px-1 text-[10px]">⌘↵</kbd>
            </Button>
          </div>
        </aside>
      </div>
    </form>
  );
}
