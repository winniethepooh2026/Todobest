"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { api } from "@/lib/api";

interface AdminSpace {
  id: string;
  name: string;
  members_count: number;
}

export default function AdminUserSpacesPage() {
  const { userId } = useParams<{ userId: string }>();
  const query = useQuery({
    queryKey: ["admin", "user-spaces", userId],
    queryFn: () => api.get<AdminSpace[]>(`/admin/users/${userId}/spaces`),
  });

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <p className="text-sm text-muted-foreground">Admin · пользователь</p>
      <h1 className="mt-1 text-3xl font-semibold">Пространства</h1>
      <div className="mt-8 space-y-4">
        {query.data?.map((space) => (
          <section key={space.id} className="rounded-2xl border p-5">
            <h2 className="font-medium">{space.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Участников: {space.members_count}
            </p>
          </section>
        ))}
        {query.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            У пользователя пока нет Spaces.
          </p>
        ) : null}
      </div>
    </div>
  );
}
