"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { FormEvent, useState } from "react";
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
import { UserPicker, type UserPickerOption } from "@/components/ui/user-picker";
import { api } from "@/lib/api";
import type { Board, Task, TeamMembers } from "@/lib/types";
import { formatError } from "@/lib/utils";

export function CreateTaskDialog({
  board,
  defaultStatusId,
  initialDeadline,
  open,
  onOpenChange,
  onCreated,
}: {
  board: Board;
  defaultStatusId?: string | null;
  initialDeadline?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (task: Task) => void | Promise<void>;
}) {
  const queryClient = useQueryClient();
  const membersQuery = useQuery({
    queryKey: ["team-members", board.team_id],
    queryFn: () => api.get<TeamMembers>(`/teams/${board.team_id}/members`),
  });
  const defaultColumn =
    board.columns.find((column) => column.is_default) ??
    [...board.columns].sort((left, right) => left.position - right.position)[0];

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [statusId, setStatusId] = useState(defaultStatusId ?? "");
  const [assigneeId, setAssigneeId] = useState("");
  const [deadline, setDeadline] = useState(
    toLocalDateTimeInput(initialDeadline ?? null),
  );
  const [loading, setLoading] = useState(false);

  const assigneeOptions: UserPickerOption[] = (membersQuery.data?.members ?? [])
    .filter((member) => member.is_active)
    .map((member) => ({
      id: member.user_id,
      name: member.name,
      email: member.email,
      avatar_url: member.avatar_url,
    }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const task = await api.post<Task>(`/boards/${board.id}/tasks`, {
        title,
        description,
        deadline: deadline ? new Date(deadline).toISOString() : null,
        status_id: statusId || null,
        assignee_id: assigneeId || null,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["board", board.id] }),
        queryClient.invalidateQueries({ queryKey: ["my-issues"] }),
      ]);
      await onCreated(task);
      onOpenChange(false);
      toast.success("Задача создана");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новая задача</DialogTitle>
          <DialogDescription>
            Новая задача может оставаться без исполнителя.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="task-title">Название</Label>
            <Input
              id="task-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={200}
              autoFocus
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-description">Описание</Label>
            <Textarea
              id="task-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={5000}
              placeholder="Короткий контекст задачи…"
            />
            <div className="text-right text-[11px] text-muted-foreground">
              {description.length}/5000
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="task-status">Статус</Label>
              <select
                id="task-status"
                value={statusId}
                onChange={(event) => setStatusId(event.target.value)}
                className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200 dark:focus:ring-neutral-700"
              >
                <option value="">
                  По умолчанию · {defaultColumn?.name ?? "первая колонка"} ★
                </option>
                {board.columns.map((column) => (
                  <option key={column.id} value={column.id}>
                    {column.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="task-assignee">Исполнитель</Label>
              <UserPicker
                id="task-assignee"
                ariaLabel="Исполнитель"
                value={assigneeId || null}
                onChange={(value) => setAssigneeId(value ?? "")}
                options={assigneeOptions}
                allowEmpty
                loading={membersQuery.isLoading}
                error={membersQuery.isError ? formatError(membersQuery.error) : null}
                emptyMessage="В Team пока нет доступных исполнителей"
                align="right"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-deadline">Дедлайн</Label>
            <DeadlinePicker
              id="task-deadline"
              value={deadline}
              onChange={setDeadline}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={loading || membersQuery.isLoading}>
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
