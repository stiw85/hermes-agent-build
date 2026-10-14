import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Settings } from '../shared/ipc.ts'
import { Backend } from './backend.ts'
import { loadSettings, saveSettings } from './settings.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const devServer = process.env.HT_DEV_SERVER
const backend = new Backend()
let win: BrowserWindow | null = null
let quitting = false

function iconPath(): string | undefined {
  return [path.join(app.getAppPath(), 'build', 'icon.png'), path.join(here, '..', 'renderer', 'icon.png')].find(f => fs.existsSync(f))
}

function createWindow(): BrowserWindow {
  const w = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    frame: false,
    backgroundColor: '#050f33',
    title: 'Hermes Trader',
    icon: iconPath(),
    webPreferences: {
      preload: path.join(here, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false
    }
  })
  // The renderer never navigates or opens windows; real links go to the system browser.
  w.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//i.test(url)) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })
  w.webContents.on('will-navigate', (e, url) => {
    if (!(devServer && url.startsWith(devServer))) {
      e.preventDefault()
    }
  })
  if (devServer) {
    void w.loadURL(devServer)
  } else {
    void w.loadFile(path.join(here, '..', 'renderer', 'index.html'))
  }
  w.once('ready-to-show', () => w.show())
  w.on('maximize', () => w.webContents.send('window:maximized', true))
  w.on('unmaximize', () => w.webContents.send('window:maximized', false))

  return w
}

function registerIpc(): void {
  ipcMain.handle('api:get', (_e, p: unknown) => (typeof p === 'string' ? backend.request('GET', p) : { ok: false, status: 400, error: 'bad path' }))
  ipcMain.handle('api:post', (_e, p: unknown, body: unknown) => {
    if (typeof p !== 'string' || (body != null && (typeof body !== 'object' || Array.isArray(body)))) {
      return { ok: false, status: 400, error: 'bad request' }
    }
    return backend.request('POST', p, (body ?? {}) as Record<string, unknown>)
  })
  ipcMain.handle('backend:state', () => backend.state)
  ipcMain.handle('backend:restart', () => backend.start(loadSettings()))
  ipcMain.handle('backend:logs', () => backend.logs.slice(-300))
  ipcMain.handle('settings:get', () => loadSettings())
  ipcMain.handle('settings:set', async (_e, patch: Partial<Settings>) => {
    // What the app executes or trusts is decided here, not by the renderer: changes need a native confirmation.
    const cur = loadSettings()
    const p = patch ?? {}
    const risky = (['command', 'projectDir', 'attachTokenFile', 'attachUrl'] as const).filter(k => p[k] !== undefined && String(p[k]) !== cur[k])
    if (risky.length) {
      const r = await dialog.showMessageBox(win!, {
        type: 'question',
        buttons: ['Apply', 'Cancel'],
        defaultId: 1,
        cancelId: 1,
        title: 'Change backend settings?',
        message: 'Hermes Trader will run or connect to the backend using these settings:',
        detail: risky.map(k => `${k}: ${String(p[k]) || '(auto)'}`).join('\n')
      })
      if (r.response !== 0) return cur
    }
    return saveSettings(p)
  })
  ipcMain.handle('dialog:pickFolder', async () => {
    const r = await dialog.showOpenDialog(win!, { properties: ['openDirectory'], defaultPath: loadSettings().projectDir })
    return r.canceled ? null : r.filePaths[0]
  })
  ipcMain.handle('shell:openPath', async (_e, p: unknown) => {
    // only the project folder (or something inside it) can be opened
    const root = path.resolve(loadSettings().projectDir)
    const target = typeof p === 'string' ? path.resolve(p) : ''
    if (target === root || target.startsWith(root + path.sep)) {
      await shell.openPath(target)
    }
  })
  ipcMain.on('window:control', (_e, action: unknown) => {
    if (!win) return
    if (action === 'minimize') win.minimize()
    else if (action === 'maximize') (win.isMaximized() ? win.unmaximize() : win.maximize())
    else if (action === 'close') win.close()
  })
  backend.on('state', s => win?.webContents.send('backend:state', s))
}

/** Quitting a spawned backend stops the bot: ask first when it is trading. */
async function confirmQuit(): Promise<boolean> {
  if (!backend.spawned || backend.state.phase !== 'ready') {
    return true
  }
  const st = await backend.request<{ bot?: { running?: boolean; stopping?: boolean }; mode?: string }>('GET', '/api/status')
  // if we can't tell (backend busy or unreachable), assume it may be trading and ask
  if (st.ok && !st.data?.bot?.running && !st.data?.bot?.stopping) {
    return true
  }
  const r = await dialog.showMessageBox(win!, {
    type: 'warning',
    buttons: ['Stop the bot and quit', 'Keep running'],
    defaultId: 1,
    cancelId: 1,
    title: 'The bot is trading',
    message: `The ${st.data?.mode === 'live' ? 'LIVE ' : ''}trading bot runs inside this app. Quitting stops it.`,
    detail: 'A cycle in progress finishes first. Open positions stay open. To trade without the app, run `hermes-trader serve --run` in tmux and use Attach mode.'
  })
  return r.response === 0
}

app.whenReady().then(() => {
  registerIpc()
  win = createWindow()
  win.on('close', async e => {
    if (quitting) return
    e.preventDefault()
    if (await confirmQuit()) {
      quitting = true
      win?.hide()
      // spawned: stop the bot and let the backend finish its cycle. attached: leave the user's bot alone.
      await backend.stop()
      app.quit()
    }
  })
  void backend.start(loadSettings())
})

app.on('window-all-closed', () => app.quit())
app.on('before-quit', () => {
  quitting = true
})
