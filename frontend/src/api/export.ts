import { http } from './http';

/**
 * Export API: request an Excel (.xlsx) or PDF report for a well's curves and
 * trigger a browser download (brief §7.9).
 *
 *   downloadXlsx(body) -> POST /api/export/xlsx  (binary blob)
 *   downloadPdf(body)  -> POST /api/export/pdf   (binary blob)
 *
 * The server streams a file; we read it as a blob and synthesize an anchor
 * click so the browser saves it. Nothing runs at module-evaluation time.
 */

/** Index axis the export should be ordered/labelled by. */
export type ExportIndexType = 'time' | 'depth';

/** Output document format. */
export type ExportFormat = 'xlsx' | 'pdf';

/** Request body shared by both export endpoints. */
export interface ExportRequest {
  wellUid: string;
  /** Mnemonics to include (order preserved). */
  mnemonics: string[];
  /** Whether the export is keyed by time or depth. */
  indexType: ExportIndexType;
  /** Optional cap on the number of samples per mnemonic. */
  limit?: number;
}

/** Default filename stem when the server does not supply one. */
function fallbackName(body: ExportRequest, ext: ExportFormat): string {
  const safe = body.wellUid.replace(/[^A-Za-z0-9_-]+/g, '_') || 'export';
  return `witsml_${safe}_${body.indexType}.${ext}`;
}

/**
 * Parse a Content-Disposition header into a filename, if present.
 * Handles both `filename="x"` and RFC 5987 `filename*=UTF-8''x`.
 */
function filenameFromDisposition(disposition: string | undefined): string | null {
  if (!disposition) return null;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(disposition);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1]?.trim() ?? null;
}

/** Save a blob to disk by synthesizing an anchor click. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the download has a chance to start.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function downloadExport(
  format: ExportFormat,
  body: ExportRequest,
): Promise<void> {
  const response = await http.post<Blob>(`/export/${format}`, body, {
    responseType: 'blob',
  });
  const disposition = response.headers['content-disposition'] as
    | string
    | undefined;
  const filename =
    filenameFromDisposition(disposition) ?? fallbackName(body, format);
  saveBlob(response.data, filename);
}

/** POST /api/export/xlsx and download the resulting workbook. */
export function downloadXlsx(body: ExportRequest): Promise<void> {
  return downloadExport('xlsx', body);
}

/** POST /api/export/pdf and download the resulting document. */
export function downloadPdf(body: ExportRequest): Promise<void> {
  return downloadExport('pdf', body);
}
