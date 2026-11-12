import { AttachmentPreview } from "./AttachmentPreview";
import { ImagePreview } from "./ImagePreview";
import { isImageAttachment, rasterImageBlob } from "../lib/imagePreview";
import { useEffect, useState } from "react";
import { apiFileBlob, apiDownload } from "../api/client";
import { portalFileBlob, downloadPortalFile } from "../portal/api";
import type { MessageBlock } from "../api/types";

type FileInfo = { id: number; filename: string; mime_type?: string | null; size_bytes?: number };
function InlineImage({ ticketId, attachment, portal, compact = false }: { ticketId: number; attachment: FileInfo; portal: boolean; compact?: boolean }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    const path = `/tickets/${ticketId}/attachments/${attachment.id}`;
    const load = portal ? portalFileBlob(path) : apiFileBlob(path);
    load.then(rasterImageBlob).then((blob) => {
      if (!active) return;
      if (!blob) { setError("Этот файл не является поддерживаемым изображением"); return; }
      objectUrl = URL.createObjectURL(blob);
      setUrl(objectUrl);
    }).catch(() => { if (active) setError("Скриншот недоступен"); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [ticketId, attachment.id, portal]);
  return <ImagePreview url={url} filename={attachment.filename} error={error} compact={compact} onDownload={() => {
    const path = `/tickets/${ticketId}/attachments/${attachment.id}`;
    (portal ? downloadPortalFile(path, attachment.filename) : apiDownload(path, attachment.filename)).catch(() => setError("Не удалось скачать оригинал"));
  }} />;

}
export function MessageContent({ ticketId, body, blocks, attachments, portal = false }: {
  ticketId: number; body: string; blocks?: MessageBlock[] | null; attachments: FileInfo[]; portal?: boolean;
}) {
  const inline = new Set((blocks ?? []).flatMap((b) => b.type === "image" ? [b.attachment_id] : []));
  const remaining = attachments.filter((a) => !inline.has(a.id));
  return <div className="rich-message-content">
    {blocks == null ? <div className="message-body">{body}</div> : blocks.map((block, i) => {
      if (block.type === "text") return block.text ? <div className="message-body" key={i}>{block.text}</div> : null;
      const attachment = attachments.find((a) => a.id === block.attachment_id);
      return attachment ? <InlineImage key={i} ticketId={ticketId} attachment={attachment} portal={portal} /> : <p key={i}>Скриншот недоступен</p>;
    })}
    <div className="message-image-previews">{remaining.filter(isImageAttachment).map((a) => <InlineImage key={a.id} ticketId={ticketId} attachment={a} portal={portal} compact />)}</div>
    <div className="message-attachments">{remaining.filter((a) => !isImageAttachment(a)).map((a) => <AttachmentPreview key={a.id} ticketId={ticketId} attachment={a} portal={portal} />)}</div>
  </div>;
}
