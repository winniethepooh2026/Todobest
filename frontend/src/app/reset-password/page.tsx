"use client";

import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { FormEvent, Suspense, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { formatError } from "@/lib/utils";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      toast.error("Пароли не совпадают");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", {
        token,
        new_password: password,
        new_password_confirm: confirm,
      });
      setDone(true);
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }
  if (done)
    return (
      <p>
        Пароль изменён.{" "}
        <Link className="underline" href="/login">
          Войти
        </Link>
      </p>
    );
  if (!token) {
    return (
      <p className="mt-6 text-sm text-destructive">
        Ссылка неполная. Запросите новую ссылку для восстановления пароля.
      </p>
    );
  }
  return (
    <form onSubmit={submit} className="mt-8 space-y-5">
      <div className="space-y-2">
        <Label htmlFor="password">Новый пароль</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          maxLength={128}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="confirm">Повторите пароль</Label>
        <Input
          id="confirm"
          type="password"
          autoComplete="new-password"
          minLength={12}
          maxLength={128}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
        />
      </div>
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? <Loader2 className="size-4 animate-spin" /> : null}
        {loading ? "Сохраняем…" : "Сохранить пароль"}
      </Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="grid min-h-screen place-items-center px-6">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-semibold">Новый пароль</h1>
        <Suspense fallback={<p>Загрузка…</p>}>
          <ResetForm />
        </Suspense>
      </div>
    </main>
  );
}
