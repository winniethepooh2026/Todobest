"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { KanbanBoard } from "@/components/kanban/kanban-board";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { Board } from "@/lib/types";

export default function BoardPage() {
  const params = useParams<{ boardId: string }>();
  const boardId = params.boardId;
  const query = useQuery({
    queryKey: ["board", boardId],
    queryFn: () => api.get<Board>(`/boards/${boardId}`),
  });

  if (query.isLoading) {
    return (
      <div>
        <div className="flex h-16 items-center gap-3 border-b px-8">
          <Skeleton className="h-6 w-12" />
          <Skeleton className="h-6 w-48" />
        </div>
        <div className="flex gap-5 p-8">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-80 w-[310px] shrink-0" />
          ))}
        </div>
      </div>
    );
  }

  if (!query.data) {
    return <div className="p-10 text-sm text-muted-foreground">Доска не найдена.</div>;
  }

  return <KanbanBoard initialBoard={query.data} />;
}

