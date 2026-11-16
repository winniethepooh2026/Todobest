"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronRight,
  Link2,
  Loader2,
  Paperclip,
  Plus,
  Trash2,
  UserCheck,
  UserRound,
  X,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { TaskComments } from "@/components/kanban/task-comments";
import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Button } from "@/components/ui/button";
import {
  DeadlinePicker,
  toLocalDateTimeInput,
} from "@/components/ui/deadline-picker";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { UserAvatar } from "@/components/ui/user-avatar";
import { UserPicker, type UserPickerOption } from "@/components/ui/user-picker";
import { api, ApiError } from "@/lib/api";
import { priorityLabel } from "@/lib/priority-label";
import { formatDateTime } from "@/lib/format";
import type {
  Board,
  Task,
  TaskActivity,
  TaskPriority,
  TaskRelation,
  TaskRelationKind,
  TaskSystemStatus,
  TeamMembers,
  UploadResult,
} from "@/lib/types";
import { formatError, safeAppReturnTo } from "@/lib/utils";

export default function TaskPage() {
  const params = useParams<{ taskId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const taskId = params.taskId;
  const requestedReturnTo = searchParams.get("returnTo");

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.get<Task>(`/tasks/${taskId}`),
  });
  const task = taskQuery.data;

  const boardQuery = useQuery({
    queryKey: ["board", task?.board_id],
    queryFn: () => api.get<Board>(`/boards/${task?.board_id}`),
    enabled: !!task,
  });
  const board = boardQuery.data;
  const returnTo = safeAppReturnTo(
    requestedReturnTo,
    board ? `/app/boards/${board.id}` : "/app/my-issues",
  );

  const membersQuery = useQuery({
    queryKey: ["team-members", board?.team_id],
    queryFn: () => api.get<TeamMembers>(`/teams/${board?.team_id}/members`),
    enabled: !!board?.can_manage_tasks,
  });
  const attachmentsQuery = useQuery({
    queryKey: ["task-attachments", taskId],
    queryFn: () => api.get<UploadResult[]>(`/tasks/${taskId}/attachments`),
  });
  const activityQuery = useQuery({
    queryKey: ["task-activity", taskId],
    queryFn: () => api.get<TaskActivity[]>(`/tasks/${taskId}/activity`),
  });
  const subtasksQuery = useQuery({
    queryKey: ["task-subtasks", taskId],
    queryFn: () => api.get<Task[]>(`/tasks/${taskId}/subtasks`),
  });
  const relationsQuery = useQuery({
    queryKey: ["task-relations", taskId],
    queryFn: () => api.get<TaskRelation[]>(`/tasks/${taskId}/relations`),
  });

  const [titleDraft, setTitleDraft] = useState<string | null>(null);
  const [descriptionDraft, setDescriptionDraft] = useState<string | null>(null);
  const [memberStatus, setMemberStatus] = useState<TaskSystemStatus | "">("");
  const [savingField, setSavingField] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [relationTarget, setRelationTarget] = useState("");
  const [relationKind, setRelationKind] =
    useState<TaskRelationKind>("relates_to");
  const [savingRelation, setSavingRelation] = useState(false);
  const titleRef = useRef<HTMLTextAreaElement>(null);
  const descriptionRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow both textareas to fit their content — otherwise a long
  // description gets clipped into a small fixed-height scroll box.
  useEffect(() => {
    for (const el of [titleRef.current, descriptionRef.current]) {
      if (!el) continue;
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [titleDraft, descriptionDraft, task?.title, task?.description]);

  useEffect(() => {
    function createAnotherTask(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        event.key.toLowerCase() !== "c" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "") ||
        !board?.can_create_tasks
      ) {
        return;
      }
      event.preventDefault();
      router.push(
        `/app/boards/${board.id}/tasks/new?returnTo=${encodeURIComponent(returnTo)}`,
      );
    }
    window.addEventListener("keydown", createAnotherTask);
    return () => window.removeEventListener("keydown", createAnotherTask);
  }, [board, returnTo, router]);

  const notFound =
    (taskQuery.error instanceof ApiError && taskQuery.error.status === 404) ||
    (boardQuery.error instanceof ApiError && boardQuery.error.status === 404);

  async function refreshLists() {
    await Promise.all([
      board
        ? queryClient.invalidateQueries({ queryKey: ["board", board.id] })
        : null,
      queryClient.invalidateQueries({ queryKey: ["my-issues"] }),
      queryClient.invalidateQueries({ queryKey: ["task-activity", taskId] }),
    ]);
  }

  async function patchTask(field: string, payload: Record<string, unknown>) {
    if (!task) return;
    setSavingField(field);
    try {
      const updated = await api.patch<Task>(`/tasks/${task.id}`, payload);
      queryClient.setQueryData(["task", task.id], updated);
      await refreshLists();
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setSavingField(null);
    }
  }

  async function saveTitle() {
    if (!task || titleDraft === null) return;
    const trimmed = titleDraft.trim();
    if (!trimmed || trimmed === task.title) {
      setTitleDraft(null);
      return;
    }
    await patchTask("title", { title: trimmed });
    setTitleDraft(null);
  }

  async function saveDescription() {
    if (!task || descriptionDraft === null) return;
    if (descriptionDraft === task.description) {
      setDescriptionDraft(null);
      return;
    }
    await patchTask("description", { description: descriptionDraft });
    setDescriptionDraft(null);
  }

  async function claim() {
    if (!task) return;
    setClaiming(true);
    try {
      const updated = await api.post<Task>(`/tasks/${task.id}/claim`);
      queryClient.setQueryData(["task", task.id], updated);
      await refreshLists();
      toast.success("Задача взята в работу");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setClaiming(false);
    }
  }

  async function saveMemberStatus() {
    if (!task || !memberStatus) return;
    setSavingField("member-status");
    try {
      const updated = await api.patch<Task>(`/tasks/${task.id}/status`, {
        status: memberStatus,
      });
      queryClient.setQueryData(["task", task.id], updated);
      await refreshLists();
      toast.success("Статус обновлён");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setSavingField(null);
    }
  }

  async function removeTask() {
    if (!task || !board || !window.confirm(`Удалить ${task.code}?`)) return;
    setDeleting(true);
    try {
      await api.delete<{ message: string }>(`/tasks/${task.id}`);
      await refreshLists();
      toast.success("Задача удалена");
      router.push(returnTo);
    } catch (error) {
      toast.error(formatError(error));
      setDeleting(false);
    }
  }

  async function uploadAttachment(file: File) {
    if (!task || !board) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      await api.upload<UploadResult>(
        `/uploads/images?team_id=${board.team_id}&task_id=${task.id}`,
        body,
      );
      await attachmentsQuery.refetch();
      toast.success("Вложение добавлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setUploading(false);
    }
  }

  async function createRelation() {
    if (!task || !relationTarget || savingRelation) return;
    setSavingRelation(true);
    try {
      await api.post<TaskRelation>(`/tasks/${task.id}/relations`, {
        target_task_id: relationTarget,
        kind: relationKind,
      });
      setRelationTarget("");
      await relationsQuery.refetch();
      toast.success("Связь добавлена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setSavingRelation(false);
    }
  }

  async function removeRelation(relationId: string) {
    try {
      await api.delete<{ message: string }>(
        `/tasks/${taskId}/relations/${relationId}`,
      );
      await relationsQuery.refetch();
    } catch (error) {
      toast.error(formatError(error));
    }
  }

  if (notFound) {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-lg font-medium">Задача не найдена</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          Возможно, она была удалена, либо у вас нет доступа.
        </p>
        <Button variant="outline" onClick={() => router.push("/app/my-issues")}>
          К моим задачам
        </Button>
      </div>
    );
  }

  if (taskQuery.isLoading || boardQuery.isLoading || !task || !board) {
    return (
      <div className="flex h-dvh flex-col overflow-hidden">
        <div className="flex h-14 items-center gap-3 border-b px-4 md:px-8">
          <Skeleton className="h-6 w-40" />
        </div>
        <div className="mx-auto flex w-full max-w-6xl flex-1 gap-10 px-6 py-10 md:px-10">
          <div className="min-w-0 flex-1 space-y-4">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
          <div className="hidden w-72 shrink-0 space-y-3 lg:block">
            <Skeleton className="h-24 w-full" />
          </div>
        </div>
      </div>
    );
  }

  const currentColumn = board.columns.find(
    (column) => column.id === task.status_id,
  );
  const systemColumns = board.columns
    .filter((column) => column.system_status !== null)
    .sort((a, b) => a.position - b.position);
  const canClaim = task.assignee === null && board.can_claim_tasks;
  const canChangeMemberStatus =
    !board.can_manage_tasks &&
    board.can_claim_tasks &&
    task.assignee?.id === board.current_user_id &&
    currentColumn !== undefined &&
    currentColumn.system_status !== null;
  const canEditCoreFields =
    board.can_manage_tasks ||
    task.created_by.id === board.current_user_id ||
    task.assignee?.id === board.current_user_id;
  const assigneeOptions: UserPickerOption[] = (membersQuery.data?.members ?? [])
    .filter((member) => member.is_active)
    .map((member) => ({
      id: member.user_id,
      name: member.name,
      email: member.email,
      avatar_url: member.avatar_url,
    }));

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3 md:px-8">
        <MobileMenuButton />
        <Link
          href={returnTo}
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-neutral-100 hover:text-foreground dark:hover:bg-neutral-800"
          aria-label="Назад к доске"
          title="Вернуться назад"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
          <Link
            href={`/app/boards/${board.id}`}
            className="truncate rounded transition hover:text-foreground hover:underline"
          >
            {board.name}
          </Link>
          <ChevronRight className="size-3.5 shrink-0" />
          <span className="shrink-0 font-mono text-foreground">
            {task.code}
          </span>
        </div>
        {board.can_create_tasks ? (
          <Link
            className="ml-auto inline-flex h-8 items-center rounded-md border bg-background px-3 text-sm font-medium hover:bg-muted"
            href={`/app/boards/${board.id}/tasks/new?returnTo=${encodeURIComponent(returnTo)}`}
          >
            Ещё задача{" "}
            <kbd className="ml-1 rounded border px-1 text-[10px]">C</kbd>
          </Link>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10 md:px-10 lg:flex-row">
          <div className="min-w-0 flex-1">
            {canEditCoreFields ? (
              <textarea
                ref={titleRef}
                value={titleDraft ?? task.title}
                onChange={(event) => setTitleDraft(event.target.value)}
                onBlur={() => void saveTitle()}
                maxLength={200}
                rows={1}
                className="block w-full resize-none overflow-hidden border-none bg-transparent text-2xl font-semibold tracking-[-0.02em] outline-none md:text-3xl"
              />
            ) : (
              <h1 className="text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
                {task.title}
              </h1>
            )}

            <div className="mt-4">
              {canEditCoreFields ? (
                <Textarea
                  ref={descriptionRef}
                  value={descriptionDraft ?? task.description}
                  onChange={(event) => setDescriptionDraft(event.target.value)}
                  onBlur={() => void saveDescription()}
                  maxLength={5000}
                  rows={1}
                  placeholder="Добавьте описание…"
                  className="resize-none overflow-hidden border-none px-0 shadow-none focus-visible:ring-0"
                />
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-6 text-foreground">
                  {task.description || "Описание не добавлено."}
                </p>
              )}
            </div>

            <hr className="my-8" />

            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">Подзадачи</h2>
                {board.can_manage_tasks ? (
                  <Link
                    href={`/app/boards/${board.id}/tasks/new?parentTaskId=${task.id}&returnTo=${encodeURIComponent(`/app/tasks/${task.id}?returnTo=${encodeURIComponent(returnTo)}`)}`}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border bg-background px-3 text-xs font-medium hover:bg-muted"
                  >
                    <Plus className="size-3.5" />
                    Добавить
                  </Link>
                ) : null}
              </div>
              <div className="divide-y rounded-lg border">
                {subtasksQuery.data?.map((subtask) => (
                  <Link
                    key={subtask.id}
                    href={`/app/tasks/${subtask.id}?returnTo=${encodeURIComponent(`/app/tasks/${task.id}?returnTo=${encodeURIComponent(returnTo)}`)}`}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-muted/60"
                  >
                    <span className="min-w-0 truncate">{subtask.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {subtask.code}
                    </span>
                  </Link>
                ))}
                {!subtasksQuery.data?.length ? (
                  <p className="px-3 py-2 text-xs text-muted-foreground">
                    Подзадач пока нет.
                  </p>
                ) : null}
              </div>
            </section>

            <section className="mt-8 space-y-3 border-t pt-6">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Link2 className="size-4" /> Связи
              </h2>
              {board.can_manage_tasks ? (
                <div className="flex flex-col gap-2 sm:flex-row">
                  <select
                    value={relationKind}
                    onChange={(event) =>
                      setRelationKind(event.target.value as TaskRelationKind)
                    }
                    className="h-9 rounded-lg border bg-background px-3 text-sm"
                  >
                    <option value="relates_to">Связана с</option>
                    <option value="blocks">Блокирует</option>
                    <option value="duplicates">Дублирует</option>
                  </select>
                  <select
                    value={relationTarget}
                    onChange={(event) => setRelationTarget(event.target.value)}
                    className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-3 text-sm"
                  >
                    <option value="">Выберите задачу…</option>
                    {board.tasks
                      .filter((candidate) => candidate.id !== task.id)
                      .map((candidate) => (
                        <option key={candidate.id} value={candidate.id}>
                          {candidate.code} · {candidate.title}
                        </option>
                      ))}
                  </select>
                  <Button
                    size="sm"
                    onClick={() => void createRelation()}
                    disabled={!relationTarget || savingRelation}
                  >
                    Добавить
                  </Button>
                </div>
              ) : null}
              <div className="space-y-2">
                {relationsQuery.data?.map((relation) => {
                  const relatedId =
                    relation.source_task_id === task.id
                      ? relation.target_task_id
                      : relation.source_task_id;
                  const related = board.tasks.find(
                    (candidate) => candidate.id === relatedId,
                  );
                  const kindLabel = {
                    blocks: "Блокирует",
                    relates_to: "Связана с",
                    duplicates: "Дублирует",
                  }[relation.kind];
                  return (
                    <div
                      key={relation.id}
                      className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
                    >
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {kindLabel}
                      </span>
                      <Link
                        href={`/app/tasks/${relatedId}?returnTo=${encodeURIComponent(`/app/tasks/${task.id}?returnTo=${encodeURIComponent(returnTo)}`)}`}
                        className="min-w-0 flex-1 truncate hover:underline"
                      >
                        {related
                          ? `${related.code} · ${related.title}`
                          : relatedId}
                      </Link>
                      {board.can_manage_tasks ? (
                        <button
                          type="button"
                          onClick={() => void removeRelation(relation.id)}
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                          aria-label="Удалить связь"
                        >
                          <X className="size-3.5" />
                        </button>
                      ) : null}
                    </div>
                  );
                })}
                {!relationsQuery.data?.length ? (
                  <p className="text-xs text-muted-foreground">
                    Связей пока нет.
                  </p>
                ) : null}
              </div>
            </section>

            <hr className="my-8" />

            <h2 className="mb-4 text-sm font-semibold tracking-tight">
              Activity
            </h2>
            <TaskComments
              taskId={task.id}
              currentUserId={board.current_user_id}
              canManageTasks={board.can_manage_tasks}
            />
            <div className="mt-8 border-t pt-6">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">Вложения</h2>
                {board.can_manage_tasks ? (
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs hover:bg-muted">
                    <Paperclip className="size-3.5" />
                    {uploading ? "Загрузка…" : "Добавить"}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      className="sr-only"
                      disabled={uploading}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void uploadAttachment(file);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                ) : null}
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {attachmentsQuery.data?.map((attachment) => (
                  <a
                    key={attachment.id}
                    href={attachment.url}
                    target="_blank"
                    rel="noreferrer"
                    className="overflow-hidden rounded-lg border"
                  >
                    <Image
                      src={attachment.url}
                      alt="Вложение задачи"
                      width={attachment.width}
                      height={attachment.height}
                      className="aspect-video w-full object-cover"
                      unoptimized
                    />
                  </a>
                ))}
              </div>
              {!attachmentsQuery.data?.length ? (
                <p className="text-xs text-muted-foreground">
                  Вложений пока нет.
                </p>
              ) : null}
            </div>
            <div className="mt-8 border-t pt-6">
              <h2 className="mb-3 text-sm font-semibold">История</h2>
              <div className="space-y-2">
                {activityQuery.data?.map((item) => (
                  <div
                    key={item.id}
                    className="flex justify-between gap-3 text-xs"
                  >
                    <span>{item.summary}</span>
                    <time className="shrink-0 text-muted-foreground">
                      {formatDateTime(item.created_at)}
                    </time>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <aside className="w-full shrink-0 space-y-6 lg:w-72">
            <div>
              <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Properties
              </div>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <Label
                    htmlFor="task-status"
                    className="text-xs text-muted-foreground"
                  >
                    Статус
                  </Label>
                  {board.can_manage_tasks ? (
                    <select
                      id="task-status"
                      value={task.status_id}
                      onChange={(event) =>
                        void patchTask("status", {
                          status_id: event.target.value,
                        })
                      }
                      disabled={savingField === "status"}
                      className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200 dark:focus:ring-neutral-700"
                    >
                      {board.columns.map((column) => (
                        <option key={column.id} value={column.id}>
                          {column.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="flex h-9 items-center gap-2 text-sm">
                      {currentColumn?.color ? (
                        <span
                          className="size-2 shrink-0 rounded-full"
                          style={{ backgroundColor: currentColumn.color }}
                        />
                      ) : null}
                      {currentColumn?.name ?? "Неизвестный статус"}
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    Исполнитель
                  </Label>
                  {board.can_manage_tasks ? (
                    <UserPicker
                      ariaLabel="Исполнитель"
                      value={task.assignee?.id ?? null}
                      onChange={(value) =>
                        void patchTask("assignee", { assignee_id: value })
                      }
                      options={assigneeOptions}
                      allowEmpty
                      loading={membersQuery.isLoading}
                      disabled={savingField === "assignee"}
                      error={
                        membersQuery.isError
                          ? formatError(membersQuery.error)
                          : null
                      }
                      emptyMessage="В команде пока нет доступных исполнителей"
                    />
                  ) : (
                    <div className="flex h-9 items-center gap-2">
                      {task.assignee ? (
                        <>
                          <UserAvatar
                            user={task.assignee}
                            size="xs"
                            tone="subtle"
                          />
                          <span className="truncate text-sm">
                            {task.assignee.name}
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="flex size-6 items-center justify-center rounded-full border border-dashed text-neutral-400 dark:text-neutral-500">
                            <UserRound className="size-3.5" />
                          </span>
                          <span className="text-sm text-muted-foreground">
                            Не назначен
                          </span>
                        </>
                      )}
                    </div>
                  )}
                  {canClaim ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={claim}
                      disabled={claiming}
                    >
                      {claiming ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <UserCheck className="size-3.5" />
                      )}
                      Взять в работу
                    </Button>
                  ) : null}
                  {canChangeMemberStatus && systemColumns.length > 0 ? (
                    <div className="flex gap-2">
                      <select
                        value={memberStatus}
                        onChange={(event) =>
                          setMemberStatus(
                            event.target.value as TaskSystemStatus,
                          )
                        }
                        className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200 dark:focus:ring-neutral-700"
                      >
                        <option value="" disabled>
                          Изменить статус
                        </option>
                        {systemColumns.map((column) => (
                          <option
                            key={column.id}
                            value={column.system_status ?? ""}
                          >
                            {column.name}
                          </option>
                        ))}
                      </select>
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => void saveMemberStatus()}
                        disabled={
                          savingField === "member-status" ||
                          !memberStatus ||
                          memberStatus === currentColumn?.system_status
                        }
                      >
                        {savingField === "member-status" ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          "OK"
                        )}
                      </Button>
                    </div>
                  ) : null}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    Приоритет
                  </Label>
                  {board.can_manage_tasks ? (
                    <select
                      value={task.priority}
                      onChange={(event) =>
                        void patchTask("priority", {
                          priority: event.target.value as TaskPriority,
                        })
                      }
                      className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
                    >
                      <option value="none">Без приоритета</option>
                      <option value="low">Низкий</option>
                      <option value="medium">Средний</option>
                      <option value="high">Высокий</option>
                      <option value="urgent">Срочный</option>
                    </select>
                  ) : (
                    <div className="text-sm">
                      {priorityLabel[task.priority]}
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    Оценка
                  </Label>
                  {board.can_manage_tasks ? (
                    <input
                      type="number"
                      min="0"
                      max="100000"
                      defaultValue={task.estimate ?? ""}
                      onBlur={(event) =>
                        void patchTask("estimate", {
                          estimate: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                      className="h-9 w-full rounded-lg border bg-background px-3 text-sm"
                    />
                  ) : (
                    <div className="text-sm">
                      {task.estimate ?? "Не задана"}
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Метки</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {board.labels.map((label) => {
                      const selected = task.labels.some(
                        (item) => item.id === label.id,
                      );
                      return (
                        <button
                          key={label.id}
                          type="button"
                          disabled={!board.can_manage_tasks}
                          onClick={() =>
                            void patchTask("labels", {
                              label_ids: selected
                                ? task.labels
                                    .filter((item) => item.id !== label.id)
                                    .map((item) => item.id)
                                : [
                                    ...task.labels.map((item) => item.id),
                                    label.id,
                                  ],
                            })
                          }
                          className="rounded-full border px-2 py-0.5 text-xs"
                          style={
                            selected
                              ? { backgroundColor: label.color, color: "white" }
                              : undefined
                          }
                        >
                          {label.name}
                        </button>
                      );
                    })}
                    {!board.labels.length ? (
                      <span className="text-sm text-muted-foreground">
                        Нет меток
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    Дедлайн
                  </Label>
                  {canEditCoreFields ? (
                    <DeadlinePicker
                      value={toLocalDateTimeInput(task.deadline)}
                      onChange={(value) =>
                        void patchTask("deadline", {
                          deadline: value
                            ? new Date(value).toISOString()
                            : null,
                        })
                      }
                    />
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      {task.deadline
                        ? formatDateTime(task.deadline)
                        : "Без дедлайна"}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t pt-4">
              <div className="flex items-center gap-2.5 text-xs text-muted-foreground">
                <UserAvatar user={task.created_by} size="xs" tone="subtle" />
                <div className="min-w-0">
                  Создал{" "}
                  <span className="font-medium text-foreground">
                    {task.created_by.name}
                  </span>
                  <div>{formatDateTime(task.created_at)}</div>
                </div>
              </div>
            </div>

            {board.can_manage_tasks ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950 dark:hover:text-red-300"
                onClick={removeTask}
                disabled={deleting}
              >
                {deleting ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Trash2 className="size-3.5" />
                )}
                Удалить задачу
              </Button>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}
