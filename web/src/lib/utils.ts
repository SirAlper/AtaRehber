import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Short random id for conversations; the API accepts [a-zA-Z0-9_-], at most 64 characters. */
export function newId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function formatDate(value: string | undefined, language: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === "tr" ? "tr-TR" : "en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Document name without the extension: "YÖNETMELİK.txt" -> "YÖNETMELİK". */
export function documentName(filename: string): string {
  return filename.replace(/\.(txt|pdf|docx)$/i, "");
}

/** Chunk text without the loader's header line "[DOCUMENT | Madde 30 – Title]". */
export function chunkText(content: string | undefined): string {
  return (content ?? "").replace(/^\[[^\]\n]*\]\n/, "").trim();
}

/** "Madde 30" from "Madde 30 – Emeklilik yaş haddi". */
export function articleShort(article: string | undefined): string {
  return (article ?? "").split(" – ")[0].trim();
}

export function splitGroups(text: string): string[] {
  return text
    .split(",")
    .map((group) => group.trim())
    .filter(Boolean);
}
