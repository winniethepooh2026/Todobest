"use client";

import { Check, ChevronDown, Loader2, Search, UserRound } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { UserAvatar } from "@/components/ui/user-avatar";
import { cn } from "@/lib/utils";

export interface UserPickerOption {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  disabled?: boolean;
  status?: string;
}

type PickerItem =
  | { kind: "empty"; id: null }
  | { kind: "user"; id: string; user: UserPickerOption };

export function UserPicker({
  value,
  onChange,
  options,
  allowEmpty = false,
  emptyLabel = "Без исполнителя",
  placeholder = "Выберите пользователя",
  searchPlaceholder = "Поиск по имени или email",
  emptyMessage = "Пользователи не найдены",
  loading = false,
  error = null,
  disabled = false,
  id,
  ariaLabel,
  align = "left",
  className,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  options: UserPickerOption[];
  allowEmpty?: boolean;
  emptyLabel?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  loading?: boolean;
  error?: string | null;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
  align?: "left" | "right";
  className?: string;
}) {
  const generatedId = useId();
  const triggerId = id ?? `${generatedId}-trigger`;
  const listboxId = `${generatedId}-listbox`;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const selected = options.find((option) => option.id === value) ?? null;
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    if (!needle) return options;
    return options.filter((option) =>
      `${option.name} ${option.email}`.toLocaleLowerCase().includes(needle),
    );
  }, [options, search]);
  const items = useMemo<PickerItem[]>(() => {
    const users: PickerItem[] = filtered.map((user) => ({
      kind: "user",
      id: user.id,
      user,
    }));
    return allowEmpty ? [{ kind: "empty", id: null }, ...users] : users;
  }, [allowEmpty, filtered]);
  const navigableIndexes = useMemo(() => {
    if (loading || error) return [];
    return items.flatMap((item, index) =>
      item.kind === "user" && item.user.disabled ? [] : [index],
    );
  }, [error, items, loading]);
  const focusedIndex = navigableIndexes.includes(activeIndex)
    ? activeIndex
    : (navigableIndexes[0] ?? null);

  function close({ restoreFocus = false } = {}) {
    setOpen(false);
    setSearch("");
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus());
  }

  function openPicker(direction: "first" | "last" = "first") {
    if (disabled) return;
    setOpen(true);
    setSearch("");
    setActiveIndex(
      direction === "last"
        ? (navigableIndexes.at(-1) ?? 0)
        : (navigableIndexes[0] ?? 0),
    );
  }

  function choose(item: PickerItem) {
    if (item.kind === "user" && item.user.disabled) return;
    onChange(item.id);
    close({ restoreFocus: true });
  }

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => searchRef.current?.focus());
  }, [open]);

  useEffect(() => {
    if (!open || focusedIndex === null) return;
    optionRefs.current[focusedIndex]?.scrollIntoView({ block: "nearest" });
  }, [focusedIndex, open]);

  return (
    <div
      ref={rootRef}
      className={cn("relative", className)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          close({ restoreFocus: true });
          return;
        }
        if (event.key === "Tab" && open) {
          close();
          return;
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          if (!open) {
            openPicker(event.key === "ArrowUp" ? "last" : "first");
            return;
          }
          if (navigableIndexes.length === 0) return;
          setActiveIndex((current) => {
            const currentPosition = navigableIndexes.indexOf(current);
            if (currentPosition < 0) {
              return event.key === "ArrowDown"
                ? navigableIndexes[0]
                : (navigableIndexes.at(-1) ?? navigableIndexes[0]);
            }
            const nextPosition =
              event.key === "ArrowDown"
                ? (currentPosition + 1) % navigableIndexes.length
                : (currentPosition - 1 + navigableIndexes.length) %
                  navigableIndexes.length;
            return navigableIndexes[nextPosition];
          });
          return;
        }
        if (
          event.key === "Enter" &&
          open &&
          focusedIndex !== null &&
          items[focusedIndex]
        ) {
          event.preventDefault();
          choose(items[focusedIndex]);
        }
      }}
    >
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-label={
          ariaLabel
            ? `${ariaLabel}: ${selected?.name ?? (allowEmpty && value === null ? emptyLabel : placeholder)}${selected?.status ? `, ${selected.status}` : ""}`
            : undefined
        }
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        disabled={disabled}
        onClick={() => (open ? close() : openPicker())}
        className="flex h-9 w-full items-center gap-2 rounded-lg border bg-background px-2.5 text-left text-sm outline-none transition hover:border-neutral-300 focus-visible:ring-2 focus-visible:ring-neutral-200 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:border-neutral-700 dark:focus-visible:ring-neutral-700"
      >
        {loading ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
        ) : selected ? (
          <UserAvatar user={selected} size="xs" />
        ) : allowEmpty && value === null ? (
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-dashed text-neutral-400 dark:text-neutral-500">
            <UserRound className="size-3" />
          </span>
        ) : null}
        <span
          className={cn(
            "flex min-w-0 flex-1 items-center gap-1.5",
            !selected &&
              !(allowEmpty && value === null) &&
              "text-muted-foreground",
          )}
        >
          <span className="truncate">
            {loading
              ? "Загрузка участников…"
              : (selected?.name ??
                (allowEmpty && value === null ? emptyLabel : placeholder))}
          </span>
          {!loading && selected?.status ? (
            <span className="shrink-0 text-[10px] font-medium text-amber-700">
              {selected.status}
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        <div
          className={cn(
            "absolute top-[calc(100%+0.375rem)] z-[70] w-full min-w-64 overflow-hidden rounded-xl border bg-card p-1.5 shadow-xl",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <div className="relative mb-1.5">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <input
              ref={searchRef}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setActiveIndex(0);
              }}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              role="combobox"
              aria-autocomplete="list"
              aria-expanded="true"
              aria-controls={listboxId}
              aria-activedescendant={
                focusedIndex !== null && items[focusedIndex]
                  ? `${listboxId}-option-${focusedIndex}`
                  : undefined
              }
              className="h-8 w-full rounded-lg border bg-background pl-8 pr-2 text-xs outline-none focus:ring-2 focus:ring-neutral-200"
            />
          </div>
          <div
            id={listboxId}
            role="listbox"
            aria-labelledby={triggerId}
            className="max-h-64 overflow-y-auto"
          >
            {loading ? (
              <div className="flex items-center justify-center gap-2 px-3 py-7 text-xs text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Загрузка участников…
              </div>
            ) : error ? (
              <div className="px-3 py-7 text-center text-xs leading-5 text-red-600">
                {error}
              </div>
            ) : items.length === 0 ? (
              <div className="px-3 py-7 text-center text-xs text-muted-foreground">
                {emptyMessage}
              </div>
            ) : (
              items.map((item, index) => {
                const isSelected = item.id === value;
                const active = index === focusedIndex;
                const optionDisabled =
                  item.kind === "user" && item.user.disabled === true;
                return (
                  <button
                    key={item.kind === "empty" ? "empty" : item.id}
                    ref={(node) => {
                      optionRefs.current[index] = node;
                    }}
                    id={`${listboxId}-option-${index}`}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={optionDisabled}
                    disabled={optionDisabled}
                    tabIndex={-1}
                    onMouseEnter={() => {
                      if (!optionDisabled) setActiveIndex(index);
                    }}
                    onClick={() => choose(item)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left outline-none",
                      active ? "bg-neutral-100 dark:bg-neutral-800" : "hover:bg-neutral-50 dark:hover:bg-neutral-800",
                      optionDisabled &&
                        "cursor-not-allowed opacity-60 hover:bg-transparent",
                    )}
                  >
                    {item.kind === "empty" ? (
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-dashed text-neutral-400 dark:text-neutral-500">
                        <UserRound className="size-4" />
                      </span>
                    ) : (
                      <UserAvatar user={item.user} size="sm" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {item.kind === "empty" ? emptyLabel : item.user.name}
                      </span>
                      {item.kind === "user" ? (
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {item.user.email}
                          {item.user.status ? (
                            <span className="font-medium text-amber-700">
                              {` · ${item.user.status}`}
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </span>
                    {isSelected ? (
                      <Check className="size-4 shrink-0" aria-hidden="true" />
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
