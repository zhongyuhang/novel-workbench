import type { TiptapDoc, TiptapNode } from "../api/types.ts";

export function emptyDocument(): TiptapDoc {
  return { type: "doc", content: [{ type: "paragraph" }] };
}

export function documentToText(document: TiptapDoc): string {
  if (!Array.isArray(document.content)) {
    return "";
  }
  return document.content.map((node) => inlineText(node)).join("\n\n");
}

export function textToDocument(text: string): TiptapDoc {
  const normalized = text.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
  if (normalized === "") {
    return emptyDocument();
  }
  const blocks = normalized.split("\n\n").map((paragraph) => {
    const children: TiptapNode[] = [];
    const lines = paragraph.split("\n");
    lines.forEach((line, index) => {
      if (index > 0) {
        children.push({ type: "hardBreak" });
      }
      if (line) {
        children.push({ type: "text", text: line });
      }
    });
    if (children.length === 0) {
      return { type: "paragraph" };
    }
    return { type: "paragraph", content: children };
  });
  return { type: "doc", content: blocks };
}

export function wordCount(document: TiptapDoc): number {
  const text = documentToText(document);
  let count = 0;
  for (const char of text) {
    if (!/\s/u.test(char)) {
      count += 1;
    }
  }
  return count;
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortJson(value));
}

export function toTiptapDoc(value: { type?: unknown }): TiptapDoc {
  if (value.type !== "doc") {
    return emptyDocument();
  }
  return value as TiptapDoc;
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
      sorted[key] = sortJson(record[key]);
    }
    return sorted;
  }
  return value;
}

function inlineText(node: TiptapNode): string {
  const pieces: string[] = [];
  collectInline(node, pieces);
  return pieces.join("");
}

function collectInline(node: unknown, pieces: string[]): void {
  if (Array.isArray(node)) {
    for (const item of node) {
      collectInline(item, pieces);
    }
    return;
  }
  if (typeof node !== "object" || node === null) {
    return;
  }
  const record = node as TiptapNode;
  if (record.type === "text" && typeof record.text === "string") {
    pieces.push(record.text);
    return;
  }
  if (record.type === "hardBreak") {
    pieces.push("\n");
    return;
  }
  if (Array.isArray(record.content)) {
    collectInline(record.content, pieces);
  }
}
