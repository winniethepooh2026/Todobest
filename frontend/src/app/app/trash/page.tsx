"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { MobileMenuButton } from "@/components/layout/mobile-menu-button";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { TrashItem } from "@/lib/types";
import { formatError } from "@/lib/utils";

export default function TrashPage() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["trash"],
    queryFn: () => api.get<TrashItem[]>("/trash"),
  });
  async function restore(item: TrashItem) {
    try {
      await api.post(`/trash/${item.kind}/${item.id}/restore`);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["trash"] }),
        client.invalidateQueries({ queryKey: ["navigation"] }),
      ]);
      toast.success("Восстановлено");
    } catch (error) {
      toast.error(formatError(error));
    }
  }
  return (
    <div className="mx-auto max-w-4xl px-6 py-12">
      <div className="mb-4 flex items-center gap-2 md:hidden">
        <MobileMenuButton />
        <span className="text-sm font-medium">Корзина</span>
      </div>
      <h1 className="text-3xl font-semibold">Корзина</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Недавно удалённые объекты можно восстановить здесь.
      </p>
      <div className="mt-8 divide-y rounded-2xl border bg-card px-5">
        {query.data?.map((item) => (
          <div
            key={`${item.kind}-${item.id}`}
            className="flex items-center justify-between gap-4 py-4"
          >
            <div>
              <p className="font-medium">{item.name}</p>
              <p className="text-xs text-muted-foreground">
                {item.kind} · удалено{" "}
                {new Date(item.deleted_at).toLocaleString("ru-RU")}
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={() => restore(item)}>
              <RotateCcw className="size-4" />
              Восстановить
            </Button>
          </div>
        ))}
        {query.data?.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Корзина пуста
          </p>
        ) : null}
      </div>
    </div>
  );
}
