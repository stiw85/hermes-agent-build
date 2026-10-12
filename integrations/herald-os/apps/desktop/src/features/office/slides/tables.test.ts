import { describe, expect, it } from 'vitest'
import { findElement, findSlide, type TableCell, type TableElement } from './deck.ts'
import { describeElement, withBox } from './elements.ts'
import * as model from './model.ts'
import { cellUnder, fitRow, insertColumn, insertRow, nextCell, removeColumns, removeRows, settleSpans, tableElement, tableText, withCell } from './tables.ts'
import { plainText } from './text.ts'

const box = { x: 0, y: 0, width: 300, height: 90 }

/** A 3 by 3 table with a1 to c3 in it. */
const grid = (): TableElement =>
  tableElement(box, 3, 3, [
    ['a1', 'b1', 'c1'],
    ['a2', 'b2', 'c2'],
    ['a3', 'b3', 'c3']
  ])

const texts = (table: TableElement) => table.cells.map((row) => row.map((cell) => (cell.merged ? '·' : plainText(cell.body))))
const spans = (table: TableElement) => table.cells.map((row) => row.map((cell) => (cell.merged ? '·' : `${cell.colSpan ?? 1}x${cell.rowSpan ?? 1}`)))
const alphas = (table: TableElement) => table.cells.map((row) => row[0].fill?.alpha ?? 1)

/** A table with some cells merged: each entry is a row, a column and the cell's reach. */
function merged(table: TableElement, merges: [number, number, Partial<TableCell>][]): TableElement {
  const reaching = merges.reduce((next, [row, column, reach]) => withCell(next, { row, column }, (cell) => ({ ...cell, ...reach })), table)

  return { ...reaching, cells: settleSpans(reaching.cells, reaching.columns.length) }
}

describe('tables', () => {
  it('makes a table as PowerPoint’s default style draws one, within PowerPoint’s limits', () => {
    const table = grid()

    expect(table).toMatchObject({ kind: 'table', columns: [100, 100, 100], rows: [30, 30, 30], rotation: 0, stroke: { color: 'bg1', width: 1, dash: 'solid' } })
    expect(texts(table)).toEqual([
      ['a1', 'b1', 'c1'],
      ['a2', 'b2', 'c2'],
      ['a3', 'b3', 'c3']
    ])
    expect(table.cells[0][0]).toMatchObject({ fill: { color: 'accent1' }, body: { style: { font: '+body', size: 18, color: 'bg1', bold: true }, anchor: 'top', inset: [7.2, 3.6, 7.2, 3.6] } })
    expect(table.cells[1][2]).toMatchObject({ fill: { color: 'accent1', alpha: 0.4 }, body: { style: { color: 'tx1' } } })
    expect(alphas(table)).toEqual([1, 0.4, 0.2])
    expect(describeElement(table)).toBe('Table')

    const huge = tableElement(box, 0, 500)
    expect([huge.rows.length, huge.columns.length]).toEqual([1, 75])
  })

  it('keeps merged cells inside the table and off each other, marking what they cover', () => {
    const table = merged(grid(), [
      [0, 0, { colSpan: 2, rowSpan: 2 }],
      [0, 2, { rowSpan: 9 }],
      [1, 1, { colSpan: 2 }],
      [2, 0, { colSpan: 3 }]
    ])

    expect(spans(table)).toEqual([
      ['2x2', '·', '1x3'],
      ['·', '·', '·'],
      ['2x1', '·', '·']
    ])
  })

  it('inserts rows formatted as their neighbours, keeping the bands taking turns and merged cells whole', () => {
    const below = insertRow(grid(), 0, 'below')

    expect(texts(below).map((row) => row[0])).toEqual(['a1', '', 'a2', 'a3'])
    expect(alphas(below)).toEqual([1, 0.4, 0.2, 0.4])
    expect(below.cells[1][0].body.style).toMatchObject({ color: 'tx1' })
    expect(below.cells[1][0].body.style.bold).toBeUndefined()
    expect([below.rows, below.height]).toEqual([[30, 30, 30, 30], 120])

    const above = insertRow(grid(), 0, 'above')
    expect(above.cells.map((row) => row[0].fill)).toEqual([{ color: 'accent1' }, { color: 'accent1' }, { color: 'accent1', alpha: 0.4 }, { color: 'accent1', alpha: 0.2 }])

    const across = insertRow(merged(grid(), [[0, 0, { rowSpan: 2 }]]), 0, 'below')
    expect(spans(across).map((row) => row[0])).toEqual(['1x3', '·', '·', '1x1'])

    const most = Array.from({ length: 80 }).reduce<TableElement>((table) => insertRow(table, 0, 'below'), grid())
    expect(most.rows).toHaveLength(75)
  })

  it('inserts and deletes columns, merged cells growing over a new one and handing their text on', () => {
    const wider = insertColumn(grid(), 1, 'right')

    expect(texts(wider)[0]).toEqual(['a1', 'b1', '', 'c1'])
    expect([wider.columns, wider.width]).toEqual([[100, 100, 100, 100], 400])
    expect(wider.cells.map((row) => row[2].fill)).toEqual(wider.cells.map((row) => row[1].fill))

    const spanning = merged(grid(), [[0, 0, { colSpan: 2 }]])
    expect(spans(insertColumn(spanning, 0, 'right'))[0]).toEqual(['3x1', '·', '·', '1x1'])

    const narrower = removeColumns(spanning, [0])!
    expect(texts(narrower)).toEqual([
      ['a1', 'c1'],
      ['b2', 'c2'],
      ['b3', 'c3']
    ])
    expect([narrower.columns, narrower.width]).toEqual([[100, 100], 200])
    expect(removeColumns(grid(), [0, 1, 2])).toBeNull()
  })

  it('deletes rows, the bands taking turns again and a merged cell starting at its first row left', () => {
    const shorter = removeRows(grid(), [1])!

    expect(texts(shorter).map((row) => row[0])).toEqual(['a1', 'a3'])
    expect(alphas(shorter)).toEqual([1, 0.4])
    expect(shorter.height).toBe(60)

    const tall = removeRows(merged(grid(), [[0, 1, { rowSpan: 3 }]]), [0])!
    expect(texts(tall)).toEqual([
      ['a2', 'b1', 'c2'],
      ['a3', '·', 'c3']
    ])
    expect(spans(tall)[0][1]).toBe('1x2')
    expect(removeRows(grid(), [0, 1, 2])).toBeNull()
  })

  it('steps through the cells merged cells do not cover, and finds the cell under a place', () => {
    const table = merged(grid(), [[0, 0, { colSpan: 2 }]])

    expect(nextCell(table, { row: 0, column: 0 }, 1)).toEqual({ row: 0, column: 2 })
    expect(nextCell(table, { row: 0, column: 2 }, 1)).toEqual({ row: 1, column: 0 })
    expect(nextCell(table, { row: 0, column: 2 }, -1)).toEqual({ row: 0, column: 0 })
    expect(nextCell(table, { row: 2, column: 2 }, 1)).toBeNull()
    expect(nextCell(table, { row: 0, column: 0 }, -1)).toBeNull()
    expect(cellUnder(table, { row: 0, column: 1 })).toEqual({ row: 0, column: 0 })
    expect(cellUnder(table, { row: 9, column: 9 })).toEqual({ row: 2, column: 2 })
  })

  it('stretches with its box, grows a row to fit its text, and reads as tab-separated text', () => {
    const table = withBox(grid(), { x: 10, y: 20, width: 600, height: 45 })

    expect(table).toMatchObject({ x: 10, y: 20, width: 600, height: 45, columns: [200, 200, 200], rows: [15, 15, 15] })
    expect(fitRow(table, { row: 1, column: 0 }, 40)).toMatchObject({ rows: [15, 40, 15], height: 70 })
    expect(fitRow(table, { row: 1, column: 0 }, 10)).toBe(table)
    expect(fitRow(merged(table, [[0, 0, { rowSpan: 2 }]]), { row: 0, column: 0 }, 40).rows).toEqual([15, 25, 15])
    expect(tableText(merged(grid(), [[0, 0, { colSpan: 2 }]]))).toBe('a1\tc1\na2\tb2\tc2\na3\tb3\tc3')
  })
})

describe('tables in a deck', () => {
  const start = () => {
    const deck = model.newDeck('Plan')
    const slideId = deck.slides[0].id
    const added = model.addTable(deck, slideId, { rows: 2, columns: 4, cells: [['Q1', 'Q2']] })

    return { slideId, added, table: () => model.requireTable(added.deck, slideId, added.elementId) }
  }

  it('adds a table in the middle of the slide, three quarters as wide, selected', () => {
    const { slideId, added, table } = start()

    expect(added.label).toBe('New Table')
    expect(added.focus).toEqual({ slideId, selected: [added.elementId] })
    expect(table()).toMatchObject({ x: 120, width: 720, height: 58.4, columns: [180, 180, 180, 180], rows: [29.2, 29.2] })
    expect(texts(table())[0]).toEqual(['Q1', 'Q2', '', ''])
  })

  it('writes cells, inserts and deletes rows and columns, and fills cells, each as one step', () => {
    const { slideId, added } = start()
    const id = added.elementId
    let deck = model.setCellText(added.deck, slideId, id, 1, 3, 'Total\nall year').deck
    const cell = model.requireTable(deck, slideId, id).cells[1][3]

    expect(cell.body.paragraphs.map((paragraph) => paragraph.runs[0].text)).toEqual(['Total', 'all year'])
    expect(() => model.setCellText(deck, slideId, id, 5, 0, 'x')).toThrow(/no cell at row 6/)

    const row = model.insertTableRow(deck, slideId, id, 1, 'below')
    expect([row.label, model.requireTable(row.deck, slideId, id).rows.length]).toEqual(['Insert Row', 3])

    const column = model.insertTableColumn(row.deck, slideId, id, 0, 'left')
    expect([column.label, model.requireTable(column.deck, slideId, id).columns.length]).toEqual(['Insert Column', 5])

    const filled = model.setCellFill(column.deck, slideId, id, [{ row: 0, column: 1 }], { color: '#ff0000' })
    expect(filled.label).toBe('Cell Fill')
    expect(model.requireTable(filled.deck, slideId, id).cells[0].map((entry) => entry.fill?.color)).toEqual(['accent1', '#ff0000', 'accent1', 'accent1', 'accent1'])
    expect(model.requireTable(model.setCellFill(filled.deck, slideId, id, 'all', null).deck, slideId, id).cells.flat().every((entry) => entry.fill === null)).toBe(true)

    deck = model.removeTableColumns(filled.deck, slideId, id, [0, 1]).deck
    expect(model.requireTable(deck, slideId, id).columns).toHaveLength(3)

    const gone = model.removeTableRows(deck, slideId, id, [0, 1, 2])
    expect(gone.label).toBe('Delete Table')
    expect(findElement(findSlide(gone.deck, slideId), id)).toBeUndefined()
  })

  it('refuses to treat other elements as tables', () => {
    const deck = model.newDeck('Plan')
    const slide = deck.slides[0]

    expect(() => model.requireTable(deck, slide.id, slide.elements[0].id)).toThrow(/not a table/)
  })
})
