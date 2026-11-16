"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { formatError } from "@/lib/utils";

export default function SecondFactorPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/totp/complete-google", { code });
      router.replace("/app");
      router.refresh();
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">Подтвердите вход</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Введите код приложения аутентификации или резервный код.
          </p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="mfa-code">Код</Label>
            <Input id="mfa-code" value={code} onChange={(event) => setCode(event.target.value)}
              autoComplete="one-time-code" autoFocus required />
          </div>
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Проверяем…" : "Продолжить"}
          </Button>
        </form>
        <Link href="/login" className="text-sm underline">Другой способ входа</Link>
      </div>
    </main>
  );
}
