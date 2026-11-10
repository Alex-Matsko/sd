import type { JSONContent } from "@tiptap/core";
import type { MessageUploadBlock } from "../api/types";

export const draftKey = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
export type DraftBlock = { id: string; type: "text"; text: string } | { id: string; type: "image"; file: File };
export interface MessageDraft { blocks: DraftBlock[]; files: File[]; pending?: boolean }
export interface DraftImageFile { file: File; url: string }
export const emptyMessageDraft = (): MessageDraft => ({ blocks: [{ id: draftKey(), type: "text", text: "" }], files: [] });
export function messageDraftPayload(draft: MessageDraft) {
  const files: File[] = [];
  const content_blocks: MessageUploadBlock[] = draft.blocks.map((block) => {
    if (block.type === "text") return { type: "text", text: block.text };
    files.push(block.file);
    return { type: "image", file_index: files.length - 1 };
  });
  files.push(...draft.files);
  return { body: draft.blocks.filter((b) => b.type === "text").map((b) => b.text).join("\n"), content_blocks, files };
}
export function draftIdentity(draft: MessageDraft) {
  return JSON.stringify([draft.blocks.map((b) => b.type === "text" ? [b.type, b.text] : [b.id, b.file.name, b.file.size, b.file.lastModified]),
    draft.files.map((f) => [f.name, f.size, f.lastModified])]);
}
export function draftToDocument(draft: MessageDraft, images: Map<string, DraftImageFile>): JSONContent {
  const content: JSONContent[] = [];
  for (const block of draft.blocks) {
    if (block.type === "text") {
      for (const text of block.text.split("\n")) content.push({ type: "paragraph", content: text ? [{ type: "text", text }] : [] });
    } else {
      const image = images.get(block.id);
      if (image) content.push({ type: "image", attrs: { draftId: block.id, src: image.url, alt: block.file.name } });
    }
  }
  if (content.at(-1)?.type !== "paragraph") content.push({ type: "paragraph" });
  return { type: "doc", content };
}
export function documentToDraft(document: JSONContent, images: Map<string, DraftImageFile>, files: File[]): MessageDraft {
  const blocks: DraftBlock[] = [];
  let paragraphs: string[] = [];
  function flush() {
    if (paragraphs.length) blocks.push({ id: `text-${blocks.length}`, type: "text", text: paragraphs.join("\n") });
    paragraphs = [];
  }
  for (const node of document.content ?? []) {
    if (node.type === "paragraph") paragraphs.push((node.content ?? []).map((n) => n.type === "hardBreak" ? "\n" : n.text ?? "").join(""));
    else if (node.type === "image") {
      flush();
      const id = node.attrs?.draftId as string;
      const image = images.get(id);
      if (image) blocks.push({ id, type: "image", file: image.file });
    }
  }
  flush();
  return { blocks: blocks.length ? blocks : emptyMessageDraft().blocks, files };
}
