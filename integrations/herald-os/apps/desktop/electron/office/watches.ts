import type { WebContents } from 'electron'
import type { FileWatcher } from './file-watch.ts'

/*
 * The files Office windows watch, by watch id. A watch ends when its window unwatches the file or
 * closes, and its close listener goes with it either way: in desktop mode one web contents holds
 * all three apps, so a listener left behind for every file opened would pile up over a session.
 */

interface Watch {
  watcher: FileWatcher
  owner: WebContents
  file: string
  end: () => void
}

export class OfficeWatches {
  private readonly watches = new Map<string, Watch>()

  /** Keep `watcher` running for `owner` until it unwatches `id` or closes. */
  add(id: string, owner: WebContents, file: string, watcher: FileWatcher): void {
    const end = () => {
      watcher.stop()
      this.watches.delete(id)
      owner.off('destroyed', end)
    }

    this.watches.set(id, { watcher, owner, file, end })
    owner.once('destroyed', end)
  }

  /** End watch `id` if `owner` started it; another window's watch is left alone. */
  remove(id: string, owner: WebContents): void {
    const watch = this.watches.get(id)

    if (watch?.owner === owner) {
      watch.end()
    }
  }

  /** The watcher `owner` keeps on `file`, if any. */
  find(file: string, owner: WebContents): FileWatcher | undefined {
    return [...this.watches.values()].find((watch) => watch.file === file && watch.owner === owner)?.watcher
  }

  get size(): number {
    return this.watches.size
  }
}
