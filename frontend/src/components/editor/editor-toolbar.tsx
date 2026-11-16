"use client";

import { type Editor, useEditorState } from "@tiptap/react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Columns3,
  Heading1,
  Heading2,
  Highlighter,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  Merge,
  Minus,
  Quote,
  Redo2,
  Rows3,
  Split,
  Strikethrough,
  Table2,
  Trash2,
  Underline,
  Undo2,
} from "lucide-react";
import { type ComponentType, useRef, useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const QUICK_TABLE_SIZE = 10;
const MAX_TABLE_DIMENSION = 50;
const ALLOWED_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);
const EXPLICIT_PROTOCOL_PATTERN = /^[a-z][a-z\d+.-]*:/i;

export function normalizeLinkHref(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed || [...trimmed].some((character) => /\s/.test(character))) {
    return null;
  }
  if (
    trimmed.startsWith("#") ||
    (trimmed.startsWith("/") && !trimmed.startsWith("//"))
  ) {
    return trimmed;
  }

  const href = trimmed.startsWith("//")
    ? `https:${trimmed}`
    : EXPLICIT_PROTOCOL_PATTERN.test(trimmed)
      ? trimmed
      : `https://${trimmed}`;

  try {
    const url = new URL(href);
    if (!ALLOWED_LINK_PROTOCOLS.has(url.protocol)) return null;
    if (url.protocol === "http:" || url.protocol === "https:") {
      if (!url.hostname || url.username || url.password) return null;
    } else if (!url.pathname) {
      return null;
    }
    return href;
  } catch {
    return null;
  }
}

interface ToolButtonProps {
  label: string;
  icon: ComponentType<{ className?: string }>;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

function ToolButton({
  label,
  icon: Icon,
  active,
  disabled,
  onClick,
}: ToolButtonProps) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-md text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-900 disabled:pointer-events-none disabled:opacity-30 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100",
        active && "bg-neutral-200 text-neutral-950 dark:bg-neutral-800 dark:text-neutral-100",
      )}
    >
      <Icon className="size-4" />
    </button>
  );
}

function Divider() {
  return <div className="mx-1 h-5 w-px shrink-0 bg-neutral-200 dark:bg-neutral-800" />;
}

interface TableActionButtonProps {
  label: string;
  icon?: ComponentType<{ className?: string }>;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}

function TableActionButton({
  label,
  icon: Icon,
  disabled,
  danger,
  onClick,
}: TableActionButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-muted-foreground transition hover:bg-card hover:text-card-foreground hover:shadow-sm disabled:pointer-events-none disabled:opacity-35",
        danger && "text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950 dark:hover:text-red-300",
      )}
    >
      {Icon ? <Icon className="size-3.5" /> : null}
      {label}
    </button>
  );
}

interface TableSizeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInsert: (rows: number, columns: number, withHeaderRow: boolean) => void;
}

export function TableSizeDialog({
  open,
  onOpenChange,
  onInsert,
}: TableSizeDialogProps) {
  const rowsInputRef = useRef<HTMLInputElement>(null);
  const [rowsInput, setRowsInput] = useState("3");
  const [columnsInput, setColumnsInput] = useState("3");
  const [withHeaderRow, setWithHeaderRow] = useState(true);

  function changeOpen(nextOpen: boolean) {
    if (nextOpen) {
      setRowsInput("3");
      setColumnsInput("3");
      setWithHeaderRow(true);
    }
    onOpenChange(nextOpen);
  }

  function parseDimension(value: string): number | null {
    const dimension = Number(value);
    return Number.isSafeInteger(dimension) &&
      dimension > 0 &&
      dimension <= MAX_TABLE_DIMENSION
      ? dimension
      : null;
  }

  const selectedRows = parseDimension(rowsInput);
  const selectedColumns = parseDimension(columnsInput);
  const canInsert = selectedRows !== null && selectedColumns !== null;

  function insert(rows: number, columns: number) {
    onInsert(rows, columns, withHeaderRow);
    onOpenChange(false);
  }

  function insertCustomSize() {
    if (!canInsert) return;
    insert(selectedRows, selectedColumns);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent
        className="max-w-md"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          rowsInputRef.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>Вставить таблицу</DialogTitle>
          <DialogDescription>
            Выберите быстрый размер или введите любое количество строк и
            столбцов вручную.
          </DialogDescription>
        </DialogHeader>

        <div>
          <div className="mb-3 text-center text-sm font-medium">
            {canInsert
              ? `${selectedRows} × ${selectedColumns}`
              : "Укажите корректный размер"}
          </div>
          <div className="mx-auto grid w-fit grid-cols-10 gap-1">
            {Array.from(
              { length: QUICK_TABLE_SIZE * QUICK_TABLE_SIZE },
              (_, index) => {
                const row = Math.floor(index / QUICK_TABLE_SIZE) + 1;
                const column = (index % QUICK_TABLE_SIZE) + 1;
                const selected =
                  selectedRows !== null &&
                  selectedColumns !== null &&
                  row <= selectedRows &&
                  column <= selectedColumns;

                return (
                  <button
                    key={`${row}-${column}`}
                    type="button"
                    aria-label={`Создать таблицу ${row} на ${column}`}
                    onMouseEnter={() => {
                      setRowsInput(String(row));
                      setColumnsInput(String(column));
                    }}
                    onFocus={() => {
                      setRowsInput(String(row));
                      setColumnsInput(String(column));
                    }}
                    onClick={() => insert(row, column)}
                    className={cn(
                      "size-5 rounded-[4px] border transition sm:size-6",
                      selected
                        ? "border-neutral-900 bg-neutral-900 dark:border-neutral-100 dark:bg-neutral-100"
                        : "border-neutral-300 bg-card hover:border-neutral-500 dark:border-neutral-700 dark:hover:border-neutral-500",
                    )}
                  />
                );
              },
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1.5 text-sm font-medium">
            <span>Строки</span>
            <input
              ref={rowsInputRef}
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_TABLE_DIMENSION}
              step={1}
              value={rowsInput}
              onChange={(event) => setRowsInput(event.target.value)}
              className="h-10 w-full rounded-lg border bg-card px-3 text-card-foreground outline-none transition focus:border-neutral-500 focus:ring-2 focus:ring-ring"
            />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            <span>Столбцы</span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_TABLE_DIMENSION}
              step={1}
              value={columnsInput}
              onChange={(event) => setColumnsInput(event.target.value)}
              className="h-10 w-full rounded-lg border bg-card px-3 text-card-foreground outline-none transition focus:border-neutral-500 focus:ring-2 focus:ring-ring"
            />
          </label>
        </div>

        <label className="flex cursor-pointer items-center gap-2 rounded-lg border bg-neutral-50 px-3 py-2.5 text-sm dark:bg-neutral-800 dark:border-neutral-700">
          <input
            type="checkbox"
            checked={withHeaderRow}
            onChange={(event) => setWithHeaderRow(event.target.checked)}
            className="size-4 accent-neutral-900 dark:accent-neutral-100"
          />
          Первая строка — заголовок
        </label>

        <button
          type="button"
          disabled={!canInsert}
          onClick={insertCustomSize}
          className="inline-flex h-10 items-center justify-center rounded-lg bg-neutral-950 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:pointer-events-none disabled:opacity-40 dark:bg-white dark:text-neutral-950 dark:hover:bg-neutral-200"
        >
          Создать таблицу
          {canInsert ? ` ${selectedRows} × ${selectedColumns}` : ""}
        </button>

        <p className="text-xs leading-5 text-muted-foreground">
          Максимум {MAX_TABLE_DIMENSION} строк и {MAX_TABLE_DIMENSION} столбцов.
        </p>
      </DialogContent>
    </Dialog>
  );
}

export function EditorToolbar({
  editor,
  uploading,
  onChooseImage,
}: {
  editor: Editor;
  uploading: boolean;
  onChooseImage: () => void;
}) {
  const [tableDialogOpen, setTableDialogOpen] = useState(false);

  useEditorState({
    editor,
    selector: ({ transactionNumber }) => transactionNumber,
  });

  const insideTable = editor.isActive("table");

  function setLink() {
    const previous = editor.getAttributes("link").href as string | undefined;
    const href = window.prompt("URL ссылки", previous ?? "https://");
    if (href === null) return;
    if (!href.trim()) {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    const normalizedHref = normalizeLinkHref(href);
    if (!normalizedHref) {
      toast.error("Укажите корректную ссылку: HTTPS, HTTP, email или телефон");
      return;
    }
    editor
      .chain()
      .focus()
      .extendMarkRange("link")
      .setLink({ href: normalizedHref })
      .run();
  }

  function insertTable(rows: number, columns: number, withHeaderRow: boolean) {
    editor
      .chain()
      .focus()
      .insertTable({
        rows,
        cols: columns,
        withHeaderRow,
      })
      .run();
  }

  return (
    <>
      <div className="border-b bg-card text-card-foreground">
        <div className="flex items-center gap-0.5 overflow-x-auto px-2 py-1.5">
          <ToolButton
            label="Отменить"
            icon={Undo2}
            disabled={!editor.can().chain().focus().undo().run()}
            onClick={() => editor.chain().focus().undo().run()}
          />
          <ToolButton
            label="Повторить"
            icon={Redo2}
            disabled={!editor.can().chain().focus().redo().run()}
            onClick={() => editor.chain().focus().redo().run()}
          />
          <Divider />
          <ToolButton
            label="Заголовок 1"
            icon={Heading1}
            active={editor.isActive("heading", { level: 1 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 1 }).run()
            }
          />
          <ToolButton
            label="Заголовок 2"
            icon={Heading2}
            active={editor.isActive("heading", { level: 2 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
          />
          <Divider />
          <ToolButton
            label="Жирный"
            icon={Bold}
            active={editor.isActive("bold")}
            onClick={() => editor.chain().focus().toggleBold().run()}
          />
          <ToolButton
            label="Курсив"
            icon={Italic}
            active={editor.isActive("italic")}
            onClick={() => editor.chain().focus().toggleItalic().run()}
          />
          <ToolButton
            label="Подчёркнутый"
            icon={Underline}
            active={editor.isActive("underline")}
            onClick={() => editor.chain().focus().toggleUnderline().run()}
          />
          <ToolButton
            label="Зачёркнутый"
            icon={Strikethrough}
            active={editor.isActive("strike")}
            onClick={() => editor.chain().focus().toggleStrike().run()}
          />
          <ToolButton
            label="Выделение"
            icon={Highlighter}
            active={editor.isActive("highlight")}
            onClick={() => editor.chain().focus().toggleHighlight().run()}
          />
          <ToolButton
            label="Код"
            icon={Code2}
            active={editor.isActive("code")}
            onClick={() => editor.chain().focus().toggleCode().run()}
          />
          <ToolButton
            label="Ссылка"
            icon={Link2}
            active={editor.isActive("link")}
            onClick={setLink}
          />
          <Divider />
          <ToolButton
            label="Маркированный список"
            icon={List}
            active={editor.isActive("bulletList")}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
          />
          <ToolButton
            label="Нумерованный список"
            icon={ListOrdered}
            active={editor.isActive("orderedList")}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
          />
          <ToolButton
            label="Цитата"
            icon={Quote}
            active={editor.isActive("blockquote")}
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
          />
          <ToolButton
            label="Разделитель"
            icon={Minus}
            onClick={() => editor.chain().focus().setHorizontalRule().run()}
          />
          <Divider />
          <ToolButton
            label="По левому краю"
            icon={AlignLeft}
            active={editor.isActive({ textAlign: "left" })}
            onClick={() => editor.chain().focus().setTextAlign("left").run()}
          />
          <ToolButton
            label="По центру"
            icon={AlignCenter}
            active={editor.isActive({ textAlign: "center" })}
            onClick={() => editor.chain().focus().setTextAlign("center").run()}
          />
          <ToolButton
            label="По правому краю"
            icon={AlignRight}
            active={editor.isActive({ textAlign: "right" })}
            onClick={() => editor.chain().focus().setTextAlign("right").run()}
          />
          <Divider />
          <ToolButton
            label="Вставить таблицу"
            icon={Table2}
            active={insideTable}
            onClick={() => setTableDialogOpen(true)}
          />
          <ToolButton
            label={uploading ? "Загрузка изображения…" : "Добавить изображение"}
            icon={ImagePlus}
            disabled={uploading}
            onClick={onChooseImage}
          />
        </div>

        {insideTable ? (
          <div className="flex items-center gap-1 overflow-x-auto border-t bg-neutral-50 px-2 py-1.5 dark:bg-neutral-800">
            <span className="mr-1 inline-flex shrink-0 items-center gap-1.5 px-1 text-[11px] font-semibold text-neutral-500 dark:text-neutral-400">
              <Table2 className="size-3.5" />
              Таблица
            </span>

            <TableActionButton
              label="Строка ↑"
              icon={Rows3}
              disabled={!editor.can().chain().focus().addRowBefore().run()}
              onClick={() => editor.chain().focus().addRowBefore().run()}
            />
            <TableActionButton
              label="Строка ↓"
              icon={Rows3}
              disabled={!editor.can().chain().focus().addRowAfter().run()}
              onClick={() => editor.chain().focus().addRowAfter().run()}
            />
            <TableActionButton
              label="Столбец ←"
              icon={Columns3}
              disabled={!editor.can().chain().focus().addColumnBefore().run()}
              onClick={() => editor.chain().focus().addColumnBefore().run()}
            />
            <TableActionButton
              label="Столбец →"
              icon={Columns3}
              disabled={!editor.can().chain().focus().addColumnAfter().run()}
              onClick={() => editor.chain().focus().addColumnAfter().run()}
            />

            <div className="mx-1 h-5 w-px shrink-0 bg-neutral-200 dark:bg-neutral-700" />

            <TableActionButton
              label="Удалить строку"
              disabled={!editor.can().chain().focus().deleteRow().run()}
              onClick={() => editor.chain().focus().deleteRow().run()}
            />
            <TableActionButton
              label="Удалить столбец"
              disabled={!editor.can().chain().focus().deleteColumn().run()}
              onClick={() => editor.chain().focus().deleteColumn().run()}
            />

            <div className="mx-1 h-5 w-px shrink-0 bg-neutral-200 dark:bg-neutral-700" />

            <TableActionButton
              label="Объединить"
              icon={Merge}
              disabled={!editor.can().chain().focus().mergeCells().run()}
              onClick={() => editor.chain().focus().mergeCells().run()}
            />
            <TableActionButton
              label="Разделить"
              icon={Split}
              disabled={!editor.can().chain().focus().splitCell().run()}
              onClick={() => editor.chain().focus().splitCell().run()}
            />
            <TableActionButton
              label="Заголовок"
              disabled={!editor.can().chain().focus().toggleHeaderRow().run()}
              onClick={() => editor.chain().focus().toggleHeaderRow().run()}
            />

            <div className="mx-1 h-5 w-px shrink-0 bg-neutral-200 dark:bg-neutral-700" />

            <TableActionButton
              label="Удалить таблицу"
              icon={Trash2}
              danger
              disabled={!editor.can().chain().focus().deleteTable().run()}
              onClick={() => editor.chain().focus().deleteTable().run()}
            />
          </div>
        ) : null}
      </div>

      <TableSizeDialog
        open={tableDialogOpen}
        onOpenChange={setTableDialogOpen}
        onInsert={insertTable}
      />
    </>
  );
}
