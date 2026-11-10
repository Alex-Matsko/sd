import { useEffect, useRef, useState } from "react";
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor } from "@tiptap/react";
import type { JSONContent, NodeViewProps } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import HardBreak from "@tiptap/extension-hard-break";
import Image from "@tiptap/extension-image";
import { UndoRedo, Gapcursor, Dropcursor } from "@tiptap/extensions";
import { EditorState } from "@tiptap/pm/state";
import { Slice } from "@tiptap/pm/model";
import { ImagePreview } from "./ImagePreview";
import { rasterImageBlob } from "../lib/imagePreview";
import { documentToDraft, draftToDocument, draftIdentity, draftKey, messageDraftPayload } from "../lib/messageDraft";
import type { DraftImageFile, MessageDraft } from "../lib/messageDraft";
export { emptyMessageDraft, messageDraftPayload, draftIdentity } from "../lib/messageDraft";
export type { MessageDraft } from "../lib/messageDraft";

function ImageNodeView({ node, deleteNode, editor }: NodeViewProps) {
  return <NodeViewWrapper className="editor-image-node" contentEditable={false}>
    <ImagePreview url={node.attrs.src} filename={node.attrs.alt || "Скриншот"} compact minimal />
    <button type="button" className="editor-image-remove" aria-label={`Удалить скриншот ${node.attrs.alt || ""}`} onClick={() => { if (editor.isEditable) deleteNode(); }}>×</button>
  </NodeViewWrapper>;
}
const DraftImage = Image.extend({
  addAttributes() { return { ...this.parent?.(), draftId: { default: null, rendered: false } }; },
  addNodeView() { return ReactNodeViewRenderer(ImageNodeView); },
}).configure({ allowBase64: false, inline: false });

function ClipIcon() {
  return <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9"/><path d="m6 14 8-8"/></svg>;
}

export function RichMessageEditor({ value, onChange, label, disabled = false }: {
  value: MessageDraft; onChange: (draft: MessageDraft) => void; label: string; disabled?: boolean;
}) {
  const images = useRef(new Map<string, DraftImageFile>());
  const current = useRef(value);
  const changed = useRef(onChange);
  const lastEmitted = useRef(draftIdentity(value));
  const savedSelection = useRef<{ from: number; to: number } | null>(null);
  const insertionBusy = useRef(false);
  const insertRef = useRef<(files: File[], selection?: { from: number; to: number }) => void>(() => {});
  const fileInput = useRef<HTMLInputElement>(null);
  const generation = useRef({ version: 0, active: true });
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [, refreshControls] = useState(0);
  useEffect(() => { current.current = value; changed.current = onChange; }, [value, onChange]);

  function emit(next: MessageDraft) {
    current.current = next; lastEmitted.current = draftIdentity(next); changed.current(next);
  }
  const editor = useEditor({
    extensions: [Document, Paragraph, Text, HardBreak, DraftImage, UndoRedo, Gapcursor, Dropcursor],
    content: { type: "doc", content: [{ type: "paragraph" }] },
    editorProps: {
      attributes: { role: "textbox", "aria-label": label, "aria-multiline": "true", class: "tiptap-message-input" },
      handlePaste(view, event) {
        const files = Array.from(event.clipboardData?.files ?? []);
        if (files.length) { event.preventDefault(); insertRef.current(files, view.state.selection); return true; }
        // Paste plain text only. External HTML and remote image URLs never enter the draft.
        const text = event.clipboardData?.getData("text/plain");
        if (text !== undefined) {
          event.preventDefault();
          const paragraphs = text.replace(/\r\n?/g, "\n").split("\n").map((line) => view.state.schema.nodes.paragraph.create(null, line ? view.state.schema.text(line) : null));
          const fragment = view.state.schema.nodes.doc.create(null, paragraphs).content;
          const tr = view.state.tr.replaceSelection(new Slice(fragment, 1, 1));
          view.dispatch(tr.scrollIntoView());
          return true;
        }
        return true;
      },
      handleDrop(view, event, _slice, moved) {
        const files = Array.from(event.dataTransfer?.files ?? []);
        if (moved) return false;
        event.preventDefault();
        const pos = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos ?? view.state.selection.from;
        if (!files.length) {
          const text = event.dataTransfer?.getData("text/plain");
          if (text) view.dispatch(view.state.tr.insertText(text, pos).scrollIntoView());
          return true;
        }
        insertRef.current(files, { from: pos, to: pos }); return true;
      },
    },
    onUpdate({ editor: active }) { emit(documentToDraft(active.getJSON(), images.current, current.current.files)); },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!disabled && !adding, false);
  }, [editor, disabled, adding]);
  useEffect(() => {
    if (!editor || value.pending || draftIdentity(value) === lastEmitted.current) return;
    lastEmitted.current = draftIdentity(value);
    const doc = draftToDocument(value, images.current);
    if (!messageDraftPayload(value).body && !messageDraftPayload(value).files.length) {
      // Sending a message clears its undo history as well as its visible contents.
      generation.current.version++;
      editor.view.updateState(EditorState.create({ schema: editor.schema, doc: editor.schema.nodeFromJSON(doc), plugins: editor.state.plugins }));
      for (const image of images.current.values()) URL.revokeObjectURL(image.url);
      images.current.clear();
      refreshControls((n) => n + 1);
    } else {
      editor.commands.setContent(doc, { emitUpdate: false });
      refreshControls((n) => n + 1);
    }
  }, [editor, value]);
  useEffect(() => {
    const pool = images.current;
    const life = generation.current;
    life.active = true;
    return () => { life.active = false; life.version++; for (const image of pool.values()) URL.revokeObjectURL(image.url); pool.clear(); };
  }, []);

  async function insert(files: File[], selection = savedSelection.current ?? editor?.state.selection) {
    if (!editor || disabled || insertionBusy.current || !files.length) return;
    const activeFiles = messageDraftPayload(current.current).files;
    if (activeFiles.length + files.length > 10) { setError("Можно прикрепить не более 10 файлов"); return; }
    if (files.some((f) => f.size > 25 * 1024 * 1024) || [...activeFiles, ...files].reduce((n, f) => n + f.size, 0) > 48 * 1024 * 1024) {
      setError("Лимит: 25 МБ на файл и 48 МБ на сообщение"); return;
    }
    insertionBusy.current = true;
    setError(""); setAdding(true);
    emit({ ...current.current, pending: true });
    const epoch = generation.current.version;
    try {
      const prepared = await Promise.all(files.map(async (file) => ({ file, blob: await rasterImageBlob(file) })));
      if (editor.isDestroyed || epoch !== generation.current.version || !generation.current.active) return;
      const nodes: JSONContent[] = [];
      const attachments = [...current.current.files];
      for (const { file, blob } of prepared) {
        if (blob && ["image/png", "image/jpeg", "image/gif", "image/webp"].includes(blob.type)) {
          const id = draftKey(), url = URL.createObjectURL(blob);
          images.current.set(id, { file, url });
          nodes.push({ type: "image", attrs: { src: url, alt: file.name, draftId: id } });
        } else attachments.push(file);
      }
      current.current = { ...current.current, files: attachments, pending: false };
      if (nodes.length) {
        nodes.push({ type: "paragraph" });
        const max = editor.state.doc.content.size;
        const from = Math.min(selection?.from ?? max, max), to = Math.min(selection?.to ?? from, max);
        editor.chain().focus().setTextSelection({ from, to }).insertContent(nodes).run();
      }
      emit(documentToDraft(editor.getJSON(), images.current, attachments));
    } catch { setError("Не удалось добавить файл. Попробуйте ещё раз."); emit({ ...current.current, pending: false }); }
    finally { insertionBusy.current = false; setAdding(false); }
  }
  useEffect(() => { insertRef.current = (files, selection) => { void insert(files, selection); }; });

  const empty = !messageDraftPayload(value).body && !value.blocks.some((b) => b.type === "image");
  return <div className={`rich-editor-shell single-message-editor ${empty ? "is-empty" : ""}`}>
    <div className="single-editor-canvas" data-placeholder={label === "Внутренний комментарий" ? "Напишите комментарий…" : "Напишите сообщение…"}>
      <EditorContent editor={editor} />
    </div>
    {value.files.length > 0 && <div className="editor-file-list">{value.files.map((file, index) => <span className="editor-file-chip" key={`${file.name}-${index}`}><ClipIcon /><span>{file.name}</span>
      <button type="button" disabled={disabled || adding} aria-label={`Удалить файл ${file.name}`} onClick={() => emit({ ...current.current, files: current.current.files.filter((_, i) => i !== index) })}>×</button></span>)}</div>}
    <div className="single-editor-toolbar"><div>
      <button type="button" className="editor-attach" disabled={disabled || adding} onClick={() => {
        if (editor) savedSelection.current = { from: editor.state.selection.from, to: editor.state.selection.to };
        fileInput.current?.click();
      }}><ClipIcon />Прикрепить</button>
      <input ref={fileInput} aria-label={`${label}: добавить файлы`} type="file" multiple hidden disabled={disabled || adding} onChange={(e) => {
        const files = Array.from(e.target.files ?? []); e.target.value = ""; void insert(files);
      }} />
      <span className="editor-toolbar-divider" />
      <button type="button" className="editor-history" aria-label={`Отменить: ${label}`} title="Отменить" disabled={disabled || adding || !editor?.can().undo()} onClick={() => editor?.chain().focus().undo().run()}>↶</button>
      <button type="button" className="editor-history" aria-label={`Повторить: ${label}`} title="Повторить" disabled={disabled || adding || !editor?.can().redo()} onClick={() => editor?.chain().focus().redo().run()}>↷</button>
    </div><span className="editor-paste-hint">{adding ? "Добавление файла…" : "Скриншот можно вставить из буфера"}</span></div>
    {error && <p role="alert" className="rich-editor-error">{error}</p>}
  </div>;
}
