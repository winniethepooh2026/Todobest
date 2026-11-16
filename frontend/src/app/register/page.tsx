"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, googleLoginUrl } from "@/lib/api";
import type { User } from "@/lib/types";
import { formatError } from "@/lib/utils";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.post<{ user: User }>("/auth/register", {
        name,
        email,
        password,
        accept_terms: true,
        accept_privacy: true,
      });
      router.replace("/app/onboarding");
      router.refresh();
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[0.9fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-[#ecebe7] p-12 lg:flex lg:flex-col lg:justify-between dark:bg-neutral-900">
        <Link
          href="/"
          className="relative flex items-center gap-2 font-semibold"
        >
          <Image src="/noki-mark.svg" alt="" width={28} height={28} />
          Noki
        </Link>
        <div className="relative">
          <div className="mb-8 grid grid-cols-3 gap-3 opacity-80">
            {["Todo", "In Progress", "Done"].map((title, index) => (
              <div
                key={title}
                className="rounded-xl border bg-white/80 p-3 shadow-sm dark:border-neutral-700 dark:bg-neutral-800"
              >
                <div className="mb-4 text-[10px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
                  {title}
                </div>
                <div
                  className={`h-16 rounded-lg border bg-white dark:border-neutral-700 dark:bg-neutral-700 ${index === 1 ? "translate-y-3" : ""}`}
                />
              </div>
            ))}
          </div>
          <p className="max-w-md text-3xl font-medium leading-tight tracking-[-0.035em]">
            Начните со структуры, которая не мешает команде работать.
          </p>
        </div>
      </aside>

      <section className="flex items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm">
          <Link
            href="/"
            className="mb-12 flex items-center gap-2 font-semibold lg:hidden"
          >
            <Image src="/noki-mark.svg" alt="" width={28} height={28} />
            Noki
          </Link>
          <h1 className="text-3xl font-semibold tracking-[-0.035em]">
            Создайте аккаунт
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Первый Space можно настроить сразу после регистрации.
          </p>

          <form onSubmit={submit} className="mt-8 space-y-5">
            <div className="space-y-2">
              <Label htmlFor="name">Имя</Label>
              <Input
                id="name"
                autoComplete="name"
                placeholder="Ваше имя"
                value={name}
                onChange={(event) => setName(event.target.value)}
                minLength={2}
                maxLength={80}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Пароль</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                placeholder="Минимум 12 символов"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={12}
                maxLength={128}
                required
              />
            </div>
            <label
              htmlFor="accept-terms"
              className="flex items-start gap-3 text-sm text-muted-foreground"
            >
              <input
                id="accept-terms"
                type="checkbox"
                checked={accepted}
                onChange={(event) => setAccepted(event.target.checked)}
                required
                className="mt-1"
              />
              <span>
                Я принимаю{" "}
                <Link className="underline" href="/legal/terms">
                  условия
                </Link>{" "}
                и{" "}
                <Link className="underline" href="/legal/privacy">
                  политику конфиденциальности
                </Link>
                .
              </span>
            </label>
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={loading || !accepted}
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              Создать аккаунт
              {!loading ? <ArrowRight className="size-4" /> : null}
            </Button>
          </form>

          <div className="my-6 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            или
            <span className="h-px flex-1 bg-border" />
          </div>
          <Button
            variant="outline"
            size="lg"
            className="w-full"
            onClick={() => {
              if (!accepted) {
                toast.error(
                  "Сначала примите условия и политику конфиденциальности",
                );
                document.getElementById("accept-terms")?.focus();
                return;
              }
              window.location.href = googleLoginUrl(undefined, true);
            }}
          >
            <span className="text-base font-semibold text-blue-600">G</span>
            Продолжить с Google
          </Button>
          <p className="mt-3 text-center text-xs leading-5 text-muted-foreground">
            Для регистрации через Google также нужно принять условия выше.
          </p>

          <p className="mt-8 text-center text-sm text-muted-foreground">
            Уже есть аккаунт?{" "}
            <Link
              href="/login"
              className="font-medium text-foreground underline"
            >
              Войти
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
