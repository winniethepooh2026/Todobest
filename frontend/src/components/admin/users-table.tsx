"use client";

import {
  LogOut,
  Loader2,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  UserX,
} from "lucide-react";
import Link from "next/link";

import { Panel, PanelEmpty } from "@/components/admin/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/ui/user-avatar";
import { formatDateTime } from "@/lib/format";
import type { AdminUser } from "@/lib/types";

function UserIdentity({ user }: { user: AdminUser }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <UserAvatar user={user} size="sm" />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <Link
            href={`/app/admin/users/${user.id}`}
            className="truncate font-medium underline-offset-2 hover:underline"
          >
            {user.name}
          </Link>
          {user.is_platform_admin ? <Badge>Администратор</Badge> : null}
        </div>
        <div className="truncate text-xs text-muted-foreground">
          {user.email}
        </div>
      </div>
    </div>
  );
}

function ToggleAdminButton({
  user,
  pending,
  onToggle,
}: {
  user: AdminUser;
  pending: boolean;
  onToggle: (user: AdminUser) => void;
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => onToggle(user)}
      disabled={pending}
    >
      {pending ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : user.is_platform_admin ? (
        <ShieldOff className="size-3.5" />
      ) : (
        <ShieldCheck className="size-3.5" />
      )}
      {user.is_platform_admin ? "Снять" : "Назначить"}
    </Button>
  );
}

export function UsersTable({
  users,
  total,
  loading,
  searching,
  pendingUserId,
  onToggleAdmin,
  onToggleActive,
  onForceLogout,
}: {
  users: AdminUser[];
  total: number;
  loading: boolean;
  searching: boolean;
  pendingUserId: string | null;
  onToggleAdmin: (user: AdminUser) => void;
  onToggleActive: (user: AdminUser) => void;
  onForceLogout: (user: AdminUser) => void;
}) {
  return (
    <Panel title={`Пользователи (${total})`}>
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      ) : users.length === 0 ? (
        <PanelEmpty>
          {searching ? "Ничего не найдено." : "Пользователей пока нет."}
        </PanelEmpty>
      ) : (
        <>
          {/* Desktop */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Пользователь</th>
                  <th className="py-2 pr-4 font-medium">Регистрация</th>
                  <th className="py-2 pr-4 font-medium">Последний вход</th>
                  <th className="py-2 pr-4 font-medium">Spaces / Teams</th>
                  <th className="py-2 pr-0 font-medium">Права</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr
                    key={user.id}
                    className="border-b last:border-0 hover:bg-neutral-50 dark:hover:bg-neutral-900/60"
                  >
                    <td className="py-3 pr-4">
                      <UserIdentity user={user} />
                    </td>
                    <td className="whitespace-nowrap py-3 pr-4 text-muted-foreground">
                      {formatDateTime(user.created_at)}
                    </td>
                    <td className="whitespace-nowrap py-3 pr-4 text-muted-foreground">
                      {formatDateTime(user.last_login_at)}
                    </td>
                    <td className="py-3 pr-4 text-muted-foreground">
                      {user.space_count} / {user.team_count}
                    </td>
                    <td className="py-3 pr-0">
                      <div className="flex gap-1">
                        <ToggleAdminButton
                          user={user}
                          pending={pendingUserId === user.id}
                          onToggle={onToggleAdmin}
                        />
                        <Button
                          variant="outline"
                          size="icon-sm"
                          title={
                            user.is_active ? "Деактивировать" : "Активировать"
                          }
                          disabled={pendingUserId === user.id}
                          onClick={() => onToggleActive(user)}
                        >
                          {user.is_active ? (
                            <UserX className="size-3.5" />
                          ) : (
                            <UserCheck className="size-3.5" />
                          )}
                        </Button>
                        <Button
                          variant="outline"
                          size="icon-sm"
                          title="Завершить все сессии"
                          disabled={pendingUserId === user.id}
                          onClick={() => onForceLogout(user)}
                        >
                          <LogOut className="size-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile */}
          <div className="flex flex-col gap-2 md:hidden">
            {users.map((user) => (
              <div key={user.id} className="rounded-xl border p-3">
                <UserIdentity user={user} />
                <div className="mt-3 grid grid-cols-2 gap-y-1.5 text-xs">
                  <div>
                    <div className="text-muted-foreground">Регистрация</div>
                    <div>{formatDateTime(user.created_at)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Последний вход</div>
                    <div>{formatDateTime(user.last_login_at)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Spaces / Teams</div>
                    <div>
                      {user.space_count} / {user.team_count}
                    </div>
                  </div>
                </div>
                <div className="mt-3">
                  <ToggleAdminButton
                    user={user}
                    pending={pendingUserId === user.id}
                    onToggle={onToggleAdmin}
                  />
                  <div className="mt-2 flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onToggleActive(user)}
                    >
                      {user.is_active ? "Деактивировать" : "Активировать"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onForceLogout(user)}
                    >
                      Выйти везде
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}
