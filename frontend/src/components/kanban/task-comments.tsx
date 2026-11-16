"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Send, Trash2, X } from "lucide-react";
import { Fragment, KeyboardEvent, ReactNode, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import type { TaskComment } from "@/lib/types";
import { formatError } from "@/lib/utils";

const MAX_COMMENT_LENGTH = 4000;

function CommentBody({ body }: { body: string }) {
  const lines = body.split("\n");
  return (
    <div className="mt-1 whitespace-pre-wrap text-sm leading-6">
      {lines.map((line, lineIndex) => {
        const parts = line.split(
          /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|@[\p{L}\p{N}_.-]+)/gu,
        );
        const content: ReactNode[] = parts.map((part, index) => {
          if (/^`[^`]+`$/.test(part))
            return (
              <code
                key={index}
                className="rounded bg-muted px-1 py-0.5 text-xs"
              >
                {part.slice(1, -1)}
              </code>
            );
          if (/^\*\*[^*]+\*\*$/.test(part))
            return <strong key={index}>{part.slice(2, -2)}</strong>;
          if (/^\*[^*]+\*$/.test(part))
            return <em key={index}>{part.slice(1, -1)}</em>;
          if (part.startsWith("@"))
            return (
              <span
                key={index}
                className="rounded bg-blue-50 px-1 font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-300"
              >
                {part}
              </span>
            );
          return <Fragment key={index}>{part}</Fragment>;
        });
        return (
          <Fragment key={lineIndex}>
            {content}
            {lineIndex < lines.length - 1 ? "\n" : null}
          </Fragment>
        );
      })}
    </div>
  );
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function TaskComments({
  taskId,
  currentUserId,
  canManageTasks,
}: {
  taskId: string;
  currentUserId: string;
  canManageTasks: boolean;
}) {
  const queryClient = useQueryClient();
  const queryKey = ["task-comments", taskId];
  const { data: comments, isLoading } = useQuery({
    queryKey,
    queryFn: () => api.get<TaskComment[]>(`/tasks/${taskId}/comments`),
  });

  const [newBody, setNewBody] = useState("");
  const [posting, setPosting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // A plain div, not a <form>: this component is rendered inside the Task
  // edit form in task-dialog.tsx, and nested <form> elements are invalid
  // HTML (the browser would hoist the submit and break the outer form).
  async function submitComment() {
    const body = newBody.trim();
    if (!body || posting) return;
    setPosting(true);
    try {
      await api.post<TaskComment>(`/tasks/${taskId}/comments`, { body });
      await queryClient.invalidateQueries({ queryKey });
      setNewBody("");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setPosting(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitComment();
    }
  }

  function startEdit(comment: TaskComment) {
    setEditingId(comment.id);
    setEditBody(comment.body);
  }

  async function saveEdit(commentId: string) {
    const body = editBody.trim();
    if (!body) return;
    setSavingId(commentId);
    try {
      await api.patch<TaskComment>(`/comments/${commentId}`, { body });
      await queryClient.invalidateQueries({ queryKey });
      setEditingId(null);
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setSavingId(null);
    }
  }

  async function removeComment(commentId: string) {
    setDeletingId(commentId);
    try {
      await api.delete<{ message: string }>(`/comments/${commentId}`);
      await queryClient.invalidateQueries({ queryKey });
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="text-xs font-medium text-muted-foreground">
        Комментарии{comments?.length ? ` · ${comments.length}` : ""}
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground">Загрузка…</div>
      ) : comments && comments.length > 0 ? (
        <div className="max-h-64 space-y-3 overflow-y-auto pr-1">
          {comments.map((comment) => {
            const isAuthor = comment.created_by.id === currentUserId;
            const isEditing = editingId === comment.id;
            const edited = comment.updated_at !== comment.created_at;
            return (
              <div key={comment.id} className="flex gap-2.5">
                <UserAvatar user={comment.created_by} size="xs" tone="subtle" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-1.5 text-xs">
                    <span className="font-medium text-foreground">
                      {comment.created_by.name}
                    </span>
                    <span className="text-muted-foreground">
                      {formatDateTime(comment.created_at)}
                      {edited ? " · изменено" : ""}
                    </span>
                  </div>
                  {isEditing ? (
                    <div className="mt-1.5 space-y-2">
                      <Textarea
                        value={editBody}
                        onChange={(event) => setEditBody(event.target.value)}
                        maxLength={MAX_COMMENT_LENGTH}
                        rows={3}
                        autoFocus
                      />
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => saveEdit(comment.id)}
                          disabled={savingId === comment.id}
                        >
                          {savingId === comment.id ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : null}
                          Сохранить
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setEditingId(null)}
                        >
                          <X className="size-3.5" />
                          Отмена
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <CommentBody body={comment.body} />
                  )}
                </div>
                {!isEditing && (isAuthor || canManageTasks) ? (
                  <div className="flex shrink-0 items-start gap-1">
                    {isAuthor ? (
                      <button
                        type="button"
                        onClick={() => startEdit(comment)}
                        className="rounded p-1 text-neutral-400 transition hover:bg-neutral-200 hover:text-neutral-700 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
                        aria-label="Редактировать комментарий"
                      >
                        <Pencil className="size-3.5" />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => removeComment(comment.id)}
                      disabled={deletingId === comment.id}
                      className="rounded p-1 text-neutral-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed dark:text-neutral-500 dark:hover:bg-red-950 dark:hover:text-red-400"
                      aria-label="Удалить комментарий"
                    >
                      {deletingId === comment.id ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="size-3.5" />
                      )}
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Комментариев пока нет.</p>
      )}

      <div className="flex gap-2">
        <Textarea
          value={newBody}
          onChange={(event) => setNewBody(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          placeholder="Написать комментарий… (Enter — отправить, Shift+Enter — новая строка)"
          maxLength={MAX_COMMENT_LENGTH}
          rows={2}
          className="resize-none"
        />
        <Button
          type="button"
          size="icon"
          onClick={() => void submitComment()}
          disabled={posting || !newBody.trim()}
          aria-label="Отправить комментарий"
          className="shrink-0"
        >
          {posting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Send className="size-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
