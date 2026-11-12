export type AttachmentPreviewData = { kind: "text"; text: string; truncated: boolean } | {
  kind: "spreadsheet"; columns: string[]; rows: string[][]; sheets: string[]; sheet: number;
  row_limit: number; column_limit: number; truncated: boolean;
};
export function documentPreviewKind(filename: string): "pdf" | "document" | "unsupported" {
  if (/\.pdf$/i.test(filename)) return "pdf";
  return /\.(xlsx|xlsm|csv|docx|txt|log|json|xml|md)$/i.test(filename) ? "document" : "unsupported";
}
