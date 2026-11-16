"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatError } from "@/lib/utils";

function Invite() {
  const token = useSearchParams().get("token") ?? "";
  const [done, setDone] = useState(false);
  async function accept() { try { await api.post("/invitations/accept", { token }); setDone(true); } catch (error) { toast.error(formatError(error)); } }
  return <div className="text-center"><h1 className="text-3xl font-semibold">Приглашение в Noki</h1><p className="mt-4 text-muted-foreground">Войдите или зарегистрируйтесь с приглашённым email, затем примите приглашение.</p>{done ? <Link href="/app" className="mt-8 inline-block underline">Открыть Noki</Link> : <Button className="mt-8" onClick={accept} disabled={!token}>Принять приглашение</Button>}<div className="mt-6 flex justify-center gap-4 text-sm"><Link href="/login" className="underline">Войти</Link><Link href="/register" className="underline">Регистрация</Link></div></div>;
}
export default function InvitePage() { return <main className="grid min-h-screen place-items-center px-6"><Suspense fallback={<p>Загрузка…</p>}><Invite /></Suspense></main>; }
