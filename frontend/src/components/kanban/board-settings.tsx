"use client";

import {
  closestCenter,
  DndContext,
  DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  GripVertical,
  Loader2,
  Plus,
  Settings2,
  Star,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
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
import { api } from "@/lib/api";
import type {
  Board,
  BoardColumn,
  NavigationBoard,
  TaskSystemStatus,
} from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

const RAINBOW_COLORS = [
  { value: "#ef4444", label: "Красный" },
  { value: "#f97316", label: "Оранжевый" },
  { value: "#eab308", label: "Жёлтый" },
  { value: "#22c55e", label: "Зелёный" },
  { value: "#06b6d4", label: "Голубой" },
  { value: "#3b82f6", label: "Синий" },
  { value: "#8b5cf6", label: "Фиолетовый" },
];

interface EditableColumn {
  clientId: string;
  id?: string;
  name: string;
  systemStatus: TaskSystemStatus | null;
  color: string | null;
  isDefault: boolean;
}

function SortableColumn({
  column,
  onChange,
  onColorChange,
  onRemove,
  onToggleDefault,
  removable,
  canManage,
}: {
  column: EditableColumn;
  onChange: (name: string) => void;
  onColorChange: (color: string | null) => void;
  onRemove: () => void;
  onToggleDefault: (alreadyDefault: boolean) => void;
  removable: boolean;
  canManage: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({
      id: column.clientId,
    });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex items-center gap-2 rounded-lg border bg-card p-2 text-card-foreground"
    >
      <button
        type="button"
        className="cursor-grab touch-none rounded p-1 text-neutral-400 hover:bg-neutral-100 dark:text-neutral-500 dark:hover:bg-neutral-800"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" />
      </button>
      {canManage ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => onToggleDefault(column.isDefault)}
          className="text-neutral-400 hover:text-amber-500 dark:text-neutral-500 dark:hover:text-amber-400"
        >
          <Star
            className={cn(
              "size-4",
              column.isDefault
                ? "fill-amber-400 text-amber-500"
                : "text-neutral-300 dark:text-neutral-600",
            )}
          />
        </Button>
      ) : null}
      <Input
        value={column.name}
        onChange={(event) => onChange(event.target.value)}
        maxLength={40}
        className="h-8 flex-1 border-0 shadow-none focus-visible:ring-0"
        required
      />
      <div className="flex flex-shrink-0 items-center gap-1">
        {RAINBOW_COLORS.map((color) => (
          <button
            key={color.value}
            type="button"
            onClick={() => onColorChange(color.value)}
            className={cn(
              "size-7 rounded-full border-2 transition",
              column.color === color.value
                ? "border-neutral-900 dark:border-neutral-100"
                : "border-transparent hover:border-neutral-300 dark:hover:border-neutral-700",
            )}
            style={{ backgroundColor: color.value }}
            title={color.label}
          />
        ))}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        disabled={!removable}
        onClick={onRemove}
        className="text-neutral-400 hover:text-red-600 dark:text-neutral-500 dark:hover:text-red-400"
      >
        <Trash2 className="size-3.5" />
      </Button>
    </div>
  );
}

export function BoardSettingsDialog({
  board,
  onSaved,
}: {
  board: Board;
  onSaved: (board: Board) => void;
}) {
  const [open, setOpen] = useState(false);
  const [boardName, setBoardName] = useState("");
  const [columns, setColumns] = useState<EditableColumn[]>([]);
  const [loading, setLoading] = useState(false);
  const queryClient = useQueryClient();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  function changeOpen(nextOpen: boolean) {
    if (nextOpen) {
      setBoardName(board.name);
      setColumns(
        [...board.columns]
          .sort((a, b) => a.position - b.position)
          .map((column) => ({
            clientId: column.id,
            id: column.id,
            name: column.name,
            systemStatus: column.system_status,
            color: column.color,
            isDefault: column.is_default,
          })),
      );
    }
    setOpen(nextOpen);
  }

  function dragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setColumns((current) => {
      const from = current.findIndex((column) => column.clientId === active.id);
      const to = current.findIndex((column) => column.clientId === over.id);
      return arrayMove(current, from, to);
    });
  }

  async function save() {
    const normalizedBoardName = boardName.trim().replace(/\s+/g, " ");
    if (!normalizedBoardName) {
      toast.error("У доски должно быть название");
      return;
    }
    if (columns.some((column) => !column.name.trim())) {
      toast.error("У каждой колонки должно быть название");
      return;
    }
    setLoading(true);
    try {
      let renamedBoard = board;
      if (normalizedBoardName !== board.name) {
        const renamed = await api.patch<NavigationBoard>(
          `/boards/${board.id}`,
          {
            name: normalizedBoardName,
          },
        );
        renamedBoard = { ...board, name: renamed.name };
        onSaved(renamedBoard);
        await queryClient.invalidateQueries({ queryKey: ["navigation"] });
      }
      const updated = await api.put<Board>(`/boards/${board.id}/columns`, {
        columns: columns.map((column) => ({
          id: column.id ?? null,
          name: column.name,
          color: column.color,
        })),
      });
      onSaved(updated);
      changeOpen(false);
      toast.success("Доска обновлена");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setLoading(false);
    }
  }

  async function toggleDefault(columnId: string, alreadyDefault: boolean) {
    if (alreadyDefault) {
      toast.message("Эта колонка уже установлена по умолчанию");
      return;
    }
    try {
      const updated = await api.patch<BoardColumn>(
        `/boards/${board.id}/columns/default`,
        { column_id: columnId },
      );
      setColumns((current) =>
        current.map((item) => ({
          ...item,
          isDefault: item.id === updated.id,
        })),
      );
      toast.success("Колонка установлена по умолчанию");
    } catch (error) {
      toast.error(formatError(error));
    }
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Settings2 className="size-4" />
          Настроить
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Настройка доски</DialogTitle>
          <DialogDescription>
            Меняйте названия и порядок колонок перетаскиванием. Задачи из
            удалённой колонки перейдут в первую.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <label htmlFor="board-name" className="text-sm font-medium">
            Название доски
          </label>
          <Input
            id="board-name"
            value={boardName}
            onChange={(event) => setBoardName(event.target.value)}
            maxLength={100}
            required
          />
        </div>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={dragEnd}
        >
          <SortableContext
            items={columns.map((column) => column.clientId)}
            strategy={verticalListSortingStrategy}
          >
            <div className="space-y-2">
              {columns.map((column, index) => (
                <SortableColumn
                  key={column.clientId}
                  column={column}
                  removable={columns.length > 1 && column.systemStatus === null}
                  canManage={board.can_manage_tasks}
                  onChange={(name) =>
                    setColumns((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, name } : item,
                      ),
                    )
                  }
                  onColorChange={(color) =>
                    setColumns((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, color } : item,
                      ),
                    )
                  }
                  onRemove={() =>
                    setColumns((current) =>
                      current.filter(
                        (item) => item.clientId !== column.clientId,
                      ),
                    )
                  }
                  onToggleDefault={() =>
                    column.id
                      ? toggleDefault(column.id, column.isDefault)
                      : undefined
                  }
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
        <Button
          type="button"
          variant="outline"
          className="w-full border-dashed"
          disabled={columns.length >= 10}
          onClick={() =>
            setColumns((current) => [
              ...current,
              {
                clientId: `new-${crypto.randomUUID()}`,
                name: "New status",
                systemStatus: null,
                color: "#06b6d4",
                isDefault: false,
              },
            ])
          }
        >
          <Plus className="size-4" />
          Добавить колонку
        </Button>
        <DialogFooter>
          <Button variant="outline" onClick={() => changeOpen(false)}>
            Отмена
          </Button>
          <Button onClick={save} disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : null}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
