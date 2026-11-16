"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, KanbanSquare, Search, SquareCheckBig } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { NavigationSpace, SearchResponse } from "@/lib/types";

interface CommandItem {
  id: string;
  title: string;
  subtitle: string;
  url: string;
  kind: "board" | "page" | "task";
}

export function CommandPalette({
  navigation,
}: {
  navigation: NavigationSpace[];
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const normalized = query.trim().toLocaleLowerCase();
  const searchQuery = useQuery({
    queryKey: ["global-search", normalized],
    queryFn: () =>
      api.get<SearchResponse>(
        `/search?q=${encodeURIComponent(normalized)}&limit=30`,
      ),
    enabled: open && normalized.length >= 2,
    staleTime: 30_000,
  });
  const localItems = useMemo(() => {
    const items: CommandItem[] = [];
    for (const space of navigation) {
      for (const team of space.teams) {
        for (const board of team.boards)
          items.push({
            id: board.id,
            title: board.name,
            subtitle: `${space.name} · ${team.name}`,
            url: `/app/boards/${board.id}`,
            kind: "board",
          });
        for (const page of team.pages)
          items.push({
            id: page.id,
            title: page.title,
            subtitle: `${space.name} · ${team.name}`,
            url: `/app/pages/${page.id}`,
            kind: "page",
          });
      }
    }
    return normalized
      ? items
          .filter((item) =>
            `${item.title} ${item.subtitle}`
              .toLocaleLowerCase()
              .includes(normalized),
          )
          .slice(0, 20)
      : items.slice(0, 12);
  }, [navigation, normalized]);
  const items = useMemo<CommandItem[]>(() => {
    const remote = (searchQuery.data?.items ?? []).map((item) => ({
      ...item,
      kind: item.kind as "task" | "page",
    }));
    const byUrl = new Map<string, CommandItem>();
    for (const item of [...localItems, ...remote]) byUrl.set(item.url, item);
    return Array.from(byUrl.values());
  }, [localItems, searchQuery.data]);

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => {
          if (value) {
            setQuery("");
            setActive(0);
          }
          return !value;
        });
      } else if (event.key === "Escape") {
        setOpen(false);
        setQuery("");
        setActive(0);
      }
    }
    window.addEventListener("keydown", keydown);
    const openPalette = () => setOpen(true);
    window.addEventListener("noki:open-command-palette", openPalette);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("noki:open-command-palette", openPalette);
    };
  }, []);
  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  function choose(item: CommandItem) {
    setOpen(false);
    setQuery("");
    setActive(0);
    router.push(item.url);
  }
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center bg-black/35 px-4 pt-[12vh] backdrop-blur-sm"
      onMouseDown={() => {
        setOpen(false);
        setQuery("");
        setActive(0);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Командная палитра"
        className="w-full max-w-xl overflow-hidden rounded-2xl border bg-background shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b px-4">
          <Search className="size-4 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((value) => Math.min(value + 1, items.length - 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((value) => Math.max(value - 1, 0));
              }
              if (event.key === "Enter" && items[active]) {
                event.preventDefault();
                choose(items[active]);
              }
            }}
            placeholder="Найти задачу, страницу или доску…"
            className="h-14 flex-1 bg-transparent text-sm outline-none"
          />
          <kbd className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
            Esc
          </kbd>
        </div>
        <div className="max-h-[55vh] overflow-y-auto p-2">
          {items.map((item, index) => {
            const Icon =
              item.kind === "task"
                ? SquareCheckBig
                : item.kind === "board"
                  ? KanbanSquare
                  : FileText;
            return (
              <button
                key={`${item.kind}:${item.id}`}
                type="button"
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(item)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left ${active === index ? "bg-muted" : ""}`}
              >
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {item.title}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {item.subtitle}
                  </span>
                </span>
              </button>
            );
          })}
          {!items.length ? (
            <div className="px-3 py-10 text-center text-sm text-muted-foreground">
              {searchQuery.isFetching
                ? "Ищем…"
                : normalized.length < 2
                  ? "Введите минимум 2 символа"
                  : "Ничего не найдено"}
            </div>
          ) : null}
        </div>
        <div className="flex gap-4 border-t px-4 py-2 text-[10px] text-muted-foreground">
          <span>↑↓ выбрать</span>
          <span>↵ открыть</span>
          <span>⌘K закрыть</span>
        </div>
      </div>
    </div>
  );
}
