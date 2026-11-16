"use client";

import CharacterCount from "@tiptap/extension-character-count";
import Highlight from "@tiptap/extension-highlight";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import { TableKit } from "@tiptap/extension-table";
import TextAlign from "@tiptap/extension-text-align";
import { Markdown } from "@tiptap/markdown";
import {
  EditorContent,
  type Editor,
  type JSONContent,
  useEditor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code2,
  Columns3,
  Heading1,
  Heading2,
  Heading3,
  Highlighter,
  ImagePlus,
  Italic,
  Link2,
  List,
  ListOrdered,
  type LucideIcon,
  Minus,
  Pilcrow,
  Quote,
  Rows3,
  Strikethrough,
  Table2,
  Trash2,
  Underline,
} from "lucide-react";
import {
  type ChangeEvent,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import {
  normalizeLinkHref,
  TableSizeDialog,
} from "@/components/editor/editor-toolbar";
import {
  commandMatchesQuery,
  findSlashCommandRange,
  type SearchableCommand,
  type SlashCommandRange,
} from "@/components/editor/editor-utils";
import { api } from "@/lib/api";
import type { UploadResult } from "@/lib/types";
import { cn, formatError } from "@/lib/utils";

const MAX_IMAGE_BYTES = 25 * 1024 * 1024;
const CONTEXT_MENU_WIDTH = 272;
const SLASH_MENU_WIDTH = 288;
const SELECTION_TOOLBAR_HEIGHT = 42;

type BlockCommandId =
  | "paragraph"
  | "heading1"
  | "heading2"
  | "heading3"
  | "bulletList"
  | "orderedList"
  | "blockquote"
  | "codeBlock"
  | "horizontalRule"
  | "table"
  | "image";

interface BlockCommand extends SearchableCommand {
  id: BlockCommandId;
  icon: LucideIcon;
  description: string;
}

const BLOCK_COMMANDS: readonly BlockCommand[] = [
  {
    id: "paragraph",
    label: "Текст",
    description: "Обычный текстовый блок",
    icon: Pilcrow,
    keywords: ["абзац", "paragraph", "text"],
  },
  {
    id: "heading1",
    label: "Заголовок 1",
    description: "Крупный заголовок раздела",
    icon: Heading1,
    keywords: ["заголовок", "h1", "heading 1"],
  },
  {
    id: "heading2",
    label: "Заголовок 2",
    description: "Средний заголовок раздела",
    icon: Heading2,
    keywords: ["заголовок", "h2", "heading 2"],
  },
  {
    id: "heading3",
    label: "Заголовок 3",
    description: "Небольшой заголовок раздела",
    icon: Heading3,
    keywords: ["заголовок", "h3", "heading 3"],
  },
  {
    id: "bulletList",
    label: "Маркированный список",
    description: "Список с маркерами",
    icon: List,
    keywords: ["список", "bullet list", "ul"],
  },
  {
    id: "orderedList",
    label: "Нумерованный список",
    description: "Список с нумерацией",
    icon: ListOrdered,
    keywords: ["список", "ordered list", "ol"],
  },
  {
    id: "blockquote",
    label: "Цитата",
    description: "Выделенная цитата",
    icon: Quote,
    keywords: ["quote", "blockquote"],
  },
  {
    id: "codeBlock",
    label: "Блок кода",
    description: "Многострочный фрагмент кода",
    icon: Code2,
    keywords: ["код", "code", "pre"],
  },
  {
    id: "horizontalRule",
    label: "Разделитель",
    description: "Горизонтальная линия",
    icon: Minus,
    keywords: ["линия", "divider", "horizontal rule", "hr"],
  },
  {
    id: "table",
    label: "Таблица",
    description: "Таблица выбранного размера",
    icon: Table2,
    keywords: ["строки", "столбцы", "table"],
  },
  {
    id: "image",
    label: "Изображение",
    description: "Загрузить изображение",
    icon: ImagePlus,
    keywords: ["картинка", "фото", "image", "photo"],
  },
];

interface PositionedMenu {
  x: number;
  y: number;
  visible: boolean;
  placeBelow?: boolean;
}

interface SlashMenuState extends PositionedMenu {
  range: SlashCommandRange | null;
}

const HIDDEN_MENU: PositionedMenu = { x: 0, y: 0, visible: false };
const HIDDEN_SLASH_MENU: SlashMenuState = {
  ...HIDDEN_MENU,
  range: null,
};

function clampMenuX(x: number, width: number): number {
  if (typeof window === "undefined") return x;
  return Math.max(8, Math.min(x, window.innerWidth - width - 8));
}

function clampMenuY(y: number, preferredHeight: number): number {
  if (typeof window === "undefined") return y;
  const availableHeight = Math.max(0, window.innerHeight - 16);
  const visibleHeight = Math.min(preferredHeight, availableHeight);
  return Math.max(8, Math.min(y, window.innerHeight - visibleHeight - 8));
}

export function PageEditor({
  initialContent,
  editable,
  teamId,
  onChange,
}: {
  initialContent: Record<string, unknown>;
  editable: boolean;
  teamId: string;
  onChange?: (content: Record<string, unknown>, markdown: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const editorContentRef = useRef<HTMLDivElement>(null);
  const [uploading, setUploading] = useState(false);
  const [tableDialogOpen, setTableDialogOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<PositionedMenu>(HIDDEN_MENU);
  const [selectionToolbar, setSelectionToolbar] =
    useState<PositionedMenu>(HIDDEN_MENU);
  const [slashMenu, setSlashMenu] = useState<SlashMenuState>(HIDDEN_SLASH_MENU);
  const [slashQuery, setSlashQuery] = useState("");
  const [selectedSlashIndex, setSelectedSlashIndex] = useState(0);

  const updateSlashMenu = useCallback(
    (activeEditor: Editor) => {
      if (!editable || !activeEditor.isEditable) {
        setSlashMenu(HIDDEN_SLASH_MENU);
        return;
      }

      const { selection } = activeEditor.state;
      const { $from } = selection;
      if (!selection.empty || !$from.parent.isTextblock) {
        setSlashMenu(HIDDEN_SLASH_MENU);
        return;
      }

      const textBeforeCursor = $from.parent.textBetween(
        0,
        $from.parentOffset,
        undefined,
        "\ufffc",
      );
      const range = findSlashCommandRange(textBeforeCursor, $from.start());
      if (!range) {
        setSlashMenu(HIDDEN_SLASH_MENU);
        return;
      }

      const coordinates = activeEditor.view.coordsAtPos(selection.from);
      setSlashQuery(range.query);
      setSelectedSlashIndex(0);
      setSlashMenu({
        x: clampMenuX(coordinates.left, SLASH_MENU_WIDTH),
        y: clampMenuY(coordinates.bottom + 8, 440),
        visible: true,
        range,
      });
    },
    [editable],
  );

  const updateSelectionToolbar = useCallback(
    (activeEditor: Editor) => {
      const { selection } = activeEditor.state;
      if (
        !editable ||
        !activeEditor.isEditable ||
        selection.empty ||
        !selection.$from.parent.inlineContent
      ) {
        setSelectionToolbar(HIDDEN_MENU);
        return;
      }

      const start = activeEditor.view.coordsAtPos(selection.from);
      const end = activeEditor.view.coordsAtPos(selection.to);
      const centeredX = (start.left + end.right) / 2;
      const selectionTop = Math.min(start.top, end.top);
      const selectionBottom = Math.max(start.bottom, end.bottom);
      const placeBelow = selectionTop < SELECTION_TOOLBAR_HEIGHT + 16;
      setSelectionToolbar({
        x:
          typeof window === "undefined"
            ? centeredX
            : Math.max(164, Math.min(centeredX, window.innerWidth - 164)),
        y:
          typeof window === "undefined"
            ? selectionTop - 8
            : placeBelow
              ? Math.min(
                  Math.max(8, selectionBottom + 8),
                  Math.max(8, window.innerHeight - SELECTION_TOOLBAR_HEIGHT - 8),
                )
              : selectionTop - 8,
        visible: true,
        placeBelow,
      });
    },
    [editable],
  );

  const editor = useEditor({
    immediatelyRender: false,
    editable,
    content: initialContent as JSONContent,
    extensions: [
      StarterKit.configure({
        link: {
          openOnClick: true,
          enableClickSelection: true,
          defaultProtocol: "https",
        },
      }),
      Highlight,
      Image.configure({
        allowBase64: false,
        HTMLAttributes: {
          class: "noki-page-image",
        },
      }),
      Placeholder.configure({
        placeholder: "Начните писать или нажмите / для команд…",
      }),
      TextAlign.configure({
        types: ["heading", "paragraph"],
      }),
      TableKit.configure({
        table: {
          resizable: true,
        },
      }),
      CharacterCount.configure({
        limit: 200_000,
      }),
      Markdown,
    ],
    editorProps: useMemo(
      () => ({
        attributes: {
          class: "mx-auto w-full max-w-3xl px-5 pb-36 pt-6 md:px-10",
        },
        handleKeyDown: (_view: unknown, event: KeyboardEvent) =>
          handleKeyDownRef.current(event),
      }),
      [],
    ),
    onUpdate: ({ editor: activeEditor }) => {
      if (!activeEditor.isEditable) return;
      onChange?.(
        activeEditor.getJSON() as Record<string, unknown>,
        activeEditor.getMarkdown(),
      );
      updateSlashMenu(activeEditor);
    },
    onSelectionUpdate: ({ editor: activeEditor }) => {
      updateSelectionToolbar(activeEditor);
      updateSlashMenu(activeEditor);
    },
    onBlur: () => {
      setSelectionToolbar(HIDDEN_MENU);
    },
  });

  const filteredSlashCommands = useMemo(
    () =>
      BLOCK_COMMANDS.filter((command) =>
        commandMatchesQuery(command, slashQuery),
      ),
    [slashQuery],
  );
  const activeSlashIndex =
    selectedSlashIndex < filteredSlashCommands.length ? selectedSlashIndex : 0;

  const slashMenuRef = useRef(slashMenu);
  const filteredSlashCommandsRef = useRef(filteredSlashCommands);
  const activeSlashIndexRef = useRef(activeSlashIndex);
  const handleKeyDownRef = useRef<(event: { key: string }) => boolean>(() => false);

  useEffect(() => {
    editor?.setEditable(editable);
  }, [editable, editor]);

  useEffect(() => {
    slashMenuRef.current = slashMenu;
  }, [slashMenu]);

  useEffect(() => {
    filteredSlashCommandsRef.current = filteredSlashCommands;
  }, [filteredSlashCommands]);

  useEffect(() => {
    activeSlashIndexRef.current = activeSlashIndex;
  }, [activeSlashIndex]);

  useEffect(() => {
    function closeMenusOnPointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest("[data-editor-menu]")) return;

      setContextMenu(HIDDEN_MENU);
      setSlashMenu(HIDDEN_SLASH_MENU);
      if (!editorContentRef.current?.contains(target)) {
        setSelectionToolbar(HIDDEN_MENU);
      }
    }

    document.addEventListener("pointerdown", closeMenusOnPointerDown);
    return () =>
      document.removeEventListener("pointerdown", closeMenusOnPointerDown);
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(HIDDEN_MENU);
  }, []);

  const closeSelectionToolbar = useCallback(() => {
    setSelectionToolbar(HIDDEN_MENU);
  }, []);

  const closeSlashMenu = useCallback(() => {
    setSlashMenu(HIDDEN_SLASH_MENU);
    setSlashQuery("");
  }, []);

  const prepareCommand = useCallback(
    (slashRange?: SlashCommandRange | null) => {
      if (!editor) return null;
      const chain = editor.chain().focus();
      if (slashRange) chain.deleteRange(slashRange);
      return chain;
    },
    [editor],
  );

  const runBlockCommand = useCallback(
    (commandId: BlockCommandId, slashRange?: SlashCommandRange | null) => {
      if (!editor) return;
      if (commandId === "image" && uploading) return;
      closeContextMenu();
      closeSelectionToolbar();
      closeSlashMenu();

      const chain = prepareCommand(slashRange);
      if (!chain) return;

      switch (commandId) {
        case "paragraph":
          chain.setParagraph().run();
          break;
        case "heading1":
          chain.toggleHeading({ level: 1 }).run();
          break;
        case "heading2":
          chain.toggleHeading({ level: 2 }).run();
          break;
        case "heading3":
          chain.toggleHeading({ level: 3 }).run();
          break;
        case "bulletList":
          chain.toggleBulletList().run();
          break;
        case "orderedList":
          chain.toggleOrderedList().run();
          break;
        case "blockquote":
          chain.toggleBlockquote().run();
          break;
        case "codeBlock":
          chain.toggleCodeBlock().run();
          break;
        case "horizontalRule":
          chain.setHorizontalRule().run();
          break;
        case "table":
          chain.run();
          setTableDialogOpen(true);
          break;
        case "image":
          chain.run();
          if (!uploading) fileInputRef.current?.click();
          break;
      }
    },
    [
      closeContextMenu,
      closeSelectionToolbar,
      closeSlashMenu,
      editor,
      prepareCommand,
      uploading,
    ],
  );

  const handleKeyDown = useCallback(
    (event: { key: string }) => {
      const currentSlashMenu = slashMenuRef.current;
      if (!currentSlashMenu.visible) return false;
      if (!filteredSlashCommandsRef.current.length) return false;

      if (event.key === "Escape") {
        closeSlashMenu();
        return true;
      }
      if (event.key === "ArrowDown") {
        setSelectedSlashIndex(
          (current) =>
            (current + 1) % filteredSlashCommandsRef.current.length,
        );
        return true;
      }
      if (event.key === "ArrowUp") {
        setSelectedSlashIndex(
          (current) =>
            (current - 1 + filteredSlashCommandsRef.current.length) %
            filteredSlashCommandsRef.current.length,
        );
        return true;
      }
      if (event.key === "Enter") {
        const command = filteredSlashCommandsRef.current[activeSlashIndexRef.current];
        if (command) runBlockCommand(command.id, currentSlashMenu.range);
        return true;
      }
      return false;
    },
    [closeSlashMenu, runBlockCommand],
  );

  useEffect(() => {
    handleKeyDownRef.current = handleKeyDown;
  }, [handleKeyDown]);

  const setLink = useCallback(() => {
    if (!editor) return;
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
  }, [editor]);

  const handleContextMenu = useCallback(
    (event: ReactMouseEvent) => {
      if (!editable || !editor) return;
      event.preventDefault();

      const position = editor.view.posAtCoords({
        left: event.clientX,
        top: event.clientY,
      });
      const { from, to } = editor.state.selection;
      if (
        position &&
        (from === to || position.pos < from || position.pos > to)
      ) {
        editor.commands.setTextSelection(position.pos);
      }

      setSelectionToolbar(HIDDEN_MENU);
      setSlashMenu(HIDDEN_SLASH_MENU);
      setContextMenu({
        x: clampMenuX(event.clientX, CONTEXT_MENU_WIDTH),
        y: clampMenuY(event.clientY, 480),
        visible: true,
      });
    },
    [editable, editor],
  );


  async function uploadImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!editable || !file || !editor) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Выберите изображение JPEG, PNG, WebP или GIF");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error("Изображение превышает лимит 25 МБ");
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const uploaded = await api.upload<UploadResult>(
        `/uploads/images?team_id=${encodeURIComponent(teamId)}`,
        formData,
      );
      editor
        .chain()
        .focus()
        .setImage({ src: uploaded.url, alt: file.name.slice(0, 200) })
        .run();
      toast.success("Изображение добавлено");
    } catch (error) {
      toast.error(formatError(error));
    } finally {
      setUploading(false);
    }
  }

  if (!editor) {
    return <div className="h-72 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />;
  }

  const insideTable = editor.isActive("table");

  return (
    <div className="editor-content" ref={editorContentRef}>
      {editable ? (
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="hidden"
          onChange={uploadImage}
        />
      ) : null}

      <EditorContent
        editor={editor}
        onContextMenu={handleContextMenu}
      />

      {contextMenu.visible && editable ? (
        <div
          data-editor-menu
          role="menu"
          aria-label="Форматирование блока"
          className="fixed z-50 w-[272px] max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xl border bg-card p-1.5 text-card-foreground shadow-xl"
          style={{
            left: contextMenu.x,
            top: contextMenu.y,
            maxHeight: `calc(100vh - ${contextMenu.y + 8}px)`,
          }}
          onMouseDown={(event) => event.preventDefault()}
        >
          <MenuLabel>Тип блока</MenuLabel>
          <div className="grid grid-cols-2 gap-0.5">
            {BLOCK_COMMANDS.slice(0, 6).map((command) => (
              <ContextMenuItem
                key={command.id}
                label={command.label}
                icon={command.icon}
                onClick={() => runBlockCommand(command.id)}
              />
            ))}
          </div>
          <MenuDivider />
          <MenuLabel>Текст</MenuLabel>
          <div className="flex items-center gap-0.5 px-1 pb-1">
            <ToolbarButton
              label="Жирный"
              icon={Bold}
              active={editor.isActive("bold")}
              onClick={() => editor.chain().focus().toggleBold().run()}
            />
            <ToolbarButton
              label="Курсив"
              icon={Italic}
              active={editor.isActive("italic")}
              onClick={() => editor.chain().focus().toggleItalic().run()}
            />
            <ToolbarButton
              label="Подчёркнутый"
              icon={Underline}
              active={editor.isActive("underline")}
              onClick={() => editor.chain().focus().toggleUnderline().run()}
            />
            <ToolbarButton
              label="Зачёркнутый"
              icon={Strikethrough}
              active={editor.isActive("strike")}
              onClick={() => editor.chain().focus().toggleStrike().run()}
            />
            <ToolbarButton
              label="Выделение"
              icon={Highlighter}
              active={editor.isActive("highlight")}
              onClick={() => editor.chain().focus().toggleHighlight().run()}
            />
            <ToolbarButton
              label="Ссылка"
              icon={Link2}
              active={editor.isActive("link")}
              onClick={setLink}
            />
          </div>
          <MenuDivider />
          <MenuLabel>Вставка</MenuLabel>
          {BLOCK_COMMANDS.slice(6).map((command) => (
            <ContextMenuItem
              key={command.id}
              label={
                command.id === "image" && uploading
                  ? "Загрузка изображения…"
                  : command.label
              }
              icon={command.icon}
              disabled={command.id === "image" && uploading}
              onClick={() => runBlockCommand(command.id)}
            />
          ))}
          <MenuDivider />
          <MenuLabel>Выравнивание</MenuLabel>
          <div className="flex items-center gap-0.5 px-1 pb-1">
            <ToolbarButton
              label="По левому краю"
              icon={AlignLeft}
              active={editor.isActive({ textAlign: "left" })}
              onClick={() => editor.chain().focus().setTextAlign("left").run()}
            />
            <ToolbarButton
              label="По центру"
              icon={AlignCenter}
              active={editor.isActive({ textAlign: "center" })}
              onClick={() =>
                editor.chain().focus().setTextAlign("center").run()
              }
            />
            <ToolbarButton
              label="По правому краю"
              icon={AlignRight}
              active={editor.isActive({ textAlign: "right" })}
              onClick={() => editor.chain().focus().setTextAlign("right").run()}
            />
          </div>

          {insideTable ? (
            <>
              <MenuDivider />
              <MenuLabel>Таблица</MenuLabel>
              <ContextMenuItem
                label="Добавить строку сверху"
                icon={Rows3}
                disabled={!editor.can().chain().focus().addRowBefore().run()}
                onClick={() => editor.chain().focus().addRowBefore().run()}
              />
              <ContextMenuItem
                label="Добавить строку снизу"
                icon={Rows3}
                disabled={!editor.can().chain().focus().addRowAfter().run()}
                onClick={() => editor.chain().focus().addRowAfter().run()}
              />
              <ContextMenuItem
                label="Добавить столбец слева"
                icon={Columns3}
                disabled={!editor.can().chain().focus().addColumnBefore().run()}
                onClick={() => editor.chain().focus().addColumnBefore().run()}
              />
              <ContextMenuItem
                label="Добавить столбец справа"
                icon={Columns3}
                disabled={!editor.can().chain().focus().addColumnAfter().run()}
                onClick={() => editor.chain().focus().addColumnAfter().run()}
              />
              <ContextMenuItem
                label="Удалить строку"
                icon={Trash2}
                disabled={!editor.can().chain().focus().deleteRow().run()}
                onClick={() => editor.chain().focus().deleteRow().run()}
                danger
              />
              <ContextMenuItem
                label="Удалить столбец"
                icon={Trash2}
                disabled={!editor.can().chain().focus().deleteColumn().run()}
                onClick={() => editor.chain().focus().deleteColumn().run()}
                danger
              />
              <ContextMenuItem
                label="Удалить таблицу"
                icon={Trash2}
                disabled={!editor.can().chain().focus().deleteTable().run()}
                onClick={() => editor.chain().focus().deleteTable().run()}
                danger
              />
            </>
          ) : null}
        </div>
      ) : null}

      {selectionToolbar.visible && editable ? (
        <div
          data-editor-menu
          role="toolbar"
          aria-label="Форматирование выделенного текста"
          className={cn(
            "fixed z-50 flex max-w-[calc(100vw-1rem)] -translate-x-1/2 items-center gap-0.5 overflow-x-auto rounded-xl border bg-card p-1 text-card-foreground shadow-xl",
            !selectionToolbar.placeBelow && "-translate-y-full",
          )}
          style={{ left: selectionToolbar.x, top: selectionToolbar.y }}
          onMouseDown={(event) => event.preventDefault()}
        >
          <ToolbarButton
            label="Жирный"
            icon={Bold}
            active={editor.isActive("bold")}
            onClick={() => editor.chain().focus().toggleBold().run()}
          />
          <ToolbarButton
            label="Курсив"
            icon={Italic}
            active={editor.isActive("italic")}
            onClick={() => editor.chain().focus().toggleItalic().run()}
          />
          <ToolbarButton
            label="Подчёркнутый"
            icon={Underline}
            active={editor.isActive("underline")}
            onClick={() => editor.chain().focus().toggleUnderline().run()}
          />
          <ToolbarButton
            label="Зачёркнутый"
            icon={Strikethrough}
            active={editor.isActive("strike")}
            onClick={() => editor.chain().focus().toggleStrike().run()}
          />
          <ToolbarButton
            label="Выделение"
            icon={Highlighter}
            active={editor.isActive("highlight")}
            onClick={() => editor.chain().focus().toggleHighlight().run()}
          />
          <ToolbarButton
            label="Код"
            icon={Code2}
            active={editor.isActive("code")}
            onClick={() => editor.chain().focus().toggleCode().run()}
          />
          <ToolbarButton
            label="Ссылка"
            icon={Link2}
            active={editor.isActive("link")}
            onClick={() => {
              closeSelectionToolbar();
              setLink();
            }}
          />
        </div>
      ) : null}

      {slashMenu.visible && editable ? (
        <div
          data-editor-menu
          role="listbox"
          aria-label="Команды редактора"
          className="fixed z-50 w-72 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xl border bg-card p-1.5 text-card-foreground shadow-xl"
          style={{
            left: slashMenu.x,
            top: slashMenu.y,
            maxHeight: `calc(100vh - ${slashMenu.y + 8}px)`,
          }}
          onMouseDown={(event) => event.preventDefault()}
        >
          <div className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">
            {slashQuery ? `Команды: ${slashQuery}` : "Что создать?"}
          </div>
          {filteredSlashCommands.length ? (
            filteredSlashCommands.map((command, index) => (
              <SlashItem
                key={command.id}
                command={command}
                selected={index === activeSlashIndex}
                disabled={command.id === "image" && uploading}
                onMouseEnter={() => setSelectedSlashIndex(index)}
                onClick={() => runBlockCommand(command.id, slashMenu.range)}
              />
            ))
          ) : (
            <div className="px-3 py-5 text-center text-sm text-muted-foreground">
              Ничего не найдено
            </div>
          )}
          <div className="border-t px-2 pb-1 pt-2 text-[11px] text-neutral-400 dark:text-neutral-500 dark:border-neutral-800">
            ↑↓ выбрать · Enter вставить · Esc закрыть
          </div>
        </div>
      ) : null}

      <TableSizeDialog
        open={tableDialogOpen}
        onOpenChange={setTableDialogOpen}
        onInsert={(rows, columns, withHeaderRow) => {
          editor
            .chain()
            .focus()
            .insertTable({ rows, cols: columns, withHeaderRow })
            .run();
        }}
      />

      <div className="pointer-events-none fixed bottom-4 right-5 rounded-full border bg-card/90 px-2.5 py-1 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
        {editor.storage.characterCount.characters().toLocaleString("ru-RU")} /
        200 000
      </div>
    </div>
  );
}

function MenuLabel({ children }: { children: string }) {
  return (
    <div className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">
      {children}
    </div>
  );
}

function MenuDivider() {
  return <div className="my-1 border-t" />;
}

function ContextMenuItem({
  label,
  icon: Icon,
  disabled,
  danger,
  onClick,
}: {
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      className={cn(
        "flex min-h-8 w-full items-center gap-2 rounded-md px-2 text-left text-xs text-neutral-600 transition hover:bg-neutral-100 hover:text-neutral-950 disabled:pointer-events-none disabled:opacity-35 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100",
        danger && "text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950 dark:hover:text-red-300",
      )}
      onClick={onClick}
    >
      <Icon className="size-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function SlashItem({
  command,
  selected,
  disabled,
  onMouseEnter,
  onClick,
}: {
  command: BlockCommand;
  selected: boolean;
  disabled?: boolean;
  onMouseEnter: () => void;
  onClick: () => void;
}) {
  const Icon = command.icon;
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition disabled:pointer-events-none disabled:opacity-35",
        selected ? "bg-neutral-100 dark:bg-neutral-800" : "hover:bg-neutral-50 dark:hover:bg-neutral-800",
      )}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-md border bg-card text-muted-foreground">
        <Icon className="size-4" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-neutral-800 dark:text-neutral-200">
          {command.label}
        </span>
        <span className="block truncate text-[11px] text-neutral-400 dark:text-neutral-500">
          {command.description}
        </span>
      </span>
    </button>
  );
}

function ToolbarButton({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string;
  icon: LucideIcon;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
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
