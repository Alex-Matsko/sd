export function isImageAttachment(file: { filename: string; mime_type?: string | null }): boolean {
  const mime = file.mime_type?.toLowerCase().split(";")[0].trim() ?? "";
  if (mime === "image/svg+xml") return false;
  return /^image\/(png|jpeg|gif|webp|bmp|avif)$/.test(mime) || /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.filename);
}

/** Normalize only the MIME header; never resize or re-encode the original bytes.
 * A filename or a supplied Content-Type must not turn HTML/SVG into a trusted blob page.
 */
export async function rasterImageBlob(blob: Blob): Promise<Blob | null> {
  const bytes = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
  const starts = (...prefix: number[]) => prefix.every((b, i) => bytes[i] === b);
  const text = (start: number, end: number) => String.fromCharCode(...bytes.slice(start, end));
  let type = "";
  if (starts(137, 80, 78, 71, 13, 10, 26, 10)) type = "image/png";
  else if (starts(255, 216, 255)) type = "image/jpeg";
  else if (["GIF87a", "GIF89a"].includes(text(0, 6))) type = "image/gif";
  else if (text(0, 4) === "RIFF" && text(8, 12) === "WEBP") type = "image/webp";
  else if (text(0, 2) === "BM") type = "image/bmp";
  else if (text(4, 8) === "ftyp" && ["avif", "avis"].includes(text(8, 12))) type = "image/avif";
  return type ? blob.slice(0, blob.size, type) : null;
}
