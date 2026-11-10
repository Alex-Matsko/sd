import { ImagePreview } from "./ImagePreview";
import { isImageAttachment, rasterImageBlob } from "../lib/imagePreview";
import { useEffect, useRef, useState } from "react";
import type { MessageUploadBlock } from "../api/types";

const key = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
type DraftBlock = { id: string; type: "text"; text: string } | { id: string; type: "image"; file: File };
export interface MessageDraft { blocks: DraftBlock[]; files: File[] }
export const emptyMessageDraft = (): MessageDraft => ({ blocks: [{ id: key(), type: "text", text: "" }], files: [] });
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
  return JSON.stringify([draft.blocks.map((b) => b.type === "text" ? b : [b.id, b.file.name, b.file.size, b.file.lastModified]),
    draft.files.map((f) => [f.name, f.size, f.lastModified])]);
}
function DraftImage({ file }: { file: File }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let next = "";
    rasterImageBlob(file).then((blob) => {
      if (!active) return;
      if (!blob) { setError("Не удалось показать превью этого файла"); return; }
      next = URL.createObjectURL(blob); setUrl(next);
    }).catch(() => { if (active) setError("Не удалось прочитать изображение"); });
    return () => { active = false; if (next) URL.revokeObjectURL(next); };
  }, [file]);
  return <ImagePreview url={url} filename={file.name} error={error} />;
}
export function RichMessageEditor({ value, onChange, label, disabled = false }: {
  value: MessageDraft; onChange: (draft: MessageDraft) => void; label: string; disabled?: boolean;
}) {
  const inputs = useRef(new Map<string, HTMLTextAreaElement>());
  const cursor = useRef<{ id: string; start: number; end: number } | null>(null);
  const [error, setError] = useState("");
  function insert(files: File[], position = cursor.current) {
    if (disabled || !files.length) return;
    const current = messageDraftPayload(value).files;
    if (current.length + files.length > 10) { setError("В одном сообщении может быть не более 10 файлов"); return; }
    if ([...current, ...files].some((f) => f.size > 25 * 1024 * 1024) || [...current, ...files].reduce((n, f) => n + f.size, 0) > 48 * 1024 * 1024) {
      setError("Лимит: 25 МБ на файл и 48 МБ на сообщение"); return;
    }
    setError("");
    const images = files.filter((f) => /^image\/(png|jpeg|gif|webp)$/.test(f.type) || (!f.type || f.type === "application/octet-stream") && /\.(png|jpe?g|gif|webp)$/i.test(f.name));
    const others = files.filter((f) => !images.includes(f));
    if (!images.length) { onChange({ ...value, files: [...value.files, ...others] }); return; }
    const saved = position;
    let at = saved ? value.blocks.findIndex((b) => b.id === saved.id && b.type === "text") : -1;
    if (at < 0) at = value.blocks.length - 1;
    const block = value.blocks[at];
    const text = block.type === "text" ? block.text : "";
    const start = saved?.id === block.id ? saved.start : text.length;
    const end = saved?.id === block.id ? saved.end : text.length;
    const tail: DraftBlock = { id: key(), type: "text", text: text.slice(end) };
    const inserted: DraftBlock[] = [{ id: block.id, type: "text", text: text.slice(0, start) },
      ...images.map((file): DraftBlock => ({ id: key(), type: "image", file })), tail];
    onChange({ blocks: [...value.blocks.slice(0, at), ...inserted, ...value.blocks.slice(at + 1)], files: [...value.files, ...others] });
    cursor.current = { id: tail.id, start: 0, end: 0 };
    requestAnimationFrame(() => { const input = inputs.current.get(tail.id); input?.focus(); input?.setSelectionRange(0, 0); });
  }
  return <div className="rich-editor-shell">
    <div className="rich-editor" aria-label={label} onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}
      onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); insert(Array.from(e.dataTransfer.files)); } }}>
      {value.blocks.map((block, index) => block.type === "text" ? <textarea key={block.id}
        ref={(el) => { if (el) inputs.current.set(block.id, el); else inputs.current.delete(block.id); }}
        aria-label={`${label}: текст ${value.blocks.slice(0, index + 1).filter((b) => b.type === "text").length}`}
        rows={Math.max(2, Math.min(16, block.text.split("\n").length + 1))} value={block.text} disabled={disabled}
        placeholder={index === 0 ? "Напишите текст или вставьте скриншот…" : "Продолжите текст после скриншота…"}
        onSelect={(e) => { cursor.current = { id: block.id, start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd }; }}
        onBlur={(e) => { cursor.current = { id: block.id, start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd }; }}
        onChange={(e) => onChange({ ...value, blocks: value.blocks.map((b) => b.id === block.id ? { ...block, text: e.target.value } : b) })}
        onPaste={(e) => { const files = Array.from(e.clipboardData.files); if (files.length) { e.preventDefault(); insert(files, { id: block.id, start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd }); } }}
      /> : <div key={block.id} className="rich-draft-image"><DraftImage file={block.file} />
        <div className="rich-draft-image-actions"><button type="button" disabled={disabled} aria-label={`Удалить скриншот ${block.file.name}`}
          onClick={() => onChange({ ...value, blocks: value.blocks.filter((b) => b.id !== block.id) })}>Удалить скриншот</button></div></div>)}
    </div>
    <div className="rich-editor-tools"><label className="rich-file-button">Добавить скриншот или файл<input aria-label={`${label}: добавить файлы`} type="file" multiple disabled={disabled}
      onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ""; insert(files); }} /></label>
      <span>Скриншот можно вставить из буфера. Enter — новая строка.</span></div>
    {value.files.map((file, i) => <div key={`${file.name}-${i}`} className="draft-file-attachment">{isImageAttachment({filename: file.name, mime_type: file.type}) ? <DraftImage file={file} /> : <span className="attachment-chip">{file.name}</span>}
      <button type="button" disabled={disabled} aria-label={`Удалить файл ${file.name}`} onClick={() => onChange({ ...value, files: value.files.filter((_, n) => n !== i) })}>Удалить файл</button></div>)}
    {error && <p role="alert" className="rich-editor-error">{error}</p>}
  </div>;
}
