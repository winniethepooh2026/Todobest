"use client";

import {
  ChevronDown,
  CircleDot,
  CheckCircle2,
  FileText,
  LayoutDashboard,
  LogOut,
  PanelLeftClose,
  Plus,
  Settings,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";

import { CreateSpaceDialog } from "@/components/modals/create-space-dialog";
import { CreateTeamDialog } from "@/components/modals/create-team-dialog";
import { Button } from "@/components/ui/button";
import { UserAvatar } from "@/components/ui/user-avatar";
import { ThemeToggle } from "@/components/theme-toggle";
import type { NavigationSpace, User } from "@/lib/types";
import { cn } from "@/lib/utils";

export const MIN_SIDEBAR_WIDTH = 220;
export const MAX_SIDEBAR_WIDTH = 420;
export const DEFAULT_SIDEBAR_WIDTH = 268;
// Dragging past this while resizing collapses the panel instead of pinning
// it at a tiny width; below MIN_SIDEBAR_WIDTH but above this just snaps
// back up to MIN_SIDEBAR_WIDTH on release.
const COLLAPSE_DRAG_THRESHOLD = 160;
// Visual floor while actively dragging, so the panel keeps shrinking
// smoothly toward the collapsed strip's width instead of stopping dead at
// MIN_SIDEBAR_WIDTH.
const DRAG_VISUAL_FLOOR = 56;

function NavLink({
  href,
  icon: Icon,
  children,
  nested = false,
}: {
  href: string;
  icon: React.ElementType;
  children: React.ReactNode;
  nested?: boolean;
}) {
  const pathname = usePathname();
  const active = pathname === href;
  return (
    <Link
      href={href}
      className={cn(
        "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-neutral-600 transition hover:bg-neutral-200/65 hover:text-neutral-950 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100",
        active &&
          "bg-neutral-200/75 font-medium text-neutral-950 dark:bg-neutral-800 dark:text-neutral-100",
        nested && "pl-3 text-[13px]",
      )}
    >
      <Icon className={cn("size-4 shrink-0", nested && "size-3.5")} />
      <span className="truncate">{children}</span>
    </Link>
  );
}

export function Sidebar({
  user,
  navigation,
  open,
  onOpenChange,
  desktopOpen,
  onDesktopOpenChange,
  desktopPeek = false,
  onDesktopPeekChange,
  width,
  onWidthChange,
  onLogout,
}: {
  user: User;
  navigation: NavigationSpace[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  desktopOpen: boolean;
  onDesktopOpenChange: (open: boolean) => void;
  desktopPeek?: boolean;
  onDesktopPeekChange?: (peek: boolean) => void;
  width: number;
  onWidthChange: (width: number) => void;
  onLogout: () => void;
}) {
  const peeking = desktopPeek && !desktopOpen;
  const resizingRef = useRef(false);
  const [collapsedSpaceIds, setCollapsedSpaceIds] = useState<Set<string>>(
    () => new Set(),
  );

  function toggleSpaceCollapsed(spaceId: string) {
    setCollapsedSpaceIds((current) => {
      const next = new Set(current);
      if (next.has(spaceId)) {
        next.delete(spaceId);
      } else {
        next.add(spaceId);
      }
      return next;
    });
  }

  function startResize(event: React.MouseEvent) {
    event.preventDefault();
    resizingRef.current = true;
    const widthBeforeDrag = width;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function handleMouseMove(moveEvent: MouseEvent) {
      if (!resizingRef.current) return;
      // Let it visually shrink past MIN while dragging, toward the
      // collapsed-strip width, so pulling to the edge feels continuous.
      const next = Math.min(
        MAX_SIDEBAR_WIDTH,
        Math.max(DRAG_VISUAL_FLOOR, moveEvent.clientX),
      );
      onWidthChange(next);
    }
    function handleMouseUp(upEvent: MouseEvent) {
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);

      const finalWidth = Math.min(
        MAX_SIDEBAR_WIDTH,
        Math.max(DRAG_VISUAL_FLOOR, upEvent.clientX),
      );
      if (finalWidth < COLLAPSE_DRAG_THRESHOLD) {
        // Dragged past the edge: collapse, and keep the last real width in
        // storage so reopening (button or hover) doesn't restore a sliver.
        onWidthChange(widthBeforeDrag);
        onDesktopOpenChange(false);
      } else {
        onWidthChange(Math.max(MIN_SIDEBAR_WIDTH, finalWidth));
      }
    }
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  }

  return (
    <>
      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={() => onOpenChange(false)}
          aria-label="Закрыть меню"
        />
      ) : null}
      <aside
        style={{ width }}
        onMouseLeave={peeking ? () => onDesktopPeekChange?.(false) : undefined}
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex h-dvh min-h-0 flex-col border-r bg-[#f4f4f2] transition-transform duration-200 dark:border-neutral-800 dark:bg-neutral-950",
          open ? "translate-x-0" : "-translate-x-full",
          desktopOpen
            ? "md:relative md:z-auto md:h-full md:shrink-0 md:translate-x-0 md:rounded-2xl md:border md:shadow-none"
            : peeking
              ? "md:fixed md:inset-y-auto md:left-2 md:top-16 md:bottom-2 md:z-50 md:h-auto md:translate-x-0 md:rounded-2xl md:border md:shadow-2xl"
              : "md:fixed md:z-50 md:-translate-x-full md:shadow-2xl",
        )}
      >
        {desktopOpen ? (
          <div
            onMouseDown={startResize}
            className="group/resize absolute -right-1 top-0 z-10 hidden h-full w-2 cursor-col-resize md:block"
          >
            <div className="mx-auto h-full w-px bg-transparent transition-colors group-hover/resize:bg-neutral-300 dark:group-hover/resize:bg-neutral-700" />
          </div>
        ) : null}
        <div className="flex h-14 items-center justify-between px-3">
          <Link
            href="/app"
            className="flex items-center gap-2 px-1 font-semibold"
          >
            <Image src="/noki-mark.svg" alt="" width={28} height={28} />
            Noki
          </Link>
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            onClick={() => onOpenChange(false)}
          >
            <X className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="hidden md:inline-flex"
            onClick={() =>
              peeking
                ? onDesktopPeekChange?.(false)
                : onDesktopOpenChange(false)
            }
            aria-label="Скрыть боковую панель"
            title="Скрыть боковую панель"
          >
            <PanelLeftClose className="size-4" />
          </Button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-5">
          <button
            type="button"
            onClick={() =>
              window.dispatchEvent(new Event("noki:open-command-palette"))
            }
            className="mb-3 flex h-9 w-full items-center gap-2 rounded-lg border bg-background/70 px-2.5 text-sm text-muted-foreground transition hover:bg-background hover:text-foreground"
          >
            <Search className="size-4" />
            <span className="flex-1 text-left">Поиск</span>
            <kbd className="rounded border px-1.5 py-0.5 text-[10px]">⌘K</kbd>
          </button>
          <div className="space-y-1">
            <NavLink href="/app" icon={LayoutDashboard}>
              Обзор
            </NavLink>
            <NavLink href="/app/my-issues" icon={CircleDot}>
              Мои задачи
            </NavLink>
            <NavLink href="/app/my-todos" icon={CheckCircle2}>
              Мои дела
            </NavLink>
            {user.is_platform_admin ? (
              <NavLink href="/app/admin" icon={ShieldCheck}>
                Администрирование
              </NavLink>
            ) : null}
          </div>

          <div className="mt-6 flex items-center justify-between px-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">
              Пространства
            </span>
            <CreateSpaceDialog />
          </div>

          <div className="mt-2 space-y-4">
            {navigation.map((space) => {
              const collapsed = collapsedSpaceIds.has(space.id);
              return (
                <div key={space.id}>
                  <div className="group mb-1 flex h-7 items-center justify-between rounded-md px-2 text-xs font-medium text-neutral-500 dark:text-neutral-400">
                    <button
                      type="button"
                      onClick={() => toggleSpaceCollapsed(space.id)}
                      className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 py-1 text-left"
                      aria-expanded={!collapsed}
                      aria-label={
                        collapsed
                          ? `Показать ${space.name}`
                          : `Свернуть ${space.name}`
                      }
                    >
                      <ChevronDown
                        className={cn(
                          "size-3 shrink-0 transition-transform",
                          collapsed && "-rotate-90",
                        )}
                      />
                      <span className="truncate">{space.name}</span>
                    </button>
                    <span className="flex items-center">
                      <Link
                        href={`/app/spaces/${space.id}/members`}
                        className="rounded p-1 text-neutral-400 transition hover:bg-neutral-200 hover:text-neutral-700 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
                        aria-label={`Участники ${space.name}`}
                      >
                        <Users className="size-3.5" />
                      </Link>
                      {space.role === "owner" || space.role === "admin" ? (
                        <Link
                          href={`/app/spaces/${space.id}/settings`}
                          className="rounded p-1 text-neutral-400 transition hover:bg-neutral-200 hover:text-neutral-700 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
                          aria-label={`Настройки ${space.name}`}
                        >
                          <Settings className="size-3.5" />
                        </Link>
                      ) : null}
                      {space.role === "owner" || space.role === "admin" ? (
                        <CreateTeamDialog spaceId={space.id} />
                      ) : null}
                    </span>
                  </div>
                  {!collapsed ? (
                    <div className="space-y-0.5">
                      {space.teams.map((team) => (
                        <div key={team.id} className="mb-2">
                          <NavLink
                            href={`/app/teams/${team.id}`}
                            icon={LayoutDashboard}
                            nested
                          >
                            {team.name}
                          </NavLink>
                          <div className="ml-5 mt-0.5 space-y-0.5 border-l pl-1.5">
                            {team.boards.map((board) => (
                              <NavLink
                                key={board.id}
                                href={`/app/boards/${board.id}`}
                                icon={CircleDot}
                                nested
                              >
                                {board.name}
                              </NavLink>
                            ))}
                            {team.pages.map((page) => (
                              <NavLink
                                key={page.id}
                                href={`/app/pages/${page.id}`}
                                icon={FileText}
                                nested
                              >
                                {page.title}
                              </NavLink>
                            ))}
                          </div>
                        </div>
                      ))}
                      {space.teams.length === 0 &&
                      (space.role === "owner" || space.role === "admin") ? (
                        <CreateTeamDialog
                          spaceId={space.id}
                          trigger={
                            <button
                              type="button"
                              className="flex h-8 w-full cursor-pointer items-center gap-2 rounded-md px-3 text-xs text-neutral-400 transition hover:bg-neutral-200/70 hover:text-neutral-700 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
                            >
                              <Plus className="size-3.5" />
                              Добавить команду
                            </button>
                          }
                        />
                      ) : space.teams.length === 0 ? (
                        <div className="px-3 py-2 text-[11px] text-neutral-400 dark:text-neutral-500">
                          Нет доступных команд
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {navigation.length === 0 ? (
              <CreateSpaceDialog
                trigger={
                  <button
                    type="button"
                    className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 py-3 text-xs text-neutral-500 transition hover:border-neutral-400 hover:bg-card dark:text-neutral-400 dark:hover:border-neutral-600"
                  >
                    <Plus className="size-4" />
                    Создать первый Space
                  </button>
                }
              />
            ) : null}
          </div>
        </nav>

        <div className="border-t p-2">
          <NavLink href="/app/settings" icon={Settings}>
            Настройки
          </NavLink>
          <NavLink href="/app/trash" icon={Trash2}>
            Корзина
          </NavLink>
          <div className="mt-2 flex items-center gap-2 rounded-lg p-2">
            <UserAvatar user={user} size="sm" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium">{user.name}</div>
              <div className="truncate text-[11px] text-neutral-400 dark:text-neutral-500">
                {user.email}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onLogout}
              aria-label="Выйти"
            >
              <LogOut className="size-3.5" />
            </Button>
          </div>
          <div className="mt-2 flex justify-center">
            <ThemeToggle />
          </div>
        </div>
      </aside>
    </>
  );
}
