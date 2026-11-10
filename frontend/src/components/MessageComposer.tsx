import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createMessage } from "../api/endpoints";
import type { Message, ResponseTemplate } from "../api/types";
import { useDraftRequestId } from "../lib/useDraftRequestId";
import { RichMessageEditor, emptyMessageDraft, messageDraftPayload, draftIdentity } from "./RichMessageEditor";

export function MessageComposer({ ticketId, direction, replyTo, clearReply, templates, recipient, channel }: {
  ticketId: number; direction: "outbound" | "internal_note"; replyTo: Message | null; clearReply: () => void;
  templates: ResponseTemplate[]; recipient: string; channel: string;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(emptyMessageDraft);
  const internal = direction === "internal_note";
  const label = internal ? "Внутренний комментарий" : "Ответ клиенту";
  const requestId = useDraftRequestId(JSON.stringify([ticketId, direction, replyTo?.id, draftIdentity(draft)]));
  const mutation = useMutation({ mutationFn: () => {
    const { files, ...payload } = messageDraftPayload(draft);
    return createMessage(ticketId, { ...payload, direction, reply_to_message_id: replyTo?.id ?? null, request_id: requestId }, files);
  }, onSuccess: () => {
    setDraft(emptyMessageDraft()); clearReply();
    qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
  } });
  const payload = messageDraftPayload(draft);
  return <section id={`compose-${direction}`} className={`message-composer ${internal ? "composer-internal" : "composer-customer"}`} aria-label={label}>
    <header><div><h3>{internal ? "🔒 " : "↗ "}{label}</h3><p>{internal ? "Только для сотрудников. Клиент не увидит текст и вложения." : `${recipient} · ${channel}`}</p></div>
      <span className="composer-audience">{internal ? "Внутри команды" : "Клиенту"}</span></header>
    {replyTo && <div className="message-quote message-quote-active">Ответ на сообщение: {replyTo.body.slice(0, 140) || "Скриншот / вложение"}
      <button type="button" aria-label={`Убрать цитату: ${label}`} onClick={clearReply}>×</button></div>}
    {!internal && templates.length > 0 && <select aria-label="Шаблон ответа клиенту" value="" disabled={mutation.isPending} onChange={(e) => {
      const text = templates.find((t) => t.id === Number(e.target.value))?.body;
      if (text) setDraft((d) => ({ ...d, blocks: [...d.blocks, { id: `template-${Date.now()}`, type: "text", text }] }));
    }}><option value="">Вставить шаблон ответа…</option>{templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>}
    <RichMessageEditor value={draft} onChange={setDraft} disabled={mutation.isPending} label={label} />
    {mutation.isError && <p className="rich-editor-error" role="alert">{mutation.error.message}</p>}
    <footer><span>{internal ? "Комментарий останется в истории заявки" : "Отправка только по нажатию кнопки"}</span>
      <button type="button" className={`btn ${internal ? "btn-ghost" : "btn-primary"}`} disabled={mutation.isPending || (!payload.body.trim() && payload.files.length === 0)} onClick={() => mutation.mutate()}>
        {mutation.isPending ? "Сохранение…" : internal ? "Добавить внутренний комментарий" : "Отправить клиенту"}</button></footer>
  </section>;
}
