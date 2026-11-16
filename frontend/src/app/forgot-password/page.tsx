"use client";

import { Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { formatError } from "@/lib/utils";

function ForgotPasswordForm() {
  const fromGoogle = useSearchParams().get("reason") === "google";
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email });
      setSent(true);
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-6">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-semibold">Восстановление пароля</h1>
        {fromGoogle && !sent ? (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Введите тот же email, который выбрали при входе через Google.
          </p>
        ) : null}

        {sent ? (
          <div className="mt-8 rounded-lg border p-5" role="status">
            <MailCheck className="size-6" />
            <p className="mt-3 font-medium">Проверьте почту</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Если активный аккаунт с локальным паролем существует, ссылка
              придёт на {email}. Проверьте также папку «Спам».
            </p>
            <Button
              type="button"
              variant="outline"
              className="mt-4 w-full"
              onClick={() => setSent(false)}
            >
              Указать другой email
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-8 space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              {loading ? "Отправляем…" : "Отправить ссылку"}
            </Button>
          </form>
        )}
        <Link href="/login" className="mt-8 inline-block text-sm underline">
          Вернуться ко входу
        </Link>
      </div>
    </main>
  );
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
