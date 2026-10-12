import type { WebContents } from 'electron'
import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import type { FileWatcher } from './file-watch.ts'
import { OfficeWatches } from './watches.ts'

const owner = () => new EventEmitter() as unknown as WebContents & EventEmitter
const watcher = () => ({ stop: vi.fn() }) as unknown as FileWatcher & { stop: ReturnType<typeof vi.fn> }

describe('OfficeWatches', () => {
  it('takes a watch’s close listener with it when the window unwatches the file', () => {
    const watches = new OfficeWatches()
    const contents = owner()
    const watchers = Array.from({ length: 40 }, watcher)

    watchers.forEach((each, index) => watches.add(`w${index}`, contents, `/tmp/file-${index}.docx`, each))
    expect(contents.listenerCount('destroyed')).toBe(40)

    watchers.forEach((_each, index) => watches.remove(`w${index}`, contents))

    expect(contents.listenerCount('destroyed')).toBe(0)
    expect(watchers.every((each) => each.stop.mock.calls.length === 1)).toBe(true)
    expect(watches.size).toBe(0)
  })

  it('ends every watch a window kept when it closes, each once', () => {
    const watches = new OfficeWatches()
    const contents = owner()
    const first = watcher()
    const second = watcher()
    watches.add('a', contents, '/tmp/Budget.xlsx', first)
    watches.add('b', contents, '/tmp/Report.docx', second)

    contents.emit('destroyed')
    watches.remove('a', contents)

    expect(first.stop).toHaveBeenCalledTimes(1)
    expect(second.stop).toHaveBeenCalledTimes(1)
    expect(contents.listenerCount('destroyed')).toBe(0)
    expect(watches.size).toBe(0)
  })

  it('finds a window’s own watcher, and lets no other window end it', () => {
    const watches = new OfficeWatches()
    const mine = owner()
    const other = owner()
    const kept = watcher()
    watches.add('a', mine, '/tmp/Deck.pptx', kept)

    watches.remove('a', other)

    expect(kept.stop).not.toHaveBeenCalled()
    expect(watches.find('/tmp/Deck.pptx', mine)).toBe(kept)
    expect(watches.find('/tmp/Deck.pptx', other)).toBeUndefined()
    expect(mine.listenerCount('destroyed')).toBe(1)
  })
})
