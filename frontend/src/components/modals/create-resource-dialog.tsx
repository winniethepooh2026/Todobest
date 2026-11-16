"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Columns3, FileText, Loader2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  cloneElement,
  type FormEvent,
  isValidElement,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";

import { DEFAULT_PAGE_TITLE } from "@/components/editor/editor-utils";
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
import { generateBoardKey } from "@/lib/board-key";
import type { NavigationBoard, PageDocument } from "@/lib/types";
import { formatError } from "@/lib/utils";

type ResourceKind = "board" | "page";

interface DirectCreateTriggerProps {
  "aria-busy"?: boolean;
  disabled?: boolean;
  onClick?: (event: ReactMouseEvent<HTMLElement>) => void;
}

export function CreateResourceDialog({
  teamId,
  kind,
  trigger,
}: {
  teamId: string;
  kind: ResourceKind;
  trigger?: ReactNode;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(false);
  const isBoard = kind === "board";

  const generatedKey = useMemo(() => generateBoardKey(name), [name]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      if (isBoard) {
        const board = await api.post<NavigationBoard>(
          `/teams/${teamId}/boards`,
          {
            name,
            key: (key || generatedKey).toUpperCase(),
          },
        );
        await queryClient.invalidateQueries({ queryKey: ["navigation"] });
        router.push(`/app/boards/${board.id}`);
      } else {
        const page = await api.post<PageDocument>(`/teams/${teamId}/pages`, {
          title: name,
        });
        await queryClient.invalidateQueries({ queryKey: ["navigation"] });
        router.push(`/app/pages/${page.id}`);
      }
      setOpen(false);
      setName("");
      setKey("");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  async function createPageDirectly() {
    setLoading(true);
    try {
      const page = await api.post<PageDocument>(`/teams/${teamId}/pages`, {
        title: DEFAULT_PAGE_TITLE,
      });
      await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      router.push(`/app/pages/${page.id}?new=1`);
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  if (kind === "page") {
    if (isValidElement<DirectCreateTriggerProps>(trigger)) {
      return cloneElement(trigger, {
        "aria-busy": loading,
        disabled: loading || trigger.props.disabled,
        onClick: (event: ReactMouseEvent<HTMLElement>) => {
          trigger.props.onClick?.(event);
          if (!event.defaultPrevented && !loading) {
            void createPageDirectly();
          }
        },
      });
    }

    return (
      <Button variant="outline" onClick={createPageDirectly} disabled={loading}>
        {loading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Plus className="size-4" />
        )}
        Page
      </Button>
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline">
            <Plus className="size-4" />
            {isBoard ? "Issue board" : "Page"}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <div className="mb-2 flex size-10 items-center justify-center rounded-xl bg-neutral-100 dark:bg-neutral-800">
            {isBoard ? (
              <Columns3 className="size-5" />
            ) : (
              <FileText className="size-5" />
            )}
          </div>
          <DialogTitle>
            {isBoard ? "Новая Issue board" : "Новая Page"}
          </DialogTitle>
          <DialogDescription>
            {isBoard
              ? "По умолчанию будут созданы Todo, In Progress и Done."
              : "Откроется визуальный Markdown-редактор с автосохранением."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor={`resource-name-${kind}`}>Название</Label>
            <Input
              id={`resource-name-${kind}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={
                isBoard ? "Product Development" : "Стратегия продукта"
              }
              maxLength={isBoard ? 100 : 200}
              autoFocus
              required
            />
          </div>
          {isBoard ? (
            <div className="space-y-2">
              <Label htmlFor="board-key">Код из 2–5 латинских букв</Label>
              <Input
                id="board-key"
                value={key || generatedKey}
                onChange={(event) =>
                  setKey(
                    event.target.value
                      .toUpperCase()
                      .replace(/[^A-Z]/g, "")
                      .slice(0, 5),
                  )
                }
                placeholder="DEV"
                minLength={2}
                maxLength={5}
                pattern="[A-Z]{2,5}"
                required
                className="font-mono uppercase"
              />
            </div>
          ) : null}
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
