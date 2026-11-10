import { useRef, useState } from "react";

export function ImagePreview({ url, filename, error = "", compact = false, onDownload }: {
  url: string; filename: string; error?: string; compact?: boolean; onDownload?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [failedUrl, setFailedUrl] = useState("");
  const failed = Boolean(error) || (Boolean(url) && failedUrl === url);
  return <>
    <figure className={`image-preview ${compact ? "image-preview-compact" : ""}`}>
      {url && !failed ? <button type="button" className="image-preview-open" aria-label={`Открыть превью ${filename}`} onClick={() => dialog.current?.showModal()}>
        <img src={url} alt={filename} loading="lazy" onError={() => setFailedUrl(url)} />
        <span className="image-preview-expand" aria-hidden="true">Увеличить ↗</span>
      </button> : <div className="image-preview-placeholder" role={failed ? "alert" : "status"}>{failed ? error || "Не удалось показать превью" : "Загрузка превью…"}</div>}
      <figcaption><span>{filename}</span>{url && !failed && <button type="button" className="btn-link" onClick={() => dialog.current?.showModal()}>Просмотреть</button>}
        {onDownload ? <button type="button" className="btn-link" onClick={onDownload}>Скачать оригинал</button> : url && <a href={url} download={filename}>Скачать оригинал</a>}</figcaption>
    </figure>
    <dialog ref={dialog} className="image-preview-dialog" aria-label={`Просмотр ${filename}`} onClick={(e) => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
      <div className="image-preview-viewer"><header><span>{filename}</span><div>
        <a href={url || undefined} target="_blank" rel="noreferrer">Открыть оригинал</a>
        <a href={url || undefined} download={filename}>Скачать</a>
        <button type="button" aria-label="Закрыть просмотр" onClick={() => dialog.current?.close()}>×</button>
      </div></header>
      {url && <img src={url} alt={filename} />}
      <footer>Оригинальное изображение · Esc — закрыть</footer></div>
    </dialog>
  </>;
}
