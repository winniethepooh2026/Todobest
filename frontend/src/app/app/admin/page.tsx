"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Layers3, Search, ShieldCheck, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { FunnelPanel } from "@/components/admin/funnel-panel";
import { MetricCard } from "@/components/admin/metric-card";
import { RegistrationsPanel } from "@/components/admin/registrations-panel";
import { UsersTable } from "@/components/admin/users-table";
import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { adminPatch, api, ApiError } from "@/lib/api";
import { formatCount } from "@/lib/format";
import type {
  AdminFunnel,
  AdminOverview,
  AdminRegistrations,
  AdminUser,
  AdminUsersPage,
} from "@/lib/types";
import { formatError } from "@/lib/utils";

const USERS_PAGE_LIMIT = 20;
const SEARCH_DEBOUNCE_MS = 300;

export default function AdminPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);

  useEffect(() => {
    const timeout = setTimeout(
      () => setDebouncedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timeout);
  }, [search]);

  const [lastSearchForOffset, setLastSearchForOffset] =
    useState(debouncedSearch);
  if (debouncedSearch !== lastSearchForOffset) {
    setLastSearchForOffset(debouncedSearch);
    setOffset(0);
  }

  const overviewQuery = useQuery({
    queryKey: ["admin", "overview"],
    queryFn: () => api.get<AdminOverview>("/admin/overview"),
  });
  const funnelQuery = useQuery({
    queryKey: ["admin", "funnel"],
    queryFn: () => api.get<AdminFunnel>("/admin/funnel"),
    enabled: overviewQuery.isSuccess,
  });
  const registrationsQuery = useQuery({
    queryKey: ["admin", "registrations"],
    queryFn: () =>
      api.get<AdminRegistrations>("/admin/registrations-timeseries?days=30"),
    enabled: overviewQuery.isSuccess,
  });
  const usersQuery = useQuery({
    queryKey: ["admin", "users", debouncedSearch, offset],
    queryFn: () =>
      api.get<AdminUsersPage>(
        `/admin/users?limit=${USERS_PAGE_LIMIT}&offset=${offset}${
          debouncedSearch ? `&q=${encodeURIComponent(debouncedSearch)}` : ""
        }`,
      ),
    enabled: overviewQuery.isSuccess,
  });

  const forbidden =
    overviewQuery.error instanceof ApiError &&
    overviewQuery.error.status === 403;

  useEffect(() => {
    if (forbidden) router.replace("/app");
  }, [forbidden, router]);

  async function toggleAdmin(user: AdminUser) {
    setPendingUserId(user.id);
    try {
      await adminPatch<AdminUser>(`/admin/users/${user.id}`, {
        is_platform_admin: !user.is_platform_admin,
      });
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(
        user.is_platform_admin ? "Права админа сняты" : "Права админа выданы",
      );
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setPendingUserId(null);
    }
  }

  async function toggleActive(user: AdminUser) {
    setPendingUserId(user.id);
    try {
      await adminPatch<AdminUser>(`/admin/users/${user.id}`, {
        is_active: !user.is_active,
      });
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(
        user.is_active
          ? "Пользователь деактивирован"
          : "Пользователь активирован",
      );
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setPendingUserId(null);
    }
  }

  async function forceLogout(user: AdminUser) {
    setPendingUserId(user.id);
    try {
      await adminPatch<AdminUser>(`/admin/users/${user.id}`, {
        force_logout: true,
      });
      toast.success("Все сессии пользователя завершены");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setPendingUserId(null);
    }
  }

  if (forbidden) return null;

  const overview = overviewQuery.data;
  const usersPage = usersQuery.data;
  const usersLoading = usersQuery.isLoading || usersQuery.isFetching;
  const rangeStart = offset + 1;
  const rangeEnd = usersPage
    ? Math.min(offset + usersPage.items.length, usersPage.total)
    : 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-12 md:px-10 md:py-16">
      <div className="mb-6 flex items-center gap-2 md:hidden">
        <MobileMenuButton />
        <span className="text-sm font-medium text-neutral-500">
          Администрирование
        </span>
      </div>
      <p className="text-sm text-muted-foreground">Администрирование</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">
        Панель администратора
      </h1>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {overview ? (
          <>
            <MetricCard
              label="Пользователи"
              value={formatCount(overview.total_users)}
              caption={`+${formatCount(overview.new_users_7d)} за 7д · +${formatCount(overview.new_users_30d)} за 30д`}
              icon={Users}
            />
            <MetricCard
              label="Активны за 7д"
              value={formatCount(overview.active_users_7d)}
              caption={`${formatCount(overview.active_users_24h)} за 24ч · ${formatCount(overview.active_users_30d)} за 30д`}
              icon={ShieldCheck}
            />
            <MetricCard
              label="Spaces / Teams"
              value={`${formatCount(overview.total_spaces)} / ${formatCount(overview.total_teams)}`}
              icon={Layers3}
            />
            <MetricCard
              label="Boards / Pages / Tasks"
              value={`${formatCount(overview.total_boards)} / ${formatCount(overview.total_pages)} / ${formatCount(overview.total_tasks)}`}
              icon={FileText}
            />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 rounded-2xl" />
          ))
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <FunnelPanel
          steps={funnelQuery.data?.steps}
          loading={funnelQuery.isLoading}
        />
        <RegistrationsPanel
          points={registrationsQuery.data?.points}
          loading={registrationsQuery.isLoading}
        />
      </div>

      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по имени или email"
              className="pl-9"
            />
          </div>
          {usersPage && usersPage.total > 0 ? (
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>
                {usersPage.total === 0
                  ? null
                  : `${rangeStart}–${rangeEnd} из ${usersPage.total}`}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() =>
                    setOffset((value) => Math.max(0, value - USERS_PAGE_LIMIT))
                  }
                >
                  Назад
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset + USERS_PAGE_LIMIT >= usersPage.total}
                  onClick={() => setOffset((value) => value + USERS_PAGE_LIMIT)}
                >
                  Вперёд
                </Button>
              </div>
            </div>
          ) : null}
        </div>

        <UsersTable
          users={usersPage?.items ?? []}
          total={usersPage?.total ?? 0}
          loading={usersLoading}
          searching={debouncedSearch.length > 0}
          pendingUserId={pendingUserId}
          onToggleAdmin={toggleAdmin}
          onToggleActive={toggleActive}
          onForceLogout={forceLogout}
        />
      </div>
    </div>
  );
}
