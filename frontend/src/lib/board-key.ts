const CYRILLIC_TO_LATIN: Record<string, string> = {
  А: "A",
  Б: "B",
  В: "V",
  Г: "G",
  Д: "D",
  Е: "E",
  Ё: "E",
  Ж: "ZH",
  З: "Z",
  И: "I",
  Й: "Y",
  К: "K",
  Л: "L",
  М: "M",
  Н: "N",
  О: "O",
  П: "P",
  Р: "R",
  С: "S",
  Т: "T",
  У: "U",
  Ф: "F",
  Х: "H",
  Ц: "TS",
  Ч: "CH",
  Ш: "SH",
  Щ: "SH",
  Ъ: "",
  Ы: "Y",
  Ь: "",
  Э: "E",
  Ю: "YU",
  Я: "YA",
};

export function generateBoardKey(name: string): string {
  const letters = Array.from(name.toUpperCase())
    .map((letter) => CYRILLIC_TO_LATIN[letter] ?? letter)
    .join("")
    .normalize("NFKD")
    .replace(/[^A-Z]/g, "");
  return letters.length >= 2 ? letters.slice(0, 3) : "NOK";
}
