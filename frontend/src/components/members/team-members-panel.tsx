"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, UserPlus, Users } from "lucide-react";
import { FormEvent, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import type {
  Invitation,
  TeamMember,
  TeamMembers,
  TeamRole,
} from "@/lib/types";
import { formatError } from "@/lib/utils";

const roleLabel: Record<TeamRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

export function TeamMembersPanel({
  teamId,
  spaceId,
}: {
  teamId: string;
  spaceId: string;
}) {
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [newRole, setNewRole] = useState<TeamRole>("member");
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const membersQuery = useQuery({
    queryKey: ["team-members", teamId],
    queryFn: () => api.get<TeamMembers>(`/teams/${teamId}/members`),
  });
  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["team-members", teamId] }),
      queryClient.invalidateQueries({ queryKey: ["navigation"] }),
      queryClient.invalidateQueries({ queryKey: ["board"] }),
    ]);
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    if (!inviteEmail) return;
    setAdding(true);
    try {
      await api.post<Invitation>(`/spaces/${spaceId}/invitations`, {
        email: inviteEmail,
        team_id: teamId,
        role: newRole,
      });
      await refresh();
      setInviteEmail("");
      setNewRole("member");
      setAddOpen(false);
      toast.success("Приглашение в Team отправлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setAdding(false);
    }
  }

  async function updateRole(member: TeamMember, role: TeamRole) {
    setBusyUserId(member.user_id);
    try {
      await api.patch<TeamMember>(
        `/teams/${teamId}/members/${member.user_id}`,
        { role },
      );
      await refresh();
      toast.success("Роль обновлена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setBusyUserId(null);
    }
  }

  async function removeMember(member: TeamMember) {
    if (!window.confirm(`Удалить ${member.name} из Team?`)) return;
    setBusyUserId(member.user_id);
    try {
      await api.delete<{ message: string }>(
        `/teams/${teamId}/members/${member.user_id}`,
      );
      await refresh();
      toast.success("Участник удалён из Team");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setBusyUserId(null);
    }
  }

  if (membersQuery.isLoading) {
    return <Skeleton className="mt-10 h-48 w-full" />;
  }

  const permissions = membersQuery.data;

  return (
    <section className="mt-10 rounded-xl border bg-card p-5">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Users className="size-4" />
            <h2 className="font-semibold">Участники Team</h2>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Исполнителем Issue может быть только участник этой Team.
          </p>
        </div>

        {permissions?.can_manage_members ? (
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <UserPlus className="size-4" />
                Добавить
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Добавить в Team</DialogTitle>
                <DialogDescription>
                  Одно приглашение добавит пользователя и в Team, и в
                  родительский Space.
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={addMember} className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor={`team-member-user-${teamId}`}>Email</Label>
                  <Input
                    id={`team-member-user-${teamId}`}
                    type="email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor={`team-member-role-${teamId}`}>Роль</Label>
                  <select
                    id={`team-member-role-${teamId}`}
                    value={newRole}
                    onChange={(event) =>
                      setNewRole(event.target.value as TeamRole)
                    }
                    className="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200"
                  >
                    <option value="member">Участник</option>
                    <option value="admin">Администратор</option>
                    {permissions.can_manage_owner_role ? (
                      <option value="owner">Владелец</option>
                    ) : null}
                  </select>
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setAddOpen(false)}
                  >
                    Отмена
                  </Button>
                  <Button type="submit" disabled={adding || !inviteEmail}>
                    {adding ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : null}
                    Добавить
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        ) : null}
      </div>

      <div className="mt-5 divide-y">
        {permissions?.members.map((member) => {
          const ownerCount = permissions.members.filter(
            (candidate) => candidate.role === "owner",
          ).length;
          const isLastOwner = member.role === "owner" && ownerCount === 1;
          const canManageTarget =
            permissions.can_manage_members &&
            (member.role !== "owner" || permissions.can_manage_owner_role);
          const loading = busyUserId === member.user_id;
          return (
            <div
              key={member.user_id}
              className="flex flex-col justify-between gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center"
            >
              <div className="flex min-w-0 items-center gap-3">
                <UserAvatar user={member} size="md" tone="subtle" />
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <div className="truncate text-sm font-medium">
                      {member.name}
                    </div>
                    {!member.is_active ? (
                      <Badge variant="warning" className="shrink-0">
                        Неактивен
                      </Badge>
                    ) : null}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {member.email}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {canManageTarget ? (
                  <>
                    <select
                      value={member.role}
                      onChange={(event) =>
                        updateRole(member, event.target.value as TeamRole)
                      }
                      disabled={loading || isLastOwner}
                      className="h-8 rounded-md border bg-background px-2 text-xs outline-none disabled:opacity-60"
                      aria-label={`Роль ${member.name}`}
                    >
                      <option value="member">Участник</option>
                      <option value="admin">Администратор</option>
                      <option
                        value="owner"
                        disabled={!permissions.can_manage_owner_role}
                      >
                        Owner
                      </option>
                    </select>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={loading || isLastOwner}
                      onClick={() => removeMember(member)}
                      aria-label={
                        isLastOwner
                          ? "Нельзя удалить последнего owner"
                          : `Удалить ${member.name}`
                      }
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
                    variant={member.role === "owner" ? "default" : "secondary"}
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
  );
}
