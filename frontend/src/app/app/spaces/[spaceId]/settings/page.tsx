"use client";

import { Settings, Users } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

export default function SpaceSettingsPage() {
  const { spaceId } = useParams<{ spaceId: string }>();
  return (
    <div className="mx-auto max-w-4xl px-6 py-12">
      <p className="text-sm text-muted-foreground">Пространство</p>
      <h1 className="mt-1 flex items-center gap-2 text-3xl font-semibold">
        <Settings /> Настройки
      </h1>
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Link
          href={`/app/spaces/${spaceId}/members`}
          className="rounded-2xl border p-5 hover:bg-muted"
        >
          <Users />
          <h2 className="mt-4 font-medium">Участники</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Роли, приглашения и управление доступом.
          </p>
        </Link>
      </div>
      <section className="mt-8 rounded-2xl border border-red-200 p-5">
        <h2 className="font-medium text-red-700">Опасная зона</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Удаление Space помещает данные в корзину.
        </p>
      </section>
    </div>
  );
}
