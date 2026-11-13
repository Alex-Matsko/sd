import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createMessage, getCustomerReplyOptions } from "../api/endpoints";
import type { Message, ResponseTemplate } from "../api/types";
import { useDraftRequestId } from "../lib/useDraftRequestId";
import { MessageEditor as RichMessageEditor } from "./MessageEditor";
import { emptyMessageDraft, messageDraftPayload, draftIdentity } from "../lib/messageDraft";

export function MessageComposer({ ticketId, direction, replyTo, clearReply, templates, recipient, channel }: {
  ticketId: number; direction: "outbound" | "internal_note"; replyTo: Message | null; clearReply: () => void;
  templates: ResponseTemplate[]; recipient: string; channel: string;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(emptyMessageDraft);
  const internal = direction === "internal_note";
  const [chosenChannel, setChosenChannel] = useState<string | null>(null);
  const routes = useQuery({ queryKey: ["ticket", ticketId, "reply-options"], queryFn: () => getCustomerReplyOptions(ticketId), enabled: !internal });
  const destination = chosenChannel ?? routes.data?.default_channel ?? "";
  const option = routes.data?.options.find(item => item.channel === destination);
  const canSend = internal || Boolean(option?.available);
  const channelNames: Record<string, string> = { max: "MAX", telegram: "Telegram", email: "Email", portal: "Личный кабинет" };
  const label = internal ? "Внутренний комментарий" : "Ответ клиенту";
  const requestId = useDraftRequestId(JSON.stringify([ticketId, direction, destination, replyTo?.id, draftIdentity(draft)]));
  const mutation = useMutation({ mutationFn: () => {
    const { files, ...payload } = messageDraftPayload(draft);
    return createMessage(ticketId, { ...payload, direction, ...(internal ? {} : { channel: destination }), reply_to_message_id: replyTo?.id ?? null, request_id: requestId }, files);
  }, onSuccess: () => {
    setDraft(emptyMessageDraft()); clearReply();
    qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
  } });
  const payload = messageDraftPayload(draft);
  return <section id={`compose-${direction}`} className={`message-composer ${internal ? "composer-internal" : "composer-customer"}`} aria-label={label}>
    <header className="composer-heading"><div className="composer-heading-title">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">{internal ? <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></> : <><path d="m21 3-7 18-4-7-7-4 18-7Z"/><path d="m10 14 6-6"/></>}</svg>
      <h3>{label}</h3></div><span className="composer-recipient">{internal ? "Только для сотрудников" : `${recipient} · источник: ${channel}`}</span></header>
    {!internal && <div className="composer-delivery-route">
      <label>Куда отправить<select aria-label="Канал ответа клиенту" value={destination} disabled={mutation.isPending || routes.isPending} onChange={event => setChosenChannel(event.target.value)}>
        <option value="">Выберите канал…</option>{routes.data?.options.map(item => <option key={item.channel} value={item.channel} disabled={!item.available}>{channelNames[item.channel] ?? item.channel}{item.available ? "" : " — недоступен"}</option>)}
      </select></label>
      {option && <p>{destination === "portal" ? option.reason : `Получатель: ${option.destination ?? recipient} · ${channelNames[destination]}`}</p>}
      {!destination && routes.isSuccess && <p>Выберите канал для этого контакта. Внутренний комментарий клиенту не отправляется.</p>}
      {routes.isError && <p role="alert">Не удалось получить каналы ответа: {routes.error.message}</p>}
      {routes.data && <details><summary>Доступность каналов</summary>{routes.data.options.filter(item => !item.available).map(item => <p key={item.channel}>{channelNames[item.channel]}: {item.reason}</p>)}</details>}
    </div>}
    {replyTo && <div className="message-quote message-quote-active">Ответ на сообщение: {replyTo.body.slice(0, 140) || "Скриншот / вложение"}
      <button type="button" aria-label={`Убрать цитату: ${label}`} onClick={clearReply}>×</button></div>}
    <RichMessageEditor value={draft} onChange={setDraft} disabled={mutation.isPending} label={label} />
    {mutation.isError && <p className="rich-editor-error" role="alert">{mutation.error.message}</p>}
    <footer>
    {!internal && templates.length > 0 && <select aria-label="Шаблон ответа клиенту" value="" disabled={mutation.isPending} onChange={(e) => {
      const text = templates.find((t) => t.id === Number(e.target.value))?.body;
      if (text) setDraft((d) => ({ ...d, blocks: [...d.blocks, { id: `template-${Date.now()}`, type: "text", text }] }));
    }}><option value="">Вставить шаблон ответа…</option>{templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>}
      <span className="spacer" />
      <button type="button" className={`btn ${internal ? "btn-ghost" : "btn-primary"}`} disabled={!canSend || mutation.isPending || draft.pending || (!payload.body.trim() && payload.files.length === 0)} onClick={() => mutation.mutate()}>
        {mutation.isPending ? "Сохранение…" : internal ? "Добавить комментарий" : destination === "portal" ? "Сохранить в кабинете" : `Отправить в ${channelNames[destination] ?? "выбранный канал"}`}</button></footer>
  </section>;
}
