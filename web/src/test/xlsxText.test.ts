import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as ExcelJS from 'exceljs';
import { extractXlsxText, MAX_LOCAL_XLSX_BYTES } from '../lib/xlsxText';
import { MAX_CONTEXT_FILE_CHARS } from '../lib/pdfText';

vi.mock('exceljs', () => ({ Workbook: vi.fn() }));

function worksheet(name: string, state: string, data: Array<Array<unknown>>) {
  return {
    name,
    state,
    eachRow: (_options: unknown, callback: (row: unknown) => void) => data.forEach((values) => callback({
      eachCell: (_cellOptions: unknown, visit: (cell: { value: unknown }, column: number) => void) =>
        values.forEach((value, index) => visit({ value }, index + 1)),
    })),
  };
}

describe('browser-local spreadsheet text extraction', () => {
  const load = vi.fn();
  const workbook = { xlsx: { load }, worksheets: [] as ReturnType<typeof worksheet>[] };

  beforeEach(() => {
    vi.clearAllMocks();
    workbook.worksheets = [];
    if (!Blob.prototype.arrayBuffer) {
      Object.defineProperty(Blob.prototype, 'arrayBuffer', {
        configurable: true,
        value: async () => new ArrayBuffer(8),
      });
    }
    vi.mocked(ExcelJS.Workbook).mockImplementation(() => workbook as unknown as ExcelJS.Workbook);
  });

  it('extracts visible sheet cells as bounded tabular text and does not evaluate formulas', async () => {
    workbook.worksheets = [
      worksheet('Summary', 'visible', [['Quarter', 'Revenue'], ['Q1', 125], ['Computed', { formula: '1+1', result: 2 }]]),
      worksheet('Hidden', 'hidden', [['private hidden sheet']]),
    ];

    await expect(extractXlsxText(new Blob(['xlsx fixture']))).resolves.toBe(
      '[Sheet: Summary]\nQuarter\tRevenue\nQ1\t125\nComputed\t2',
    );
    expect(load).toHaveBeenCalledWith(expect.any(ArrayBuffer));
  });

  it('rejects empty and oversized workbooks before loading them', async () => {
    await expect(extractXlsxText(new Blob([]))).rejects.toThrow('spreadsheet is empty');
    await expect(extractXlsxText(new Blob([new Uint8Array(MAX_LOCAL_XLSX_BYTES + 1)]))).rejects.toThrow('10 MB browser parsing limit');
    expect(load).not.toHaveBeenCalled();
  });

  it('caps extracted text and hides malformed workbook details', async () => {
    workbook.worksheets = [worksheet('Large', 'visible', [[`a${'b'.repeat(MAX_CONTEXT_FILE_CHARS + 5)}`]])];
    const text = await extractXlsxText(new Blob(['xlsx fixture']));
    expect(Array.from(text)).toHaveLength(MAX_CONTEXT_FILE_CHARS);

    load.mockRejectedValueOnce(new Error('private ZIP parser detail'));
    await expect(extractXlsxText(new Blob(['not xlsx']))).rejects.toThrow('AURA could not extract text from this spreadsheet in the browser.');
  });

  it('bounds the number of visible sheets and rows included', async () => {
    workbook.worksheets = Array.from({ length: 11 }, (_, index) => worksheet(
      `Sheet ${index + 1}`,
      'visible',
      index === 0 ? Array.from({ length: 251 }, (_, row) => [`row ${row + 1}`]) : [[`sheet ${index + 1}`]],
    ));
    Object.defineProperty(workbook.worksheets[0], 'rowCount', { value: 251 });

    const text = await extractXlsxText(new Blob(['xlsx fixture']));
    expect(text).toContain('[Additional rows omitted]');
    expect(text).toContain('[Additional visible worksheets omitted]');
    expect(text).not.toContain('[Sheet: Sheet 11]');
  });
});
