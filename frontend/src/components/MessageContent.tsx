import { useEffect, useState } from "react";
import { apiFileBlob, apiDownload } from "../api/client";
import { portalFileBlob, downloadPortalFile } from "../portal/api";
import type { MessageBlock } from "../api/types";

type FileInfo = { id: number; filename: string; mime_type?: string | null };
function InlineImage({ ticketId, attachment, portal }: { ticketId: number; attachment: FileInfo; portal: boolean }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    const path = `/tickets/${ticketId}/attachments/${attachment.id}`;
    const load = portal ? portalFileBlob(path) : apiFileBlob(path);
    load.then((blob) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    }).catch(() => { if (active) setError("Скриншот недоступен"); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [ticketId, attachment.id, portal]);
  return <figure className="message-inline-image">
    {url ? <a href={url} target="_blank" rel="noreferrer" title="Открыть оригинал в полном размере"><img src={url} alt={attachment.filename} loading="lazy" /></a> : <span role={error ? "alert" : "status"}>{error || "Загрузка скриншота…"}</span>}
    <figcaption>{attachment.filename}{url && <> · <a href={url} target="_blank" rel="noreferrer">Открыть оригинал</a></>}</figcaption>
  </figure>;
}
export function MessageContent({ ticketId, body, blocks, attachments, portal = false }: {
  ticketId: number; body: string; blocks?: MessageBlock[] | null; attachments: FileInfo[]; portal?: boolean;
}) {
  const [downloadError, setDownloadError] = useState("");
  const inline = new Set((blocks ?? []).flatMap((b) => b.type === "image" ? [b.attachment_id] : []));
  return <div className="rich-message-content">
    {blocks == null ? <div className="message-body">{body}</div> : blocks.map((block, i) => {
      if (block.type === "text") return block.text ? <div className="message-body" key={i}>{block.text}</div> : null;
      const attachment = attachments.find((a) => a.id === block.attachment_id);
      return attachment ? <InlineImage key={i} ticketId={ticketId} attachment={attachment} portal={portal} /> : <p key={i}>Скриншот недоступен</p>;
    })}
    <div className="message-attachments">{attachments.filter((a) => !inline.has(a.id)).map((a) => <button key={a.id} type="button" className="attachment-chip" onClick={() => {
      const path = `/tickets/${ticketId}/attachments/${a.id}`;
      (portal ? downloadPortalFile(path, a.filename) : apiDownload(path, a.filename)).catch(() => setDownloadError("Не удалось скачать файл"));
    }}>{a.filename}</button>)}</div>
    {downloadError && <p className="rich-editor-error" role="alert">{downloadError}</p>}
  </div>;
}
