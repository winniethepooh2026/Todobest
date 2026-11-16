import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

export function safeAppReturnTo(value: string | null, fallback: string): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return fallback;
  try {
    const parsed = new URL(value, "https://noki.invalid");
    if (
      parsed.origin !== "https://noki.invalid" ||
      (parsed.pathname !== "/app" && !parsed.pathname.startsWith("/app/"))
    ) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

