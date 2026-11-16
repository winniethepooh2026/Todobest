"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CircleDot,
  FileText,
  LayoutDashboard,
  Loader2,
  Pencil,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { TeamMembersPanel } from "@/components/members/team-members-panel";
import { CreateResourceDialog } from "@/components/modals/create-resource-dialog";
import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn, formatError } from "@/lib/utils";
import type { NavigationSpace, Team, TeamMembers } from "@/lib/types";

export default function TeamPage() {
  const params = useParams<{ teamId: string }>();
  const teamId = params.teamId;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [renameOpen, setRenameOpen] = useState(false);
  const [teamName, setTeamName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [deleteName, setDeleteName] = useState("");
  const teamQuery = useQuery({
    queryKey: ["team", teamId],
    queryFn: () => api.get<Team>(`/teams/${teamId}`),
  });
  const navigationQuery = useQuery({
    queryKey: ["navigation"],
    queryFn: () => api.get<NavigationSpace[]>("/navigation"),
  });
  const membersQuery = useQuery({
    queryKey: ["team-members", teamId],
    queryFn: () => api.get<TeamMembers>(`/teams/${teamId}/members`),
  });

  const navTeam = navigationQuery.data
    ?.flatMap((space) => space.teams)
    .find((team) => team.id === teamId);
  const canManageBoards =
    membersQuery.data?.current_user_space_role === "owner" ||
    membersQuery.data?.current_user_space_role === "admin" ||
    membersQuery.data?.current_user_team_role === "owner" ||
    membersQuery.data?.current_user_team_role === "admin";

  function openRename() {
    setTeamName(teamQuery.data?.name ?? "");
    setRenameOpen(true);
  }

  async function renameTeam() {
    const normalizedName = teamName.trim().replace(/\s+/g, " ");
    if (!normalizedName) return;
    setRenaming(true);
    try {
      const updated = await api.patch<Team>(`/teams/${teamId}`, {
        name: normalizedName,
      });
      queryClient.setQueryData(["team", teamId], updated);
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      setRenameOpen(false);
      toast.success("Команда переименована");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setRenaming(false);
    }
  }

  async function deleteTeam() {
    try {
      await api.delete(`/teams/${teamId}`, { name: deleteName });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      router.replace("/app/trash");
    } catch (error) {
      toast.error(formatError(error));
    }
  }

  if (teamQuery.isLoading || membersQuery.isLoading) {
    return (
      <div className="p-10">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="mt-8 h-44 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-12 md:px-10 md:py-16">
      <div className="flex items-center gap-2 md:hidden mb-4">
        <MobileMenuButton />
        <span className="text-sm font-medium">{teamQuery.data?.name}</span>
      </div>
      <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950">
            <LayoutDashboard className="size-5" />
          </div>
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-semibold tracking-[-0.035em]">
              {teamQuery.data?.name}
            </h1>
            {canManageBoards ? (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={openRename}
                aria-label="Переименовать команду"
                title="Переименовать команду"
              >
                <Pencil className="size-4" />
              </Button>
            ) : null}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Доски задач и страницы этой команды.
          </p>
        </div>
        <div className="flex gap-2">
          {canManageBoards ? (
            <CreateResourceDialog
              teamId={teamId}
              kind="board"
              trigger={
                <Button variant="outline">
                  <CircleDot className="size-4" />
                  Issue board
                </Button>
              }
            />
          ) : null}
          <CreateResourceDialog
            teamId={teamId}
            kind="page"
            trigger={
              <Button>
                <Plus className="size-4" />
                Page
              </Button>
            }
          />
          {navTeam?.boards[0] ? (
            <Link
              href={`/app/boards/${navTeam.boards[0].id}`}
              className={cn(
                "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors outline-none disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                "h-9 px-4 py-2 bg-primary text-primary-foreground hover:bg-primary/88",
              )}
            >
              <Plus className="size-4" />
              Новая задача
            </Link>
          ) : null}
        </div>
      </div>

      {teamQuery.data ? (
        <TeamMembersPanel teamId={teamId} spaceId={teamQuery.data.space_id} />
      ) : null}

      <section className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">Доски задач</h2>
          <span className="text-xs text-muted-foreground">
            {navTeam?.boards.length ?? 0}/3
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {navTeam?.boards.map((board) => (
            <Link
              key={board.id}
              href={`/app/boards/${board.id}`}
              className="group flex min-h-28 items-center justify-between rounded-xl border bg-card p-5 transition hover:border-neutral-300 hover:shadow-sm dark:hover:border-neutral-700"
            >
              <div>
                <div className="mb-3 inline-flex items-center gap-1.5 rounded-md bg-neutral-100 px-2 py-1 font-mono text-[11px] font-semibold dark:bg-neutral-800 dark:text-neutral-200">
                  {board.key}
                </div>
                <div className="font-medium">{board.name}</div>
              </div>
              <ArrowRight className="size-4 text-neutral-300 transition group-hover:translate-x-0.5 group-hover:text-neutral-900 dark:text-neutral-600 dark:group-hover:text-neutral-100" />
            </Link>
          ))}
          {!navTeam?.boards.length && canManageBoards ? (
            <CreateResourceDialog
              teamId={teamId}
              kind="board"
              trigger={
                <button
                  type="button"
                  className="flex min-h-28 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground transition hover:border-neutral-400 hover:text-foreground dark:border-neutral-700 dark:hover:border-neutral-600"
                >
                  <Plus className="size-4" />
                  Создать первую доску
                </button>
              }
            />
          ) : !navTeam?.boards.length ? (
            <div className="flex min-h-28 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
              В этой команде пока нет досок задач
            </div>
          ) : null}
        </div>
      </section>

      <section className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold">Страницы</h2>
          <span className="text-xs text-muted-foreground">
            {navTeam?.pages.length ?? 0}/3
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {navTeam?.pages.map((page) => (
            <Link
              key={page.id}
              href={`/app/pages/${page.id}`}
              className="group flex min-h-24 items-center justify-between rounded-xl border bg-card p-5 transition hover:border-neutral-300 hover:shadow-sm dark:hover:border-neutral-700"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-neutral-100 dark:bg-neutral-800">
                  <FileText className="size-4" />
                </div>
                <span className="font-medium">{page.title}</span>
              </div>
              <ArrowRight className="size-4 text-neutral-300 transition group-hover:translate-x-0.5 group-hover:text-neutral-900 dark:text-neutral-600 dark:group-hover:text-neutral-100" />
            </Link>
          ))}
          {!navTeam?.pages.length ? (
            <CreateResourceDialog
              teamId={teamId}
              kind="page"
              trigger={
                <button
                  type="button"
                  className="flex min-h-24 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground transition hover:border-neutral-400 hover:text-foreground dark:border-neutral-700 dark:hover:border-neutral-600"
                >
                  <Plus className="size-4" />
                  Создать первую Page
                </button>
              }
            />
          ) : null}
        </div>
      </section>

      {canManageBoards ? (
        <section className="mt-12 rounded-2xl border border-red-200 bg-card p-5 dark:border-red-900">
          <h2 className="font-medium text-red-700 dark:text-red-400">
            Удалить команду
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Команда будет перемещена в корзину вместе со скрытием её ресурсов.
          </p>
          <div className="mt-4 flex max-w-lg gap-3">
            <Input
              value={deleteName}
              onChange={(event) => setDeleteName(event.target.value)}
              placeholder={teamQuery.data?.name}
            />
            <Button
              variant="destructive"
              disabled={deleteName !== teamQuery.data?.name}
              onClick={deleteTeam}
            >
              Удалить
            </Button>
          </div>
        </section>
      ) : null}

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Переименовать команду</DialogTitle>
            <DialogDescription>
              Новое название будет видно всем участникам команды.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={teamName}
            onChange={(event) => setTeamName(event.target.value)}
            maxLength={80}
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter") void renameTeam();
            }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() => void renameTeam()}
              disabled={renaming || !teamName.trim()}
            >
              {renaming ? <Loader2 className="size-4 animate-spin" /> : null}
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
