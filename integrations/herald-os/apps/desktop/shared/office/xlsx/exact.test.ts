import ExcelJS from 'exceljs'
import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import type { CellSnapshot, WorkbookSnapshot } from '../workbook.ts'
import { workbookFromXlsx } from './read.ts'
import { xlsxFromWorkbook } from './write.ts'

/** A one-sheet workbook with these cells, each with its value and number format. */
async function bookWith(cells: [address: string, value: ExcelJS.CellValue, numFmt?: string][], options: { date1904?: boolean } = {}): Promise<Uint8Array> {
  const book = new ExcelJS.Workbook()
  book.properties.date1904 = Boolean(options.date1904)
  const sheet = book.addWorksheet('Sheet')

  for (const [address, value, numFmt] of cells) {
    const cell = sheet.getCell(address)
    cell.value = value

    if (numFmt) {
      cell.numFmt = numFmt
    }
  }

  return new Uint8Array(await book.xlsx.writeBuffer())
}

async function roundTrip(bytes: Uint8Array) {
  const first = await workbookFromXlsx(bytes, { id: 'book', name: 'Book' })
  const written = await xlsxFromWorkbook(first.workbook)
  const second = await workbookFromXlsx(written.bytes, { id: 'book', name: 'Book' })

  return { first, written, second }
}

const partOf = async (bytes: Uint8Array, path: string) => (await JSZip.loadAsync(bytes)).file(path)?.async('string') ?? ''
const cellsOf = (workbook: WorkbookSnapshot) => workbook.sheets[workbook.sheetOrder[0]].cellData
const columnA = (workbook: WorkbookSnapshot, rows: number) => Array.from({ length: rows }, (_, row) => cellsOf(workbook)[row]?.[0]?.v)

function patternOf(workbook: WorkbookSnapshot, cell: CellSnapshot): string | undefined {
  const style = typeof cell.s === 'string' ? workbook.styles[cell.s] : cell.s

  return (style as { n?: { pattern?: string } } | null | undefined)?.n?.pattern
}

describe('what an open and save keeps exactly', () => {
  it('keeps times and date-times to the last digit, in both date systems', async () => {
    const times = [1 / 3, 555 / 1440, 1 / 86400, 45000.333333333336, 1000.25]
    const formats = ['h:mm', 'h:mm', 'h:mm:ss', 'm/d/yy h:mm', 'mm-dd-yy']
    const { first, second } = await roundTrip(await bookWith(times.map((time, row) => [`A${row + 1}`, time, formats[row]])))
    const mac = await roundTrip(await bookWith([['A1', 1 / 3, 'h:mm'], ['A2', 1000.25, 'mm-dd-yy']], { date1904: true }))

    expect(columnA(first.workbook, times.length)).toEqual(times)
    expect(columnA(second.workbook, times.length)).toEqual(times)
    expect(columnA(mac.second.workbook, 2)).toEqual([1 / 3, 1000.25])
  })

  it('saves the built-in date formats under their ids, which Excel shows in the reader’s own date order', async () => {
    const { first, written } = await roundTrip(await bookWith([['A1', 45000, 'mm-dd-yy'], ['A2', 45000.385416666664, 'm/d/yy "h":mm']]))
    const cells = cellsOf(first.workbook)
    const styles = await partOf(written.bytes, 'xl/styles.xml')
    const used = [...styles.replace(/[\s\S]*<cellXfs[^>]*>/, '').replace(/<\/cellXfs>[\s\S]*/, '').matchAll(/numFmtId="(\d+)"/g)].map((match) => match[1])

    expect([patternOf(first.workbook, cells[0][0]), patternOf(first.workbook, cells[1][0])]).toEqual(['m/d/yyyy', 'm/d/yyyy h:mm'])
    expect(used).toEqual(expect.arrayContaining(['14', '22']))
    expect(styles).not.toContain('formatCode="m/d/yyyy')
  })

  it('keeps text that reads like an error as text, and every error value as an error', async () => {
    const errors = ['#N/A', '#FIELD!', '#SPILL!', '#BLOCKED!', '#PYTHON!']
    const { written, second } = await roundTrip(await bookWith([['A1', '#N/A'], ...errors.map((error, row): [string, ExcelJS.CellValue] => [`A${row + 2}`, { error } as ExcelJS.CellErrorValue])]))
    const sheet = await partOf(written.bytes, 'xl/worksheets/sheet1.xml')
    const typeOf = (address: string) => sheet.match(new RegExp(`<c r="${address}"([^>]*)>`))?.[1].match(/ t="(\w+)"/)?.[1]

    expect(typeOf('A1')).toBe('s')
    expect(errors.map((_, row) => typeOf(`A${row + 2}`))).toEqual(errors.map(() => 'e'))
    expect(columnA(second.workbook, 6)).toEqual(['#N/A', ...errors])
  })

  it('keeps formulas whose functions Excel prefixes, even ones Herald has no name for', async () => {
    const formulas = ['SUM(_xlfn.ANCHORARRAY(B1))', 'IFERROR(_xlfn.XLOOKUP(B1,B2:B3,C2:C3),"")', '_xlfn.SINGLE(B1:B3)', '_xlfn.ENCODEURL("a b")', '_xlfn.SOMEDAY(B1)', '_xludf.MYADDIN(B1)', 'SUM(_xlfn._xlws.SORT(B1:B3))']
    const { first, written } = await roundTrip(await bookWith(formulas.map((formula, row): [string, ExcelJS.CellValue] => [`A${row + 1}`, { formula, result: 1 }])))
    const sheet = await partOf(written.bytes, 'xl/worksheets/sheet1.xml')

    expect([...sheet.matchAll(/<f>([^<]*)<\/f>/g)].map((match) => match[1].replace(/&quot;/g, '"'))).toEqual(formulas)
    expect(cellsOf(first.workbook)[0][0].f).toBe('=SUM(ANCHORARRAY(B1))')
    expect(cellsOf(first.workbook)[4][0].f).toBe('=_xlfn.SOMEDAY(B1)')
  })

  it('keeps control characters, carriage returns and text that reads like an escape', async () => {
    const { first, second } = await roundTrip(await bookWith([['A1', 'ctl_x0001_end'], ['A2', 'line1_x000D_\nline2'], ['A3', '_x005F_x0041_ stays'], ['A4', 'tab\tstays']]))
    const expected = ['ctl\u0001end', 'line1\r\nline2', '_x0041_ stays', 'tab\tstays']

    expect(columnA(first.workbook, 4)).toEqual(expected)
    expect(columnA(second.workbook, 4)).toEqual(expected)
  })

  it('writes a line break that rich text has as CR LF as one line break', async () => {
    const rich = { richText: [{ text: 'bold_x000D_\n', font: { bold: true } }, { text: 'rest' }] } as ExcelJS.CellRichTextValue
    const { second } = await roundTrip(await bookWith([['A1', rich]]))

    expect(cellsOf(second.workbook)[0][0].v).toBe('bold\nrest')
  })
})
