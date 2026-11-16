"use client";

import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, googleLoginUrl } from "@/lib/api";
import type { User } from "@/lib/types";
import { formatError } from "@/lib/utils";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.post<{ user: User }>("/auth/login", {
        email, password, mfa_code: mfaRequired ? mfaCode : null,
      });
      router.replace("/app");
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 428) {
        setMfaRequired(true);
        return;
      }
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1fr_0.9fr]">
      <section className="flex items-center justify-center px-6 py-12 bg-background">
        <div className="w-full max-w-sm">
          <Link
            href="/"
            className="mb-12 flex items-center gap-2 font-semibold"
          >
            <Image src="/noki-mark.svg" alt="" width={28} height={28} />
            Noki
          </Link>
          <h1 className="text-3xl font-semibold tracking-[-0.035em]">
            С возвращением
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Войдите, чтобы продолжить работу в своём пространстве.
          </p>

          {searchParams.get("email_verified") === "1" ? (
            <div className="mt-6 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100" role="status">
              Email подтверждён. Войдите с паролем и кодом приложения.
            </div>
          ) : null}

          {searchParams.get("oauth_error") === "account_exists" ? (
            <div
              className="mt-6 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
              role="alert"
            >
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <div>
                  <p className="font-medium">Этот email уже зарегистрирован</p>
                  <p className="mt-1 leading-5">
                    Войдите по email и паролю. Если пароль не помните,
                    восстановите его — аккаунт и данные останутся на месте.
                  </p>
                  <Link
                    href="/forgot-password?reason=google"
                    className="mt-3 inline-block font-medium underline"
                  >
                    Восстановить пароль
                  </Link>
                </div>
              </div>
            </div>
          ) : null}

          {searchParams.get("oauth_error") === "account_disabled" ? (
            <div
              className="mt-6 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              Этот аккаунт отключён. Обратитесь к администратору.
            </div>
          ) : null}

          {searchParams.get("oauth_error") === "google_identity_conflict" ? (
            <div
              className="mt-6 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
              role="alert"
            >
              Этот email уже связан с другим Google-аккаунтом. Войдите по email
              и паролю либо восстановите пароль.
            </div>
          ) : null}

          <form onSubmit={submit} className="mt-8 space-y-5">
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
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Пароль</Label>
                <Link href="/forgot-password" className="text-xs underline">
                  Забыли пароль?
                </Link>
              </div>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {mfaRequired ? (
              <div className="space-y-2">
                <Label htmlFor="mfa-code">Код приложения или резервный код</Label>
                <Input
                  id="mfa-code"
                  autoComplete="one-time-code"
                  inputMode="text"
                  value={mfaCode}
                  onChange={(event) => setMfaCode(event.target.value)}
                  required
                  autoFocus
                />
              </div>
            ) : null}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={loading}
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              Войти
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
              window.location.href = googleLoginUrl();
            }}
          >
            <span className="text-base font-semibold text-blue-600">G</span>
            Продолжить с Google
          </Button>

          <p className="mt-8 text-center text-sm text-muted-foreground">
            Нет аккаунта?{" "}
            <Link
              href="/register"
              className="font-medium text-foreground underline"
            >
              Зарегистрироваться
            </Link>
          </p>
        </div>
      </section>

      <aside className="relative hidden overflow-hidden border-l bg-neutral-950 p-12 text-white lg:flex lg:flex-col lg:justify-end dark:bg-neutral-900">
        <div className="absolute -right-32 -top-32 size-96 rounded-full bg-white/10 blur-3xl" />
        <p className="relative max-w-md text-3xl font-medium leading-tight tracking-[-0.035em]">
          «Инструмент должен освобождать внимание, а не требовать его».
        </p>
        <p className="relative mt-5 text-sm text-neutral-400">
          Noki — Issues и Pages в одном спокойном интерфейсе.
        </p>
      </aside>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
