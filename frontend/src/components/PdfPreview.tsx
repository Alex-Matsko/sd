import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

export default function PdfPreview({ blob }: { blob: Blob }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const canvas = useRef<HTMLCanvasElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    let active = true;
    let task: ReturnType<typeof getDocument> | undefined;
    blob.arrayBuffer().then((data) => {
      if (!active) return;
      task = getDocument({ data: new Uint8Array(data), enableXfa: false, useWasm: false });
      return task.promise.then((pdf) => { if (active) setDocument(pdf); });
    }).catch(() => { if (active) { setError("Не удалось открыть PDF. Возможно, файл повреждён или защищён паролем."); setBusy(false); } });
    return () => { active = false; void task?.destroy(); };
  }, [blob]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!document) return;
    let active = true;
    let render: ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | undefined;
    document.getPage(page).then((pdfPage) => {
      if (!active || !canvas.current) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(Math.max(width - 32, 200) / base.width, 1500 / base.width, 2400 / base.height);
      const viewport = pdfPage.getViewport({ scale });
      canvas.current.width = Math.ceil(viewport.width);
      canvas.current.height = Math.ceil(viewport.height);
      render = pdfPage.render({ canvas: canvas.current, viewport });
      return render.promise;
    }).then(() => { if (active) setBusy(false); }).catch((err: Error) => {
      if (active && err.name !== "RenderingCancelledException") { setError("Не удалось показать страницу PDF"); setBusy(false); }
    });
    return () => { active = false; render?.cancel(); };
  }, [document, page, width]);
  function choosePage(next: number) { setBusy(true); setError(""); setPage(next); }
  return <div className="pdf-preview" ref={container}>
    {document && <div className="pdf-preview-navigation"><button type="button" className="btn btn-ghost" disabled={page <= 1} onClick={() => choosePage(page - 1)}>← Назад</button><span>Страница {page} из {document.numPages}</span><button type="button" className="btn btn-ghost" disabled={page >= document.numPages} onClick={() => choosePage(page + 1)}>Вперёд →</button></div>}
    {busy && <p role="status">Загрузка PDF…</p>}{error && <p role="alert">{error}</p>}
    <canvas ref={canvas} role="img" aria-label={`Страница ${page} PDF`} hidden={Boolean(error)} />
  </div>;
}
