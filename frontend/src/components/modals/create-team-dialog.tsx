"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { FormEvent, ReactNode, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { Team } from "@/lib/types";
import { formatError } from "@/lib/utils";

export function CreateTeamDialog({
  spaceId,
  trigger,
}: {
  spaceId: string;
  trigger?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      await api.post<Team>(`/spaces/${spaceId}/teams`, { name });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      setOpen(false);
      setName("");
      toast.success("Команда создана");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <button
            type="button"
            className="rounded p-1 text-neutral-400 transition hover:bg-neutral-200 hover:text-neutral-700 dark:text-neutral-500 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
            aria-label="Создать команду"
          >
            <Plus className="size-3.5" />
          </button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Новая команда</DialogTitle>
          <DialogDescription>
            В команде можно создавать доски задач и страницы.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor={`team-name-${spaceId}`}>Название</Label>
            <Input
              id={`team-name-${spaceId}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Development"
              maxLength={80}
              autoFocus
              required
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? <Loader2 className="size-4 animate-spin" /> : null}
              Создать
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
