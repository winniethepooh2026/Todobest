"use client";

import { UserRound } from "lucide-react";
import Image from "next/image";
import { useState } from "react";

import { cn } from "@/lib/utils";

const sizeStyles = {
  xs: {
    box: "size-6",
    pixels: 24,
    text: "text-[9px]",
    icon: "size-3",
  },
  sm: {
    box: "size-8",
    pixels: 32,
    text: "text-[10px]",
    icon: "size-4",
  },
  md: {
    box: "size-10",
    pixels: 40,
    text: "text-sm",
    icon: "size-5",
  },
  lg: {
    box: "size-16",
    pixels: 64,
    text: "text-lg",
    icon: "size-7",
  },
  xl: {
    box: "size-20",
    pixels: 80,
    text: "text-xl",
    icon: "size-8",
  },
} as const;

export type UserAvatarSize = keyof typeof sizeStyles;

export interface AvatarUser {
  name: string;
  avatar_url: string | null;
}

export function userInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  const selected =
    parts.length === 1
      ? parts[0].slice(0, 2)
      : `${parts[0][0]}${parts.at(-1)?.[0] ?? ""}`;
  return selected.toLocaleUpperCase();
}

export function UserAvatar({
  user,
  size = "sm",
  tone = "dark",
  alt = "",
  title,
  className,
}: {
  user: AvatarUser;
  size?: UserAvatarSize;
  tone?: "dark" | "subtle";
  alt?: string;
  title?: string;
  className?: string;
}) {
  const styles = sizeStyles[size];
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const imageUrl =
    user.avatar_url && failedUrl !== user.avatar_url ? user.avatar_url : null;
  const initials = userInitials(user.name);

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full ring-1 ring-black/10 dark:ring-neutral-800",
        styles.box,
        imageUrl
          ? "bg-neutral-100 dark:bg-neutral-800"
          : tone === "dark"
            ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-950"
            : "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
        styles.text,
        "font-semibold",
        className,
      )}
      title={title}
    >
      {imageUrl ? (
        <Image
          key={imageUrl}
          src={imageUrl}
          alt={alt}
          width={styles.pixels}
          height={styles.pixels}
          unoptimized
          draggable={false}
          className="size-full object-cover"
          onError={() => setFailedUrl(imageUrl)}
        />
      ) : initials ? (
        <span aria-hidden="true">{initials}</span>
      ) : (
        <UserRound className={styles.icon} aria-hidden="true" />
      )}
      {!imageUrl && alt ? <span className="sr-only">{alt}</span> : null}
    </span>
  );
}
