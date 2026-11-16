"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { formatError } from "@/lib/utils";

function Verification() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token");
  const [message, setMessage] = useState(
    token ? "Подтверждаем адрес…" : "Письмо отправлено. Проверьте почту.",
  );
  useEffect(() => {
    if (!token) return;
    api
      .post<{ user: User } | { message: string }>("/auth/verify-email", { token })
      .then((result) => {
        router.replace("user" in result ? "/app/settings" : "/login?email_verified=1");
        router.refresh();
      })
      .catch((error) => setMessage(formatError(error)));
  }, [router, token]);
  return (
    <div className="text-center">
      <h1 className="text-3xl font-semibold">Подтверждение email</h1>
      <p className="mt-4 text-muted-foreground">{message}</p>
      {token ? <Loader2 className="mx-auto mt-6 size-5 animate-spin" /> : null}
      <Link href="/login" className="mt-8 inline-block underline">
        Вернуться ко входу
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <main className="grid min-h-screen place-items-center px-6">
      <Suspense fallback={<Loader2 className="size-5 animate-spin" />}>
        <Verification />
      </Suspense>
    </main>
  );
}
