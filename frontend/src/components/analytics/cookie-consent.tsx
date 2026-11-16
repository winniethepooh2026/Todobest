"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { YandexMetrica } from "@/components/analytics/yandex-metrica";

const KEY = "noki-cookie-consent-v1";

export function CookieConsent() {
  const choice = useSyncExternalStore(
    (notify) => {
      window.addEventListener("noki-cookie-consent", notify);
      return () => window.removeEventListener("noki-cookie-consent", notify);
    },
    () => {
      const saved = localStorage.getItem(KEY);
      return saved === "accepted" || saved === "rejected" ? saved : null;
    },
    () => null,
  );
  function choose(value: "accepted" | "rejected") {
    localStorage.setItem(KEY, value);
    window.dispatchEvent(new Event("noki-cookie-consent"));
  }
  return <><YandexMetrica enabled={choice === "accepted"} />{choice === null ? <aside className="fixed inset-x-4 bottom-4 z-[100] mx-auto max-w-2xl rounded-xl border bg-background p-4 shadow-xl"><p className="text-sm">Noki использует необходимые cookies для входа. Аналитические cookies Яндекс Метрики включаются только с вашего согласия. <Link href="/legal/cookies" className="underline">Подробнее</Link></p><div className="mt-3 flex gap-2"><Button size="sm" onClick={() => choose("accepted")}>Разрешить аналитику</Button><Button size="sm" variant="outline" onClick={() => choose("rejected")}>Только необходимые</Button></div></aside> : null}</>;
}
