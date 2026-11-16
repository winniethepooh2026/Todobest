"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { PanelLeftOpen } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  Sidebar,
} from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { CommandPalette } from "@/components/navigation/command-palette";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import type { NavigationSpace, User } from "@/lib/types";
import { formatError } from "@/lib/utils";

const SIDEBAR_WIDTH_STORAGE_KEY = "noki_sidebar_width";

const SidebarContext = createContext<{
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
  desktopOpen: boolean;
  setDesktopOpen: (open: boolean) => void;
} | null>(null);

export function useSidebar() {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within AppShell");
  }
  return context;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(true);
  const [desktopPeek, setDesktopPeek] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);

  useEffect(() => {
    // Reads a browser-only external source (localStorage) once after mount.
    // Rendering the default on both server and first client pass (like
    // theme-provider.tsx's getStoredTheme) avoids a hydration mismatch;
    // this necessarily updates state from an effect, not during render.
    const stored = Number(localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));
    if (stored >= MIN_SIDEBAR_WIDTH && stored <= MAX_SIDEBAR_WIDTH) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSidebarWidth(stored);
    }
  }, []);

  function handleSidebarWidthChange(width: number) {
    setSidebarWidth(width);
    localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(width));
  }

  const userQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/users/me"),
  });
  const navigationQuery = useQuery({
    queryKey: ["navigation"],
    queryFn: () => api.get<NavigationSpace[]>("/navigation"),
    enabled: userQuery.isSuccess,
  });
  const unauthorized =
    (userQuery.error instanceof ApiError && userQuery.error.status === 401) ||
    (navigationQuery.error instanceof ApiError &&
      navigationQuery.error.status === 401);

  useEffect(() => {
    if (unauthorized) {
      router.replace("/login");
    }
  }, [router, unauthorized]);

  async function logout() {
    try {
      await api.post<{ message: string }>("/auth/logout");
      router.replace("/login");
      router.refresh();
    } catch (error) {
      toast.error(formatError(error));
    }
  }

  if (userQuery.isLoading || navigationQuery.isLoading) {
    return (
      <div className="flex h-dvh min-h-0 overflow-hidden">
        <div className="hidden w-[268px] border-r bg-[#f4f4f2] p-4 md:block dark:bg-neutral-950 dark:border-neutral-800">
          <Skeleton className="h-8 w-24" />
          <div className="mt-12 space-y-3">
            {Array.from({ length: 7 }).map((_, index) => (
              <Skeleton key={index} className="h-7 w-full" />
            ))}
          </div>
        </div>
        <div className="flex-1 p-10">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="mt-5 h-28 w-full max-w-4xl" />
        </div>
      </div>
    );
  }

  if (unauthorized) return null;

  if (userQuery.isError || navigationQuery.isError || !userQuery.data) {
    const error = userQuery.error ?? navigationQuery.error;
    return (
      <div className="grid min-h-screen place-items-center bg-background px-6">
        <div className="max-w-md rounded-xl border bg-card p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold">Не удалось загрузить Noki</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {formatError(error)}
          </p>
          <button
            type="button"
            className="mt-5 rounded-lg bg-neutral-950 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 dark:bg-white dark:text-neutral-950 dark:hover:bg-neutral-200"
            onClick={() => {
              void userQuery.refetch();
              if (userQuery.data) void navigationQuery.refetch();
            }}
          >
            Повторить
          </button>
        </div>
      </div>
    );
  }

  return (
    <SidebarContext.Provider
      value={{ mobileOpen, setMobileOpen, desktopOpen, setDesktopOpen }}
    >
      <div className="flex h-dvh min-h-0 overflow-hidden bg-[#eeeeec] md:gap-2 md:p-2 dark:bg-neutral-900">
        <CommandPalette navigation={navigationQuery.data ?? []} />
        <Sidebar
          user={userQuery.data}
          navigation={navigationQuery.data ?? []}
          open={mobileOpen}
          onOpenChange={setMobileOpen}
          desktopOpen={desktopOpen}
          onDesktopOpenChange={setDesktopOpen}
          desktopPeek={desktopPeek}
          onDesktopPeekChange={setDesktopPeek}
          width={sidebarWidth}
          onWidthChange={handleSidebarWidthChange}
          onLogout={logout}
        />
        {!desktopOpen ? (
          <div
            className="hidden h-full w-14 shrink-0 flex-col items-center rounded-2xl border bg-[#f4f4f2] md:flex dark:border-neutral-800 dark:bg-neutral-950"
            onMouseEnter={() => setDesktopPeek(true)}
          >
            <div className="flex h-14 items-center justify-center">
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                onClick={() => setDesktopOpen(true)}
                aria-label="Открыть боковую панель"
                title="Открыть боковую панель"
              >
                <PanelLeftOpen className="size-4" />
              </Button>
            </div>
          </div>
        ) : null}
        <main className="h-full min-h-0 min-w-0 flex-1 overflow-y-auto bg-background md:rounded-2xl md:border md:shadow-sm dark:md:border-neutral-800">
          {children}
        </main>
      </div>
    </SidebarContext.Provider>
  );
}
