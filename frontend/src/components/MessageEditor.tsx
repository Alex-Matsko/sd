import { lazy, Suspense } from "react";
import type { MessageDraft } from "../lib/messageDraft";
const Editor = lazy(() => import("./RichMessageEditor").then((module) => ({ default: module.RichMessageEditor })));
export function MessageEditor(props: { value: MessageDraft; onChange: (draft: MessageDraft) => void; label: string; disabled?: boolean }) {
  return <Suspense fallback={<div className="message-editor-loading" role="status">Загрузка редактора…</div>}><Editor {...props} /></Suspense>;
}
