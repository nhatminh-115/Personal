import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_XLSX_BYTES = 10 * 1024 * 1024;
const MAX_SHEETS = 10;
const MAX_ROWS_PER_SHEET = 250;
const MAX_COLUMNS_PER_ROW = 40;

function cellText(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'object') {
    const record = value as { text?: unknown; result?: unknown; richText?: Array<{ text?: unknown }> };
    if (Array.isArray(record.richText)) return record.richText.map((part) => String(part.text ?? '')).join('');
    if (typeof record.text === 'string') return record.text;
    if (typeof record.result === 'string' || typeof record.result === 'number' || typeof record.result === 'boolean') return String(record.result);
  }
  return '';
}

export async function extractXlsxText(blob: Blob): Promise<string> {
  if (blob.size === 0) throw new Error('The selected spreadsheet is empty.');
  if (blob.size > MAX_LOCAL_XLSX_BYTES) {
    throw new Error('The selected spreadsheet exceeds the 10 MB browser parsing limit.');
  }

  try {
    const ExcelJS = await import('exceljs');
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(await blob.arrayBuffer());
    const output: string[] = [];
    let remaining = MAX_CONTEXT_FILE_CHARS;
    let visibleSheets = 0;

    for (const worksheet of workbook.worksheets) {
      if (worksheet.state !== 'visible') continue;
      visibleSheets += 1;
      if (visibleSheets > MAX_SHEETS) {
        output.push('[Additional visible worksheets omitted]');
        break;
      }
      output.push(`[Sheet: ${worksheet.name}]`);
      let rows = 0;
      worksheet.eachRow({ includeEmpty: false }, (row) => {
        if (rows >= MAX_ROWS_PER_SHEET || remaining <= 0) return;
        rows += 1;
        const cells: string[] = [];
        row.eachCell({ includeEmpty: true }, (cell, columnNumber) => {
          if (columnNumber > MAX_COLUMNS_PER_ROW) return;
          cells[columnNumber - 1] = cellText(cell.value);
        });
        const line = cells.join('\t').replace(/[\t ]+$/u, '');
        if (line) {
          const bounded = Array.from(line).slice(0, remaining).join('');
          output.push(bounded);
          remaining -= Array.from(bounded).length + 1;
        }
      });
      if (rows >= MAX_ROWS_PER_SHEET && worksheet.rowCount > MAX_ROWS_PER_SHEET) {
        output.push('[Additional rows omitted]');
      }
    }

    const text = output.join('\n').trim();
    if (!text) throw new Error('This spreadsheet has no extractable text in visible worksheets.');
    if (Array.from(text).length > MAX_CONTEXT_FILE_CHARS) {
      return Array.from(text).slice(0, MAX_CONTEXT_FILE_CHARS).join('');
    }
    return text;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('This spreadsheet')) throw error;
    if (error instanceof Error && error.message.startsWith('The selected spreadsheet')) throw error;
    throw new Error('AURA could not extract text from this spreadsheet in the browser.');
  }
}
