"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  FileText,
  Loader2,
  Lock,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { PageEditor } from "@/components/editor/page-editor";
import { DEFAULT_PAGE_TITLE } from "@/components/editor/editor-utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api, ApiError } from "@/lib/api";
import type { PageDocument } from "@/lib/types";
import { formatError } from "@/lib/utils";

type SaveState = "saved" | "saving" | "error";

interface Draft {
  title: string;
  content: Record<string, unknown>;
  markdown: string;
}

function PageView({
  initialPage,
  focusTitle,
}: {
  initialPage: PageDocument;
  focusTitle: boolean;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(initialPage.title);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [hasConflict, setHasConflict] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const titleInputRef = useRef<HTMLTextAreaElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const revisionRef = useRef(0);
  const persistedRevisionRef = useRef(0);
  const flushRequestedRef = useRef(false);
  const savePromiseRef = useRef<Promise<void> | null>(null);
  const mountedRef = useRef(true);
  const removedRef = useRef(false);
  const conflictRef = useRef(false);
  const serverUpdatedAtRef = useRef(initialPage.updated_at);
  const draftRef = useRef<Draft>({
    title: initialPage.title,
    content: initialPage.content,
    markdown: initialPage.markdown,
  });

  const runSaveQueue = useCallback((): Promise<void> => {
    if (
      !initialPage.can_edit ||
      removedRef.current ||
      conflictRef.current ||
      !flushRequestedRef.current
    ) {
      if (conflictRef.current) flushRequestedRef.current = false;
      return Promise.resolve();
    }
    if (savePromiseRef.current) return savePromiseRef.current;

    flushRequestedRef.current = false;
    const revision = revisionRef.current;
    const snapshot = { ...draftRef.current };
    if (!snapshot.title.trim()) {
      if (mountedRef.current) {
        setSaveState("error");
        setSaveError("Введите название страницы");
      }
      return Promise.resolve();
    }

    if (mountedRef.current) {
      setSaveState("saving");
      setSaveError(null);
    }

    const operation = (async () => {
      try {
        const saved = await api.patch<PageDocument>(
          `/pages/${initialPage.id}`,
          {
            ...snapshot,
            expected_updated_at: serverUpdatedAtRef.current,
          },
        );
        serverUpdatedAtRef.current = saved.updated_at;
        persistedRevisionRef.current = Math.max(
          persistedRevisionRef.current,
          revision,
        );
        queryClient.setQueryData(["page", initialPage.id], saved);
        void queryClient.invalidateQueries({ queryKey: ["navigation"] });
        if (!mountedRef.current || removedRef.current) return;

        if (revision === revisionRef.current) {
          draftRef.current = {
            title: saved.title,
            content: saved.content,
            markdown: saved.markdown,
          };
          setTitle(saved.title);
          setSaveState("saved");
          setSaveError(null);
          setHasConflict(false);
        } else if (!draftRef.current.title.trim()) {
          setSaveState("error");
          setSaveError("Введите название страницы");
        } else {
          setSaveState("saving");
        }
      } catch (error) {
        if (!mountedRef.current || removedRef.current) return;
        if (error instanceof ApiError && error.status === 409) {
          conflictRef.current = true;
          flushRequestedRef.current = false;
          setHasConflict(true);
          setSaveState("error");
          setSaveError(
            "Страница изменена в другой вкладке. Обновите её перед продолжением.",
          );
          toast.error("Обнаружен конфликт изменений");
          return;
        }
        setSaveState("error");
        setSaveError(formatError(error));
        toast.error(formatError(error));
      }
    })();

    const tracked = operation.finally(() => {
      savePromiseRef.current = null;
    });
    savePromiseRef.current = tracked;
    return tracked;
  }, [initialPage.can_edit, initialPage.id, queryClient]);

  const requestFlush = useCallback(async () => {
    if (!initialPage.can_edit || removedRef.current || conflictRef.current) {
      return;
    }
    flushRequestedRef.current = true;
    do {
      await runSaveQueue();
    } while (flushRequestedRef.current && !removedRef.current);
  }, [initialPage.can_edit, runSaveQueue]);

  function scheduleSave(patch: Partial<Draft>) {
    if (!initialPage.can_edit || removedRef.current) return;
    draftRef.current = { ...draftRef.current, ...patch };
    revisionRef.current += 1;
    if (timerRef.current) clearTimeout(timerRef.current);

    if (conflictRef.current) {
      setSaveState("error");
      setHasConflict(true);
      setSaveError(
        "Страница изменена в другой вкладке. Обновите её перед продолжением.",
      );
      return;
    }

    if (!draftRef.current.title.trim()) {
      flushRequestedRef.current = false;
      setSaveState("error");
      setSaveError("Введите название страницы");
      return;
    }

    setSaveState("saving");
    setSaveError(null);
    timerRef.current = setTimeout(() => void requestFlush(), 700);
  }

  useEffect(() => {
    mountedRef.current = true;
    const hasUnsavedChanges = () =>
      persistedRevisionRef.current < revisionRef.current;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges() && !savePromiseRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden" && hasUnsavedChanges()) {
        if (timerRef.current) clearTimeout(timerRef.current);
        void requestFlush();
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      if (timerRef.current) clearTimeout(timerRef.current);
      mountedRef.current = false;
      if (
        !removedRef.current &&
        !conflictRef.current &&
        hasUnsavedChanges() &&
        draftRef.current.title.trim()
      ) {
        void requestFlush();
      }
    };
  }, [requestFlush]);

  useEffect(() => {
    if (!focusTitle || !initialPage.can_edit) return;
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
    router.replace(`/app/pages/${initialPage.id}`, { scroll: false });
  }, [focusTitle, initialPage.can_edit, initialPage.id, router]);

  useEffect(() => {
    serverUpdatedAtRef.current = initialPage.updated_at;
  }, [initialPage.updated_at]);

  useEffect(() => {
    const element = titleInputRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [title]);

  async function removePage() {
    if (
      !initialPage.can_delete ||
      !window.confirm(`Удалить страницу «${title}»?`)
    ) {
      return;
    }
    setDeleting(true);
    try {
      await api.delete<{ message: string }>(`/pages/${initialPage.id}`);
      removedRef.current = true;
      flushRequestedRef.current = false;
      persistedRevisionRef.current = revisionRef.current;
      if (timerRef.current) clearTimeout(timerRef.current);
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      toast.success("Страница удалена");
      router.push("/app");
    } catch (error) {
      toast.error(formatError(error));
      setDeleting(false);
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="flex min-h-14 items-center justify-between gap-4 border-b px-3 md:px-8">
        <div className="flex min-w-0 items-center gap-2">
          <MobileMenuButton />
          <nav
            aria-label="Навигационная цепочка"
            className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-neutral-500 dark:text-neutral-400"
          >
            <Link
              href={`/app/teams/${initialPage.team_id}`}
              className="shrink-0 transition-colors hover:text-foreground"
            >
              Team
            </Link>
            <ChevronRight className="size-3.5 shrink-0" />
            <span
              className="flex min-w-0 items-center gap-1.5"
              aria-current="page"
            >
              <FileText className="size-4 shrink-0 text-neutral-400 dark:text-neutral-500" />
              <span className="truncate">{title || DEFAULT_PAGE_TITLE}</span>
            </span>
          </nav>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {initialPage.can_edit ? (
            <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
              {saveState === "saving" ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Сохранение…
                </>
              ) : saveState === "error" ? (
                <button
                  type="button"
                  className="text-red-600 hover:underline dark:text-red-400"
                  title={saveError ?? "Изменения не сохранены"}
                  onClick={
                    hasConflict
                      ? () => window.location.reload()
                      : () => void requestFlush()
                  }
                >
                  {saveError ?? "Не сохранено"} ·{" "}
                  {hasConflict ? "обновить" : "повторить"}
                </button>
              ) : (
                <>
                  <Check className="size-3.5" />
                  Сохранено
                </>
              )}
            </span>
          ) : (
            <span
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
              title={`Автор: ${initialPage.created_by.name}`}
            >
              <UserAvatar
                user={initialPage.created_by}
                size="xs"
                tone="subtle"
                alt={`Автор: ${initialPage.created_by.name}`}
              />
              <span className="hidden max-w-32 truncate lg:inline">
                {initialPage.created_by.name}
              </span>
              <Lock className="size-3.5" />
              <span className="hidden sm:inline">Только чтение</span>
            </span>
          )}
          {initialPage.can_delete ? (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label="Удалить страницу"
              onClick={removePage}
              disabled={deleting}
              className="text-neutral-400 hover:bg-red-50 hover:text-red-600 dark:text-neutral-500 dark:hover:bg-red-950 dark:hover:text-red-400"
            >
              {deleting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
            </Button>
          ) : null}
        </div>
      </header>
      <div className="mx-auto w-full max-w-3xl px-5 pt-12 md:px-10 md:pt-16">
        <textarea
          ref={titleInputRef}
          value={title}
          onChange={
            initialPage.can_edit
              ? (event) => {
                  setTitle(event.target.value);
                  scheduleSave({ title: event.target.value });
                }
              : undefined
          }
          readOnly={!initialPage.can_edit}
          maxLength={200}
          rows={1}
          aria-label="Название страницы"
          aria-readonly={!initialPage.can_edit}
          className="block w-full resize-none overflow-hidden break-words bg-transparent text-4xl font-semibold leading-tight tracking-[-0.04em] outline-none placeholder:text-neutral-300 read-only:cursor-default md:text-5xl dark:text-neutral-100 dark:placeholder:text-neutral-600"
          placeholder={DEFAULT_PAGE_TITLE}
        />
      </div>
      <PageEditor
        initialContent={initialPage.content}
        editable={initialPage.can_edit}
        teamId={initialPage.team_id}
        onChange={
          initialPage.can_edit
            ? (content, markdown) => scheduleSave({ content, markdown })
            : undefined
        }
      />
    </div>
  );
}

export default function PageRoute() {
  const params = useParams<{ pageId: string }>();
  const searchParams = useSearchParams();
  const pageId = params.pageId;
  const query = useQuery({
    queryKey: ["page", pageId],
    queryFn: () => api.get<PageDocument>(`/pages/${pageId}`),
  });

  if (query.isLoading) {
    return (
      <div className="min-h-screen bg-background">
        <div className="flex h-16 items-center gap-3 border-b px-8">
          <Skeleton className="size-4" />
          <Skeleton className="h-5 w-48" />
        </div>
        <div className="mx-auto max-w-3xl space-y-4 px-10 py-16">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-36 w-full" />
        </div>
      </div>
    );
  }

  if (!query.data) {
    return (
      <div className="p-10 text-sm text-muted-foreground">
        Страница не найдена.
      </div>
    );
  }

  return (
    <PageView
      key={query.data.id}
      initialPage={query.data}
      focusTitle={searchParams.get("new") === "1"}
    />
  );
}
