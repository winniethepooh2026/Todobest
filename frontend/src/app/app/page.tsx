"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CircleDot, FileText, Layers3, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { CreateSpaceDialog } from "@/components/modals/create-space-dialog";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/user-avatar";
import { api } from "@/lib/api";
import { ONBOARDING_SKIPPED_KEY } from "@/lib/onboarding";
import type { NavigationSpace, User } from "@/lib/types";

export default function OverviewPage() {
  const router = useRouter();
  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });
  const { data: navigation, isLoading: navigationLoading } = useQuery({
    queryKey: ["navigation"],
    queryFn: () => api.get<NavigationSpace[]>("/navigation"),
  });

  const needsOnboarding =
    !navigationLoading &&
    !!navigation &&
    navigation.length === 0 &&
    typeof window !== "undefined" &&
    !localStorage.getItem(ONBOARDING_SKIPPED_KEY);

  useEffect(() => {
    if (needsOnboarding) router.replace("/app/onboarding");
  }, [needsOnboarding, router]);

  const teams = (navigation ?? []).flatMap((space) => space.teams);
  const boards = teams.flatMap((team) => team.boards);
  const pages = teams.flatMap((team) => team.pages);

  return (
    <div className="mx-auto max-w-6xl px-6 py-12 md:px-10 md:py-16">
      <div className="flex items-center gap-2 md:hidden mb-6">
        <MobileMenuButton />
        <span className="text-sm font-medium text-neutral-500">Обзор</span>
      </div>
      <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
        <div className="flex items-center gap-4">
          {user ? <UserAvatar user={user} size="lg" tone="subtle" /> : null}
          <div>
            <p className="text-sm text-muted-foreground">Обзор</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-[-0.035em]">
              Привет, {user?.name.split(" ")[0] ?? ""}
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              Здесь собрана краткая картина вашего пространства Noki.
            </p>
          </div>
        </div>
        <CreateSpaceDialog
          trigger={
            <Button>
              <Plus className="size-4" />
              Новое пространство
            </Button>
          }
        />
      </div>

      <div className="mt-10 grid gap-4 sm:grid-cols-3">
        {[
          { label: "Команды", value: teams.length, icon: Layers3 },
          { label: "Доски задач", value: boards.length, icon: CircleDot },
          { label: "Страницы", value: pages.length, icon: FileText },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-2xl border bg-card p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">{label}</span>
              <Icon className="size-4 text-neutral-400" />
            </div>
            <div className="mt-6 text-3xl font-semibold tracking-tight">
              {value}
            </div>
          </div>
        ))}
      </div>

      <section className="mt-12">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold tracking-tight">Ваши команды</h2>
          <span className="text-xs text-muted-foreground">
            Команд: {teams.length}
          </span>
        </div>
        {teams.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {teams.map((team) => (
              <Link
                key={team.id}
                href={`/app/teams/${team.id}`}
                className="group flex items-center justify-between rounded-xl border bg-card p-5 transition hover:border-neutral-300 hover:shadow-sm"
              >
                <div>
                  <div className="font-medium">{team.name}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {team.boards.length} досок · {team.pages.length} страниц
                  </div>
                </div>
                <ArrowUpRight className="size-4 text-neutral-400 transition group-hover:text-neutral-900" />
              </Link>
            ))}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed px-6 py-14 text-center">
            <Layers3 className="mx-auto size-7 text-neutral-300" />
            <h3 className="mt-4 font-medium">Пока нет ни одной команды</h3>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
              Сначала создайте пространство через кнопку выше, затем добавьте
              команду в боковой панели.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
