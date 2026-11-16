export interface SlashCommandRange {
  from: number;
  to: number;
  query: string;
}

export interface SearchableCommand {
  label: string;
  keywords: readonly string[];
}

export const DEFAULT_PAGE_TITLE = "Без названия";

/**
 * Slash commands are intentionally limited to the beginning of the current
 * text block. This keeps URLs and ordinary prose containing a slash from
 * opening the command menu.
 */
export function findSlashCommandRange(
  textBeforeCursor: string,
  blockStart: number,
): SlashCommandRange | null {
  const match = /^\/([^/]*)$/u.exec(textBeforeCursor);
  if (!match) return null;

  return {
    from: blockStart,
    to: blockStart + textBeforeCursor.length,
    query: match[1],
  };
}

function normalizeSearchValue(value: string): string {
  return value.trim().toLocaleLowerCase("ru-RU").replace(/\s+/g, " ");
}

export function commandMatchesQuery(
  command: SearchableCommand,
  query: string,
): boolean {
  const normalizedQuery = normalizeSearchValue(query);
  if (!normalizedQuery) return true;

  return [command.label, ...command.keywords].some((candidate) =>
    normalizeSearchValue(candidate).includes(normalizedQuery),
  );
}
