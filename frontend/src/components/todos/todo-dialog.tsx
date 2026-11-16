"use client";

import { Loader2, Trash2 } from "lucide-react";
import { FormEvent, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DeadlinePicker,
  toLocalDateTimeInput,
} from "@/components/ui/deadline-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import {
  normalizeTimeZone,
  zonedDateTimeInputToISOString,
} from "@/lib/timezone";
import type { Todo, TodoStatus, User } from "@/lib/types";
import { formatError } from "@/lib/utils";

export function TodoDialog({
  open,
  todo,
  defaultDeadline,
  user,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  todo: Todo | null;
  defaultDeadline: string | null;
  user: User;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void | Promise<void>;
}) {
  const timeZone = normalizeTimeZone(user.timezone);
  const initialDeadlineSource = todo?.deadline ?? defaultDeadline;
  const [initialDeadline] = useState(() => ({
    source: initialDeadlineSource,
    wallValue: toLocalDateTimeInput(initialDeadlineSource, timeZone),
  }));
  const deadlineDirtyRef = useRef(false);
  const [title, setTitle] = useState(todo?.title ?? "");
  const [description, setDescription] = useState(todo?.description ?? "");
  const [deadline, setDeadline] = useState(initialDeadline.wallValue);
  const [status, setStatus] = useState<TodoStatus>(todo?.status ?? "todo");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const busyRef = useRef(false);
  const busy = saving || deleting;

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen && busyRef.current) return;
    onOpenChange(nextOpen);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setSaving(true);
    try {
      const payload = {
        title,
        description,
        deadline: deadline
          ? !deadlineDirtyRef.current &&
            initialDeadline.source &&
            deadline === initialDeadline.wallValue
            ? initialDeadline.source
            : zonedDateTimeInputToISOString(deadline, timeZone)
          : null,
        status,
      };
      if (todo) {
        await api.patch<Todo>(`/todos/${todo.id}`, payload);
      } else {
        await api.post<Todo>("/todos", payload);
      }
      await onSaved();
      onOpenChange(false);
      toast.success(todo ? "Задача обновлена" : "Задача создана");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      busyRef.current = false;
      setSaving(false);
    }
  }

  async function remove() {
    if (!todo || !window.confirm(`Удалить задачу «${todo.title}»?`)) return;
    if (busyRef.current) return;
    busyRef.current = true;
    setDeleting(true);
    try {
      await api.delete<{ message: string }>(`/todos/${todo.id}`);
      await onSaved();
      onOpenChange(false);
      toast.success("Задача удалена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      busyRef.current = false;
      setDeleting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] gap-0 overflow-visible p-0"
        onEscapeKeyDown={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
      >
        <div className="min-h-0 overflow-y-auto p-5 sm:p-6">
          <DialogHeader>
            <DialogTitle>
              {todo ? "Редактировать задачу" : "Новая задача"}
            </DialogTitle>
            <DialogDescription>
              Личная задача видна только вам. Исполнитель закреплён за текущим
              пользователем.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={submit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="todo-title">Название</Label>
              <Input
                id="todo-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={200}
                placeholder="Что нужно сделать?"
                autoFocus
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="todo-description">Описание</Label>
              <Textarea
                id="todo-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={5000}
                rows={4}
                placeholder="Добавьте детали задачи…"
              />
              <div className="text-right text-[11px] text-muted-foreground">
                {description.length}/5000
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="todo-status">Статус</Label>
                <select
                  id="todo-status"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as TodoStatus)
                  }
                  className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200 dark:focus:ring-neutral-700"
                >
                  <option value="todo">К выполнению</option>
                  <option value="in_progress">В работе</option>
                  <option value="done">Готово</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="todo-deadline">Дедлайн</Label>
                <DeadlinePicker
                  id="todo-deadline"
                  value={deadline}
                  onChange={(value) => {
                    deadlineDirtyRef.current = true;
                    setDeadline(value);
                  }}
                  align="right"
                  portal
                  timeZone={timeZone}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Исполнитель</Label>
              <div className="flex items-center gap-3 rounded-lg border bg-neutral-50 px-3 py-2.5 dark:bg-neutral-800 dark:border-neutral-700">
                <UserAvatar user={user} size="sm" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">
                    {user.name}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {user.email} · только вы
                  </div>
                </div>
              </div>
            </div>

            <DialogFooter className="sm:justify-between">
              <div>
                {todo ? (
                  <Button
                    type="button"
                    variant="ghost"
                    className="text-red-600 hover:bg-red-50 hover:text-red-700"
                    onClick={remove}
                    disabled={busy}
                  >
                    {deleting ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="size-4" />
                    )}
                    Удалить
                  </Button>
                ) : null}
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => onOpenChange(false)}
                  disabled={busy}
                >
                  Отмена
                </Button>
                <Button type="submit" disabled={busy}>
                  {saving ? <Loader2 className="size-4 animate-spin" /> : null}
                  {todo ? "Сохранить" : "Создать"}
                  {!todo ? (
                    <kbd className="ml-1 rounded border px-1 text-[10px]">
                      ↵
                    </kbd>
                  ) : null}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
