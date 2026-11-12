import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiDownload, apiFileBlob, apiRequest } from "../api/client";
import { downloadPortalFile, portalFileBlob, portalAttachmentPreview } from "../portal/api";
import { documentPreviewKind } from "../lib/attachmentPreview";
import type { AttachmentPreviewData } from "../lib/attachmentPreview";

const PdfPreview = lazy(() => import("./PdfPreview"));
type FileInfo = { id: number; filename: string; size_bytes?: number };
export function AttachmentPreview({ ticketId, attachment, portal = false }: { ticketId: number; attachment: FileInfo; portal?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const card = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [open, setOpen] = useState(false);
  const [sheet, setSheet] = useState(0);
  const [downloadError, setDownloadError] = useState("");
  const kind = documentPreviewKind(attachment.filename);
  const path = `/tickets/${ticketId}/attachments/${attachment.id}`;
  const preview = useQuery({ queryKey: ["attachment-preview", portal, ticketId, attachment.id, sheet],
    queryFn: () => portal ? portalAttachmentPreview(path, sheet) : apiRequest<AttachmentPreviewData>(`${path}/preview`, { query: { sheet } }),
    enabled: kind === "document" && (visible || open), staleTime: 300_000, retry: false });
  const pdf = useQuery({ queryKey: ["attachment-pdf", portal, ticketId, attachment.id],
    queryFn: async () => {
      const blob = await (portal ? portalFileBlob(path) : apiFileBlob(path));
      const header = await blob.slice(0, 5).text();
      if (header !== "%PDF-") throw new Error("Этот файл не является PDF-документом");
      return blob;
    }, enabled: open && kind === "pdf", staleTime: 300_000, retry: false });
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } }, { rootMargin: "100px" });
    if (card.current) observer.observe(card.current);
    return () => observer.disconnect();
  }, []);
  function show() { setOpen(true); dialog.current?.showModal(); }
  function close() { dialog.current?.close(); setOpen(false); }
  async function download() {
    setDownloadError("");
    try { await (portal ? downloadPortalFile(path, attachment.filename) : apiDownload(path, attachment.filename)); }
    catch { setDownloadError("Не удалось скачать оригинал"); }
  }
  const data = preview.data;
  const sample = data?.kind === "spreadsheet" ? data.rows.filter((row) => row.some(Boolean)).slice(0, 3) : [];
  const extension = attachment.filename.split(".").pop()?.slice(0, 8).toUpperCase() ?? "ФАЙЛ";
  return <>
    <article className="attachment-document" ref={card}>
      <button type="button" className="attachment-document-cover" aria-label={`Предпросмотр ${attachment.filename}`} onClick={show}>
        <span className="attachment-file-type">{extension}</span>
        {sample.length > 0 ? <table className="attachment-document-sample" aria-hidden="true"><tbody>{sample.map((row, i) => <tr key={i}>{row.slice(0, 4).map((value, j) => <td key={j}>{value || " "}</td>)}</tr>)}</tbody></table>
          : data?.kind === "text" ? <pre className="attachment-document-sample" aria-hidden="true">{data.text.slice(0, 180)}</pre> : <span className="attachment-document-symbol" aria-hidden="true">▤</span>}
        <span className="attachment-document-open">Просмотреть ↗</span>
      </button>
      <div className="attachment-document-caption"><strong>{attachment.filename}</strong>{attachment.size_bytes !== undefined && <span>{Math.max(1, Math.round(attachment.size_bytes / 1024))} КБ</span>}<div><button type="button" className="btn-link" onClick={show}>Просмотреть</button><button type="button" className="btn-link" onClick={download}>Скачать оригинал</button></div>{downloadError && <p role="alert">{downloadError}</p>}</div>
    </article>
    <dialog ref={dialog} className="attachment-preview-dialog" aria-label={`Просмотр ${attachment.filename}`} onClose={() => setOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
      <header><strong>{attachment.filename}</strong><div><button type="button" className="btn btn-ghost" onClick={download}>Скачать оригинал</button><button type="button" className="icon-btn" aria-label="Закрыть просмотр" onClick={close}>×</button></div></header>
      {downloadError && <p role="alert">{downloadError}</p>}
      {open && <div className="attachment-preview-content">
        {kind === "unsupported" && <p className="attachment-preview-notice">Предпросмотр этого формата пока недоступен. Вы можете скачать оригинал.</p>}
        {kind === "document" && <>{preview.isPending && <p role="status">Загрузка документа…</p>}{preview.isError && <p role="alert">{preview.error.message}</p>}
          {data?.kind === "text" && <pre className="attachment-text-preview">{data.text}</pre>}
          {data?.kind === "spreadsheet" && <>{data.sheets.length > 0 && <div className="attachment-sheet-tabs" role="group" aria-label="Листы документа">{data.sheets.map((name, index) => <button type="button" key={index} aria-pressed={sheet === index} onClick={() => setSheet(index)}>{name}</button>)}</div>}
            <div className="attachment-sheet-scroll" tabIndex={0} aria-label="Содержимое таблицы">{data.columns.length > 0 ? <table className="attachment-sheet"><thead><tr><th aria-label="Строка" />{data.columns.map((name) => <th scope="col" key={name}>{name}</th>)}</tr></thead><tbody>{data.rows.map((row, index) => <tr key={index}><th scope="row">{index + 1}</th>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></table> : <p>Лист пуст</p>}</div>
          </>}
          {data && <p className="attachment-preview-notice">{data.kind === "spreadsheet" ? `Предпросмотр значений таблицы${data.truncated ? ` · первые ${data.row_limit} строк и ${data.column_limit} столбцов` : ""}. Форматирование и формулы доступны в оригинале.` : data.truncated ? "Показано начало документа. Полный текст доступен в оригинале." : "Текст документа · оригинал доступен для скачивания"}</p>}
        </>}
        {kind === "pdf" && <>{pdf.isPending && <p role="status">Загрузка PDF…</p>}{pdf.isError && <p role="alert">{pdf.error.message}</p>}{pdf.data && <Suspense fallback={<p role="status">Открытие PDF…</p>}><PdfPreview blob={pdf.data} /></Suspense>}</>}
      </div>}
      <footer>Esc — закрыть просмотр</footer>
    </dialog>
  </>;
}
