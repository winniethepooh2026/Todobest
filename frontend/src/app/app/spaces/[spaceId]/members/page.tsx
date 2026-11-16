"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, Loader2, Shield, Trash2, Users } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AddSpaceMemberDialog } from "@/components/members/add-space-member-dialog";
import { PendingInvitations } from "@/components/members/pending-invitations";
import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import type {
  Space,
  SpaceMember,
  SpaceMembers,
  SpaceRole,
  User,
} from "@/lib/types";
import { formatError } from "@/lib/utils";

const roleLabel: Record<SpaceRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

export default function SpaceMembersPage() {
  const params = useParams<{ spaceId: string }>();
  const spaceId = params.spaceId;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<SpaceMember | null>(null);
  const [deleteName, setDeleteName] = useState("");
  const [deletingSpace, setDeletingSpace] = useState(false);
  const [exporting, setExporting] = useState(false);

  async function exportSpace() {
    setExporting(true);
    try {
      await api.post(`/spaces/${spaceId}/exports`);
      toast.success("Экспорт поставлен в очередь. Ссылка придёт на email.");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setExporting(false);
    }
  }

  async function deleteSpace() {
    setDeletingSpace(true);
    try {
      await api.delete(`/spaces/${spaceId}`, { name: deleteName });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      router.replace("/app/trash");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setDeletingSpace(false);
    }
  }

  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });
  const spaceQuery = useQuery({
    queryKey: ["space", spaceId],
    queryFn: () => api.get<Space>(`/spaces/${spaceId}`),
  });
  const membersQuery = useQuery({
    queryKey: ["space-members", spaceId],
    queryFn: () => api.get<SpaceMembers>(`/spaces/${spaceId}/members`),
  });

  const members = membersQuery.data?.members ?? [];
  const currentRole = membersQuery.data?.current_user_role;
  const canManage = membersQuery.data?.can_manage_members ?? false;
  const ownerCount = members.filter((member) => member.role === "owner").length;

  function canManageTarget(member: SpaceMember) {
    return (
      canManage &&
      (currentRole === "owner" || member.role !== "owner") &&
      !(member.role === "owner" && ownerCount === 1)
    );
  }

  async function updateRole(member: SpaceMember, role: SpaceRole) {
    setBusyUserId(member.user_id);
    try {
      await api.patch<SpaceMember>(
        `/spaces/${spaceId}/members/${member.user_id}`,
        { role },
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["space-members", spaceId],
        }),
        queryClient.invalidateQueries({ queryKey: ["navigation"] }),
      ]);
      toast.success("Роль обновлена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setBusyUserId(null);
    }
  }

  async function removeMember() {
    if (!removeTarget) return;
    setBusyUserId(removeTarget.user_id);
    try {
      await api.delete<{ message: string }>(
        `/spaces/${spaceId}/members/${removeTarget.user_id}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["space-members", spaceId],
        }),
        queryClient.invalidateQueries({ queryKey: ["navigation"] }),
      ]);
      setRemoveTarget(null);
      toast.success("Участник удалён");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setBusyUserId(null);
    }
  }

  if (spaceQuery.isLoading || membersQuery.isLoading) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-12 md:px-10 md:py-16">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="mt-8 h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-12 md:px-10 md:py-16">
      <div className="flex items-center gap-2 md:hidden mb-4">
        <MobileMenuButton />
        <span className="text-sm font-medium">Участники Space</span>
      </div>
      <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950">
            <Users className="size-5" />
          </div>
          <p className="text-sm text-muted-foreground">
            {spaceQuery.data?.name}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">
            Участники Space
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Доступ к пространству нужен для работы в его командах.
          </p>
        </div>
        {canManage && currentRole ? (
          <AddSpaceMemberDialog
            spaceId={spaceId}
            currentUserRole={currentRole}
          />
        ) : null}
      </div>

      <section className="mt-10 overflow-hidden rounded-2xl border bg-card">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 className="font-medium">Участники</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {members.length} участник{members.length === 1 ? "" : "ов"}
            </p>
          </div>
          {currentRole ? (
            <Badge variant={currentRole === "owner" ? "default" : "secondary"}>
              Ваша роль: {roleLabel[currentRole]}
            </Badge>
          ) : null}
        </div>

        <div className="divide-y">
          {members.map((member) => {
            const manageable = canManageTarget(member);
            const loading = busyUserId === member.user_id;
            return (
              <div
                key={member.user_id}
                className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <UserAvatar user={member} size="md" tone="subtle" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {member.name}
                      </span>
                      {member.user_id === user?.id ? (
                        <Badge variant="outline">Вы</Badge>
                      ) : null}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {member.email}
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-3 sm:justify-end">
                  <div className="hidden items-center gap-1.5 text-xs text-muted-foreground md:flex">
                    {member.role === "owner" ? (
                      <Crown className="size-3.5" />
                    ) : (
                      <Shield className="size-3.5" />
                    )}
                    С{" "}
                    {new Intl.DateTimeFormat("ru-RU", {
                      dateStyle: "medium",
                    }).format(new Date(member.created_at))}
                  </div>

                  {canManage ? (
                    <>
                      <select
                        value={member.role}
                        onChange={(event) =>
                          updateRole(member, event.target.value as SpaceRole)
                        }
                        disabled={!manageable || loading}
                        aria-label={`Роль ${member.name}`}
                        className="h-8 rounded-md border bg-background px-2 text-xs outline-none disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <option value="member">Участник</option>
                        <option value="admin">Администратор</option>
                        <option
                          value="owner"
                          disabled={currentRole !== "owner"}
                        >
                          Owner
                        </option>
                      </select>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={!manageable || loading}
                        onClick={() => setRemoveTarget(member)}
                        aria-label={`Удалить ${member.name}`}
                      >
                        {loading ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="size-3.5 text-red-600 dark:text-red-400" />
                        )}
                      </Button>
                    </>
                  ) : (
                    <Badge
                      variant={
                        member.role === "owner" ? "default" : "secondary"
                      }
                    >
                      {roleLabel[member.role]}
                    </Badge>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
      {canManage ? <PendingInvitations spaceId={spaceId} /> : null}
      <section className="mt-6 rounded-2xl border bg-card p-5">
        <h2 className="font-medium">Экспорт данных</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          ZIP содержит JSON-структуру, Markdown страниц, задачи с комментариями
          и изображения.
        </p>
        <Button
          className="mt-4"
          variant="outline"
          onClick={exportSpace}
          disabled={exporting}
        >
          {exporting ? <Loader2 className="size-4 animate-spin" /> : null}
          Создать экспорт
        </Button>
      </section>
      {currentRole === "owner" ? (
        <section className="mt-6 rounded-2xl border border-red-200 bg-card p-5 dark:border-red-900">
          <h2 className="font-medium text-red-700 dark:text-red-400">
            Удалить Space
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Введите точное название. Space будет перемещён в корзину.
          </p>
          <div className="mt-4 flex max-w-lg gap-3">
            <Input
              value={deleteName}
              onChange={(event) => setDeleteName(event.target.value)}
              placeholder={spaceQuery.data?.name}
            />
            <Button
              variant="destructive"
              disabled={deletingSpace || deleteName !== spaceQuery.data?.name}
              onClick={deleteSpace}
            >
              Удалить
            </Button>
          </div>
        </section>
      ) : null}

      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить участника?</DialogTitle>
            <DialogDescription>
              {removeTarget?.name} потеряет доступ к пространству и всем его
              командам.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveTarget(null)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={removeMember}
              disabled={
                removeTarget !== null && busyUserId === removeTarget.user_id
              }
            >
              {removeTarget !== null && busyUserId === removeTarget.user_id ? (
                <Loader2 className="size-4 animate-spin" />
              ) : null}
              Удалить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
